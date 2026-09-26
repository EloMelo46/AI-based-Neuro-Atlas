"""Run the LAN HTTPS server: Caddy -> loopback-only Waitress -> Flask.

Certificates and keys stay in .local/https. Only the exported root certificate
is copied to client devices; this launcher never changes system trust stores.
"""
import argparse
import hashlib
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def host_address(value):
    if value == 'localhost':
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Use localhost or the server\'s LAN IP address.') from error
    if address.is_unspecified or address.is_multicast or address.is_global or getattr(address, 'scope_id', None):
        raise argparse.ArgumentTypeError('Use a local IP, not 0.0.0.0 or a public address.')
    return address.compressed


def port_number(value):
    try:
        number = int(value)
        if 1 <= number <= 65535:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Port must be between 1 and 65535.')


def site_url(host, port):
    return f'https://[{host}]:{port}' if ':' in host else f'https://{host}:{port}'


def find_caddy(explicit=None):
    executable = 'caddy.exe' if os.name == 'nt' else 'caddy'
    candidate = explicit or shutil.which('caddy') or str(PROJECT_ROOT / '.tools' / executable)
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError('Caddy not found. Install Caddy or place it in .tools; see docs/https.md.')
    return path


def create_backend(port):
    from waitress import create_server
    from main.brain_viewer import app

    # This listener is exclusively behind our HTTPS proxy. Preserve Caddy's
    # original Host and set the scheme so the assistant's Origin check works.
    # Use a separate cookie name from the optional HTTP development server.
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_NAME='neuro_atlas_https')
    return create_server(app, host='127.0.0.1', port=port, threads=8,
                         url_scheme='https', max_request_body_size=11 * 1024 * 1024)


def ensure_free_port(host, port):
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            raise RuntimeError(f'Port {port} is unavailable. Stop the other server or choose another port.') from error


def start_process(arguments, env):
    return subprocess.Popen(arguments, cwd=PROJECT_ROOT, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_ready(url, processes, root_certificate=None):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('A server process exited during startup; see its output above.')
        try:
            handlers = [ProxyHandler({})]
            if root_certificate:
                context = ssl.create_default_context(cafile=str(root_certificate))
                handlers.append(HTTPSHandler(context=context))
            with build_opener(*handlers).open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f'Server did not become ready: {url}')


def run(args):
    caddy = find_caddy(args.caddy)
    try:
        import waitress  # noqa: F401 -- fail before starting either process
    except ImportError as error:
        raise RuntimeError('Install HTTPS dependencies: python -m pip install -r requirements.txt') from error
    if args.port == args.backend_port:
        raise RuntimeError('HTTPS and backend ports must be different.')
    ensure_free_port('0.0.0.0', args.port)
    ensure_free_port('127.0.0.1', args.backend_port)
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage = state_dir / 'caddy'
    hosts = list(dict.fromkeys([args.host, 'localhost', '127.0.0.1']))
    caddy_env = dict(os.environ, NEURO_TLS_STORAGE=storage.as_posix(),
                     NEURO_HTTPS_SITES=', '.join(site_url(host, args.port) for host in hosts),
                     NEURO_BACKEND_PORT=str(args.backend_port))
    caddy_env.pop('OPENAI_API_KEY', None)
    # Generated runtime configuration also works without a repository Caddyfile.
    config = state_dir / 'Caddyfile'
    config.write_text("""{
    admin off
    auto_https disable_redirects
    skip_install_trust
    storage file_system {
        root {$NEURO_TLS_STORAGE}
    }
}
{$NEURO_HTTPS_SITES} {
    tls internal
    reverse_proxy 127.0.0.1:{$NEURO_BACKEND_PORT}
}
""", encoding='utf-8')
    processes = []
    try:
        backend = start_process([sys.executable, '-m', 'main.https_server', '--backend',
                                 '--backend-port', str(args.backend_port)], os.environ.copy())
        processes.append(backend)
        wait_ready(f'http://127.0.0.1:{args.backend_port}/api/assistant/config', processes)
        proxy = start_process([str(caddy), 'run', '--config', str(config),
                               '--adapter', 'caddyfile'], caddy_env)
        processes.append(proxy)
        root_certificate = storage / 'pki' / 'authorities' / 'local' / 'root.crt'
        wait_ready(f'https://localhost:{args.port}/api/assistant/config', processes, root_certificate)
        export_dir = state_dir / 'share'
        export_dir.mkdir(exist_ok=True)
        exported = export_dir / 'neuro-atlas-root.crt'
        shutil.copyfile(root_certificate, exported)
        der = ssl.PEM_cert_to_DER_cert(root_certificate.read_text(encoding='ascii'))
        fingerprint = hashlib.sha256(der).hexdigest().upper()
        print(f'\nNeuro Atlas: {site_url(args.host, args.port)}', flush=True)
        print(f'Install this public root certificate on each client: {exported}', flush=True)
        print(f'SHA-256: {fingerprint}', flush=True)
        print('Device instructions: docs/https.md. Stop both servers with Ctrl+C.\n', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError('A server process stopped; both servers have been shut down.')
    finally:
        for process in reversed(processes):
            stop_process(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=host_address, default='localhost', help='LAN IP of this computer (default: localhost)')
    parser.add_argument('--port', type=port_number, default=8443, help='HTTPS port (default: 8443)')
    parser.add_argument('--backend-port', type=port_number, default=5001, help='Loopback-only backend port (default: 5001)')
    parser.add_argument('--caddy', help='Path to the Caddy executable')
    parser.add_argument('--state-dir', type=Path, default=PROJECT_ROOT / '.local' / 'https')
    parser.add_argument('--backend', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.backend:
            from main.brain_viewer import gestures
            if os.environ.get('NEURO_GESTURES') == '1':
                gestures.start()
            try:
                create_backend(args.backend_port).run()
            finally:
                gestures.stop()
        else:
            run(args)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'HTTPS startup failed: {error}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())

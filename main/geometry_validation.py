"""Bind offline cut eligibility to the exact GLB bytes inspected by the audit."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=4)
def _read_report(path, modified, size):
    del modified, size  # File metadata invalidates the cache after regeneration.
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return {item['region_id']: item for item in data['regions']}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@lru_cache(maxsize=256)
def _digest(path, modified, size):
    del modified, size
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def cut_validation(directory, regions):
    """Fail closed for absent, stale or rejected geometry validation records.

    Rendering the original region remains allowed. Only synthetic cut surfaces
    require a positive audit; this function never repairs source geometry.
    """
    directory = Path(directory)
    report = directory / 'geometry_validation.json'
    try:
        stat = report.stat()
        records = _read_report(str(report), stat.st_mtime_ns, stat.st_size)
    except OSError:
        records = {}
    result = {}
    for region in regions:
        record = records.get(region['region_id'], {})
        eligible = False
        digest = ''
        reason = 'Kein passender Geometrieprüfbericht vorhanden.'
        path = directory / region['mesh_glb']
        try:
            stat = path.stat()
            digest = _digest(str(path), stat.st_mtime_ns, stat.st_size)
            if record.get('sha256') == digest:
                eligible = record.get('stencil_cut_eligible', record.get('cut_eligible')) is True
                reason = '' if eligible else 'Geometrieprüfung: keine verlässliche gefüllte Schnittfläche.'
            elif record:
                reason = 'GLB wurde ersetzt: Geometrieprüfbericht muss aktualisiert werden.'
        except OSError:
            pass
        result[region['region_id']] = {'cut_eligible': eligible, 'cut_validation_note': reason,
                                      'mesh_sha256': digest}
    return result

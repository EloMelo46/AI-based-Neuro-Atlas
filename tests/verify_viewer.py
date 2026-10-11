"""Current viewer regression entrypoint; delegates to the 98-solid-GLB suite."""
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.verify_solid_viewer import main

if __name__ == '__main__':
    main()

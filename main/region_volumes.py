"""Measured voxel-label volumes, shared by text and realtime voice contexts."""
import json
import math
from functools import lru_cache
from pathlib import Path

from .mesh_catalog import DEFAULT_EXPORT_DIR, available_region_ids


@lru_cache(maxsize=8)
def _read(path, modified_ns, size):
    del modified_ns, size
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('volume_unit') != 'mm3' or not isinstance(data.get('regions'), dict):
        raise ValueError('Ungültige Volumendaten.')
    return data


def assistant_volume_context(directory=DEFAULT_EXPORT_DIR):
    """Never infer tissue volumes from smoothed meshes or technical fills."""
    path = Path(directory) / 'region_volumes.json'
    try:
        stat = path.stat()
        data = _read(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, TypeError, AttributeError):
        return {'available': False, 'regions': {}}
    volumes = {}
    for region_id in available_region_ids(directory):
        entry = data['regions'].get(region_id, {})
        if not isinstance(entry, dict) or entry.get('region_id') != region_id:
            continue
        volume = entry.get('volume_mm3')
        if type(volume) not in (int, float) or not math.isfinite(volume) or volume < 0:
            continue
        record = {'volume_mm3': volume, 'volume_ml': round(volume / 1000, 6)}
        if entry.get('is_derived_subset'):
            record.update(is_derived_subset=True, interpretation=entry.get('interpretation', ''),
                          measurement_method=entry.get('measurement_method', ''))
        volumes[region_id] = record
    return {'available': bool(volumes), 'source': path.name,
            'measurement': 'Volumen der ursprünglichen Segmentierungsmaske; kein geglättetes Meshvolumen.',
            'limits': 'Segmentierungsbasierte Schätzwerte. Überlappende Labels nicht zu einem Gesamtgehirnvolumen addieren. Keine Normwert- oder Diagnoseaussagen aus diesen Werten.',
            'regions': volumes}

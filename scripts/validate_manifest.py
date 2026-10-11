#!/usr/bin/env python3
"""Read-only manifest/GLB metadata census; does not certify mesh topology."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main.mesh_catalog import load_regions, region_groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, default=ROOT / 'segmentation_export')
    args = parser.parse_args()
    rows = load_regions(args.export)
    records = []
    for row in rows:
        path = args.export / row['mesh_glb']
        data = path.read_bytes()
        assert data[:4] == b'glTF' and struct.unpack_from('<I', data, 4)[0] == 2, path
        assert struct.unpack_from('<I', data, 8)[0] == len(data), path
        length, kind = struct.unpack_from('<II', data, 12)
        assert kind == 0x4e4f534a, path
        doc = json.loads(data[20:20+length])
        triangles = 0
        for mesh in doc['meshes']:
            for primitive in mesh['primitives']:
                assert primitive.get('mode', 4) == 4, path
                accessor = primitive.get('indices', primitive['attributes']['POSITION'])
                count = doc['accessors'][accessor]['count']
                assert count % 3 == 0, path
                triangles += count // 3
        records.append({
            'region_id':row['region_id'], 'mesh_glb':row['mesh_glb'],
            'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data),
            'triangles_from_accessors':triangles,
            'manifest_bytes_match':len(data) == row['optimized_bytes'],
            'manifest_triangles_match':triangles == row['triangles_optimized'],
            'generator':doc['asset'].get('generator'), 'asset_extras':doc['asset'].get('extras'),
            'extras':doc.get('extras'), 'extensions_required':doc.get('extensionsRequired', []),
            'nodes':doc.get('nodes'), 'meshes_have_extras':any('extras' in m for m in doc['meshes']),
        })
    groups = region_groups(args.export)
    ids = {r['region_id'] for r in rows}
    report = {
        'schema_version':1,
        'method':'Read current TSV and GLB JSON chunks; compare byte sizes and triangle accessor counts; hash complete GLBs; resolve groups. No topology or anatomical registration check.',
        'manifest_sha256':hashlib.sha256((args.export / 'regions_manifest.tsv').read_bytes()).hexdigest(),
        'region_count':len(rows), 'categories':dict(Counter(r['category'] for r in rows)),
        'selectable_count':sum(r['selectable'] for r in rows),
        'renderable_count':sum(r['renderable'] for r in rows),
        'disabled_regions':[r['region_id'] for r in rows if not r['renderable']],
        'fill_count':sum(r['render_role'] == 'fill' for r in rows),
        'default_hidden':[r['region_id'] for r in rows if not r['default_visible']],
        'sources':dict(Counter(r['source'] for r in rows)),
        'geometry_sources':sorted({r['geometry_source'] for r in rows}),
        'mask_paths_supplied':sum(bool(r['mask_nii']) for r in rows),
        'missing_volumes':[r['region_id'] for r in rows if r['volume_mm3'] is None],
        'group_variants':len(groups),
        'all_group_members_exist':all(set(g['region_ids']) <= ids for g in groups),
        'declared_triangle_count':sum(r['triangles_optimized'] for r in rows),
        'declared_source_triangle_count':sum(r['triangles_source'] for r in rows),
        'declared_file_bytes':sum(r['optimized_bytes'] for r in rows),
        'all_simplify_ratios_one':all(r['simplify_ratio'] == 1 for r in rows),
        'all_manifest_file_sizes_match':all(r['manifest_bytes_match'] for r in records),
        'all_manifest_triangle_counts_match':all(r['manifest_triangles_match'] for r in records),
        'regions':records,
    }
    (args.export / 'manifest_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'regions'}, indent=2))


if __name__ == '__main__':
    main()

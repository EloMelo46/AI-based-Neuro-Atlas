#!/usr/bin/env python3
"""Offline, read-only audit of manifest GLBs (NumPy, Node; optional C++ compiler).

Example: python scripts/validate_geometry.py --node /path/to/node --intersections
The report is tied to each source GLB by SHA-256. No source mesh is repaired.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def inspect_topology(vertices, normals, faces):
    # Exact welding joins split normal seams; never merge nearby anatomical surfaces.
    welded, inverse = np.unique(vertices, axis=0, return_inverse=True)
    welded_faces = inverse[faces]
    triangles = vertices[faces]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    double_area = np.linalg.norm(cross, axis=1)
    degenerate = double_area <= 1e-12
    edges = np.concatenate([welded_faces[:, [0, 1]], welded_faces[:, [1, 2]], welded_faces[:, [2, 0]]])
    directions = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    ordered = np.sort(edges, axis=1)
    unique_edges, edge_inverse, counts = np.unique(ordered, axis=0, return_inverse=True, return_counts=True)
    balances = np.bincount(edge_inverse, weights=directions)
    # A closed oriented triangle chain has zero boundary. Ignore self-loops:
    # collapsed edges contribute nothing to the winding count.
    unbalanced = int(np.count_nonzero((unique_edges[:, 0] != unique_edges[:, 1]) & (balances != 0)))
    boundaries = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))
    inconsistent = int(np.count_nonzero((counts == 2) & (balances != 0)))
    duplicates = int(len(welded_faces) - len(np.unique(np.sort(welded_faces, axis=1), axis=0)))
    signed_volume = float(np.einsum('ij,ij->i', triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6)
    valid_faces = ~degenerate
    face_normals = cross[valid_faces] / double_area[valid_faces, None]
    corner_normals = normals[faces[valid_faces]]
    dots = np.einsum('ij,ikj->ik', face_normals, corner_normals)
    # Smooth normals may exceed 90 degrees at folded or very coarse vertices.
    opposite_corners = int(np.count_nonzero(dots < -0.05))
    normal_lengths = np.linalg.norm(normals, axis=1)
    return {
        'vertices': len(vertices), 'welded_vertices': len(welded), 'triangles': len(faces),
        'edges': len(unique_edges), 'boundary_edges': boundaries,
        'nonmanifold_edges': nonmanifold, 'inconsistent_winding_edges': inconsistent,
        'unbalanced_oriented_edges': unbalanced,
        'degenerate_triangles': int(degenerate.sum()), 'duplicate_triangles': duplicates,
        'euler_characteristic': int(len(welded) - len(unique_edges) + len(faces)),
        'watertight': boundaries == 0 and nonmanifold == 0 and not np.any(degenerate),
        'consistent_winding': inconsistent == 0,
        'winding_scope': 'Opposite directions on edges incident to exactly two faces; manifoldness evaluated separately',
        'signed_volume_mm3': signed_volume,
        'normal_zero_or_invalid': int(np.count_nonzero(~np.isfinite(normal_lengths) | (normal_lengths < 0.5))),
        'normal_face_opposition_corners': opposite_corners,
        'normal_face_opposition_fraction': opposite_corners / max(1, len(dots) * 3),
    }, welded, welded_faces


def stencil_ineligibility_reasons(topology, hemisphere_position_consistent=None):
    """Gate integer winding sections, separately from strict surface quality.

    A closed oriented triangle chain defines integer winding even when shells
    touch at a vertex/edge. Every noncollapsed edge must cancel directionally;
    manifoldness is not required by this renderer. Zero-area triangles and
    opposing sheets contribute no volume. Preserve all quality defects in the
    strict audit; never infer closure from a positive signed volume alone.
    """
    reasons = []
    for key in ('boundary_edges', 'unbalanced_oriented_edges'):
        if topology.get(key) != 0:
            reasons.append(key)
    if topology.get('vertex_links_checked') is not True:
        reasons.append('vertex_links_not_checked')
    volume = topology.get('signed_volume_mm3', float('nan'))
    if not np.isfinite(volume) or volume <= 0:
        reasons.append('nonpositive_or_invalid_signed_volume')
    if hemisphere_position_consistent is False:
        reasons.append('hemisphere_position_mismatch')
    return reasons


def read_decoded(path):
    data = path.read_bytes()
    count, triangles, primitives = struct.unpack_from('<III', data)
    positions = np.frombuffer(data, dtype='<f8', count=count*3, offset=12).reshape(-1, 3)
    normals = np.frombuffer(data, dtype='<f8', count=count*3, offset=12+count*24).reshape(-1, 3)
    faces = np.frombuffer(data, dtype='<u4', count=triangles*3, offset=12+count*48).reshape(-1, 3)
    if not np.isfinite(positions).all() or (faces.size and int(faces.max()) >= count):
        raise ValueError('Non-finite vertex or out-of-bounds triangle index')
    return positions, normals, faces, primitives


def resolve_mesh(export, row):
    declared = export / row['mesh_glb']
    if declared.is_file():
        return declared
    # This export renamed the models directory to regions; preserve the subpath.
    relative = Path(row['mesh_glb'])
    if relative.parts[0] == 'models':
        candidate = export / 'regions' / Path(*relative.parts[1:])
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Missing GLB for {row['region_id']}: {declared}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, default=ROOT/'segmentation_export')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--region', action='append', default=[], help='Audit only these exact region IDs; repeat as needed')
    parser.add_argument('--intersections', action='store_true', help='Compile/run numerical BVH triangle intersection screening')
    args = parser.parse_args()
    if not args.node:
        parser.error('Node.js is required; pass --node /path/to/node')
    output = args.output or args.export/'geometry_validation.json'
    rows = list(csv.DictReader((args.export/'regions_manifest.tsv').open(), delimiter='\t'))
    if args.region:
        requested=set(args.region)
        rows=[row for row in rows if row['region_id'] in requested]
        if {row['region_id'] for row in rows} != requested:
            parser.error('Unknown requested region_id')
    paths = [resolve_mesh(args.export, row).resolve() for row in rows]
    records = []
    with tempfile.TemporaryDirectory(prefix='neuroatlas-mesh-audit-') as temporary:
        temp = Path(temporary)
        requests = [{'input':str(p), 'output':str(temp/f'{i}.bin'), 'metadata':str(temp/f'{i}.json')} for i,p in enumerate(paths)]
        subprocess.run([args.node, str(ROOT/'scripts/decode_geometry.mjs')], input=json.dumps(requests), text=True, check=True)
        detector = None
        if args.intersections:
            detector = temp/'mesh_intersections'
            subprocess.run(['g++','-O3','-std=c++17',str(ROOT/'scripts/mesh_intersections.cpp'),'-o',str(detector)], check=True)
        for i,(row,path) in enumerate(zip(rows, paths)):
            vertices, normals, faces, primitives = read_decoded(temp/f'{i}.bin')
            normal_metadata = json.loads((temp/f'{i}.json').read_text())['normals']
            topology, welded, welded_faces = inspect_topology(vertices, normals, faces)
            intersections = {'status':'not_checked'}
            if detector:
                detector_input = temp/'intersections.bin'
                with detector_input.open('wb') as stream:
                    stream.write(struct.pack('<II',len(welded),len(welded_faces)))
                    stream.write(welded.astype('<f8').tobytes())
                    stream.write(welded_faces.astype('<u4').tobytes())
                result = subprocess.run([str(detector),str(detector_input)], capture_output=True, text=True, check=True)
                intersections = json.loads(result.stdout)
                topology['nonmanifold_vertices'] = intersections.pop('nonmanifold_vertices')
                topology['vertex_links_checked'] = intersections.pop('vertex_links_checked')
                topology['watertight'] = topology['watertight'] and topology['nonmanifold_vertices'] == 0
            reasons = []
            if not topology['watertight']: reasons.append('topology_not_watertight')
            if not topology['consistent_winding']: reasons.append('inconsistent_triangle_winding')
            if topology['signed_volume_mm3'] <= 0: reasons.append('nonpositive_signed_volume')
            if topology['normal_zero_or_invalid']: reasons.append('invalid_normals')
            if topology['duplicate_triangles']: reasons.append('duplicate_triangles')
            if intersections.get('intersecting_pairs',0): reasons.append('self_intersections_detected')
            if intersections['status'] == 'not_checked': reasons.append('self_intersections_not_checked')
            segmented = float(row['volume_mm3']) if row['volume_mm3'].strip() else None
            centroid = vertices.mean(axis=0)
            name = row['region']
            hemisphere = 'left' if name.startswith(('lh.', 'lh_')) else 'right' if name.startswith(('rh.', 'rh_')) else None
            hemisphere_position_consistent = None if hemisphere is None else bool(centroid[0] < 0 if hemisphere == 'left' else centroid[0] > 0)
            if hemisphere_position_consistent is False: reasons.append('hemisphere_position_mismatch')
            stencil_reasons = stencil_ineligibility_reasons(topology, hemisphere_position_consistent)
            records.append({
                'region_id': row['region_id'], 'path': str(path.relative_to(args.export.resolve())),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes':path.stat().st_size,
                'primitives':primitives, 'normal_data':normal_metadata,
                'bounds_mm':[vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()],
                'vertex_centroid_mm':centroid.tolist(), 'hemisphere':hemisphere,
                'hemisphere_position_consistent':hemisphere_position_consistent, 'topology':topology,
                'segmented_volume_mm3':segmented,
                'mesh_to_segmented_volume_ratio':topology['signed_volume_mm3']/segmented if segmented else None,
                'self_intersections':intersections, 'cut_eligible':not reasons, 'cut_ineligibility_reasons':reasons,
                'stencil_cut_eligible':not stencil_reasons, 'stencil_ineligibility_reasons':stencil_reasons,
            })
            print(f"{i+1}/{len(rows)} {row['region_id']}: boundary={topology['boundary_edges']} nonmanifold={topology['nonmanifold_edges']} intersections={intersections.get('intersecting_pairs','unchecked')}", flush=True)
    reference = args.export/'reference'
    if not reference.is_dir():
        reference = args.export/'export_brain_mirror_source_v3_solid'/'reference'
    if not reference.is_dir() and (args.export/'extraction_metrics.json').is_file():
        extraction = json.loads((args.export/'extraction_metrics.json').read_text())
        reference = Path(extraction['source'])/'reference'
    reference_available = (reference/'vox2ras_tkras.txt').is_file()
    reference_metadata = None
    if reference_available:
        affine = np.loadtxt(reference/'vox2ras_tkras.txt')
        reference_metadata = {'path':os.path.relpath(reference,args.export), 'vox2ras_tkras':affine.tolist(),
            'voxel_spacing_mm':np.linalg.norm(affine[:3,:3],axis=0).tolist(),
            'vox2ras_tkras_sha256':hashlib.sha256((reference/'vox2ras_tkras.txt').read_bytes()).hexdigest(),
            'gltf_transform':'(x,y,z)_tkRAS -> (x,z,-y)_glTF',
            'mri_reference_present':(reference/'T1.nii.gz').is_file()}
    report = {
        'schema_version':2,
        'source_reference':reference_metadata,
        'source_manifest_sha256':hashlib.sha256((args.export/'regions_manifest.tsv').read_bytes()).hexdigest(),
        'method':{
            'decoder':'vendored Three.js r152 MeshoptDecoder; KHR_mesh_quantization and complete node hierarchy transforms applied',
            'topology':'Exact position welding; undirected edge incidence and directed winding; degenerate/duplicate triangles; signed volume; normal-to-face dot products',
            'stencil_cut_policy':'Closed oriented triangle chain: zero boundary edges, zero oriented edge imbalance, finite positive algebraic volume and matching hemisphere. Vertex links must be audited; nonmanifold contacts remain quality findings but do not invalidate integer winding. Independent of shading normals and strict self-intersection quality checks.',
            'coordinate_system':{'axes':{'x':'right','y':'superior','z':'posterior'},'units':'millimetres',
                'confidence':'Confirmed by supplied source README, tkRAS affine and bilateral/landmark geometry checks' if reference_available else 'Inferred from bilateral hemispheres, superior cortex, brainstem and gland landmarks; original affine/MRI missing'},
            'self_intersection_screening':'Double-precision BVH; excludes degenerate triangles and tangential/edge-only contacts; checks proper non-coplanar crossings and positive-area coplanar overlaps. Not an exact-arithmetic certification.',
            'limitations':[
                'Source MRI/masks/affine are available; this mesh audit checks coordinate metadata and geometric plausibility, not clinical segmentation accuracy or MRI voxel registration.' if reference_available else 'Original MRI, masks and FreeSurfer affine are absent: precise anatomical registration and segmentation accuracy cannot be verified.',
                'Tangential/edge-only contacts are not reported. Shared-vertex triangle pairs are still screened for proper crossings and positive-area coplanar overlaps.',
                'Inter-region overlaps are not checked. Closed vertex links are checked when --intersections is enabled; otherwise topology is limited to edges and nondegenerate faces.',
                'Smoothed normals opposing individual sharply folded triangle faces are reported diagnostically; they do not alone disable caps.',
                'When NORMAL is absent, normals are derived from the supplied triangles exactly as in the viewer fallback; explicit zero/invalid supplied normals are not replaced. Per-region normal_data records the origin.',
                'Signed volume is algebraic and may be misleading for self-intersecting meshes.',
                'cut_eligible retains the strict mesh-quality gate. stencil_cut_eligible permits winding-count sections of closed oriented surfaces, including local intersections and zero-volume sheets. Neither certifies anatomical correctness or repairs defects.',
            ],
        },
        'summary':{
            'regions':len(records), 'total_bytes':sum(r['bytes'] for r in records),
            'total_triangles':sum(r['topology']['triangles'] for r in records),
            'watertight_regions':sum(r['topology']['watertight'] for r in records),
            'consistent_winding_regions':sum(r['topology']['consistent_winding'] for r in records),
            'hemisphere_position_mismatches':sum(r['hemisphere_position_consistent'] is False for r in records),
            'max_mesh_volume_relative_error':max(abs(r['mesh_to_segmented_volume_ratio']-1) for r in records if r['mesh_to_segmented_volume_ratio'] is not None),
            'regions_with_self_intersections':sum(r['self_intersections'].get('intersecting_pairs',0)>0 for r in records),
            'cut_eligible_regions':sum(r['cut_eligible'] for r in records),
            'stencil_cut_eligible_regions':sum(r['stencil_cut_eligible'] for r in records),
            'bounds_mm':[np.min([r['bounds_mm'][0] for r in records],axis=0).tolist(),np.max([r['bounds_mm'][1] for r in records],axis=0).tolist()],
        }, 'regions':records,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'],indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Numerical cross-region triangle screening using the same offline BVH as mesh QA.

This checks proper crossings and positive-area coplanar overlaps. It does not
measure overlap volume, check containment, or certify exact geometry.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import numpy as np

from validate_geometry import ROOT, read_decoded, resolve_mesh


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--node',default=shutil.which('node'))
    parser.add_argument('--region',action='append',default=[])
    args=parser.parse_args()
    if not args.node:parser.error('Node.js is required; pass --node')
    rows=list(csv.DictReader((args.export/'regions_manifest.tsv').open(),delimiter='\t'))
    if args.region:rows=[r for r in rows if r['region_id'] in set(args.region)]
    paths=[resolve_mesh(args.export,row) for row in rows]
    with tempfile.TemporaryDirectory(prefix='neuroatlas-interface-qa-') as temporary:
        temp=Path(temporary)
        requests=[{'input':str(p),'output':str(temp/f'{i}.bin')} for i,p in enumerate(paths)]
        subprocess.run([args.node,str(ROOT/'scripts/decode_geometry.mjs')],input=json.dumps(requests),text=True,check=True)
        all_vertices=[];all_faces=[];all_groups=[];offset=0
        for i in range(len(rows)):
            vertices,_,faces,_=read_decoded(temp/f'{i}.bin')
            all_vertices.append(vertices);all_faces.append(faces+offset);all_groups.append(np.full(len(faces),i,dtype='<u4'))
            offset+=len(vertices)
        vertices=np.concatenate(all_vertices);faces=np.concatenate(all_faces).astype('<u4');groups=np.concatenate(all_groups)
        binary=temp/'combined.bin'
        with binary.open('wb') as stream:
            stream.write(struct.pack('<II',len(vertices),len(faces)));stream.write(vertices.astype('<f8').tobytes());stream.write(faces.tobytes());stream.write(groups.tobytes())
        detector=temp/'mesh_intersections'
        subprocess.run(['g++','-O3','-std=c++17',str(ROOT/'scripts/mesh_intersections.cpp'),'-o',str(detector)],check=True)
        raw=subprocess.run([str(detector),str(binary),'--between-regions'],capture_output=True,text=True,check=True)
        result=json.loads(raw.stdout)
        result.pop('nonmanifold_vertices',None);result.pop('vertex_links_checked',None)
        result['region_pairs']=[{'region_a':rows[a]['region_id'],'region_b':rows[b]['region_id'],'intersecting_triangle_pairs':count,'proper_crossing_pairs':proper,'coplanar_overlap_pairs':coplanar} for a,b,count,proper,coplanar in result.pop('region_pair_counts')]
        result['method']='Double-precision BVH, proper crossings and positive-area coplanar overlaps; no overlap-volume or containment test, tangent contacts excluded'
        result['regions']=[{'region_id':r['region_id'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for r,p in zip(rows,paths)]
        result['summary']={'regions':len(rows),'intersecting_triangle_pairs':result['intersecting_pairs'],'affected_region_pairs':len(result['region_pairs'])}
        output=args.output or args.export/'interface_validation.json'
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result['summary'],indent=2))


if __name__=='__main__':main()

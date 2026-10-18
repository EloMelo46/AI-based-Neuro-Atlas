"""Local MRI volumes and source-aware segmentation, in the selected scan's grid.

Only explicitly catalogued images are served. Derived files live in .local;
the uploaded FreeSurfer subject is never modified or exposed as a directory.
"""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import threading

from flask import Blueprint, abort, request, send_file
import nibabel as nib
import numpy as np
from scipy.ndimage import affine_transform

from .mesh_catalog import _identity

SCANS = {
    'brain': ('brain.mgz', 'Brain Only', 'MRT-Aufnahme mit freigestelltem Gehirn'),
    'original': ('orig/001.mgz', 'Original MRI', 'Originale MRT-Aufnahme des ganzen Kopfes'),
}
SOURCES = {
    'dkt': 'aparc.DKTatlas+aseg.mgz',
    'aseg': 'aseg.mgz',
    'brainstem': 'brainstemSsLabels.FSvoxelSpace.mgz',
    'hypothalamus': 'hypothalamic_subunits_seg.v1.mgz',
    'pglands': 'T1.pglands.mgz',
    'claustrum_lh': 'claustrum/claustrum.lh.nii.gz',
    'claustrum_rh': 'claustrum/claustrum.rh.nii.gz',
}


def mri_regions():
    """Public FreeSurfer label identities only; no meshes or personal measurements."""
    records = json.loads(Path(__file__).with_name('mri_regions.json').read_text())
    for region in records:
        name, hemisphere, aliases = _identity(region['region_id'])
        region.update(name=name.replace(chr(223), 'ss'), hemisphere=hemisphere,
                      aliases=aliases, selectable=True, highlightable=True)
    return records


def source_key(region):
    if region['source'] == 'claustrum':
        return 'claustrum_lh' if region['hemisphere'] == 'left' else 'claustrum_rh'
    return region['source']


class MRIStore:
    def __init__(self, subject_dir, export_dir, cache_dir):
        self.root = Path(subject_dir).resolve() / 'mri'
        self.export_dir = Path(export_dir)
        self.cache = Path(cache_dir)
        self.lock = threading.RLock()

    def _file(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('Die benötigte MRT-Datei fehlt: ' + relative)
        return path

    def regions(self):
        return {r['region_id']: r for r in mri_regions()}

    def _key(self, *paths, extra=''):
        stats = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
        return hashlib.sha256(json.dumps([4, stats, extra], sort_keys=True).encode()).hexdigest()[:32]

    def catalog(self):
        scans = [dict(id=key, name=name, description=description)
                 for key, (path, name, description) in SCANS.items() if (self.root / path).is_file()]
        available = {key for key, path in SOURCES.items() if (self.root / path).is_file()}
        return dict(scans=scans, regions=[r['region_id'] for r in self.regions().values()
                                        if source_key(r) in available])

    def _save(self, data, affine, path):
        image = nib.Nifti1Image(data, affine)
        image.set_qform(affine, code=1)
        image.set_sform(affine, code=1)
        image.header.set_xyzt_units('mm')
        # Preserve measured values, including original floating-point images.
        image.header['cal_min'] = 0
        image.header['cal_max'] = float(np.max(data))
        tmp = path.with_name('tmp-' + path.name)
        nib.save(image, tmp)
        tmp.replace(path)

    def scan(self, scan_id):
        if scan_id not in SCANS:
            raise ValueError('Unbekannte MRT-Aufnahme.')
        source = self._file(SCANS[scan_id][0])
        key = self._key(source)
        with self.lock:
            folder = self.cache / key
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / 'scan.nii.gz'
            if not output.exists():
                volume = nib.load(source)
                data = np.asanyarray(volume.dataobj)
                if data.ndim != 3:
                    raise ValueError('Für diese Ansicht wird eine dreidimensionale MRT-Aufnahme benötigt.')
                self._save(data, volume.affine, output)
            return dict(url=f'/api/mri/files/{key}/scan.nii.gz', scan=scan_id)

    def _labels(self, source_key_value, reference):
        source = self._file(SOURCES[source_key_value])
        key = self._key(source, extra=json.dumps([list(map(int, reference.shape)), reference.affine.tolist()]))
        path = self.cache / (key + '.npy')
        if not path.exists():
            image = nib.load(source)
            data = np.asanyarray(image.dataobj).squeeze()
            transform = np.linalg.inv(image.affine) @ reference.affine
            if data.shape != reference.shape or not np.allclose(transform, np.eye(4), atol=1e-5):
                data = affine_transform(data, transform[:3, :3], transform[:3, 3],
                                        output_shape=reference.shape, output=np.int16,
                                        order=0, mode='constant', cval=0, prefilter=False)
            temporary = path.with_name('tmp-' + path.name)
            np.save(temporary, data.astype(np.int16))
            temporary.replace(path)
        return np.load(path, mmap_mode='r')

    def selection(self, scan_id, ids):
        if not isinstance(ids, list) or not ids or len(ids) > 200 or any(not isinstance(x, str) for x in ids):
            raise ValueError('Mindestens eine gültige MRT-Region auswählen.')
        regions = self.regions()
        if any(i not in regions for i in ids):
            raise ValueError('Unbekannte MRT-Region.')
        ids = sorted(set(ids))
        if scan_id not in SCANS:
            raise ValueError('Unbekannte MRT-Aufnahme.')
        source = self._file(SCANS[scan_id][0])
        sources = {source_key(regions[i]) for i in ids}
        if not sources <= SOURCES.keys():
            raise ValueError('Für diese Region ist keine MRT-Segmentierung verfügbar.')
        files = [self._file(SOURCES[k]) for k in sorted(sources)]
        key = self._key(source, *files, extra=json.dumps([(i, regions[i]['label_ids']) for i in ids]))
        with self.lock:
            folder = self.cache / key
            folder.mkdir(parents=True, exist_ok=True)
            metadata = folder / 'selection.json'
            if metadata.exists():
                return json.loads(metadata.read_text())
            reference = nib.load(source)
            labels = np.zeros(reference.shape, dtype=np.uint16)
            grouped = defaultdict(list)
            for value, region_id in enumerate(ids, 1):
                grouped[source_key(regions[region_id])].append((value, regions[region_id]))
            for kind, group in grouped.items():
                data = self._labels(kind, reference)
                for value, region in group:
                    mask = np.isin(data, region['label_ids'])
                    if not np.any(mask):
                        raise ValueError('Keine passenden Segmentierungsvoxel für ' + region['name'])
                    labels[mask] = value
            # Choose an actual selected voxel near the centre, even for disjoint ROIs.
            occupied = labels != 0
            total = np.count_nonzero(occupied)
            middle = [np.dot(np.arange(occupied.shape[axis]), occupied.sum(axis=tuple(i for i in range(3) if i != axis))) / total
                      for axis in range(3)]
            best = float('inf')
            # Bound temporary memory even when selecting the entire cortex.
            for x in range(occupied.shape[0]):
                y, z = np.nonzero(occupied[x])
                if not len(y):
                    continue
                distances = (x - middle[0]) ** 2 + (y - middle[1]) ** 2 + (z - middle[2]) ** 2
                candidate = distances.argmin()
                if distances[candidate] < best:
                    best = distances[candidate]
                    centre = [x, y[candidate], z[candidate]]
            centre_mm = nib.affines.apply_affine(reference.affine, centre).tolist()
            self._save(labels, reference.affine, folder / 'labels.nii.gz')
            result = dict(region_ids=ids, center_mm=centre_mm,
                          labels_url=f'/api/mri/files/{key}/labels.nii.gz',
                          names=[regions[i]['name'] for i in ids])
            metadata.write_text(json.dumps(result))
            return result


def create_mri_blueprint(project_root, export_dir, store=None):
    bp = Blueprint('mri', __name__)
    store = store or MRIStore(os.environ.get('NEURO_ATLAS_MRI_DIR', str(project_root / 'original_mri')),
                             export_dir, project_root / '.local' / 'mri')

    @bp.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.errorhandler(ValueError)
    def invalid(error):
        return {'error': str(error)}, 400

    @bp.get('/api/mri/catalog')
    def catalog():
        return store.catalog()

    @bp.get('/api/mri/scan/<scan_id>')
    def scan(scan_id):
        return store.scan(scan_id)

    @bp.post('/api/mri/selection')
    def selection():
        if request.headers.get('X-Brain-Viewer') != '1':
            abort(403)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('scan'), str):
            raise ValueError('Ungültige MRT-Auswahl.')
        return store.selection(body['scan'], body.get('region_ids'))

    @bp.get('/api/mri/files/<key>/<filename>')
    def file(key, filename):
        if not re.fullmatch(r'[a-f0-9]{32}', key) or filename not in ('scan.nii.gz', 'labels.nii.gz'):
            abort(404)
        path = store.cache / key / filename
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='application/octet-stream', conditional=True)

    return bp

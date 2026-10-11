"""Manifest-backed solid-region catalog shared by viewer and assistant.

The active export uses the manifest's ``models/`` paths directly. Older
deliveries with that directory renamed to ``regions/`` remain supported.
"""
import csv
import math
import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from .region_vocabulary import (names_for, normalize_selection_name, SELECTION_SHORTCUTS,
                                SPINAL_CORD_NOTE, UNAVAILABLE_NARRATION_NAMES)

# Kept for callers that explicitly reject retired whole-hemisphere surfaces.
EXCLUDED_MESH_FILES = frozenset({
    'lh.pial.obj', 'rh.pial.obj', 'lh.white.obj', 'rh.white.obj', 'lh_hippo_mc.obj',
})
DEFAULT_EXPORT_DIR = Path(os.environ.get('NEURO_ATLAS_EXPORT_DIR',
    Path(__file__).resolve().parent.parent / 'segmentation_export')).resolve()

CORTEX_NAMES = {
    'caudalanteriorcingulate': 'Kaudaler anteriorer cingulärer Kortex',
    'caudalmiddlefrontal': 'Mittlerer frontaler Gyrus (kaudal)',
    'cuneus': 'Cuneus', 'entorhinal': 'Entorhinaler Kortex', 'fusiform': 'Gyrus fusiformis',
    'inferiorparietal': 'Inferiorer Parietallappen', 'inferiortemporal': 'Inferiorer temporaler Gyrus',
    'isthmuscingulate': 'Isthmus des cingulären Kortex', 'lateraloccipital': 'Lateraler okzipitaler Kortex',
    'lateralorbitofrontal': 'Lateraler orbitofrontaler Kortex', 'lingual': 'Gyrus lingualis',
    'medialorbitofrontal': 'Medialer orbitofrontaler Kortex', 'middletemporal': 'Mittlerer temporaler Gyrus',
    'parahippocampal': 'Parahippocampaler Kortex', 'paracentral': 'Lobulus paracentralis',
    'parsopercularis': 'Pars opercularis', 'parsorbitalis': 'Pars orbitalis',
    'parstriangularis': 'Pars triangularis', 'pericalcarine': 'Pericalcariner Kortex',
    'postcentral': 'Gyrus postcentralis', 'posteriorcingulate': 'Posteriorer cingulärer Kortex',
    'precentral': 'Gyrus praecentralis', 'precuneus': 'Precuneus',
    'rostralanteriorcingulate': 'Rostraler anteriorer cingulärer Kortex',
    'rostralmiddlefrontal': 'Mittlerer frontaler Gyrus (rostral)',
    'superiorfrontal': 'Superiorer frontaler Gyrus', 'superiorparietal': 'Superiorer Parietallappen',
    'superiortemporal': 'Superiorer temporaler Gyrus', 'supramarginal': 'Gyrus supramarginalis',
    'transversetemporal': 'Transversaler temporaler Kortex (Heschl)', 'insula': 'Insula',
}
STRUCTURE_NAMES = {
    'cerebral_white_matter': 'Großhirnmarklager', 'cerebellar_white_matter': 'Kleinhirnmarklager',
    'cerebellar_cortex': 'Kleinhirnrinde', 'thalamus': 'Thalamus', 'caudate': 'Nucleus caudatus',
    'putamen': 'Putamen', 'pallidum': 'Globus pallidus', 'hippocampus': 'Hippocampus',
    'amygdala': 'Amygdala', 'accumbens': 'Nucleus accumbens', 'corpus_callosum': 'Corpus callosum',
    'lateral_ventricle': 'Seitenventrikel', 'third_ventricle': 'III. Ventrikel',
    'fourth_ventricle': 'IV. Ventrikel', 'midbrain': 'Mittelhirn', 'pons': 'Pons',
    'medulla': 'Medulla oblongata', 'superior_cerebellar_peduncle': 'Oberer Kleinhirnstiel',
    'hypothalamus': 'Hypothalamus', 'hypophyse': 'Hypophyse', 'epiphyse': 'Epiphyse',
    'infundibulum': 'Infundibulum', 'claustrum': 'Claustrum',
    'missing_csf_24': 'Zusätzlicher Liquor (CSF)',
}
LEGACY_STRUCTURES = {
    'cerebral_white_matter': 'Cerebral-White-Matter',
    'cerebellar_white_matter': 'Cerebellum-White-Matter', 'cerebellar_cortex': 'Cerebellum-Cortex',
    'thalamus': 'Thalamus', 'caudate': 'Caudate', 'putamen': 'Putamen', 'pallidum': 'Pallidum',
    'hippocampus': 'Hippocampus', 'amygdala': 'Amygdala', 'accumbens': 'Accumbens-area',
    'lateral_ventricle': 'Lateral-Ventricle', 'hypothalamus': 'Hypothalamus', 'claustrum': 'Claustrum',
}


def region_hemisphere(region):
    if region.startswith(('lh.', 'lh_')):
        return 'left'
    if region.startswith(('rh.', 'rh_')):
        return 'right'
    return 'midline'


def _labels(value):
    result = []
    for item in value.split(','):
        match = re.fullmatch(r'(\d+)(?:-(\d+))?', item.strip())
        if not match:
            raise ValueError(f'Ungültige Label-IDs: {value}')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 0 <= end - start <= 1000:
            raise ValueError(f'Ungültiger Label-Bereich: {value}')
        result.extend(range(start, end + 1))
    return result


def _flag(row, name, default=True):
    value = row.get(name, '').strip().lower()
    if not value:
        return default
    if value not in ('true', 'false'):
        raise ValueError(f'Ungültiger Manifest-Schalter {name}: {value}')
    return value == 'true'


def _mesh_path(directory, value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in value or path.suffix.lower() != '.glb':
        raise ValueError(f'Ungültiger GLB-Pfad im Manifest: {value}')
    candidates = [path]
    if path.parts[0] == 'models':
        candidates.append(PurePosixPath('regions', *path.parts[1:]))
    for candidate in candidates:
        asset = directory / str(candidate)
        if not asset.resolve().is_relative_to(directory):
            raise ValueError(f'GLB-Pfad verlässt das Exportverzeichnis: {value}')
        if asset.is_file():
            return candidate.as_posix()
    raise ValueError(f'GLB aus Manifest fehlt: {value}')


def _identity(region_id):
    """Return aliases and display metadata without guessing anatomical equivalence."""
    region = region_id.split('.', 2)[2]
    hemisphere = region_hemisphere(region)
    bare = region[3:] if hemisphere != 'midline' else region
    name = CORTEX_NAMES.get(bare, STRUCTURE_NAMES.get(bare, bare.replace('_', ' ')))
    aliases = [region]
    if hemisphere != 'midline':
        name += ' links' if hemisphere == 'left' else ' rechts'
        if bare in LEGACY_STRUCTURES:
            aliases.append(('Left-' if hemisphere == 'left' else 'Right-') + LEGACY_STRUCTURES[bare])
    if bare == 'third_ventricle':
        aliases.append('3rd-Ventricle')
    elif bare == 'fourth_ventricle':
        aliases.append('4th-Ventricle')
    elif bare == 'corpus_callosum':
        aliases.append('Corpus-Callosum')
    return name, hemisphere, aliases


@lru_cache(maxsize=8)
def _read_manifest(root, modified_ns, size):
    directory = Path(root)
    records = []
    seen_ids, seen_paths = set(), set()
    with (directory / 'regions_manifest.tsv').open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        required = {'region_id', 'category', 'source', 'region', 'label_ids', 'mesh_glb', 'volume_mm3', 'status'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Unvollständige Spalten im Regionsmanifest.')
        for row in reader:
            region_id = row['region_id']
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', region_id) or region_id.count('.') < 2:
                raise ValueError(f'Ungültige region_id: {region_id}')
            if region_id in seen_ids:
                raise ValueError(f'Doppelte region_id: {region_id}')
            if row['status'] != 'complete':
                raise ValueError(f'Region nicht vollständig exportiert: {region_id} ({row["status"]})')
            path = _mesh_path(directory, row['mesh_glb'])
            if path in seen_paths:
                raise ValueError(f'Doppelte GLB-Geometrie: {path}')
            seen_ids.add(region_id)
            seen_paths.add(path)
            name, hemisphere, aliases = _identity(region_id)
            volume = float(row['volume_mm3']) if row['volume_mm3'].strip() else None
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                raise ValueError(f'Ungültiges Volumen: {region_id}')
            record = dict(row, mesh_glb=path, manifest_mesh_glb=row['mesh_glb'],
                          name=name, hemisphere=hemisphere, aliases=aliases,
                          label_ids=_labels(row['label_ids']), volume_mm3=volume)
            role = row.get('render_role') or 'anatomy'
            if role not in ('anatomy', 'fill'):
                raise ValueError(f'Unbekannte Darstellungsrolle: {role}')
            record['render_role'] = role
            for field in ('renderable', 'selectable', 'highlightable', 'default_visible', 'visible_in_slice'):
                record[field] = _flag(row, field)
            if role == 'fill':
                record.update(selectable=False, highlightable=False)
            for field in ('triangles_source', 'triangles_optimized', 'source_bytes', 'optimized_bytes'):
                if row.get(field):
                    record[field] = int(row[field])
            if row.get('simplify_ratio'):
                record['simplify_ratio'] = float(row['simplify_ratio'])
            records.append(record)
    if not records:
        raise ValueError('Das Regionsmanifest ist leer.')
    return tuple(records)


def load_regions(directory=DEFAULT_EXPORT_DIR):
    directory = Path(directory).resolve()
    stat = (directory / 'regions_manifest.tsv').stat()
    # Return independent dictionaries; route-specific URLs/QA must not mutate cache.
    return [dict(record, aliases=list(record['aliases']), label_ids=list(record['label_ids']))
            for record in _read_manifest(str(directory), stat.st_mtime_ns, stat.st_size)]


def available_mesh_names(directory=DEFAULT_EXPORT_DIR):
    return [record['mesh_glb'] for record in load_regions(directory) if record['renderable']]


def available_region_ids(directory=DEFAULT_EXPORT_DIR):
    """The assistant/selection catalog excludes technical filling geometries."""
    return [record['region_id'] for record in load_regions(directory)
            if record['renderable'] and record['selectable']]


def selection_aliases(directory=DEFAULT_EXPORT_DIR):
    from .region_groups import groups_for_ids
    records = [record for record in load_regions(directory) if record['renderable'] and record['selectable']]
    ids = [record['region_id'] for record in records]
    aliases = aliases_for_ids(ids)
    for record in records:
        aliases[record['name']] = [record['region_id']]
    for group in groups_for_ids(ids):
        for alias in [group['group_id'], *group['aliases']]:
            aliases[alias] = list(group['region_ids'])
    # Block shorter generic narration names from selecting the wrong structure.
    aliases.update({name: [] for name in UNAVAILABLE_NARRATION_NAMES})
    return aliases


def aliases_for_ids(ids):
    """Shared anatomical names and legacy selections resolve to whole labels."""
    known = set(ids)
    aliases = {}
    for region_id in ids:
        if region_id.count('.') < 2:
            continue
        for alias in _identity(region_id)[2]:
            aliases[alias] = [region_id]
        region = region_id.split('.', 2)[2]
        hemisphere = region_hemisphere(region)
        bare = region[3:] if hemisphere != 'midline' else region
        display = CORTEX_NAMES.get(bare, STRUCTURE_NAMES.get(bare, bare.replace('_', ' ')))
        for alias in names_for(bare, display):
            aliases.setdefault(alias, []).append(region_id)
            if hemisphere != 'midline':
                side = 'links' if hemisphere == 'left' else 'rechts'
                aliases.setdefault(f'{alias} {side}', []).append(region_id)
    for side, hemi in [('Left', 'lh'), ('Right', 'rh')]:
        cortex = [value for value in ids if value.startswith(f'cortex.dkt.{hemi}.')]
        if cortex:
            aliases[f'{side}-Cerebral-Cortex'] = cortex
        lateral = f'ventricular_system.aseg.{hemi}_lateral_ventricle'
        if lateral in known:
            aliases[f'{side}-Inf-Lat-Vent'] = [lateral]
    callosum = 'subcortex.aseg.corpus_callosum'
    if callosum in known:
        for part in ('Anterior', 'Mid_Anterior', 'Central', 'Mid_Posterior', 'Posterior'):
            aliases[f'CC_{part}'] = [callosum]
    brainstem = [value for value in ids if value in {
        'subcortex.brainstem.midbrain', 'subcortex.brainstem.pons', 'subcortex.brainstem.medulla'}]
    if brainstem:
        aliases['Brain-Stem'] = brainstem
    return {name: list(dict.fromkeys(members)) for name, members in aliases.items()}


def assistant_vocabulary_context(ids):
    """Compact base names once per label family, with explicit command shortcuts."""
    families = {}
    for region_id in ids:
        if region_id.count('.') < 2:
            continue
        region = region_id.split('.', 2)[2]
        bare = region[3:] if region_hemisphere(region) != 'midline' else region
        display = CORTEX_NAMES.get(bare, STRUCTURE_NAMES.get(bare, bare.replace('_', ' ')))
        family = families.setdefault(bare, {'region_ids': [], 'names': names_for(bare, display)})
        family['region_ids'].append(region_id)
    return {'regions': list(families.values()),
            'selection_shortcuts': [{'name': name, 'region_id': target, 'note': SPINAL_CORD_NOTE}
                                   for name, target in SELECTION_SHORTCUTS.items() if target in ids]}


def region_groups(directory=DEFAULT_EXPORT_DIR):
    from .region_groups import groups_for_ids
    return groups_for_ids(available_region_ids(directory))


def expand_region_ids(values, ids):
    """Expand groups and old IDs, returning a deterministic deduplicated selection."""
    from .region_groups import groups_for_ids
    known = set(ids)
    if all(value in known for value in values):
        return list(dict.fromkeys(values))
    aliases = aliases_for_ids(ids)
    for group in groups_for_ids(ids):
        for alias in [group['group_id'], *group['aliases']]:
            aliases[alias] = group['region_ids']
    # These are requested selection conventions, not anatomical narration names.
    aliases.update({name: [target] for name, target in SELECTION_SHORTCUTS.items() if target in known})
    normalized = {normalize_selection_name(name): members for name, members in aliases.items()}
    result = []
    for value in values:
        targets = [value] if value in known else normalized.get(normalize_selection_name(value))
        if not targets:
            raise ValueError('Unbekanntes Areal.')
        for target in targets:
            if target not in result:
                result.append(target)
    return result

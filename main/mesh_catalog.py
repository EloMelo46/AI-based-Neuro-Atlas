"""Mesh selection shared by the viewer, assistant and download routes."""

# Keep source assets on disk, but do not expose alternative surfaces or duplicates.
EXCLUDED_MESH_FILES = frozenset({
    'lh.pial.obj', 'rh.pial.obj',
    'lh.white.obj', 'rh.white.obj',
    'lh_hippo_mc.obj',
})


def available_mesh_names(directory):
    return sorted(path.name for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() == '.obj'
                  and path.name.lower() not in EXCLUDED_MESH_FILES)


def available_region_ids(directory):
    return [name[:-4] for name in available_mesh_names(directory)]

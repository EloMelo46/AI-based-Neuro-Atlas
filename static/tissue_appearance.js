// Muted explanatory cut colors, inspired by gross gray/white matter contrast.
// Neighboring nuclei get gentle variations; these are not measured tissue colors.
const CUT_COLORS = {
  'Cerebral-Cortex': 0xb89d90,
  'Cerebellum-Cortex': 0xaf9487,
  'Cerebral-White-Matter': 0xddd3b9,
  'Cerebellum-White-Matter': 0xd8ccb0,
  'Brain-Stem': 0xc7b49c,
  Thalamus: 0xc4aca0,
  Hippocampus: 0xaf9598,
  Amygdala: 0xbf9990,
  Caudate: 0xc6a38c,
  Putamen: 0xaf9484,
  Pallidum: 0xcbbca2,
  VentralDC: 0xb3a794,
  'Accumbens-area': 0xbca19f,
  'WM-hypointensities': 0xbeb49f,
};

export function naturalCutColor(id) {
  const name = id.replace(/^(Left|Right)-/, '');
  if (name.startsWith('CC_')) return 0xdfd4bd;
  // Fluid spaces are deliberately cooler than tissue.
  if (/Ventricle|Inf-Lat-Vent|^CSF$/.test(name)) return 0x8c9c9d;
  return CUT_COLORS[name] ?? 0xc3aa9c;
}

// Bake low-frequency tissue variation once per geometry, not per fragment/frame.
const preparedGeometries = new WeakSet();
const fract = value => value - Math.floor(value);
const mix = (a, b, t) => a + (b - a) * t;
function tissueHash(x, y, z) {
  x = fract(x * 0.1031); y = fract(y * 0.1031); z = fract(z * 0.1031);
  const d = x * (y + 33.33) + y * (z + 33.33) + z * (x + 33.33);
  return fract((x + y + 2 * d) * (z + d));
}
function tissueNoise(x, y, z) {
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z);
  let fx = fract(x), fy = fract(y), fz = fract(z);
  fx *= fx * (3 - 2 * fx); fy *= fy * (3 - 2 * fy); fz *= fz * (3 - 2 * fz);
  return mix(
    mix(mix(tissueHash(ix, iy, iz), tissueHash(ix + 1, iy, iz), fx),
        mix(tissueHash(ix, iy + 1, iz), tissueHash(ix + 1, iy + 1, iz), fx), fy),
    mix(mix(tissueHash(ix, iy, iz + 1), tissueHash(ix + 1, iy, iz + 1), fx),
        mix(tissueHash(ix, iy + 1, iz + 1), tissueHash(ix + 1, iy + 1, iz + 1), fx), fy), fz);
}

export function prepareTissueVariation(THREE, geometry) {
  if (preparedGeometries.has(geometry)) return;
  const position = geometry.getAttribute('position');
  const values = new Float32Array(position.count);
  for (let i = 0; i < position.count; i++) {
    const x = position.getX(i), y = position.getY(i), z = position.getZ(i);
    values[i] = 0.65 * tissueNoise(x * 0.09, y * 0.09, z * 0.09)
      + 0.35 * tissueNoise(x * 0.38, y * 0.38, z * 0.38);
  }
  geometry.setAttribute('brainTissueVariation', new THREE.BufferAttribute(values, 1));
  preparedGeometries.add(geometry);
}

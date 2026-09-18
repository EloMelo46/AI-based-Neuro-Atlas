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

// Continuous, object-space variation, without painted vessels or extra anatomy.
export const tissueNoiseGLSL = `
  float tissueHash(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
  }
  float tissueNoise(vec3 p) {
    vec3 cell = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(tissueHash(cell), tissueHash(cell + vec3(1, 0, 0)), f.x),
          mix(tissueHash(cell + vec3(0, 1, 0)), tissueHash(cell + vec3(1, 1, 0)), f.x), f.y),
      mix(mix(tissueHash(cell + vec3(0, 0, 1)), tissueHash(cell + vec3(1, 0, 1)), f.x),
          mix(tissueHash(cell + vec3(0, 1, 1)), tissueHash(cell + vec3(1, 1, 1)), f.x), f.y), f.z);
  }
`;

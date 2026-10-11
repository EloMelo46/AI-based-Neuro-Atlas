// The hologram emits its own color. It needs normals for contours, but no
// Phong lighting, tissue shading or light uniforms on every transparent layer.
export function createDigitalMaterial(THREE, detailed, center, radius) {
  const appearance = detailed.userData.appearance;
  const material = new THREE.ShaderMaterial({
    uniforms: {
      opacity: { value: detailed.opacity },
      brainRimColor: appearance.rimColor,
      brainSoftness: appearance.softness,
      brainFocus: appearance.focus,
      brainCenter: center,
      brainRadius: radius,
      brainAnatomicalTransform: { value: detailed.userData.anatomicalTransform },
    },
    vertexShader: `
      #include <common>
      #include <clipping_planes_pars_vertex>
      attribute vec3 brainSoftNormal;
      uniform float brainSoftness;
      uniform vec3 brainCenter;
      uniform mat4 brainAnatomicalTransform;
      varying vec3 vBrainPosition;
      varying float vBrainDepth;
      varying vec3 vBrainNormal;
      varying vec3 vBrainView;
      void main() {
        vBrainNormal = normalize(normalMatrix * mix(normal, brainSoftNormal, brainSoftness));
        vBrainPosition = (brainAnatomicalTransform * vec4(position, 1.0)).xyz;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vBrainView = -mvPosition.xyz;
        vBrainDepth = -mvPosition.z + (viewMatrix * vec4(brainCenter, 1.0)).z;
        gl_Position = projectionMatrix * mvPosition;
        #include <clipping_planes_vertex>
      }`,
    fragmentShader: `
      #include <common>
      #include <clipping_planes_pars_fragment>
      uniform float opacity;
      uniform float brainRadius;
      uniform float brainFocus;
      uniform vec3 brainRimColor;
      varying vec3 vBrainPosition;
      varying float vBrainDepth;
      varying vec3 vBrainNormal;
      varying vec3 vBrainView;
      void main() {
        #include <clipping_planes_fragment>
        float facing = clamp(abs(dot(normalize(vBrainNormal), normalize(vBrainView))), 0.0, 1.0);
        float scanPosition = vBrainPosition.z * 0.32;
        float scanDistance = abs(fract(scanPosition) - 0.5);
        float scanWidth = max(fwidth(scanPosition), 0.015);
        float scanLine = 1.0 - smoothstep(0.035, 0.035 + scanWidth, scanDistance);
        float contour = pow(1.0 - facing, 2.2);
        float coverage = 0.025 + 0.38 * contour + 0.17 * scanLine;
        coverage = mix(coverage, 0.2 + 0.55 * contour + 0.2 * scanLine, brainFocus);
        float layerDepth = clamp((vBrainDepth + brainRadius * 0.8) / (brainRadius * 1.6), 0.0, 1.0);
        coverage *= mix(exp(-3.5 * layerDepth), 1.0, brainFocus);
        gl_FragColor = vec4(brainRimColor * (0.32 + 0.8 * contour + 0.3 * scanLine),
                            opacity * clamp(coverage, 0.0, 0.9));
        #include <tonemapping_fragment>
        #include <encodings_fragment>
        #include <premultiplied_alpha_fragment>
      }`,
    clipping: true, clippingPlanes: detailed.clippingPlanes,
    side: THREE.FrontSide, transparent: true, depthWrite: false,
  });
  material.extensions.derivatives = true;
  // Shared appearance state also drives narration and region-colored caps.
  material.userData.appearance = appearance;
  material.userData.anatomicalTransform = detailed.userData.anatomicalTransform;
  material.color = new THREE.Color();
  return material;
}

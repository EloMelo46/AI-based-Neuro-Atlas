// Offline inspection only. Decode each GLB without altering the source assets.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// A data URL also works in projects that do not set package.json type=module.
const decoderSource = fs.readFileSync(path.join(root, 'static/vendor/three/examples/jsm/libs/meshopt_decoder.module.js'), 'utf8');
const { MeshoptDecoder } = await import(`data:text/javascript;base64,${Buffer.from(decoderSource).toString('base64')}`);
await MeshoptDecoder.ready;
const identity = () => [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
function multiply(a,b) {
  const out = Array(16).fill(0);
  for (let c=0;c<4;c++) for (let r=0;r<4;r++) for (let k=0;k<4;k++) out[c*4+r]+=a[k*4+r]*b[c*4+k];
  return out;
}
function matrix(node) {
  if(node.matrix) return node.matrix;
  const [x,y,z,w] = node.rotation || [0,0,0,1];
  const [sx,sy,sz] = node.scale || [1,1,1];
  const [tx,ty,tz] = node.translation || [0,0,0];
  return [(1-2*y*y-2*z*z)*sx,(2*x*y+2*z*w)*sx,(2*x*z-2*y*w)*sx,0,
          (2*x*y-2*z*w)*sy,(1-2*x*x-2*z*z)*sy,(2*y*z+2*x*w)*sy,0,
          (2*x*z+2*y*w)*sz,(2*y*z-2*x*w)*sz,(1-2*x*x-2*y*y)*sz,0,tx,ty,tz,1];
}
function decode(filename) {
  const raw = fs.readFileSync(filename);
  if (raw.toString('utf8',0,4)!=='glTF' || raw.readUInt32LE(4)!==2 || raw.readUInt32LE(8)!==raw.length) throw Error('Invalid GLB');
  let json,bin;
  for(let offset=12;offset<raw.length;) {
    const size=raw.readUInt32LE(offset), type=raw.readUInt32LE(offset+4), chunk=raw.subarray(offset+8,offset+8+size);
    if(type===0x4e4f534a) json=JSON.parse(chunk.toString());
    if(type===0x004e4942) bin=chunk;
    offset+=8+size;
  }
  const views=json.bufferViews.map(view=>{
    const ext=view.extensions?.EXT_meshopt_compression;
    if(!ext) {
      if(view.buffer!==0) throw Error('Unsupported external buffer');
      return bin.subarray(view.byteOffset||0,(view.byteOffset||0)+view.byteLength);
    }
    if(ext.buffer!==0) throw Error('Unsupported external compressed buffer');
    const result=new Uint8Array(ext.count*ext.byteStride);
    MeshoptDecoder.decodeGltfBuffer(result,ext.count,ext.byteStride,bin.subarray(ext.byteOffset||0,(ext.byteOffset||0)+ext.byteLength),ext.mode,ext.filter);
    return result;
  });
  function accessor(index) {
    const a=json.accessors[index];
    if(a.sparse) throw Error('Sparse accessor not implemented');
    const widths={SCALAR:1,VEC2:2,VEC3:3,VEC4:4};
    const types={5120:['getInt8',1,127],5121:['getUint8',1,255],5122:['getInt16',2,32767],5123:['getUint16',2,65535],5125:['getUint32',4,4294967295],5126:['getFloat32',4,1]};
    const [getter,size,denom]=types[a.componentType], width=widths[a.type], source=views[a.bufferView];
    const view=new DataView(source.buffer,source.byteOffset,source.byteLength), stride=json.bufferViews[a.bufferView].byteStride || width*size;
    const out=new Float64Array(a.count*width);
    for(let i=0;i<a.count;i++) for(let j=0;j<width;j++) {
      let value=view[getter]((a.byteOffset||0)+i*stride+j*size,true);
      if(a.normalized) value=Math.max(-1,value/denom);
      out[i*width+j]=value;
    }
    return out;
  }
  const positions=[], normals=[], indices=[];
  const normalMetadata={authored_primitives:0,derived_primitives:0,derived_vertices:0,
    derivation:'Area-weighted local triangle normals at each indexed vertex, followed by inverse-transpose node transform and normalization; matches viewer computeVertexNormals fallback. Source GLB bytes are unchanged.'};
  let primitives=0;
  function visit(index,parent) {
    const node=json.nodes[index], m=multiply(parent,matrix(node));
    if(node.mesh!==undefined) for(const p of json.meshes[node.mesh].primitives) {
      if(p.mode!==undefined && p.mode!==4) throw Error('Non-triangle primitive');
      const pos=accessor(p.attributes.POSITION);
      const ids=p.indices===undefined?Array.from({length:pos.length/3},(_,i)=>i):accessor(p.indices);
      let nor;
      if(p.attributes.NORMAL===undefined) {
        nor=new Float64Array(pos.length);
        for(let face=0;face<ids.length;face+=3) {
          const a=ids[face]*3,b=ids[face+1]*3,c=ids[face+2]*3;
          const ab=[pos[b]-pos[a],pos[b+1]-pos[a+1],pos[b+2]-pos[a+2]];
          const ac=[pos[c]-pos[a],pos[c+1]-pos[a+1],pos[c+2]-pos[a+2]];
          const n=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]];
          for(const vertex of [a,b,c]) for(let d=0;d<3;d++) nor[vertex+d]+=n[d];
        }
        normalMetadata.derived_primitives++;
        normalMetadata.derived_vertices+=pos.length/3;
      } else {
        nor=accessor(p.attributes.NORMAL);
        normalMetadata.authored_primitives++;
      }
      const base=positions.length/3;
      // Inverse transpose using cofactor matrix, with determinant sign retained.
      const a=m[0],b=m[4],c=m[8],d=m[1],e=m[5],f=m[9],g=m[2],h=m[6],i=m[10];
      const cof=[e*i-f*h,f*g-d*i,d*h-e*g,c*h-b*i,a*i-c*g,b*g-a*h,b*f-c*e,c*d-a*f,a*e-b*d];
      const det=a*cof[0]+b*cof[1]+c*cof[2];
      if(!det) throw Error('Singular node matrix');
      for(let v=0;v<pos.length;v+=3) {
        const [x,y,z]=pos.subarray(v,v+3);
        positions.push(m[0]*x+m[4]*y+m[8]*z+m[12],m[1]*x+m[5]*y+m[9]*z+m[13],m[2]*x+m[6]*y+m[10]*z+m[14]);
        if(nor) {
          const [nx,ny,nz]=nor.subarray(v,v+3);
          const n=[(cof[0]*nx+cof[1]*ny+cof[2]*nz)/det,(cof[3]*nx+cof[4]*ny+cof[5]*nz)/det,(cof[6]*nx+cof[7]*ny+cof[8]*nz)/det];
          const len=Math.hypot(...n); normals.push(...n.map(v=>v/(len||1)));
        } else normals.push(0,0,0);
      }
      for(const index of ids) indices.push(base+index);
      primitives++;
    }
    for(const child of node.children||[]) visit(child,m);
  }
  for(const index of json.scenes[json.scene||0].nodes) visit(index,identity());
  return {positions:new Float64Array(positions),normals:new Float64Array(normals),indices:new Uint32Array(indices),primitives,normalMetadata};
}
const requests=JSON.parse(fs.readFileSync(0,'utf8'));
for(const request of requests) {
  const result=decode(request.input);
  const header=Buffer.alloc(12); header.writeUInt32LE(result.positions.length/3,0);header.writeUInt32LE(result.indices.length/3,4);header.writeUInt32LE(result.primitives,8);
  fs.writeFileSync(request.output,Buffer.concat([header,Buffer.from(result.positions.buffer),Buffer.from(result.normals.buffer),Buffer.from(result.indices.buffer)]));
  if(request.metadata) fs.writeFileSync(request.metadata,JSON.stringify({normals:result.normalMetadata}));
}

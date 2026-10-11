// Offline numerical screening, not an exact-arithmetic geometry certificate.
// Input: little-endian uint32 vertex/triangle counts, float64 xyz, uint32 triangles.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <numeric>
#include <map>
#include <string>
#include <vector>
using V = std::array<double,3>;
V sub(V a,V b){return {a[0]-b[0],a[1]-b[1],a[2]-b[2]};}
V cross(V a,V b){return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
double dot(V a,V b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
struct Triangle {std::array<uint32_t,3> indices; std::array<V,3> p; V min,max,center,normal; double norm; uint32_t group=0;};
struct Node {V min,max; int start,end,left=-1,right=-1;};
std::vector<Triangle> triangles;
std::vector<uint32_t> order;
std::vector<Node> nodes;
uint64_t candidates=0,found=0,degenerates=0;
std::vector<std::array<uint32_t,2>> examples;
bool betweenGroups=false,lastCoplanar=false;
uint64_t coplanarPairs=0,properPairs=0;
std::map<std::pair<uint32_t,uint32_t>,std::array<uint64_t,3>> regionPairs;
constexpr double eps=1e-8; // physical millimetres, after dequantization
bool overlap(V amin,V amax,V bmin,V bmax){for(int i=0;i<3;i++) if(amax[i]<bmin[i]-eps || bmax[i]<amin[i]-eps)return false;return true;}
int build(int start,int end){
 Node n; n.start=start;n.end=end;n.min={1e100,1e100,1e100};n.max={-1e100,-1e100,-1e100};
 for(int i=start;i<end;i++)for(int d=0;d<3;d++){n.min[d]=std::min(n.min[d],triangles[order[i]].min[d]);n.max[d]=std::max(n.max[d],triangles[order[i]].max[d]);}
 int id=nodes.size();nodes.push_back(n);
 if(end-start>8){
  int axis=0;for(int d=1;d<3;d++)if(n.max[d]-n.min[d]>n.max[axis]-n.min[axis])axis=d;
  int mid=(start+end)/2;
  std::nth_element(order.begin()+start,order.begin()+mid,order.begin()+end,[axis](int a,int b){return triangles[a].center[axis]<triangles[b].center[axis];});
  int left=build(start,mid),right=build(mid,end);nodes[id].left=left;nodes[id].right=right;
 }
 return id;
}
// For coplanar triangles, 2D separating axes detect strictly positive area overlap.
bool coplanar(const Triangle&a,const Triangle&b){
 int drop=0;for(int d=1;d<3;d++)if(std::abs(a.normal[d])>std::abs(a.normal[drop]))drop=d;
 int x=(drop+1)%3,y=(drop+2)%3;
 for(int shape=0;shape<2;shape++){
  const auto&t=shape?b:a;
  for(int i=0;i<3;i++){
   const auto&p=t.p[i];const auto&q=t.p[(i+1)%3];
   double nx=q[y]-p[y],ny=p[x]-q[x],length=std::hypot(nx,ny);
   if(length<=eps)continue;
   nx/=length;ny/=length;
   double amin=1e100,amax=-1e100,bmin=1e100,bmax=-1e100;
   for(int j=0;j<3;j++){
    double av=nx*a.p[j][x]+ny*a.p[j][y],bv=nx*b.p[j][x]+ny*b.p[j][y];
    amin=std::min(amin,av);amax=std::max(amax,av);bmin=std::min(bmin,bv);bmax=std::max(bmax,bv);
   }
   if(amax<=bmin+eps || bmax<=amin+eps)return false;
  }
 }
 return true;
}
// Segment-triangle intersection; exclude only contacts at segment endpoints.
bool edge_crosses(V origin,V end,const Triangle&t){
 V direction=sub(end,origin),e1=sub(t.p[1],t.p[0]),e2=sub(t.p[2],t.p[0]);
 V h=cross(direction,e2);double determinant=dot(e1,h);
 if(std::abs(determinant)<1e-14)return false;
 double inv=1/determinant;
 V s=sub(origin,t.p[0]);double u=dot(s,h)*inv;
 if(u<-1e-10 || u>1+1e-10)return false;
 V q=cross(s,e1);double v=dot(direction,q)*inv;
 if(v<-1e-10 || u+v>1+1e-10)return false;
 double along=dot(e2,q)*inv;
 return along>1e-10 && along<1-1e-10;
}
bool intersects(const Triangle&a,const Triangle&b){
 lastCoplanar=false;
 if(betweenGroups && a.group==b.group)return false;
 if(a.norm<1e-12 || b.norm<1e-12)return false;
 if(!overlap(a.min,a.max,b.min,b.max))return false;
 candidates++;
 double dA[3],dB[3];
 for(int i=0;i<3;i++){dA[i]=dot(a.normal,sub(b.p[i],a.p[0]))/a.norm;dB[i]=dot(b.normal,sub(a.p[i],b.p[0]))/b.norm;}
 auto separated=[](double*d){return (*std::min_element(d,d+3)>eps)||(*std::max_element(d,d+3)<-eps);};
 if(separated(dA)||separated(dB))return false;
 bool samePlane=true;for(int i=0;i<3;i++)if(std::abs(dA[i])>eps || std::abs(dB[i])>eps)samePlane=false;
 if(samePlane){lastCoplanar=true;return coplanar(a,b);}
 // If triangles only touch from one side there is no proper crossing.
 auto straddles=[](double*d){return *std::min_element(d,d+3)<-eps && *std::max_element(d,d+3)>eps;};
 if(!straddles(dA)||!straddles(dB))return false;
 for(int i=0;i<3;i++)if(edge_crosses(a.p[i],a.p[(i+1)%3],b)||edge_crosses(b.p[i],b.p[(i+1)%3],a))return true;
 return false;
}
void record(uint32_t a,uint32_t b){
 if(!intersects(triangles[a],triangles[b]))return;
 found++;if(lastCoplanar)coplanarPairs++;else properPairs++;if(examples.size()<10)examples.push_back({a,b});
 if(betweenGroups){auto&counts=regionPairs[std::minmax(triangles[a].group,triangles[b].group)];counts[0]++;counts[lastCoplanar?2:1]++;}
}
void pair_nodes(int ia,int ib){
 const Node&a=nodes[ia];const Node&b=nodes[ib];
 if(!overlap(a.min,a.max,b.min,b.max))return;
 if(ia==ib){
  if(a.left>=0){pair_nodes(a.left,a.left);pair_nodes(a.left,a.right);pair_nodes(a.right,a.right);return;}
  for(int i=a.start;i<a.end;i++)for(int j=i+1;j<a.end;j++){
   record(order[i],order[j]);
  }return;
 }
 if(a.left<0 && b.left<0){
  for(int i=a.start;i<a.end;i++)for(int j=b.start;j<b.end;j++){
   record(order[i],order[j]);
  }return;
 }
 if(a.left>=0 && (b.left<0 || a.end-a.start>=b.end-b.start)){pair_nodes(a.left,ib);pair_nodes(a.right,ib);}
 else{pair_nodes(ia,b.left);pair_nodes(ia,b.right);}
}
int main(int argc,char**argv){
 if(argc<2 || argc>3){std::cerr<<"Expected binary mesh path [--between-regions]\n";return 2;}
 betweenGroups=argc==3 && std::string(argv[2])=="--between-regions";
 std::ifstream input(argv[1],std::ios::binary);uint32_t nv=0,nf=0;
 input.read(reinterpret_cast<char*>(&nv),4);input.read(reinterpret_cast<char*>(&nf),4);
 if(!input || nv==0 || nf==0){std::cerr<<"Invalid header\n";return 2;}
 std::vector<V> vertices(nv);input.read(reinterpret_cast<char*>(vertices.data()),nv*sizeof(V));
 triangles.resize(nf);order.resize(nf);std::iota(order.begin(),order.end(),0);
 for(auto&t:triangles){
  input.read(reinterpret_cast<char*>(t.indices.data()),12);if(!input)return 2;
  t.min={1e100,1e100,1e100};t.max={-1e100,-1e100,-1e100};t.center={0,0,0};
  for(int i=0;i<3;i++){
   if(t.indices[i]>=nv)return 2;t.p[i]=vertices[t.indices[i]];
   for(int d=0;d<3;d++){t.min[d]=std::min(t.min[d],t.p[i][d]);t.max[d]=std::max(t.max[d],t.p[i][d]);t.center[d]+=t.p[i][d]/3;}
  }
  t.normal=cross(sub(t.p[1],t.p[0]),sub(t.p[2],t.p[0]));t.norm=std::sqrt(dot(t.normal,t.normal));if(t.norm<1e-12)degenerates++;
 }
 if(betweenGroups){for(auto&t:triangles)input.read(reinterpret_cast<char*>(&t.group),4);if(!input)return 2;}
 // A closed edge-manifold mesh may still pinch at a vertex. Its vertex link
 // must be one connected cycle, so check connectivity and degree explicitly.
 uint64_t nonmanifoldVertices=0;
 if(!betweenGroups){
 std::vector<std::vector<std::array<uint32_t,2>>> links(nv);
 for(const auto&t:triangles)for(int c=0;c<3;c++)links[t.indices[c]].push_back({t.indices[(c+1)%3],t.indices[(c+2)%3]});
 for(uint32_t v=0;v<nv;v++){
  const auto&link=links[v];if(link.empty())continue;
  std::vector<uint32_t> neighbors;
  for(const auto&e:link){neighbors.push_back(e[0]);neighbors.push_back(e[1]);}
  std::sort(neighbors.begin(),neighbors.end());neighbors.erase(std::unique(neighbors.begin(),neighbors.end()),neighbors.end());
  std::vector<int> parent(neighbors.size()),degree(neighbors.size(),0);std::iota(parent.begin(),parent.end(),0);
  auto root=[&parent](int n){while(parent[n]!=n){parent[n]=parent[parent[n]];n=parent[n];}return n;};
  bool invalid=std::binary_search(neighbors.begin(),neighbors.end(),v);
  for(const auto&e:link){
   int a=std::lower_bound(neighbors.begin(),neighbors.end(),e[0])-neighbors.begin();
   int b=std::lower_bound(neighbors.begin(),neighbors.end(),e[1])-neighbors.begin();
   degree[a]++;degree[b]++;parent[root(a)]=root(b);
  }
  int first=root(0);
  for(size_t n=0;n<neighbors.size();n++)if(degree[n]!=2 || root(n)!=first)invalid=true;
  if(invalid)nonmanifoldVertices++;
 }
 }
 build(0,nf);pair_nodes(0,0);
 std::cout<<"{\"status\":\"numerically_screened\",\"intersecting_pairs\":"<<found<<",\"proper_crossing_pairs\":"<<properPairs<<",\"coplanar_overlap_pairs\":"<<coplanarPairs<<",\"nonmanifold_vertices\":"<<nonmanifoldVertices<<",\"vertex_links_checked\":"<<(betweenGroups?"false":"true")<<",\"candidate_pairs\":"<<candidates<<",\"degenerate_triangles_excluded\":"<<degenerates<<",\"sample_triangle_pairs\":[";
 for(size_t i=0;i<examples.size();i++){if(i)std::cout<<',';std::cout<<'['<<examples[i][0]<<','<<examples[i][1]<<']';}
 std::cout<<"],\"region_pair_counts\":[";bool first=true;
 for(const auto&pair:regionPairs){if(!first)std::cout<<',';first=false;std::cout<<'['<<pair.first.first<<','<<pair.first.second<<','<<pair.second[0]<<','<<pair.second[1]<<','<<pair.second[2]<<']';}
 std::cout<<"]}\n";
}

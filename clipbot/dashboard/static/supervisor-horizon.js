/* Original gravitational instrument; ambient artwork is never an agent-work signal. */
export function createHorizon(THREE) {
  const group=new THREE.Group(), uniforms={time:{value:0},intensity:{value:1}};
  const disk=new THREE.Mesh(new THREE.RingGeometry(1.03,2.7,160,12),new THREE.ShaderMaterial({
    uniforms,side:THREE.DoubleSide,transparent:true,depthWrite:false,toneMapped:false,
    vertexShader:`varying vec3 p; void main(){p=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
    fragmentShader:`varying vec3 p;uniform float time;uniform float intensity;
      float hash(float n){return fract(sin(n)*43758.5453);}
      void main(){float r=length(p.xy);float a=atan(p.y,p.x);float d=(r-1.03)/1.67;
        float bands=pow(.5+.5*sin(r*118.+sin(a*7.-time*.12)*1.4),5.);
        float flow=.56+.44*sin(a*13.+r*19.-time*.15);
        float edge=pow(max(0.,1.-d),2.8)*smoothstep(1.03,1.12,r);
        float hot=pow(max(0.,1.-d),12.);
        vec3 cold=vec3(.69,.23,.07),warm=vec3(1.7,.82,.28),white=vec3(3.2,2.5,1.7);
        vec3 color=mix(cold,warm,edge)+white*hot*.72;
        float energy=edge*(.25+.75*bands)*(.55+.45*flow);
        gl_FragColor=vec4(color*intensity,clamp(energy,0.,.94));}`
  }));
  disk.rotation.x=Math.PI*.40;disk.rotation.z=-.14;group.add(disk);
  const shadow=new THREE.Mesh(new THREE.SphereGeometry(1.035,64,48),new THREE.MeshBasicMaterial({color:0x010206}));group.add(shadow);
  const rim=new THREE.Mesh(new THREE.TorusGeometry(1.075,.018,12,160),new THREE.MeshBasicMaterial({color:new THREE.Color(0xffd4a2).multiplyScalar(3.4),toneMapped:false}));group.add(rim);
  const lens=new THREE.Mesh(new THREE.TorusGeometry(1.15,.035,12,160),new THREE.MeshBasicMaterial({color:new THREE.Color(0xffc889).multiplyScalar(1.7),transparent:true,opacity:.54,toneMapped:false}));lens.rotation.x=.12;group.add(lens);
  const reticle=new THREE.Group();
  for(let i=0;i<4;i++){
    const arc=new THREE.Mesh(new THREE.TorusGeometry(3.2,.004,3,48,Math.PI*.22),new THREE.MeshBasicMaterial({color:0x547391,transparent:true,opacity:.2}));
    arc.rotation.z=i*Math.PI/2+.18;reticle.add(arc);
  }
  reticle.rotation.x=.25;group.add(reticle);
  const positions=[];
  for(let i=0;i<240;i++){
    const angle=i*2.399963, radius=5.7+(i%19)*.35;
    positions.push(Math.cos(angle)*radius,Math.sin(angle)*radius*.62,-3-(i%11)*.3);
  }
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  const stars=new THREE.Points(geo,new THREE.PointsMaterial({color:0x9bbcd9,size:.014,transparent:true,opacity:.4,depthWrite:false}));group.add(stars);
  return {group,update(time,reduced=false){uniforms.time.value=reduced?0:time;}};
}

// Dialogue reel renderer: low-poly classroom + auto-director camera.
// Placeholder characters (VINEET + ONE mascot) built from primitives; the
// final look swaps in real models, while timeline/director/board stay as-is.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const W = 720, H = 1280;
const params = new URLSearchParams(location.search);
const TL = await (await fetch(params.get('timeline'))).json();
const FPS = TL.fps;
const HANDLE = params.get('handle') || '@aibyvineet';

await Promise.all([
  document.fonts.load('700 40px Kalam'), document.fonts.load('400 40px Kalam'),
  document.fonts.load('700 40px Poppins'), document.fonts.load('800 40px Poppins'),
]);

// ---------- renderer ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const comp = document.createElement('canvas');
comp.width = W; comp.height = H;
document.body.appendChild(comp);
const cx = comp.getContext('2d');

const scene = new THREE.Scene();
scene.background = new THREE.Color('#1c2438');
const camera = new THREE.PerspectiveCamera(55, W / H, 0.05, 60);
const composer = new EffectComposer(renderer);
composer.setPixelRatio(1); composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new UnrealBloomPass(new THREE.Vector2(W, H), 0.28, 0.35, 0.95));
const bokeh = new BokehPass(scene, camera, { focus: 3, aperture: 0.002, maxblur: 0.009 });
composer.addPass(bokeh);
composer.addPass(new OutputPass());

const flat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, flatShading: true, roughness: 0.85, metalness: 0, ...extra });
function mesh(geo, mat, x = 0, y = 0, z = 0, parent = scene) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.castShadow = true; m.receiveShadow = true;
  parent.add(m);
  return m;
}
const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);

// ---------- lights ----------
scene.add(new THREE.HemisphereLight('#a9c1ff', '#5a3a28', 0.75));
const key = new THREE.DirectionalLight('#ffd9b0', 2.2);
key.position.set(3, 5, 4);
key.castShadow = true;
key.shadow.mapSize.set(1024, 1024);
Object.assign(key.shadow.camera, { left: -4, right: 4, top: 4, bottom: -2, near: 0.5, far: 15 });
scene.add(key);
const rim = new THREE.PointLight('#6fa8ff', 6, 8);
rim.position.set(-1.5, 3, -2.2);
scene.add(rim);
const faceFill = new THREE.PointLight('#ffd2a8', 4.5, 3.2);
faceFill.position.set(0.1, 1.75, 0.0);
scene.add(faceFill);
const lamp = new THREE.PointLight('#ffb36b', 3, 4);
lamp.position.set(1.9, 1.6, -0.4);
scene.add(lamp);

// ---------- location ----------
// The set changes per episode ("location" in the script); the layout contract
// stays the same so characters, shots and the board logic never change:
// board on the back wall, a counter/desk where VINEET's arms rest (top ~0.84 m),
// ONE's perch at x -0.95 / z -0.45, VINEET's seat at x 1.2 / z -0.95.
const LOC = TL.location || 'classroom';
const BSTYLE = TL.board_style || ({ tapri: 'chalk', studio: 'sign', terrace: 'none', bedroom: 'none', court: 'plaque',
  newsroom: 'news', podcast: 'onair', office: 'none' }[LOC] || 'white');
const CHALK = BSTYLE === 'chalk';
const BOARD = { x: -0.35, y: 2.15, z: -3.25, w: 2.7, h: 2.7 / 1.6 };
const boardC = document.createElement('canvas'); boardC.width = 1024; boardC.height = 640;
const bctx = boardC.getContext('2d');
const boardTex = new THREE.CanvasTexture(boardC); boardTex.colorSpace = THREE.SRGBColorSpace;
boardTex.anisotropy = 4;
const boardFace = new THREE.Mesh(new THREE.PlaneGeometry(BOARD.w, BOARD.h),
  new THREE.MeshStandardMaterial({ map: boardTex, roughness: 0.95 }));
boardFace.position.set(BOARD.x, BOARD.y, BOARD.z);
scene.add(boardFace);
boardFace.visible = BSTYLE !== 'none';
const boardToWorld = (px, py) => new THREE.Vector3(
  BOARD.x - BOARD.w / 2 + (px / 1024) * BOARD.w, BOARD.y + BOARD.h / 2 - (py / 640) * BOARD.h, BOARD.z + 0.01);
let STACK_TOP = 1.32;

// Backdrops are painted on a canvas and pre-blurred: no small sharp repeating
// detail exists in 3D, so nothing shimmers when the camera moves.
function paintBackdrop(kind) {
  const c = document.createElement('canvas'); c.width = 2048; c.height = 1024;
  const raw = document.createElement('canvas'); raw.width = 2048; raw.height = 1024;
  const g = raw.getContext('2d');
  let sd = kind === 'street' ? 13 : 7; const rnd = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
  const gr = g.createLinearGradient(0, 0, 0, 1024);
  if (kind === 'studio') {
    gr.addColorStop(0, '#05061a'); gr.addColorStop(0.6, '#140f33'); gr.addColorStop(1, '#0a0a18');
    g.fillStyle = gr; g.fillRect(0, 0, 2048, 1024);
    for (let i = 0; i < 9; i++) {                       // light beams
      const x = 120 + i * 230, b = g.createLinearGradient(x, 0, x, 900);
      b.addColorStop(0, i % 2 ? 'rgba(255,63,164,0.35)' : 'rgba(54,224,255,0.35)'); b.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = b; g.beginPath(); g.moveTo(x - 20, 0); g.lineTo(x + 20, 0); g.lineTo(x + 160, 900); g.lineTo(x - 160, 900); g.fill();
    }
    g.fillStyle = '#07071a';                             // audience heads
    for (let x = -20; x < 2080; x += 46) { g.beginPath(); g.arc(x + rnd() * 10, 860 + rnd() * 30, 30, 0, Math.PI * 2); g.fill(); }
    g.fillRect(0, 880, 2048, 144);
  } else if (kind === 'sunset') {
    gr.addColorStop(0, '#3b3f8f'); gr.addColorStop(0.35, '#c75b8a'); gr.addColorStop(0.6, '#ff9a5c'); gr.addColorStop(0.78, '#ffd28a'); gr.addColorStop(1, '#c98a6a');
    g.fillStyle = gr; g.fillRect(0, 0, 2048, 1024);
    g.fillStyle = 'rgba(255,240,200,0.9)'; g.beginPath(); g.arc(1500, 640, 90, 0, Math.PI * 2); g.fill();   // sun
    let x = -30;
    while (x < 2100) {                                   // rooftops with tanks
      const w = 140 + rnd() * 220, h = 140 + rnd() * 200;
      g.fillStyle = ['#7a5a6e', '#6a4d63', '#835f6f'][Math.floor(rnd() * 3)]; g.fillRect(x, 780 - h, w, 400);
      if (rnd() > 0.4) { g.fillStyle = '#3a2c3a'; g.fillRect(x + w * 0.3, 780 - h - 50, 46, 50); }
      x += w + rnd() * 16;
    }
    for (let i = 0; i < 6; i++) {                        // kites
      const kx = 200 + rnd() * 1650, ky = 120 + rnd() * 300, ks = 18 + rnd() * 14;
      g.fillStyle = ['#ff3b5c', '#ffd23b', '#3bc6ff', '#7b4dff'][i % 4];
      g.beginPath(); g.moveTo(kx, ky - ks); g.lineTo(kx + ks * 0.8, ky); g.lineTo(kx, ky + ks); g.lineTo(kx - ks * 0.8, ky); g.fill();
    }
  } else if (kind === 'street') {
    gr.addColorStop(0, '#0d1226'); gr.addColorStop(0.5, '#1f2547'); gr.addColorStop(0.7, '#3a2f4a'); gr.addColorStop(1, '#141218');
    g.fillStyle = gr; g.fillRect(0, 0, 2048, 1024);
    // shop fronts with warm/neon light, a street-light glow, road at the bottom
    let x = -30;
    while (x < 2100) {
      const w = 160 + rnd() * 200, h = 260 + rnd() * 220, top = 760 - h;
      g.fillStyle = ['#2a2238', '#33263a', '#262a3d'][Math.floor(rnd() * 3)]; g.fillRect(x, top, w, 1024);
      g.fillStyle = ['rgba(255,190,90,0.9)', 'rgba(255,120,80,0.85)', 'rgba(120,220,200,0.8)', 'rgba(255,230,160,0.9)'][Math.floor(rnd() * 4)];
      g.fillRect(x + 14, 600, w - 28, 120);                  // lit shop shutter opening
      g.fillStyle = ['#e8742c', '#2bb3a3', '#c94c4c', '#f2c14e'][Math.floor(rnd() * 4)];
      g.fillRect(x + 10, 560, w - 20, 30);                   // shop sign band
      x += w + 6 + rnd() * 20;
    }
    g.fillStyle = '#18161c'; g.fillRect(0, 770, 2048, 254);  // road
  } else {
    gr.addColorStop(0, '#16284f'); gr.addColorStop(0.45, '#3f5f98'); gr.addColorStop(0.62, '#7d97c4'); gr.addColorStop(1, '#2a3550');
    g.fillStyle = gr; g.fillRect(0, 0, 2048, 1024);
    for (const [layer, col, base] of [[0, '#2c3a5e', 520], [1, '#1d2744', 600]]) {
      let x = -40;
      while (x < 2100) {
        const w = 110 + rnd() * 160, h = 180 + rnd() * (layer ? 300 : 220);
        g.fillStyle = col; g.fillRect(x, base + 260 - h, w, 1024);
        for (let wy = base + 260 - h + 18; wy < 1000; wy += 26) for (let wx = x + 12; wx < x + w - 14; wx += 24)
          if (rnd() > 0.62) { g.fillStyle = rnd() > 0.25 ? 'rgba(255,210,122,0.85)' : 'rgba(170,205,255,0.7)'; g.fillRect(wx, wy, 10, 12); }
        x += w + 8 + rnd() * 30;
      }
    }
  }
  const out = c.getContext('2d');
  out.filter = { street: 'blur(9px)', studio: 'blur(6px)', sunset: 'blur(4px)' }[kind] || 'blur(7px)'; out.drawImage(raw, 0, 0); out.filter = 'none';
  const n = { street: 90, studio: 60, sunset: 25 }[kind] ?? 70;
  for (let i = 0; i < n; i++) {
    const x = rnd() * 2048, y = (kind === 'street' ? 480 : 380) + rnd() * (kind === 'street' ? 420 : 600), r = 14 + rnd() * 38;
    const pick = rnd();
    const col = kind === 'studio' ? (pick < 0.5 ? [255, 80, 180] : [70, 220, 255]) : kind === 'sunset' ? [255, 230, 170] : kind === 'street'
      ? (pick < 0.45 ? [255, 200, 120] : pick < 0.65 ? [255, 90, 80] : pick < 0.85 ? [255, 245, 220] : [120, 220, 200])
      : (pick > 0.3 ? [255, 205, 120] : [150, 200, 255]);
    const rg = out.createRadialGradient(x, y, 0, x, y, r);
    rg.addColorStop(0, `rgba(${col},0.55)`); rg.addColorStop(0.7, `rgba(${col},0.22)`); rg.addColorStop(1, 'rgba(0,0,0,0)');
    out.fillStyle = rg; out.beginPath(); out.arc(x, y, r, 0, Math.PI * 2); out.fill();
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
async function addBackdrop(kind) {
  const sky = new THREE.Mesh(new THREE.PlaneGeometry(28, 14), new THREE.MeshBasicMaterial({ map: paintBackdrop(kind) }));
  // Optional painted backdrop (e.g. a Leonardo/ChatGPT image): assets/backdrop_<location>.jpg or ?backdrop=
  const url = params.get('backdrop') || `assets/backdrop_${LOC}.jpg`;
  const ok = await fetch(url, { method: 'HEAD' }).then(r => r.ok).catch(() => false);
  if (ok) {
    const tex = await new THREE.TextureLoader().loadAsync(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    sky.material.map = tex; sky.material.needsUpdate = true;
  }
  sky.position.set(0, 3, -11); scene.add(sky);
}

function buildClassroom() {
  mesh(box(10, 0.1, 9), flat('#7a4e33'), 0, -0.05, -1);
  const wallMat = flat('#34405e');
  mesh(box(1.6, 4.2, 0.15), wallMat, -3.7, 2.1, -4);
  mesh(box(1.6, 4.2, 0.15), wallMat, 3.7, 2.1, -4);
  mesh(box(10, 0.6, 0.15), wallMat, 0, 0.3, -4);
  mesh(box(10, 0.5, 0.15), wallMat, 0, 4.15, -4);
  const barMat = flat('#14161c');
  for (const x of [-2.9, -1.0, 1.0, 2.9]) mesh(box(0.09, 3.4, 0.12), barMat, x, 2.25, -3.95);
  for (const y of [0.6, 2.1, 3.9]) mesh(box(5.9, 0.09, 0.12), barMat, 0, y, -3.95);
  // bookshelf right
  const shelfMat = flat('#6b4630');
  mesh(box(1.1, 2.6, 0.45), shelfMat, 3.3, 1.3, -3.4);
  const bookCols = ['#e0703a', '#f2c14e', '#3d8b6d', '#c94c4c', '#4f6fb3', '#e8e2d0'];
  for (let r = 0; r < 4; r++) for (let i = 0; i < 6; i++) {
    const h = 0.32 + ((i + r) % 3) * 0.04;
    mesh(box(0.11, h, 0.3), flat(bookCols[(i + r * 2) % 6]), 2.85 + i * 0.15, 0.35 + r * 0.6 + h / 2, -3.3);
  }
  // whiteboard frame, tray, markers, legs
  mesh(box(BOARD.w + 0.12, BOARD.h + 0.12, 0.06), flat('#9aa1ab'), BOARD.x, BOARD.y, BOARD.z - 0.04);
  mesh(box(BOARD.w * 0.8, 0.05, 0.12), flat('#9aa1ab'), BOARD.x, BOARD.y - BOARD.h / 2 - 0.05, BOARD.z + 0.05);
  ['#2b3a8c', '#c0392b', '#1d6b3a'].forEach((c, i) =>
    mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.16, 6), flat(c), BOARD.x - 0.25 + i * 0.22, BOARD.y - BOARD.h / 2 - 0.01, BOARD.z + 0.07)
      .rotation.z = Math.PI / 2);
  mesh(box(0.06, 2.2, 0.06), flat('#7c838c'), BOARD.x - 1.0, 0.6, BOARD.z);
  mesh(box(0.06, 2.2, 0.06), flat('#7c838c'), BOARD.x + 1.0, 0.6, BOARD.z);
  // desk + props
  mesh(box(3.0, 0.08, 1.1), flat('#b07a4f'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#8f5f3c'), 0.15, 0.4, -1.05);
  mesh(new THREE.CylinderGeometry(0.07, 0.065, 0.14, 8), flat('#f3f1ea'), 0.55, 0.91, -0.25); // mug
  mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.16, 7), flat('#25505a'), -0.25, 0.92, -0.75); // pen pot
  ['#f2c14e', '#e0703a', '#3d8b6d'].forEach((c, i) => {
    const p = mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.22, 5), flat(c), -0.27 + i * 0.02, 1.0, -0.75); p.rotation.z = 0.1 - i * 0.1;
  });
  mesh(box(0.34, 0.05, 0.25), flat('#e8e2d0'), 0.1, 0.865, -0.3);
  mesh(box(0.3, 0.04, 0.22), flat('#e46a8a'), 0.1, 0.905, -0.3);
  // book stack for ONE
  const stack = [['#2f8a5a', 0.1], ['#7a4fb3', 0.09], ['#f2c14e', 0.1], ['#c94c4c', 0.09], ['#25505a', 0.1]];
  let sy = 0.84;
  stack.forEach(([c, h], i) => { mesh(box(0.5 - i * 0.015, h, 0.36), flat(c), -0.95 + (i % 2) * 0.02, sy + h / 2, -0.45); sy += h; });
  STACK_TOP = sy;
  // chair
  mesh(box(0.6, 0.07, 0.55), flat('#2c6b6b'), 1.2, 0.5, -0.95);
  mesh(box(0.6, 0.7, 0.07), flat('#2c6b6b'), 1.42, 0.85, -1.15).rotation.y = -0.6;
  for (const [dx, dz] of [[-0.25, -0.22], [0.25, -0.22], [-0.25, 0.22], [0.25, 0.22]])
    mesh(box(0.05, 0.47, 0.05), flat('#1f4a4a'), 1.2 + dx, 0.24, -0.95 + dz);
}

// Night chai tapri: tin roof, chalkboard menu, kettle + kulhads on the counter,
// string lights, street glowing behind.
function buildTapri() {
  scene.background = new THREE.Color('#0d1020');
  mesh(box(12, 0.1, 10), flat('#2c2b30'), 0, -0.05, -1);                 // road
  mesh(box(5.2, 0.12, 3.6), flat('#6d6862'), -0.2, 0.06, -2.0);          // footpath slab under the stall
  // stall back wall (painted tin panels, wide so nothing shimmers)
  ['#8a3b2e', '#7a3328', '#8a3b2e', '#7a3328'].forEach((c, i) => mesh(box(1.0, 3.1, 0.1), flat(c), -1.85 + i * 1.0, 1.65, -3.42));
  mesh(box(0.12, 3.3, 0.12), flat('#4a3326'), -2.4, 1.65, -3.35);         // posts
  mesh(box(0.12, 3.3, 0.12), flat('#4a3326'), 1.7, 1.65, -3.35);
  mesh(box(0.1, 3.0, 0.1), flat('#4a3326'), -2.4, 1.5, -0.15);
  // tin roof sloping towards the street + fabric valance
  const roof = mesh(box(4.6, 0.06, 3.8), flat('#9aa3a8', { roughness: 0.6 }), -0.35, 3.25, -1.6);
  roof.rotation.x = 0.1;
  mesh(box(4.6, 0.26, 0.04), flat('#e8742c'), -0.35, 3.0, 0.27);
  // chalkboard frame (wood) and chalk ledge
  mesh(box(BOARD.w + 0.16, BOARD.h + 0.16, 0.06), flat('#6b4630'), BOARD.x, BOARD.y, BOARD.z - 0.04);
  mesh(box(BOARD.w * 0.9, 0.05, 0.1), flat('#6b4630'), BOARD.x, BOARD.y - BOARD.h / 2 - 0.06, BOARD.z + 0.05);
  ['#f4f1e8', '#ffd86b', '#ff8fa3'].forEach((c, i) =>
    mesh(new THREE.CylinderGeometry(0.013, 0.013, 0.09, 6), flat(c), BOARD.x - 0.2 + i * 0.16, BOARD.y - BOARD.h / 2 - 0.025, BOARD.z + 0.06)
      .rotation.z = Math.PI / 2);
  // shelf with glass jars behind the counter (left of the board, low)
  mesh(box(0.9, 0.05, 0.3), flat('#6b4630'), -2.0, 1.25, -3.2);
  ['#f2c14e', '#c94c4c', '#e8e2d0'].forEach((c, i) => {
    mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.24, 10), flat('#cfe3e6', { roughness: 0.35 }), -2.3 + i * 0.3, 1.4, -3.2);
    mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.12, 10), flat(c), -2.3 + i * 0.3, 1.36, -3.2);
    mesh(new THREE.CylinderGeometry(0.095, 0.095, 0.04, 10), flat('#c94c4c'), -2.3 + i * 0.3, 1.54, -3.2);
  });
  // counter (same footprint as the classroom desk)
  mesh(box(3.0, 0.08, 1.1), flat('#8b5a3c'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.76, 0.06), flat('#c0622f'), 0.15, 0.4, -0.02);          // painted front panel facing the street
  mesh(box(2.9, 0.04, 0.07), flat('#f2c14e'), 0.15, 0.62, 0.0);           // stripe
  // kettle on a small stove
  mesh(box(0.34, 0.1, 0.3), flat('#2c2b30'), 0.0, 0.89, -0.85);
  mesh(new THREE.ConeGeometry(0.05, 0.05, 8), new THREE.MeshBasicMaterial({ color: '#4fb3ff' }), 0.0, 0.965, -0.85);
  const steel = flat('#c9ced3', { roughness: 0.45, flatShading: false });
  mesh(new THREE.CylinderGeometry(0.12, 0.14, 0.22, 14), steel, 0.0, 1.06, -0.85);
  mesh(new THREE.SphereGeometry(0.12, 14, 6, 0, Math.PI * 2, 0, Math.PI / 2), steel, 0.0, 1.17, -0.85);
  const spout = mesh(new THREE.CylinderGeometry(0.015, 0.03, 0.16, 8), steel, 0.15, 1.1, -0.85); spout.rotation.z = -0.9;
  mesh(new THREE.TorusGeometry(0.1, 0.012, 6, 12, Math.PI), flat('#2c2b30'), 0.0, 1.26, -0.85);
  // kulhads on a tray + one in front of VINEET
  mesh(box(0.42, 0.02, 0.26), flat('#a8a39b'), -0.45, 0.85, -0.3);
  const clay = flat('#b5562f');
  for (let i = 0; i < 6; i++) mesh(new THREE.CylinderGeometry(0.04, 0.03, 0.08, 9), clay, -0.6 + (i % 3) * 0.12, 0.9, -0.36 + Math.floor(i / 3) * 0.12);
  mesh(new THREE.CylinderGeometry(0.045, 0.034, 0.09, 9), clay, 0.62, 0.885, -0.38);
  mesh(new THREE.CylinderGeometry(0.038, 0.038, 0.005, 9), flat('#c58b5a'), 0.62, 0.928, -0.38);   // chai inside
  // ONE's perch: stacked biscuit tins (same height as the book stack)
  const tins = [['#c94c4c', 0.16], ['#f2c14e', 0.16], ['#2f6fb3', 0.16]];
  let sy = 0.84;
  tins.forEach(([c, h], i) => { mesh(new THREE.CylinderGeometry(0.21 - i * 0.012, 0.21 - i * 0.012, h, 14), flat(c, { flatShading: false, roughness: 0.5 }), -0.95, sy + h / 2, -0.45); sy += h; });
  STACK_TOP = sy;
  // stool for VINEET
  mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.06, 10), flat('#3d7a5a'), 1.2, 0.5, -0.95);
  for (const a of [0, 2.1, 4.2]) mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.48, 5), flat('#2a2a2a'), 1.2 + Math.cos(a) * 0.17, 0.24, -0.95 + Math.sin(a) * 0.17);
  // gas cylinder + crate at the side
  mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.6, 12), flat('#c9302c', { flatShading: false }), -2.0, 0.42, -2.6);
  mesh(box(0.55, 0.38, 0.4), flat('#a77b4f'), 2.1, 0.31, -2.5);
  // warm bulb under the roof + string lights along the roof edge (few, big, static)
  mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.4, 4), flat('#111'), 1.45, 3.05, -2.1);
  mesh(new THREE.SphereGeometry(0.06, 12, 8), new THREE.MeshBasicMaterial({ color: '#ffd9a0' }), 1.45, 2.83, -2.1);
  const bulbLight = new THREE.PointLight('#ffb766', 6, 5); bulbLight.position.set(0.6, 2.5, -1.2); scene.add(bulbLight);
  ['#ffcf6b', '#ff7a7a', '#7ff2e0', '#ffcf6b', '#b7a0ff', '#ffcf6b', '#ff7a7a'].forEach((c, i) =>
    mesh(new THREE.SphereGeometry(0.05, 10, 6), new THREE.MeshBasicMaterial({ color: c }), -2.3 + i * 0.65, 2.78 + 0.05 * Math.sin(i * 1.7), 0.22));
}


// Quiz show studio: dark stage, neon "AI QUIZ" sign where the board is, podium
// with a buzzer for VINEET, a golden host stand for ONE.
function buildStudio() {
  scene.background = new THREE.Color('#0a0b1c');
  mesh(box(12, 0.1, 10), flat('#1d1836', { roughness: 0.6 }), 0, -0.05, -1);
  mesh(new THREE.CylinderGeometry(2.6, 2.6, 0.06, 40), flat('#2a2150', { flatShading: false, roughness: 0.6 }), 0.1, 0.03, -1.0); // stage disc
  mesh(box(9, 4.6, 0.12), flat('#151a3a'), 0, 2.3, -3.55);
  for (const [y, c] of [[0.35, '#ff3fa4'], [4.1, '#36e0ff']]) mesh(box(8.6, 0.07, 0.04), new THREE.MeshBasicMaterial({ color: c }), 0, y, -3.47);
  for (const x of [-3.2, 2.6]) mesh(box(0.07, 3.6, 0.04), new THREE.MeshBasicMaterial({ color: x < 0 ? '#ff3fa4' : '#36e0ff' }), x, 2.2, -3.47);
  mesh(box(BOARD.w + 0.2, BOARD.h + 0.2, 0.06), new THREE.MeshBasicMaterial({ color: '#7b4dff' }), BOARD.x, BOARD.y, BOARD.z - 0.04);
  // contestant podium (same footprint as the desk)
  mesh(box(3.0, 0.08, 1.1), flat('#1f1b3a'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.76, 0.06), flat('#ff3fa4', { emissive: '#5a0f3a', emissiveIntensity: 0.6 }), 0.15, 0.4, -0.02);
  mesh(box(2.9, 0.05, 0.07), new THREE.MeshBasicMaterial({ color: '#36e0ff' }), 0.15, 0.7, 0.0);
  mesh(new THREE.CylinderGeometry(0.11, 0.12, 0.05, 16), flat('#2a2a2a', { flatShading: false }), 0.7, 0.865, -0.42);
  mesh(new THREE.SphereGeometry(0.09, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), flat('#e5262f', { flatShading: false, emissive: '#5a0000', emissiveIntensity: 0.6, roughness: 0.4 }), 0.7, 0.89, -0.42);
  // ONE's host stand
  mesh(new THREE.CylinderGeometry(0.24, 0.3, STACK_TOP - 0.84 + 0.84, 16), flat('#d4a24c', { flatShading: false, roughness: 0.45 }), -0.95, (STACK_TOP) / 2, -0.45);
  mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.03, 16), new THREE.MeshBasicMaterial({ color: '#36e0ff' }), -0.95, STACK_TOP - 0.015, -0.45);
  // stool
  mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.06, 12), flat('#36e0ff', { flatShading: false }), 1.2, 0.5, -0.95);
  for (const a of [0, 2.1, 4.2]) mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.48, 5), flat('#cfcfcf'), 1.2 + Math.cos(a) * 0.17, 0.24, -0.95 + Math.sin(a) * 0.17);
  const pink = new THREE.PointLight('#ff4fb0', 5, 6); pink.position.set(-2.2, 2.6, -0.6); scene.add(pink);
  const cyan = new THREE.PointLight('#40d8ff', 5, 6); cyan.position.set(2.4, 2.6, -0.4); scene.add(cyan);
}

// Rooftop at sunset: parapet, black water tank, clothesline, plants, plastic
// table and chair, ONE on an upturned bucket on bricks.
function buildTerrace() {
  scene.background = new THREE.Color('#f29c6b');
  mesh(box(12, 0.1, 10), flat('#a39b8e'), 0, -0.05, -1);
  mesh(box(9, 1.0, 0.22), flat('#d8c7ad'), 0, 0.5, -3.6);
  mesh(box(9, 0.08, 0.3), flat('#bfae94'), 0, 1.04, -3.6);
  mesh(box(0.22, 1.0, 5), flat('#d8c7ad'), -4.4, 0.5, -1.2);
  // water tank
  mesh(new THREE.CylinderGeometry(0.55, 0.6, 1.15, 16), flat('#1d1d20', { flatShading: false, roughness: 0.5 }), 2.7, 1.3, -2.9);
  mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.1, 16), flat('#2a2a2e', { flatShading: false }), 2.7, 1.92, -2.9);
  mesh(box(1.3, 0.72, 1.3), flat('#9d958a'), 2.7, 0.36, -2.9);
  // clothesline with a few clothes
  mesh(box(0.05, 2.1, 0.05), flat('#6b6b6b'), -3.3, 1.05, -2.6);
  mesh(box(0.05, 2.1, 0.05), flat('#6b6b6b'), -1.3, 1.05, -3.2);
  const rope = mesh(new THREE.CylinderGeometry(0.008, 0.008, 2.1, 4), flat('#eeeeee'), -2.3, 2.0, -2.9);
  rope.rotation.z = Math.PI / 2; rope.rotation.y = 0.29;
  [['#e8742c', -2.9], ['#2f7fbf', -2.4], ['#f2c14e', -1.85]].forEach(([c, x]) => mesh(box(0.34, 0.5, 0.03), flat(c), x, 1.72, -2.9 + (x + 2.3) * -0.3));
  // plants
  for (const [x, z, s] of [[-2.6, -1.6, 1], [-3.0, -0.6, 0.8]]) {
    mesh(new THREE.CylinderGeometry(0.22 * s, 0.16 * s, 0.32 * s, 10), flat('#b5562f'), x, 0.16 * s, z);
    mesh(new THREE.IcosahedronGeometry(0.32 * s, 0), flat('#3d8b4d'), x, 0.5 * s, z);
  }
  // plastic table (counter footprint) and chair
  mesh(box(3.0, 0.06, 1.1), flat('#ecebe6'), 0.15, 0.81, -0.55);
  for (const [dx, dz] of [[-1.35, -0.45], [1.35, -0.45], [-1.35, 0.45], [1.35, 0.45]])
    mesh(box(0.06, 0.78, 0.06), flat('#d9d7d0'), 0.15 + dx, 0.39, -0.55 + dz);
  mesh(new THREE.CylinderGeometry(0.06, 0.05, 0.12, 10), flat('#f3f1ea'), 0.6, 0.9, -0.35);           // chai glass
  mesh(box(0.16, 0.012, 0.3), flat('#1b1b1b'), 0.35, 0.845, -0.3);                                     // phone on the table
  mesh(box(0.6, 0.06, 0.55), flat('#c9302c'), 1.2, 0.5, -0.95);
  mesh(box(0.6, 0.6, 0.06), flat('#c9302c'), 1.42, 0.82, -1.15).rotation.y = -0.6;
  for (const [dx, dz] of [[-0.25, -0.22], [0.25, -0.22], [-0.25, 0.22], [0.25, 0.22]])
    mesh(box(0.05, 0.47, 0.05), flat('#a52521'), 1.2 + dx, 0.24, -0.95 + dz);
  // ONE's perch: bricks + upturned blue bucket up to the same height
  mesh(box(0.46, 0.14, 0.24), flat('#a8513a'), -0.95, 0.91, -0.45);
  mesh(box(0.46, 0.14, 0.24), flat('#b45e44'), -0.95, 1.05, -0.45);
  mesh(new THREE.CylinderGeometry(0.17, 0.21, STACK_TOP - 1.12, 14), flat('#2f6fb3', { flatShading: false, roughness: 0.5 }), -0.95, 1.12 + (STACK_TOP - 1.12) / 2, -0.45);
  // string lights + warm sun rim
  ['#ffcf6b', '#fff1c8', '#ffcf6b', '#fff1c8', '#ffcf6b', '#fff1c8'].forEach((c, i) =>
    mesh(new THREE.SphereGeometry(0.05, 10, 6), new THREE.MeshBasicMaterial({ color: c }), -2.6 + i * 0.95, 2.55 + 0.08 * Math.sin(i * 1.3), -1.9));
  const sun = new THREE.PointLight('#ff9a4d', 8, 12); sun.position.set(-3, 3, -5); scene.add(sun);
}

// VINEET's room at night: study table with laptop and lamp, posters, a shelf,
// window with the city outside, ONE on a pile of cushions and books.
function buildBedroom() {
  scene.background = new THREE.Color('#141a2e');
  mesh(box(10, 0.1, 9), flat('#6b4a35'), 0, -0.05, -1);
  mesh(box(3.4, 0.02, 2.4), flat('#3a4a7a'), 0.3, 0.01, -1.4);                      // rug
  const wall = flat('#2f3a5c');
  mesh(box(3.2, 4.2, 0.15), wall, -3.0, 2.1, -4);
  mesh(box(2.2, 4.2, 0.15), wall, 2.9, 2.1, -4);
  mesh(box(3.6, 1.0, 0.15), wall, 0.0, 0.5, -4);
  mesh(box(3.6, 1.2, 0.15), wall, 0.0, 3.6, -4);
  const frameMat = flat('#e8e2d0');
  for (const x of [-1.8, 0.0, 1.8]) mesh(box(0.08, 2.0, 0.12), frameMat, x, 2.0, -3.95);
  for (const y of [1.0, 3.0]) mesh(box(3.7, 0.08, 0.12), frameMat, 0, y, -3.95);
  // posters + shelf
  [['#e8742c', -3.2, 2.5, 0.8, 1.1], ['#2bb3a3', -2.3, 2.9, 0.6, 0.8], ['#f2c14e', 2.6, 2.6, 0.7, 0.9]].forEach(([c, x, y, w, h]) => {
    mesh(box(w, h, 0.02), flat(c), x, y, -3.91);
    mesh(box(w * 0.7, h * 0.12, 0.02), flat('#1b1b1b'), x, y - h * 0.25, -3.9);
  });
  mesh(box(1.4, 0.05, 0.3), flat('#6b4630'), 2.6, 1.6, -3.8);
  ['#c94c4c', '#4f6fb3', '#f2c14e', '#3d8b6d', '#e8e2d0'].forEach((c, i) => mesh(box(0.1, 0.3 + (i % 2) * 0.05, 0.22), flat(c), 2.1 + i * 0.13, 1.78, -3.8));
  // bed at the right edge
  mesh(box(1.6, 0.45, 2.2), flat('#3b3f6b'), 3.1, 0.23, -2.2);
  mesh(box(1.6, 0.18, 2.1), flat('#d9d4e8'), 3.1, 0.54, -2.2);
  mesh(box(0.9, 0.16, 0.45), flat('#f0eadf'), 3.1, 0.7, -3.0);
  // study table (desk footprint) + laptop + lamp + phone
  mesh(box(3.0, 0.08, 1.1), flat('#c49a6c'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#a07a50'), 0.15, 0.4, -1.05);
  mesh(box(0.5, 0.02, 0.34), flat('#9aa1ab'), -0.15, 0.85, -0.55);
  const lid = mesh(box(0.5, 0.32, 0.02), flat('#9aa1ab'), -0.15, 1.0, -0.73); lid.rotation.x = -0.25;
  mesh(box(0.44, 0.27, 0.005), new THREE.MeshBasicMaterial({ color: '#4fb3ff' }), -0.15, 1.0, -0.715).rotation.x = -0.25;
  mesh(new THREE.CylinderGeometry(0.07, 0.08, 0.03, 10), flat('#2a2a2a'), 0.75, 0.855, -0.85);
  mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.36, 6), flat('#2a2a2a'), 0.75, 1.04, -0.85);
  mesh(new THREE.ConeGeometry(0.13, 0.16, 12, 1, true), flat('#f2c14e', { side: THREE.DoubleSide }), 0.75, 1.25, -0.85);
  const desk = new THREE.PointLight('#ffc27a', 5, 3.5); desk.position.set(0.7, 1.15, -0.75); scene.add(desk);
  mesh(box(0.09, 0.012, 0.18), flat('#1b1b1b'), 0.55, 0.845, -0.3);
  // ONE's perch: books + two cushions, up to the same height
  mesh(box(0.46, 0.12, 0.34), flat('#4f6fb3'), -0.95, 0.9, -0.45);
  mesh(box(0.42, 0.1, 0.32), flat('#c94c4c'), -0.95, 1.01, -0.45);
  const cu1 = mesh(new THREE.SphereGeometry(0.25, 12, 6), flat('#f2c14e', { flatShading: false }), -0.95, 1.13, -0.45); cu1.scale.set(1, 0.32, 0.8);
  const cu2 = mesh(new THREE.SphereGeometry(0.22, 12, 6), flat('#e46a8a', { flatShading: false }), -0.95, 1.24, -0.45); cu2.scale.set(1, 0.3, 0.8);
  STACK_TOP = 1.3;
  // chair
  mesh(box(0.6, 0.07, 0.55), flat('#33415e'), 1.2, 0.5, -0.95);
  mesh(box(0.6, 0.7, 0.07), flat('#33415e'), 1.42, 0.85, -1.15).rotation.y = -0.6;
  for (const [dx, dz] of [[-0.25, -0.22], [0.25, -0.22], [-0.25, 0.22], [0.25, 0.22]])
    mesh(box(0.05, 0.47, 0.05), flat('#222a3d'), 1.2 + dx, 0.24, -0.95 + dz);
  // fairy lights along the window top (few, big, static)
  ['#ffcf6b', '#fff1c8', '#ffcf6b', '#fff1c8', '#ffcf6b'].forEach((c, i) =>
    mesh(new THREE.SphereGeometry(0.045, 10, 6), new THREE.MeshBasicMaterial({ color: c }), -1.6 + i * 0.8, 3.12 - 0.06 * Math.sin(i * 1.2), -3.85));
}

// Canvas-text plate (name plates, desk logos): big, flat, static so nothing shimmers.
function plate(text, w, h, bg, fg, font = '800 120px Poppins') {
  const c = document.createElement('canvas'); c.width = 1024; c.height = Math.round(1024 * h / w);
  const g = c.getContext('2d');
  g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = fg; g.font = font; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, c.width / 2, c.height / 2 + 6);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshBasicMaterial({ map: t });
}
function addChair(col, dark) {
  mesh(box(0.6, 0.07, 0.55), flat(col), 1.2, 0.5, -0.95);
  mesh(box(0.6, 0.7, 0.07), flat(col), 1.42, 0.85, -1.15).rotation.y = -0.6;
  for (const [dx, dz] of [[-0.25, -0.22], [0.25, -0.22], [-0.25, 0.22], [0.25, 0.22]])
    mesh(box(0.05, 0.47, 0.05), flat(dark), 1.2 + dx, 0.24, -0.95 + dz);
}

// Courtroom: wood-panelled wall, maroon case plaque where the board is, judge's
// bench (ONE) with a gavel, lawyer's table with red-tape files, the accused's dock.
function buildCourt() {
  scene.background = new THREE.Color('#2a1b12');
  mesh(box(12, 0.1, 10), flat('#6e4a2e'), 0, -0.05, -1);
  mesh(box(10, 4.6, 0.15), flat('#5a3a22'), 0, 2.3, -3.6);
  for (const x of [-3.6, -2.0, 1.4, 3.0]) mesh(box(0.34, 4.4, 0.1), flat('#47301c'), x, 2.2, -3.5);   // pilasters
  mesh(box(10, 0.16, 0.12), flat('#3a2616'), 0, 1.0, -3.5);                                          // dado rail
  mesh(box(BOARD.w + 0.24, BOARD.h + 0.24, 0.06), flat('#c9a14a', { roughness: 0.5 }), BOARD.x, BOARD.y, BOARD.z - 0.04);
  // wall clock (big and simple)
  mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.05, 24), flat('#f3ead6', { flatShading: false }), 2.25, 3.25, -3.45).rotation.x = Math.PI / 2;
  mesh(box(0.025, 0.2, 0.02), flat('#222'), 2.25, 3.3, -3.41);
  mesh(box(0.15, 0.025, 0.02), flat('#222'), 2.31, 3.25, -3.41);
  // lawyer's table (desk footprint) + red-tape files
  mesh(box(3.0, 0.08, 1.1), flat('#7a4f2c'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#5e3c21'), 0.15, 0.4, -0.02);
  for (const [x, z, n] of [[0.35, -0.45, 3], [0.75, -0.6, 2]]) for (let i = 0; i < n; i++) {
    mesh(box(0.34, 0.06, 0.26), flat(['#d8c9a3', '#cdb98c', '#e2d4b0'][i]), x, 0.87 + i * 0.065, z);
    mesh(box(0.35, 0.012, 0.03), flat('#b3261e'), x, 0.87 + i * 0.065, z);
  }
  // judge's bench on the table: panelled block up to ONE's perch height + gavel
  mesh(box(0.72, STACK_TOP - 0.84, 0.5), flat('#4a2f1a'), -0.95, 0.84 + (STACK_TOP - 0.84) / 2, -0.45);
  mesh(box(0.8, 0.04, 0.56), flat('#6b4426'), -0.95, STACK_TOP - 0.02, -0.45);
  mesh(box(0.42, 0.24, 0.01), plate('JUDGE', 0.42, 0.24, '#2a1a0e', '#e2c16a'), -0.95, 1.04, -0.195);
  mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.03, 14), flat('#3a2414', { flatShading: false }), -0.6, STACK_TOP + 0.015, -0.3);
  // the accused's dock (kathghara) at the back right, with the "mujrim": a laptop
  mesh(box(1.1, 0.9, 0.08), flat('#5e3c21'), 2.6, 0.45, -2.2);
  for (const x of [2.1, 2.35, 2.6, 2.85, 3.1]) mesh(box(0.05, 0.5, 0.05), flat('#3a2616'), x, 1.15, -2.2);
  mesh(box(1.15, 0.06, 0.12), flat('#3a2616'), 2.6, 1.42, -2.2);
  mesh(box(0.5, 0.02, 0.34), flat('#9aa1ab'), 2.6, 0.93, -2.55);
  const lid = mesh(box(0.5, 0.32, 0.02), flat('#9aa1ab'), 2.6, 1.08, -2.73); lid.rotation.x = -0.2;
  mesh(box(0.44, 0.27, 0.005), new THREE.MeshBasicMaterial({ color: '#5ff2df' }), 2.6, 1.08, -2.715).rotation.x = -0.2;
  addChair('#7a2a2a', '#3a1414');
  const warm = new THREE.PointLight('#ffc07a', 5, 7); warm.position.set(0.5, 3.2, -1.2); scene.add(warm);
}

// TV newsroom: navy set, big video wall (board), side screens with the city,
// glossy anchor desk with the channel logo, red accent strips.
function buildNewsroom() {
  scene.background = new THREE.Color('#070c1c');
  mesh(box(12, 0.1, 10), flat('#141a30', { roughness: 0.5 }), 0, -0.05, -1);
  mesh(box(10, 4.6, 0.15), flat('#0e1630'), 0, 2.3, -3.6);
  mesh(box(BOARD.w + 0.16, BOARD.h + 0.16, 0.06), flat('#05070f'), BOARD.x, BOARD.y, BOARD.z - 0.04);
  const city = new THREE.MeshBasicMaterial({ map: paintBackdrop('city') });
  for (const x of [-2.75, 2.35]) {
    mesh(box(1.5, 1.9, 0.05), flat('#05070f'), x, 2.2, -3.45);
    const s = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.8), city); s.position.set(x, 2.2, -3.42); scene.add(s);
  }
  for (const y of [0.55, 3.95]) mesh(box(9.6, 0.06, 0.04), new THREE.MeshBasicMaterial({ color: '#e8213b' }), 0, y, -3.5);
  // anchor desk (desk footprint): dark top, logo front, red light strip
  mesh(box(3.0, 0.08, 1.1), flat('#1c2440', { roughness: 0.35 }), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#111933'), 0.15, 0.4, -0.02);
  mesh(box(1.3, 0.3, 0.01), plate('ONE NEWS', 1.3, 0.3, '#c8102e', '#ffffff'), 0.15, 0.45, 0.015);
  mesh(box(2.9, 0.04, 0.07), new THREE.MeshBasicMaterial({ color: '#4fb3ff' }), 0.15, 0.74, 0.0);
  mesh(box(0.22, 0.012, 0.3), flat('#eeeeee'), 0.45, 0.845, -0.35);                               // script papers
  // ONE's riser on the desk
  mesh(new THREE.CylinderGeometry(0.2, 0.25, STACK_TOP - 0.84, 14), flat('#2a3560', { flatShading: false, roughness: 0.4 }), -0.95, 0.84 + (STACK_TOP - 0.84) / 2, -0.45);
  mesh(new THREE.CylinderGeometry(0.23, 0.23, 0.02, 14), new THREE.MeshBasicMaterial({ color: '#e8213b' }), -0.95, STACK_TOP - 0.01, -0.45);
  addChair('#2a3560', '#141a30');
  const blue = new THREE.PointLight('#4fa3ff', 5, 7); blue.position.set(2.4, 2.8, -0.8); scene.add(blue);
  const red = new THREE.PointLight('#ff3048', 3, 6); red.position.set(-2.6, 2.6, -1.2); scene.add(red);
}

// Podcast room: warm wall with big acoustic panels, ON AIR neon sign (board),
// two boom mics on the table, mug, plant, shelf with records.
let micArms = [];
function buildPodcast() {
  scene.background = new THREE.Color('#1e1418');
  mesh(box(12, 0.1, 10), flat('#4a3530'), 0, -0.05, -1);
  mesh(box(3.2, 0.02, 2.4), flat('#7a2e3a'), 0.3, 0.01, -1.4);                                    // rug
  mesh(box(10, 4.6, 0.15), flat('#3a2a30'), 0, 2.3, -3.6);
  for (const [x, y, c] of [[-3.0, 2.6, '#c25b3a'], [-2.1, 1.7, '#7a3550'], [1.9, 2.9, '#2f5a6a'], [2.9, 1.8, '#c25b3a'], [2.2, 1.0, '#7a3550']])
    mesh(box(0.8, 0.8, 0.12), flat(c, { roughness: 1 }), x, y, -3.45);                             // acoustic panels
  mesh(box(BOARD.w + 0.16, BOARD.h + 0.16, 0.06), flat('#120c10'), BOARD.x, BOARD.y, BOARD.z - 0.04);
  mesh(box(1.4, 0.05, 0.3), flat('#5a3a2a'), -2.7, 1.25, -3.4);
  ['#1b1b1b', '#c94c4c', '#1b1b1b', '#f2c14e', '#1b1b1b'].forEach((c, i) => mesh(box(0.04, 0.34, 0.3), flat(c), -3.2 + i * 0.12, 1.45, -3.4));
  // table (desk footprint) + mics on boom arms + mug + plant
  mesh(box(3.0, 0.08, 1.1), flat('#6b4630'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#4e3222'), 0.15, 0.4, -0.02);
  for (const [x, z, ry] of [[0.55, -0.35, -0.5], [-0.45, -0.3, 0.6]]) {
    mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.03, 12), flat('#222'), x, 0.855, z);
    const arm = mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.4, 6), flat('#2a2a2a'), x, 1.05, z); arm.rotation.z = ry * 0.4;
    const mic = mesh(new THREE.CapsuleGeometry(0.045, 0.1, 4, 10), flat('#3a3a3f', { flatShading: false, roughness: 0.4 }), x - ry * 0.16, 1.27, z);
    mic.rotation.z = ry; micArms.push(mic);
  }
  mesh(new THREE.CylinderGeometry(0.05, 0.045, 0.11, 12), flat('#f2c14e', { flatShading: false }), 0.95, 0.895, -0.75);
  mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.3, 10), flat('#b5562f'), 3.0, 0.15, -2.4);
  mesh(new THREE.IcosahedronGeometry(0.34, 0), flat('#3d8b4d'), 3.0, 0.55, -2.4);
  // ONE's perch: crate + headphones case
  mesh(box(0.46, 0.24, 0.36), flat('#8a6a4a'), -0.95, 0.96, -0.45);
  mesh(new THREE.CylinderGeometry(0.17, 0.2, STACK_TOP - 1.08, 14), flat('#2b2b33', { flatShading: false }), -0.95, 1.08 + (STACK_TOP - 1.08) / 2, -0.45);
  addChair('#c25b3a', '#4a2a20');
  const warm = new THREE.PointLight('#ff9a6b', 5, 6); warm.position.set(1.8, 2.6, -0.6); scene.add(warm);
  const pink = new THREE.PointLight('#ff3f6a', 3, 5); pink.position.set(-1.2, 2.6, -2.4); scene.add(pink);
}

// HR interview cabin: light walls, window with the city, company logo, plant,
// water cooler, desk with nameplate, files and laptop.
function buildOffice() {
  scene.background = new THREE.Color('#d9dde4');
  mesh(box(12, 0.1, 10), flat('#8c8f96'), 0, -0.05, -1);
  const wall = flat('#e3e6ec');
  mesh(box(3.0, 4.4, 0.15), wall, -3.4, 2.2, -4);
  mesh(box(2.6, 4.4, 0.15), wall, 3.3, 2.2, -4);
  mesh(box(4.2, 0.9, 0.15), wall, 0.0, 0.45, -4);
  mesh(box(4.2, 1.1, 0.15), wall, 0.0, 3.85, -4);
  for (const x of [-1.95, 0.0, 1.95]) mesh(box(0.07, 2.4, 0.12), flat('#9aa0aa'), x, 2.1, -3.95);
  for (const y of [0.92, 3.3]) mesh(box(4.0, 0.07, 0.12), flat('#9aa0aa'), 0, y, -3.95);
  mesh(box(1.1, 0.4, 0.02), plate('AI Pvt Ltd', 1.1, 0.4, '#2b3a8c', '#ffffff', '800 150px Poppins'), -3.3, 3.0, -3.91);
  mesh(box(0.8, 1.0, 0.02), flat('#f2c14e'), 3.2, 2.5, -3.91);
  mesh(box(0.56, 0.12, 0.02), flat('#1b1b1b'), 3.2, 2.3, -3.9);
  // water cooler + plant
  mesh(box(0.4, 1.0, 0.4), flat('#f4f4f4'), -2.9, 0.5, -3.2);
  mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.42, 14), flat('#7fc4ff', { flatShading: false, roughness: 0.3 }), -2.9, 1.22, -3.2);
  mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.32, 10), flat('#e8e8e8'), 2.9, 0.16, -2.6);
  mesh(new THREE.IcosahedronGeometry(0.38, 0), flat('#3d8b4d'), 2.9, 0.6, -2.6);
  // desk (desk footprint) + files + laptop + nameplate in front of ONE
  mesh(box(3.0, 0.08, 1.1), flat('#b98b5e'), 0.15, 0.8, -0.55);
  mesh(box(2.9, 0.75, 0.06), flat('#9a7048'), 0.15, 0.4, -0.02);
  for (let i = 0; i < 3; i++) mesh(box(0.3, 0.03, 0.24), flat(['#2b3a8c', '#c94c4c', '#2bb3a3'][i]), 0.65, 0.855 + i * 0.032, -0.7);
  mesh(box(0.5, 0.02, 0.34), flat('#9aa1ab'), 0.2, 0.85, -0.75);
  const lid = mesh(box(0.5, 0.32, 0.02), flat('#9aa1ab'), 0.2, 1.0, -0.93); lid.rotation.x = -0.25;
  mesh(box(0.38, 0.1, 0.06), plate('HR', 0.38, 0.1, '#1b1b1b', '#f2c14e'), -0.95, 0.9, -0.12);
  // ONE's perch: office chair cushion on a box file stack
  mesh(box(0.44, 0.3, 0.32), flat('#5a6475'), -0.95, 0.99, -0.45);
  mesh(new THREE.CylinderGeometry(0.2, 0.2, STACK_TOP - 1.14, 14), flat('#2f3442', { flatShading: false }), -0.95, 1.14 + (STACK_TOP - 1.14) / 2, -0.45);
  addChair('#2f3442', '#1b1e26');
  const day = new THREE.PointLight('#ffffff', 4, 8); day.position.set(0.5, 3.2, -1.0); scene.add(day);
}

({ tapri: buildTapri, studio: buildStudio, terrace: buildTerrace, bedroom: buildBedroom, court: buildCourt,
   newsroom: buildNewsroom, podcast: buildPodcast, office: buildOffice }[LOC] || buildClassroom)();
await addBackdrop({ tapri: 'street', studio: 'studio', terrace: 'sunset' }[LOC] || 'city');

// ---------- VINEET (low-poly boy: hoodie, headphones round the neck, quiff) ----------
const boy = new THREE.Group();
boy.position.set(1.2, 0, -0.95);
boy.rotation.y = -0.95; // faces the board/ONE (towards -x)
scene.add(boy);
const hoodie = flat('#2f7fbf'), hoodieDark = flat('#24679c'), skin = flat('#c68a5e'), jeans = flat('#2e3550');
const torso = mesh(new THREE.CylinderGeometry(0.24, 0.31, 0.62, 8), hoodie, 0, 0.86, 0, boy);
mesh(new THREE.TorusGeometry(0.19, 0.075, 5, 10, Math.PI), hoodieDark, 0, 1.1, -0.1, boy).rotation.set(-1.0, 0, 0); // hood
mesh(box(0.012, 0.16, 0.012), flat('#f3f1ea'), -0.06, 1.0, 0.255, boy);
mesh(box(0.012, 0.16, 0.012), flat('#f3f1ea'), 0.06, 1.0, 0.255, boy);
mesh(box(0.3, 0.12, 0.02), hoodieDark, 0, 0.72, 0.28, boy); // pocket
// headphones resting on the neck
const hpMat = flat('#1d1f27'), hpAccent = flat('#ff9a1f');
const hpBand = mesh(new THREE.TorusGeometry(0.15, 0.022, 5, 12, Math.PI), hpMat, 0, 1.12, 0.0, boy);
hpBand.rotation.set(-1.25, 0, 0);
for (const sx of [-1, 1]) {
  const cup = mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.05, 8), hpMat, sx * 0.165, 1.1, 0.07, boy);
  cup.rotation.z = Math.PI / 2;
  const cap = mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.012, 8), hpAccent, sx * 0.196, 1.1, 0.07, boy);
  cap.rotation.z = Math.PI / 2;
}
const armL = mesh(box(0.13, 0.13, 0.46), hoodie, -0.22, 0.88, 0.2, boy);
const armR = mesh(box(0.13, 0.13, 0.46), hoodie, 0.22, 0.88, 0.2, boy);
mesh(box(0.1, 0.07, 0.11), skin, 0, -0.01, 0.27, armL);
mesh(box(0.1, 0.07, 0.11), skin, 0, -0.01, 0.27, armR);
mesh(box(0.42, 0.16, 0.45), jeans, 0, 0.6, 0.12, boy); // lap
for (const sx of [-1, 1]) {
  mesh(box(0.15, 0.48, 0.15), jeans, sx * 0.11, 0.3, 0.32, boy);
  mesh(box(0.16, 0.08, 0.24), flat('#f3f1ea'), sx * 0.11, 0.04, 0.36, boy);
}
const headPivot = new THREE.Group(); headPivot.position.set(0, 1.22, 0); boy.add(headPivot);
mesh(new THREE.CylinderGeometry(0.075, 0.085, 0.14, 7), skin, 0, 0.0, 0, headPivot);
const head = mesh(new THREE.SphereGeometry(0.255, 9, 7), skin, 0, 0.23, 0, headPivot);
head.scale.set(1, 1.1, 0.98);
const hairMat = flat('#1a1310');
const hair = mesh(new THREE.SphereGeometry(0.268, 9, 5, 0, Math.PI * 2, 0, Math.PI * 0.45), hairMat, 0, 0.255, -0.02, headPivot);
hair.scale.set(1.0, 1.12, 1.03); hair.rotation.x = -0.3;
[[-0.09, 0.45, 0.12, 0.25], [0.02, 0.475, 0.14, -0.05], [0.11, 0.455, 0.11, -0.3]].forEach(([x, y, z, rz]) => {
  const q = mesh(box(0.14, 0.09, 0.14), hairMat, x, y, z, headPivot); q.rotation.set(-0.45, 0.1, rz);
});
for (const sx of [-1, 1]) {
  mesh(box(0.05, 0.13, 0.1), hairMat, sx * 0.235, 0.29, 0.02, headPivot);
  mesh(box(0.03, 0.07, 0.06), skin, sx * 0.262, 0.22, 0, headPivot); // ears
}
const ink = new THREE.MeshBasicMaterial({ color: '#15131a' });
const shine = new THREE.MeshBasicMaterial({ color: '#ffffff' });
const eyeL = mesh(box(0.045, 0.068, 0.02), ink, -0.085, 0.245, 0.238, headPivot);
const eyeR = mesh(box(0.045, 0.068, 0.02), ink, 0.085, 0.245, 0.238, headPivot);
mesh(box(0.014, 0.014, 0.01), shine, 0.01, 0.017, 0.011, eyeL);
mesh(box(0.014, 0.014, 0.01), shine, 0.01, 0.017, 0.011, eyeR);
const browL = mesh(box(0.09, 0.022, 0.02), ink, -0.088, 0.325, 0.232, headPivot);
const browR = mesh(box(0.09, 0.022, 0.02), ink, 0.088, 0.325, 0.232, headPivot);
browL.rotation.z = 0.08; browR.rotation.z = -0.08;
mesh(new THREE.ConeGeometry(0.026, 0.065, 4), flat('#b0734c'), 0, 0.19, 0.262, headPivot).rotation.x = Math.PI / 2;
const mouth = mesh(box(0.08, 0.018, 0.02), new THREE.MeshBasicMaterial({ color: '#4a1c1c' }), 0, 0.105, 0.236, headPivot);
// Children of the mouth live in the mouth's own units (metres, then scaled with
// it), so they are sized to sit INSIDE the 0.08 x 0.018 m mouth box.
const teeth = mesh(box(0.068, 0.005, 0.004), new THREE.MeshBasicMaterial({ color: '#f4efe6' }), 0, 0.006, 0.009, mouth);
const tongue = mesh(box(0.046, 0.006, 0.004), new THREE.MeshBasicMaterial({ color: '#b5524f' }), 0, -0.005, 0.009, mouth);
teeth.castShadow = tongue.castShadow = false;
const eyeBase = { L: eyeL.position.clone(), R: eyeR.position.clone() };

// ---------- ONE (original mascot: teal low-poly orb, dark face visor, cyan LED eyes, antenna bulb) ----------
const one = new THREE.Group();
one.position.set(-0.95, STACK_TOP, -0.45);
scene.add(one);
const oneBody = new THREE.Group(); one.add(oneBody);
const tealMat = flat('#2bb3a3', { emissive: '#0c3b36', emissiveIntensity: 0.5 });
const orb = mesh(new THREE.IcosahedronGeometry(0.2, 1), tealMat, 0, 0.21, 0, oneBody);
orb.scale.set(1.08, 0.95, 1);
const visor = mesh(new THREE.SphereGeometry(0.205, 12, 6, Math.PI / 2 - 0.8, 1.6, 1.0, 0.95),
  new THREE.MeshStandardMaterial({ color: '#0e1a2e', roughness: 0.7, metalness: 0.0, flatShading: false }), 0, 0.21, 0.012, oneBody);
visor.scale.set(1.08, 0.95, 1);
visor.castShadow = false;
mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.14, 5), flat('#1b6f66'), 0, 0.46, 0, oneBody);
const bulbMat = new THREE.MeshStandardMaterial({ color: '#ffb547', emissive: '#ff9a1f', emissiveIntensity: 1.2, flatShading: true });
const bulb = mesh(new THREE.IcosahedronGeometry(0.04, 0), bulbMat, 0, 0.55, 0, oneBody);
const footMat = flat('#1f8f83');
mesh(new THREE.IcosahedronGeometry(0.06, 0), footMat, -0.08, 0.03, 0.05, one).scale.set(1.2, 0.6, 1.3);
mesh(new THREE.IcosahedronGeometry(0.06, 0), footMat, 0.08, 0.03, 0.05, one).scale.set(1.2, 0.6, 1.3);
const led = new THREE.MeshBasicMaterial({ color: '#8ffcff' });
const oEyeL = mesh(box(0.038, 0.07, 0.02), led, -0.062, 0.245, 0.222, oneBody);
const oEyeR = mesh(box(0.038, 0.07, 0.02), led, 0.062, 0.245, 0.222, oneBody);
const oneMouth = mesh(box(0.05, 0.012, 0.02), led, 0, 0.178, 0.219, oneBody);
const armOne = mesh(new THREE.CapsuleGeometry(0.025, 0.08, 3, 6), tealMat, -0.2, 0.16, 0.03, oneBody);
armOne.rotation.z = -0.5;
const oneGlow = new THREE.PointLight('#5ff2df', 0.0, 1.2); oneGlow.position.set(0, 0.25, 0.6); oneBody.add(oneGlow);
// pointer stick, held in ONE's right hand
const stickPivot = new THREE.Group(); stickPivot.position.set(0.19, 0.18, 0.03); one.add(stickPivot);
mesh(new THREE.CapsuleGeometry(0.028, 0.05, 3, 6), tealMat, 0, 0.0, 0, stickPivot);
const stick = mesh(new THREE.CylinderGeometry(0.008, 0.012, 1.0, 5), flat('#f1e3b8'), 0, 0.5, 0, stickPivot);
stick.castShadow = false;
// The pointer stick only makes sense when ONE writes on a board.
stick.visible = stickPivot.visible = TL.lines.some(l => (l.board || []).some(o => o.op === 'write'));

// Gavel in ONE's right hand (court episodes): swings down on every knock.
const gavel = new THREE.Group(); gavel.position.set(0.2, 0.17, 0.08); oneBody.add(gavel);
mesh(new THREE.CapsuleGeometry(0.028, 0.05, 3, 6), tealMat, 0, 0, 0, gavel);
mesh(new THREE.CylinderGeometry(0.012, 0.014, 0.24, 8), flat('#7a4a22', { flatShading: false }), 0.12, 0, 0, gavel).rotation.z = Math.PI / 2;
mesh(new THREE.CylinderGeometry(0.036, 0.036, 0.12, 12), flat('#5a3418', { flatShading: false }), 0.24, 0, 0, gavel).rotation.x = Math.PI / 2;
gavel.visible = LOC === 'court';

// Costume accessories on ONE (the character itself never changes): judge | tie | anchor | headset
const COSTUME = TL.costume || ({ court: 'judge', office: 'tie', newsroom: 'anchor', podcast: 'headset' }[LOC] || '');
if (COSTUME === 'judge') {
  mesh(new THREE.CylinderGeometry(0.15, 0.17, 0.05, 16), flat('#16161a', { flatShading: false }), 0, 0.045, 0, oneBody);
  for (const x of [-0.019, 0.019]) { const b = mesh(box(0.026, 0.06, 0.008), flat('#f6f6f2'), x, 0.05, 0.17, oneBody); b.rotation.x = 0.35; }
}
if (COSTUME === 'tie' || COSTUME === 'anchor') {
  const col = COSTUME === 'tie' ? '#c62a3a' : '#1f4fa8';
  mesh(new THREE.CylinderGeometry(0.15, 0.17, 0.04, 16), flat('#f4f4f4', { flatShading: false }), 0, 0.04, 0, oneBody);
  mesh(box(0.034, 0.03, 0.012), flat(col), 0, 0.075, 0.175, oneBody).rotation.x = 0.4;
  const tie = mesh(new THREE.ConeGeometry(0.026, 0.09, 4), flat(col), 0, 0.03, 0.172, oneBody); tie.rotation.x = Math.PI + 0.4; tie.rotation.y = Math.PI / 4;
  if (COSTUME === 'anchor') mesh(box(0.02, 0.026, 0.012), flat('#111'), 0.06, 0.07, 0.165, oneBody).rotation.x = 0.4;
}
if (COSTUME === 'headset') {
  const band = mesh(new THREE.TorusGeometry(0.215, 0.014, 6, 20, Math.PI), flat('#222', { flatShading: false }), 0, 0.22, -0.02, oneBody);
  for (const x of [-0.215, 0.215]) mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.04, 14), flat('#ff5c74', { flatShading: false }), x, 0.22, -0.02, oneBody).rotation.z = Math.PI / 2;
  const boom = mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.16, 5), flat('#222'), -0.2, 0.15, 0.08, oneBody); boom.rotation.x = 1.2; boom.rotation.z = 0.5;
  mesh(new THREE.SphereGeometry(0.016, 8, 6), flat('#222'), -0.15, 0.13, 0.15, oneBody);
}

// ---------- timeline helpers ----------
const lines = TL.lines;
const lineAt = t => lines.find(l => t >= l.start - 0.05 && t <= l.end + 0.05);
const lastLineBefore = t => [...lines].reverse().find(l => l.start <= t) || lines[0];
const ease = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const clamp01 = x => Math.max(0, Math.min(1, x));

// board ops with absolute times
const ops = [];
for (const l of lines) for (const op of l.board || []) {
  const t0 = l.start + op.at * (l.end - l.start);
  const dur = op.op === 'write' ? Math.min(1.3, Math.max(0.5, op.text.length * 0.045)) : op.op === 'strike' ? 0.3 : op.op === 'stamp' ? 0.28 : 0.55;
  ops.push({ ...op, t0, t1: t0 + dur, line: l });
}
const byId = Object.fromEntries(ops.filter(o => o.op === 'write').map(o => [o.id, o]));
function writeFont(o) { return `700 ${o.size}px Kalam`; }
for (const o of Object.values(byId)) { bctx.font = writeFont(o); o.width = bctx.measureText(o.text).width; o.penX = o.x; }
for (const o of ops) if (o.op === 'stamp') { o.penX = o.x; o.size = o.size || 64; }
for (const o of ops) if (o.op !== 'write' && o.op !== 'stamp' && byId[o.target]) { o.y = byId[o.target].y; o.size = byId[o.target].size; o.x = byId[o.target].x; o.penX = o.x; }

// overlay data (used by the director, the board screens and the 2D overlays)
const NEWS = lines.filter(l => l.overlay?.type === 'news').map(l => ({ headline: l.overlay.headline || '', ticker: l.overlay.ticker || '', t0: l.start, line: l }));
const RAPID = lines.map((l, i) => ({ l, i })).filter(({ l }) => l.overlay?.type === 'rapid').map(({ l, i }) => {
  const q = lines[i - 1] || l;
  return { n: l.overlay.n, of: l.overlay.of, buzz: !!l.overlay.buzz, limit: l.overlay.limit || 5, qStart: q.start, qEnd: q.end, aStart: l.start, aEnd: l.end };
});
const VERDICTS = lines.filter(l => l.overlay?.type === 'verdict').map(l => ({ ...l.overlay, tb: l.start + (l.overlay.at ?? 0.35) * (l.end - l.start), line: l }));
const SCORES = lines.filter(l => l.overlay?.type === 'score').map(l => ({ ...l.overlay, t0: l.start, t1: l.end }));
// gavel knocks: three before each verdict, two on lines marked "gavel": true ("Order, order!")
const KNOCKS = [...VERDICTS.flatMap(v => [v.tb - 0.44, v.tb - 0.22, v.tb]),
                ...lines.filter(l => l.gavel).flatMap(l => [l.start + 0.1, l.start + 0.36])].sort((a, b) => a - b);
function gavelAngle(t) {   // rest raised (+0.35); each knock: lift, strike down (-0.42), back up
  let a = 0.35;
  for (const k of KNOCKS) {
    const d = t - k;
    if (d > -0.1 && d <= 0) a = 0.35 - 0.77 * ease((d + 0.1) / 0.1);
    else if (d > 0 && d < 0.12) a = -0.42 + 0.77 * ease(d / 0.12);
  }
  return a;
}

function drawBoard(t) {
  const g = bctx;
  if (BSTYLE === 'none') return null;
  if (BSTYLE === 'sign') {        // quiz-show screen: neon title + live score
    g.fillStyle = '#0b0f24'; g.fillRect(0, 0, 1024, 640);
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.save(); g.shadowColor = '#ff3fa4'; g.shadowBlur = 28; g.fillStyle = '#ffd6ef'; g.font = '800 150px Poppins';
    g.fillText(TL.board_title || 'AI QUIZ', 512, 270); g.restore();
    const sc = quizScore(t);
    g.save(); g.shadowColor = '#36e0ff'; g.shadowBlur = 18; g.fillStyle = '#c9f6ff'; g.font = '700 58px Poppins';
    g.fillText(sc.total ? `SCORE  ${sc.right} / ${sc.total}` : 'Get ready!', 512, 470); g.restore();
    g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    boardTex.needsUpdate = true;
    return null;
  }
  if (BSTYLE === 'news') { drawNewsScreen(g, t); boardTex.needsUpdate = true; return null; }
  if (BSTYLE === 'onair') { drawOnAir(g, t); boardTex.needsUpdate = true; return null; }
  const PLAQUE = BSTYLE === 'plaque';
  if (PLAQUE) drawPlaque(g);
  else {
  g.fillStyle = CHALK ? '#243b30' : '#f6f5f0'; g.fillRect(0, 0, 1024, 640);
  if (CHALK) {   // old chalk dust: big soft smudges only (no fine grain that could shimmer)
    for (const [x, y, r] of [[220, 420, 260], [760, 260, 300], [520, 560, 220]]) {
      const sm = g.createRadialGradient(x, y, 0, x, y, r);
      sm.addColorStop(0, 'rgba(255,255,255,0.06)'); sm.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = sm; g.fillRect(0, 0, 1024, 640);
    }
  }
  const vg = g.createRadialGradient(512, 320, 200, 512, 320, 700);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, CHALK ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.07)');
  g.fillStyle = vg; g.fillRect(0, 0, 1024, 640);
  g.fillStyle = CHALK ? '#f4f1e8' : '#1b1b1b'; g.font = '700 58px Kalam'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
  g.fillText(TL.board_title, 512, 95);
  g.fillRect(260, 118, 504, 6);
  }
  g.textAlign = 'left';
  let pen = null;
  for (const o of ops) {
    if (t < o.t0) continue;
    const p = clamp01((t - o.t0) / (o.t1 - o.t0));
    if (p < 1) pen = o;
    if (o.op === 'write') {
      g.font = writeFont(o); g.fillStyle = o.color;
      const n = Math.ceil(o.text.length * p);
      g.fillText(o.text.slice(0, n), o.x, o.y);
      o.penX = o.x + g.measureText(o.text.slice(0, n)).width;
    } else if (o.op === 'strike') {
      const tg = byId[o.target]; if (!tg) continue;
      g.strokeStyle = CHALK ? '#ff8fa3' : '#d0312d'; g.lineWidth = 7; g.lineCap = 'round';
      g.beginPath(); g.moveTo(tg.x - 8, tg.y - tg.size * 0.3);
      g.lineTo(tg.x - 8 + (tg.width + 16) * p, tg.y - tg.size * 0.3 + 4 * p); g.stroke();
      o.penX = tg.x + tg.width * p; o.y = tg.y;
    } else if (o.op === 'circle') {
      const tg = byId[o.target]; if (!tg) continue;
      g.strokeStyle = CHALK ? '#ffd86b' : '#d0312d'; g.lineWidth = 6;
      g.beginPath();
      g.ellipse(tg.x + tg.width / 2, tg.y - tg.size * 0.32, tg.width / 2 + 34, tg.size * 0.85, -0.03,
        -Math.PI * 0.6, -Math.PI * 0.6 + Math.PI * 2.1 * p);
      g.stroke();
      o.penX = tg.x + tg.width / 2; o.y = tg.y;
    } else if (o.op === 'stamp') {
      // rubber-stamp verdict: drops in from 1.5x and settles (smooth over ~8 frames)
      const k = ease(p), sc = 1 + 0.5 * (1 - k);
      g.save(); g.globalAlpha = 0.25 + 0.75 * k;
      g.translate(o.x, o.y); g.rotate(o.rot ?? -0.14); g.scale(sc, sc);
      g.font = `800 ${o.size}px Poppins`; g.textAlign = 'center'; g.textBaseline = 'middle';
      const w = g.measureText(o.text).width + 44, h = o.size * 1.25;
      g.strokeStyle = o.color; g.lineWidth = 7; g.strokeRect(-w / 2, -h / 2, w, h);
      g.lineWidth = 3; g.strokeRect(-w / 2 + 9, -h / 2 + 9, w - 18, h - 18);
      g.fillStyle = o.color; g.fillText(o.text, 0, 4);
      g.restore(); g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    }
  }
  boardTex.needsUpdate = true;
  return pen;
}
// Court case plaque: maroon cloth, gold border, scales, case title.
function drawPlaque(g) {
  const bg = g.createLinearGradient(0, 0, 0, 640); bg.addColorStop(0, '#6a1f26'); bg.addColorStop(1, '#4a1218');
  g.fillStyle = bg; g.fillRect(0, 0, 1024, 640);
  g.strokeStyle = '#e2c16a'; g.lineWidth = 10; g.strokeRect(26, 26, 972, 588); g.lineWidth = 3; g.strokeRect(44, 44, 936, 552);
  g.strokeStyle = '#e2c16a'; g.fillStyle = '#e2c16a'; g.lineWidth = 8; g.lineCap = 'round';        // scales of justice
  g.beginPath(); g.moveTo(512, 90); g.lineTo(512, 250); g.moveTo(400, 130); g.lineTo(624, 130); g.moveTo(470, 250); g.lineTo(554, 250); g.stroke();
  for (const x of [400, 624]) {
    g.lineWidth = 3; g.beginPath(); g.moveTo(x, 130); g.lineTo(x - 40, 200); g.moveTo(x, 130); g.lineTo(x + 40, 200); g.stroke();
    g.beginPath(); g.arc(x, 200, 42, 0, Math.PI); g.fill();
  }
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.font = '800 110px Poppins'; g.fillText(TL.board_title || 'AI ADALAT', 512, 365);
  g.fillStyle = '#f6e7c1'; g.font = '700 44px Poppins'; g.fillText(TL.board_sub || '', 512, 470);
  g.textBaseline = 'alphabetic';
}
// Newsroom video wall: channel tag, LIVE, the current headline (cross-fades on change).
function drawNewsScreen(g, t) {
  const bg = g.createLinearGradient(0, 0, 1024, 640); bg.addColorStop(0, '#0d2a78'); bg.addColorStop(1, '#071338');
  g.fillStyle = bg; g.fillRect(0, 0, 1024, 640);
  g.fillStyle = 'rgba(79,179,255,0.10)'; for (let k = 0; k < 4; k++) { g.beginPath(); g.arc(860, 520, 160 + k * 120, 0, Math.PI * 2); g.lineWidth = 26; g.strokeStyle = 'rgba(79,179,255,0.07)'; g.stroke(); }
  g.fillStyle = '#c8102e'; g.fillRect(40, 40, 330, 86);
  g.fillStyle = '#fff'; g.font = '800 52px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle'; g.fillText(TL.board_title || 'AI NEWS', 62, 85);
  g.fillStyle = '#ffffff'; g.fillRect(800, 52, 180, 62);
  g.fillStyle = '#c8102e'; g.beginPath(); g.arc(832, 83, 13, 0, Math.PI * 2); g.fill();
  g.font = '800 40px Poppins'; g.fillText('LIVE', 856, 85);
  const i = NEWS.reduce((k, n, j) => (t >= n.t0 - 0.1 ? j : k), -1);
  const head = k => (k < 0 ? TL.board_sub || 'Aaj ki khabrein' : NEWS[k].headline);
  const k = i < 0 ? 1 : ease(clamp01((t - NEWS[i].t0 + 0.1) / 0.35));
  const drawHead = (txt, a) => {
    g.globalAlpha = a; g.fillStyle = '#ffffff'; g.font = '800 68px Poppins'; g.textAlign = 'center';
    const rows = wrap(g, txt, 900).slice(0, 3);
    rows.forEach((r, n) => g.fillText(r, 512, 330 - (rows.length - 1) * 40 + n * 80));
  };
  if (k < 1 && i >= 0) drawHead(head(i - 1), 1 - k);
  drawHead(head(i), k); g.globalAlpha = 1;
  if (NEWS.length) {
    g.fillStyle = '#ffd23f'; g.font = '700 38px Poppins'; g.textAlign = 'center';
    g.fillText(i < 0 ? `${NEWS.length} khabrein` : `KHABAR ${i + 1} / ${NEWS.length}`, 512, 560);
  }
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
// Podcast "ON AIR" neon sign + show title + question counter.
function drawOnAir(g, t) {
  g.fillStyle = '#100a0e'; g.fillRect(0, 0, 1024, 640);
  g.save(); g.shadowColor = '#ff2a4a'; g.shadowBlur = 30; g.strokeStyle = '#ff5c74'; g.lineWidth = 10;
  roundRect(g, 262, 60, 500, 170, 40); g.stroke();
  g.fillStyle = '#ffd0d8'; g.font = '800 110px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('ON AIR', 512, 150); g.restore();
  g.save(); g.shadowColor = '#36e0ff'; g.shadowBlur = 20; g.fillStyle = '#c9f6ff'; g.font = '800 96px Poppins';
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(TL.board_title || 'RAPID FIRE', 512, 360); g.restore();
  const cur = [...RAPID].reverse().find(r => t >= r.qStart - 0.1);
  g.fillStyle = '#ffd23f'; g.font = '700 54px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(cur ? `SAWAAL ${cur.n} / ${cur.of}` : (TL.board_sub || '5 second, 5 shabd'), 512, 520);
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
const activeOp = t => ops.find(o => t >= o.t0 - 0.25 && t <= o.t1 + 0.6);

// ---------- auto-director ----------
const P = (x, y, z) => new THREE.Vector3(x, y, z);
const boyHeadW = () => boy.localToWorld(P(0, 1.44, 0));   // stable anchor: head nods must not shake the camera
const oneW = () => one.localToWorld(P(0, 0.25, 0));
const SHOTS = {
  WIDE: () => ({ pos: P(0.2, 2.05, 4.2), tgt: P(0.0, 1.55, -1.6), fov: 56 }),
  BOY_MED: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.75, 0.15, 1.0)), tgt: h.clone().add(P(0, -0.22, 0)), fov: 42 }; },
  BOY_CU: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.55, 0.08, 0.85)), tgt: h.clone().add(P(0, -0.13, 0)), fov: 38 }; },
  BOY_PUNCH: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.3, 0.04, 0.62)), tgt: h.clone().add(P(0, -0.08, 0)), fov: 36 }; },
  BOY_CAM: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-0.75, 0.08, 1.6)), tgt: h.clone().add(P(0, -0.18, 0)), fov: 40 }; },
  ONE_CU: () => { const o = oneW(); return { pos: o.clone().add(P(0.5, 0.12, 1.05)), tgt: o.clone().add(P(0, 0.02, 0)), fov: 38 }; },
  ONE_MED: () => { const o = oneW(); return { pos: o.clone().add(P(0.9, 0.35, 1.7)), tgt: o.clone().add(P(0.15, 0.25, -0.4)), fov: 44 }; },
  ONE_LOW: () => { const o = oneW(); return { pos: o.clone().add(P(0.8, -0.04, 1.35)), tgt: o.clone().add(P(0.22, -0.08, 0)), fov: 42 }; },
  // HR scorecard framing: ONE high in frame, card underneath
  ONE_HIGH: () => { const o = oneW(); return { pos: o.clone().add(P(0.55, 0.1, 1.35)), tgt: o.clone().add(P(0.05, -0.17, 0)), fov: 40 }; },
  // anchor framing: ONE in the upper middle, so the news lower third sits under the face
  ANCHOR: () => { const o = oneW(); return { pos: o.clone().add(P(0.55, 0.15, 1.45)), tgt: o.clone().add(P(0.1, -0.06, 0)), fov: 40 }; },
  OTS: () => ({ pos: P(1.75, 1.85, 0.35), tgt: P(-0.75, 1.55, -1.7), fov: 50 }),
  BOARD_FULL: () => ({ pos: P(BOARD.x + 0.2, 1.95, BOARD.z + 5.2), tgt: P(BOARD.x, 1.85, BOARD.z), fov: 50 }),
  BOARD_TRACK: (op) => () => {
    const w = boardToWorld(op.penX, op.y - (op.size || 50) * 0.3);
    const lim = BOARD.w / 2 - 0.74;
    w.x = Math.max(BOARD.x - lim, Math.min(BOARD.x + lim, w.x));
    w.y = Math.max(BOARD.y - 0.35, Math.min(BOARD.y + 0.3, w.y));
    return { pos: w.clone().add(P(0.12, -0.1, 3.0)), tgt: w, fov: 46 };
  },
};

// Keyframes: {t, shot, blend (s, 0 = hard cut), drift (dolly-in per s), punch}
const KF = [];
const add = (t, shot, blend = 0.45, drift = 0.04, punch = 0) => KF.push({ t, shot, blend, drift, punch, name: Object.keys(SHOTS).find(k => SHOTS[k] === shot) || 'BOARD_TRACK' });
add(0, SHOTS.WIDE, 0, 0.02);
for (const l of lines) {
  const d = l.end - l.start, lops = ops.filter(o => o.line === l);
  switch (l.shot) {
    case 'hook':
      add(l.start + 0.6, SHOTS.BOY_MED, 1.1, 0.05);
      add(l.start + d * 0.62, SHOTS.BOY_CU, 0.5, 0.04);
      break;
    case 'simpler':
      add(l.start - 0.02, SHOTS.BOY_PUNCH, 0, 0.08, 1);
      if (lops.length) add(Math.min(l.end - 0.2, lops[0].t0 + 0.05), SHOTS.BOARD_FULL, 0.28, 0.08);
      break;
    case 'explain': case 'story': case 'reveal': {
      add(l.start - 0.05, l.shot === 'story' ? SHOTS.ONE_MED : SHOTS.ONE_CU, l.shot === 'reveal' ? 0.6 : 0.35, 0.05);
      for (const o of lops.filter(o => o.op === 'write')) add(o.t0 - 0.3, SHOTS.BOARD_TRACK(o), 0.55, 0.06);
      const circle = lops.find(o => o.op === 'circle');
      if (circle) add(circle.t0 - 0.1, SHOTS.BOARD_FULL, 0.7, 0.05);
      break;
    }
    case 'claim':      // VINEET states a claim; camera follows it onto the board
      add(l.start - 0.05, SHOTS.BOY_CU, 0.4, 0.05);
      for (const o of lops.filter(o => o.op === 'write')) add(o.t0 - 0.25, SHOTS.BOARD_TRACK(o), 0.5, 0.05);
      break;
    case 'verdict': {  // ONE judges: punch on ONE, hard cut to the stamp, back to ONE to explain
      add(l.start - 0.05, SHOTS.ONE_CU, 0.3, 0.1, 0.5);
      const st = lops.find(o => o.op === 'stamp');
      if (st) {
        add(st.t0 - 0.12, SHOTS.BOARD_TRACK(st), 0, 0.12, 0.8);
        if (st.t1 + 1.0 < l.end - 0.8) add(st.t1 + 1.0, SHOTS.ONE_MED, 0.45, 0.05);
      }
      break;
    }
    case 'question':   // quiz host asks: medium on ONE, push in while options appear
      add(l.start - 0.05, SHOTS.ONE_MED, 0.4, 0.04);
      add(l.start + d * 0.55, SHOTS.ONE_CU, 0.8, 0.05);
      break;
    case 'answer':     // contestant locks an option
      add(l.start - 0.05, SHOTS.BOY_CU, 0.35, 0.07);
      break;
    case 'result':     // right / wrong reveal
      add(l.start - 0.05, SHOTS.ONE_CU, 0.25, 0.1, 0.5);
      break;
    case 'chat':       // phone overlay on screen; camera stays wide-ish behind it
      add(l.start - 0.05, SHOTS.BOY_MED, 0.45, 0.03);
      break;
    case 'react':      // short reaction between chat steps
      add(l.start - 0.05, l.who === 'ONE' ? SHOTS.ONE_CU : SHOTS.BOY_PUNCH, 0.3, 0.08, 0.3);
      break;
    case 'call':       // VINEET on a phone call (call screen overlay)
      add(l.start - 0.05, SHOTS.BOY_MED, 0.45, 0.04);
      break;
    case 'flag':       // ONE walks through the red flags
      add(l.start - 0.05, SHOTS.ONE_MED, 0.4, 0.04);
      break;
    case 'tier':       // ONE ranks; tier list overlay below the faces
      add(l.start - 0.05, l.who === 'ONE' ? SHOTS.ONE_MED : SHOTS.BOY_MED, 0.4, 0.04);
      break;
    case 'argue':      // VINEET objects
      add(l.start - 0.05, SHOTS.BOY_PUNCH, 0.25, 0.07, 0.35);
      break;
    case 'charge':     // judge / host speaks; "Order, order!" opens on a low shot of the gavel
      if (l.gavel) { add(l.start - 0.05, SHOTS.ONE_LOW, 0, 0.05, 0.6); add(l.start + 1.0, SHOTS.ONE_MED, 0.6, 0.04); }
      else add(l.start - 0.05, LOC === 'newsroom' ? SHOTS.ANCHOR : SHOTS.ONE_MED, 0.4, 0.03);
      add(l.start + d * 0.6, LOC === 'newsroom' ? SHOTS.ANCHOR : SHOTS.ONE_CU, 0.8, 0.03);
      break;
    case 'gavel': {    // verdict: ONE close, cut low for the knocks, punch on the final bang, pull back
      const v = VERDICTS.find(v => v.line === l), tb = v ? v.tb : l.start + d * 0.35;
      add(l.start - 0.05, SHOTS.ONE_CU, 0.3, 0.06);
      add(tb - 0.6, SHOTS.ONE_LOW, 0, 0.04);
      add(tb, SHOTS.ONE_LOW, 0, 0.05, 1);
      add(tb + 0.9, SHOTS.ONE_MED, 0.6, 0.03);
      break;
    }
    case 'news':       // anchor reads; the video wall shows the headline
      add(l.start - 0.05, SHOTS.ANCHOR, 0.45, 0.02);
      add(l.start + d * 0.3, SHOTS.BOARD_FULL, 0.6, 0.03);
      add(l.start + d * 0.68, SHOTS.ANCHOR, 0.6, 0.03);
      break;
    case 'rapidq':     // rapid fire: hard cuts back and forth
      add(l.start - 0.03, SHOTS.BOY_PUNCH, 0, 0.06, 0.35);
      break;
    case 'rapida':
      add(l.start - 0.03, SHOTS.ONE_CU, 0, 0.08, 0.35);
      break;
    case 'ask':        // interviewer asks
      add(l.start - 0.05, SHOTS.ONE_MED, 0.4, 0.04);
      add(l.start + d * 0.55, SHOTS.ONE_CU, 0.7, 0.03);
      break;
    case 'score':      // interviewer scores the answer
      add(l.start - 0.05, SHOTS.ONE_HIGH, 0.3, 0.03, 0.3);
      break;
    case 'realize':
      add(l.start - 0.05, SHOTS.OTS, 0.5, 0.03);
      add(l.start + d * 0.45, SHOTS.BOY_CU, 1.4, 0.07);
      break;
    case 'payoff':
      add(l.start - 0.05, SHOTS.ONE_CU, 0.3, 0.14, 0.5);
      break;
    case 'cta':
      add(l.start - 0.05, SHOTS.BOY_CAM, 0.45, 0.06, 0.4);
      break;
    case 'follow':
      add(l.start - 0.05, SHOTS.ONE_CU, 0.35, 0.1, 0.5);
      add(l.start + d * 0.6, SHOTS.WIDE, 1.0, 0.02);
      break;
    default:
      add(l.start, l.who === 'ONE' ? SHOTS.ONE_CU : SHOTS.BOY_CU);
  }
}
KF.sort((a, b) => a.t - b.t);
// Every shot holds at least MIN_SHOT seconds: a keyframe that comes too soon is
// pushed later (never dropped), so no 1-2 frame flashes of another angle.
const MIN_SHOT = 0.6;
for (let i = 1; i < KF.length; i++) if (KF[i].t - KF[i - 1].t < MIN_SHOT) KF[i].t = KF[i - 1].t + MIN_SHOT;

function shotPose(kf, t) {
  const s = kf.shot();
  const dt = Math.max(0, t - kf.t);
  const dir = s.tgt.clone().sub(s.pos);
  const dist = dir.length();
  const k = Math.min(0.35, kf.drift * Math.min(dt, 6));
  return { pos: s.pos.clone().add(dir.multiplyScalar(k * Math.min(1, 1.2 / dist))), tgt: s.tgt, fov: s.fov * (1 - k * 0.15) };
}
const lerpPose = (a, b, x) => ({ pos: a.pos.clone().lerp(b.pos, x), tgt: a.tgt.clone().lerp(b.tgt, x), fov: a.fov + (b.fov - a.fov) * x });

let camFocus = 3;
function placeCamera(t) {
  let i = 0;
  while (i + 1 < KF.length && KF[i + 1].t <= t) i++;
  const cur = KF[i];
  let pose = shotPose(cur, t);
  if (i > 0 && cur.blend > 0 && t - cur.t < cur.blend) {
    const from = shotPose(KF[i - 1], cur.t);
    // Shots far apart (other side of the room): clean cut instead of a whip
    // that sweeps through the set and flashes random objects.
    const to = shotPose(cur, cur.t);
    const turn = from.tgt.clone().sub(from.pos).normalize().angleTo(to.tgt.clone().sub(to.pos).normalize());
    if (from.pos.distanceTo(to.pos) < 1.4 && turn < 0.8)
      pose = lerpPose(shotPose(KF[i - 1], t), pose, ease((t - cur.t) / cur.blend));
  }
  // handheld + punch shake
  const hh = 0.006;
  const n = (f, p) => Math.sin(t * f + p);
  const shake = KF.filter(k => k.punch && t >= k.t && t - k.t < 0.45).reduce((s, k) => s + k.punch * Math.exp(-(t - k.t) * 9), 0);
  const off = P(hh * (n(1.3, 0) + 0.5 * n(3.1, 2)) + shake * 0.02 * n(24, 1), hh * (n(1.7, 1) + 0.5 * n(2.3, 4)) + shake * 0.02 * n(27, 3), 0);
  camera.position.copy(pose.pos).add(off);
  camera.lookAt(pose.tgt.clone().add(off.multiplyScalar(0.5)));
  camera.fov = pose.fov * (1 - shake * 0.03);
  camera.updateProjectionMatrix();
  camFocus = camera.position.distanceTo(pose.tgt);
}

// ---------- character behaviour (stateful, frames rendered in order) ----------
let boyYaw = 0.0, boyPitch = 0, oneYaw = 0.5, stickAim = new THREE.Vector3(), nodSm = 0, mB = 0, mO = 0, oneEnv = 0, oneEnv1 = 0, shBs = 0.5, shOs = 0.5;
// Natural blinking: irregular gaps (2-5 s), smooth close/open, sometimes a double blink.
function blinkTrack(seed, total) {
  let s = seed; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const times = []; let t = 0.8 + rnd();
  while (t < total) { times.push(t); if (rnd() < 0.2) times.push(t + 0.28); t += 2 + rnd() * 3; }
  return times;
}
const BLINKS = { boy: blinkTrack(11, TL.duration), one: blinkTrack(29, TL.duration) };
function blink(which, t) {
  let v = 1;
  // ~7 frames per blink so the eye never snaps shut for a single frame
  for (const b of BLINKS[which]) { const d = t - b; if (d >= 0 && d < 0.24) v = Math.min(v, 0.1 + 0.9 * (0.5 + 0.5 * Math.cos(2 * Math.PI * d / 0.24))); }
  return v;
}
// Extra blink right after every hard camera cut feels natural on screen.
const isQuestion = l => /\?\s*$/.test(l.caption);
const tmpQ = new THREE.Quaternion();

function animate(t, f) {
  const l = lineAt(t);
  const speaker = l ? l.who : null;
  // mouth/voice envelopes smoothed a little so no single-frame pops
  mB += ((TL.amp.VINEET?.[f] || 0) - mB) * 0.5; mO += ((TL.amp.ONE?.[f] || 0) - mO) * 0.5;
  // two-pole envelope for ONE's body/glow (mouth keeps mO): a one-pole filter still left V-shaped
  // dips that read as a 1px body jolt in close-ups
  oneEnv1 += ((TL.amp.ONE?.[f] || 0) - oneEnv1) * 0.22; oneEnv += (oneEnv1 - oneEnv) * 0.22;
  const aB = mB, aO = mO;
  // vowel shape smoothed too: a raw per-frame width change read as a one-frame mouth pop in close-ups
  shBs += ((TL.shape?.VINEET?.[f] ?? 0.5) - shBs) * 0.35; shOs += ((TL.shape?.ONE?.[f] ?? 0.5) - shOs) * 0.35;
  const shB = shBs, shO = shOs;
  const writing = ops.find(o => t >= o.t0 - 0.1 && t <= o.t1 + 0.2);
  const recent = lastLineBefore(t);

  // boy head: look at ONE by default, at the board while it is being written, at camera for CTA
  let target = oneW();
  if (writing && writing.line.who === 'ONE') target = boardToWorld(writing.penX, writing.y);
  if (recent.shot === 'cta' && t > recent.start + (recent.end - recent.start) * 0.3) target = camera.position.clone();
  if (![target.x, target.y, target.z].every(Number.isFinite)) target = oneW();
  const local = boy.worldToLocal(target.clone()).sub(P(0, 1.42, 0));
  const wantYaw = Math.max(-1.1, Math.min(1.1, Math.atan2(local.x, local.z)));
  const wantPitch = Math.max(-0.35, Math.min(0.35, -Math.atan2(local.y, Math.hypot(local.x, local.z))));
  boyYaw += (wantYaw - boyYaw) * 0.18; boyPitch += (wantPitch - boyPitch) * 0.18;
  const prevB = TL.amp.VINEET?.[Math.max(0, f - 3)] || 0;
  nodSm += ((speaker === 'VINEET' ? Math.max(0, aB - prevB) * 0.12 : 0) - nodSm) * 0.25;   // soft nod on stressed syllables
  const nod = nodSm;
  headPivot.rotation.set(boyPitch + nod, boyYaw, 0.03 * Math.sin(t * 0.9) + (speaker === 'VINEET' ? 0.03 * Math.sin(t * 2.3) : 0));
  // lip sync: open with loudness, width with vowel shape (ee wide / oo round)
  mouth.scale.set(0.75 + shB * 0.55 - aB * 0.15, 1 + aB * 3.0, 1);
  // teeth/tongue grow in gradually (no on/off pop in close-ups)
  const tk = clamp01((aB - 0.25) / 0.25) * clamp01((shB - 0.3) / 0.2), gk = clamp01((aB - 0.45) / 0.25);
  teeth.visible = tk > 0.01; teeth.scale.set(1, tk, 1);
  tongue.visible = gk > 0.01; tongue.scale.set(1, gk, 1);
  // eyes follow where he looks
  const look = Math.max(-1, Math.min(1, (wantYaw - boyYaw) * 3));
  eyeL.position.x = eyeBase.L.x + look * 0.012; eyeR.position.x = eyeBase.R.x + look * 0.012;
  const bb = blink('boy', t);
  eyeL.scale.y = eyeR.scale.y = bb;
  const surprise = recent.shot === 'realize' && speaker === 'VINEET' ? 0.03 : 0;
  const lp = l ? (t - l.start) / (l.end - l.start) : 1;
  const ask = l && l.who === 'VINEET' && isQuestion(l) && lp > 0.5 ? 0.025 : 0;   // brows up on a question
  const annoyed = recent.shot === 'simpler' && t < recent.end + 0.4;               // "Nahi. Aur simple."
  browL.position.y = browR.position.y = 0.325 + surprise + ask + (annoyed ? -0.012 : 0) + (speaker === 'VINEET' ? aB * 0.01 : 0);
  browL.rotation.z = annoyed ? -0.3 : 0.08; browR.rotation.z = annoyed ? 0.3 : -0.08;
  torso.rotation.z = 0.015 * Math.sin(t * 1.1);
  armR.rotation.x = speaker === 'VINEET' ? -0.25 * aB : 0;

  // ONE: bounce while talking, glow with voice, face VINEET
  const fl = lines.find(x => x.shot === 'follow');
  // smooth hops (sin^2: no hard bounce at the landing, so no one-frame snap)
  const jump = fl && t > fl.start ? Math.pow(Math.sin((t - fl.start) * 3.6), 2) * 0.05 * Math.max(0, 1 - (t - fl.start) / 3) : 0;
  const bounce = 0.012 * Math.sin(t * 2.2) + oneEnv * 0.03 + jump;
  oneBody.position.y = bounce;
  oneBody.scale.set(1 + oneEnv * 0.04, 1 - oneEnv * 0.035, 1 + oneEnv * 0.04);
  const toBoy = one.worldToLocal(boyHeadW());
  let wantOne = Math.atan2(toBoy.x, toBoy.z) * 0.55;
  if (speaker === 'ONE' && !writing) wantOne = 0.35;
  oneYaw += (wantOne - oneYaw) * 0.15;
  oneBody.rotation.y = oneYaw;
  const happy = ['payoff', 'follow'].includes(recent.shot) || (recent.shot === 'reveal' && t > recent.start + 1);
  const ob = blink('one', t);
  oEyeL.scale.y = oEyeR.scale.y = ob * (happy ? 0.38 : 1);
  oEyeL.rotation.z = happy ? 0.35 : 0; oEyeR.rotation.z = happy ? -0.35 : 0;
  bulbMat.emissiveIntensity = 1.0 + oneEnv * 2;
  oneGlow.intensity = oneEnv * 1.0;
  bulb.position.y = 0.55 + 0.01 * Math.sin(t * 6);
  oneMouth.scale.set(0.8 + shO * 0.7 + (happy ? 0.4 : 0), 1 + aO * 3.4, 1);
  armOne.rotation.z = -0.5 - (speaker === 'ONE' ? 0.5 * oneEnv + 0.15 * Math.sin(t * 5) : 0);
  if (gavel.visible) gavel.rotation.z = gavelAngle(t);

  // pointer stick aims at the pen while writing, else rests diagonally up-left
  const aim = writing ? boardToWorld(writing.penX, writing.y - 10)
                      : one.localToWorld(P(-0.2, 1.6, -0.4));
  stickAim.lerp(aim, f === 0 ? 1 : 0.2);
  const from = stickPivot.getWorldPosition(new THREE.Vector3());
  const dir = stickAim.clone().sub(from).normalize();
  tmpQ.setFromUnitVectors(P(0, 1, 0), dir);
  stickPivot.quaternion.copy(one.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(tmpQ));
  const reach = Math.min(1.1, stickAim.distanceTo(from) * 0.35 + 0.35);
  stick.scale.y = reach; stick.position.y = 0.5 * reach;
}

// ---------- captions ----------
function chunks(line) {
  const parts = line.caption.match(/[^.?!,…]+[.?!,…]*/g) || [line.caption];
  const out = [];
  for (const p of parts) {
    const words = p.trim().split(/\s+/);
    for (let i = 0; i < words.length; i += 6) out.push(words.slice(i, i + 6).join(' '));
  }
  // merge very short trailing bits
  const merged = [];
  for (const c of out) {
    if (merged.length && (c.length < 10 || merged[merged.length - 1].length < 10) && (merged[merged.length - 1] + ' ' + c).length < 34) merged[merged.length - 1] += ' ' + c;
    else merged.push(c);
  }
  const total = merged.reduce((s, c) => s + c.length, 0);
  let acc = line.start;
  return merged.map(c => { const d = (c.length / total) * (line.end - line.start); const r = { text: c, t0: acc, t1: acc + d, who: line.who }; acc += d; return r; });
}
const CAPS = lines.flatMap(chunks);

function roundRect(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
function wrap(g, text, maxW) {
  const words = text.split(' '); const rows = []; let row = '';
  for (const w of words) { const tr = row ? row + ' ' + w : w; if (g.measureText(tr).width > maxW && row) { rows.push(row); row = w; } else row = tr; }
  if (row) rows.push(row); return rows;
}
// ---------- CTA cards ----------
const CTA = lines.filter(l => l.cta_card).map(l => ({ ...l.cta_card, t0: l.start, t1: l.end }));
function drawCtaCards(g, t) {
  const follow = CTA.find(c => c.type === 'follow');
  for (const c of CTA) {
    if (t < c.t0 - 0.1) continue;
    const inP = ease(clamp01((t - c.t0 + 0.1) / 0.35));
    let y = H * 0.8 + (1 - inP) * 260;
    if (c.type === 'comment' && follow && t > follow.t0) y -= ease(clamp01((t - follow.t0) / 0.35)) * 150;
    g.save(); g.globalAlpha = inP;
    if (c.type === 'comment') drawComment(g, c, t, y); else drawFollow(g, c, t, y);
    g.restore();
  }
}
function drawComment(g, c, t, y) {
  const w = W * 0.86, h = 128, x = (W - w) / 2;
  g.fillStyle = 'rgba(255,255,255,0.96)'; roundRect(g, x, y - h / 2, w, h, 26); g.fill();
  // avatar (ONE's teal face)
  g.fillStyle = '#2bb3a3'; g.beginPath(); g.arc(x + 58, y, 32, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#0e1a2e'; roundRect(g, x + 36, y - 14, 44, 24, 10); g.fill();
  g.fillStyle = '#8ffcff'; g.fillRect(x + 46, y - 9, 7, 14); g.fillRect(x + 63, y - 9, 7, 14);
  g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillStyle = '#3b4252'; g.font = '700 27px Poppins'; g.fillText('Comment karo', x + 108, y - 26);
  // keyword typed into the input, then a pulsing chip
  const typed = clamp01((t - c.t0 - 0.5) / 0.9);
  const kw = c.keyword.slice(0, Math.ceil(c.keyword.length * typed));
  g.fillStyle = '#eef1f6'; roundRect(g, x + 104, y - 2, w - 130, 50, 25); g.fill();
  const pulse = 1 + 0.06 * Math.max(0, Math.sin((t - c.t0) * 6)) * (typed >= 1 ? 1 : 0);
  g.save(); g.translate(x + 124, y + 23); g.scale(pulse, pulse);
  g.fillStyle = '#ff7a1a'; g.font = '800 30px Poppins';
  g.fillText(kw + ((Math.floor(t * 3) % 2 && typed < 1) ? '|' : ''), 0, 1);
  g.restore();
  if (typed >= 1) {
    g.fillStyle = '#1d6b3a'; g.font = '700 22px Poppins'; g.textAlign = 'right';
    g.fillText('DM me system milega', x + w - 40, y + 23);
  }
}
function drawFollow(g, c, t, y) {
  const w = W * 0.86, h = 120, x = (W - w) / 2;
  g.fillStyle = 'rgba(255,255,255,0.96)'; roundRect(g, x, y - h / 2, w, h, 26); g.fill();
  g.fillStyle = '#1b1b1b'; g.font = '800 30px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(HANDLE, x + 34, y - 16);
  g.fillStyle = '#5b6475'; g.font = '700 21px Poppins'; g.fillText('Roz ek AI concept, simple', x + 34, y + 22);
  const tap = c.t0 + (c.t1 - c.t0) * 0.45;
  const done = t >= tap;
  const press = Math.exp(-Math.pow((t - tap) * 9, 2));
  const bw = 170, bh = 62, bx = x + w - bw - 26;
  g.save(); g.translate(bx + bw / 2, y); g.scale(1 - press * 0.12, 1 - press * 0.12);
  g.fillStyle = done ? '#e4e8ef' : '#ff7a1a'; roundRect(g, -bw / 2, -bh / 2, bw, bh, 31); g.fill();
  g.fillStyle = done ? '#1b1b1b' : '#ffffff'; g.font = '800 26px Poppins'; g.textAlign = 'center';
  g.fillText(done ? 'Following ✓' : '+ Follow', 0, 1);
  g.restore();
  // tap ripple + sparkles
  if (t > tap - 0.25 && t < tap + 0.6) {
    const k = clamp01((t - tap + 0.25) / 0.85);
    g.strokeStyle = `rgba(255,122,26,${1 - k})`; g.lineWidth = 5;
    g.beginPath(); g.arc(bx + bw / 2, y, 20 + k * 90, 0, Math.PI * 2); g.stroke();
  }
  if (done && t < tap + 1.2) {
    const k = (t - tap) / 1.2;
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2, r = 40 + k * 140;
      g.fillStyle = ['#ff7a1a', '#2bb3a3', '#f2c14e'][i % 3]; g.globalAlpha = 1 - k;
      g.beginPath(); g.arc(bx + bw / 2 + Math.cos(a) * r, y + Math.sin(a) * r * 0.7, 7 * (1 - k) + 2, 0, Math.PI * 2); g.fill();
    }
    g.globalAlpha = 1;
  }
}

// ---------- format overlays (quiz card, phone chat) ----------
// Every animation here is monotonic or a slow sine, so nothing pops for a frame.
const QUIZ = TL.quiz || {};
const quizLines = lines.filter(l => l.overlay?.type === 'quiz');
const quizIds = [...new Set(quizLines.map(l => l.overlay.id))];
function quizState(t) {
  // the question whose lines cover t (with a short tail for the slide-out)
  for (const id of quizIds) {
    const ls = quizLines.filter(l => l.overlay.id === id);
    const t0 = ls[0].start - 0.2, t1 = ls[ls.length - 1].end + 0.6;
    if (t >= t0 && t <= t1) {
      const pickL = ls.find(l => l.overlay.stage === 'pick'), revL = ls.find(l => l.overlay.stage === 'reveal');
      return { id, q: QUIZ[id], t0, t1, ask: ls[0], pickL, revL };
    }
  }
  return null;
}
function quizScore(t) {
  let right = 0, total = 0;
  for (const id of quizIds) {
    const ls = quizLines.filter(l => l.overlay.id === id);
    const rev = ls.find(l => l.overlay.stage === 'reveal'), pk = ls.find(l => l.overlay.stage === 'pick');
    if (rev && t >= rev.start + 0.25) { total++; if (pk && pk.overlay.pick === QUIZ[id].answer) right++; }
  }
  return { right, total };
}
function drawQuiz(g, t) {
  const st = quizState(t);
  if (!st || !st.q) return false;
  const inP = ease(clamp01((t - st.t0) / 0.35)), outP = ease(clamp01((st.t1 - t) / 0.35));
  const vis = Math.min(inP, outP);
  const cw = W * 0.9, ch = 380, x0 = (W - cw) / 2, y0 = H * 0.5 + (1 - vis) * 120;
  g.save(); g.globalAlpha = vis;
  g.fillStyle = 'rgba(14,16,40,0.92)'; roundRect(g, x0, y0, cw, ch, 28); g.fill();
  g.strokeStyle = 'rgba(123,77,255,0.9)'; g.lineWidth = 3; roundRect(g, x0, y0, cw, ch, 28); g.stroke();
  // question
  g.fillStyle = '#ffffff'; g.font = '700 31px Poppins'; g.textAlign = 'left'; g.textBaseline = 'top';
  wrap(g, st.q.q, cw - 150).forEach((r, i) => g.fillText(r, x0 + 28, y0 + 26 + i * 40));
  // timer ring during the pick line
  if (st.pickL) {
    const tp = clamp01((t - st.ask.start) / Math.max(0.5, st.pickL.end - st.ask.start));
    const cx0 = x0 + cw - 62, cy0 = y0 + 58;
    g.lineWidth = 9; g.strokeStyle = 'rgba(255,255,255,0.15)'; g.beginPath(); g.arc(cx0, cy0, 34, 0, Math.PI * 2); g.stroke();
    g.strokeStyle = tp < 0.75 ? '#36e0ff' : '#ff6b6b';
    g.beginPath(); g.arc(cx0, cy0, 34, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - tp)); g.stroke();
    g.fillStyle = '#ffffff'; g.font = '800 26px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(String(Math.ceil(5 * (1 - tp))), cx0, cy0 + 1);
  }
  // options 2x2, appearing one by one during the question
  const ow = (cw - 28 * 3) / 2, oh = 82;
  const revOn = st.revL && t >= st.revL.start + 0.2, pickOn = st.pickL && t >= st.pickL.start + (st.pickL.end - st.pickL.start) * 0.55;
  const pick = st.pickL?.overlay.pick;
  st.q.options.forEach((opt, i) => {
    const appear = ease(clamp01((t - (st.ask.start + 0.4 + i * 0.35)) / 0.3));
    if (appear <= 0) return;
    const ox = x0 + 28 + (i % 2) * (ow + 28), oy = y0 + 150 + Math.floor(i / 2) * (oh + 20) + (1 - appear) * 20;
    let fill = 'rgba(255,255,255,0.08)', edge = 'rgba(255,255,255,0.25)';
    if (pickOn && i === pick) { fill = 'rgba(255,200,60,0.30)'; edge = '#ffc83c'; }
    if (revOn && i === st.q.answer) { fill = 'rgba(46,204,113,0.45)'; edge = '#2ecc71'; }
    else if (revOn && i === pick) { fill = 'rgba(231,76,60,0.45)'; edge = '#e74c3c'; }
    g.globalAlpha = vis * appear;
    g.fillStyle = fill; roundRect(g, ox, oy, ow, oh, 20); g.fill();
    g.strokeStyle = edge; g.lineWidth = 3; roundRect(g, ox, oy, ow, oh, 20); g.stroke();
    g.fillStyle = edge; g.beginPath(); g.arc(ox + 34, oy + oh / 2, 20, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#0e1028'; g.font = '800 22px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('ABCD'[i], ox + 34, oy + oh / 2 + 1);
    g.fillStyle = '#ffffff'; g.font = '700 23px Poppins'; g.textAlign = 'left';
    const rows = wrap(g, opt, ow - 80);
    rows.slice(0, 2).forEach((r, k) => g.fillText(r, ox + 64, oy + oh / 2 + (k - (Math.min(rows.length, 2) - 1) / 2) * 27));
  });
  // score chip
  const sc = quizScore(t);
  g.globalAlpha = vis; g.fillStyle = '#7b4dff'; roundRect(g, x0 + 20, y0 - 26, 180, 46, 23); g.fill();
  g.fillStyle = '#ffffff'; g.font = '800 22px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(`SCORE ${sc.right}/${quizIds.length}`, x0 + 110, y0 - 3);
  g.restore();
  return vis > 0.05;
}

const chatLines = lines.filter(l => l.overlay?.type === 'chat');
const CHAT = [];
for (const l of chatLines) {
  const msgs = l.overlay.msgs || [], d = l.end - l.start;
  msgs.forEach((m, k) => CHAT.push({ ...m, t0: l.start + (m.at ?? (k / msgs.length) * 0.85 + 0.05) * d }));
}
let phoneShow = 0, chatScroll = 0;
function drawChat(g, t) {
  if (!chatLines.length) return false;
  // visible while a chat line runs, and until the last AI reply has finished streaming
  const streamEnd = CHAT.reduce((e, m) => Math.max(e, m.t0 + (m.from === 'ai' ? 0.7 + m.text.split(' ').length / 9 : 0.3)), 0);
  const active = chatLines.some(l => t >= l.start - 0.15 && t <= l.end + 0.25) || (t >= CHAT[0]?.t0 && t <= streamEnd + 0.9);
  phoneShow += ((active ? 1 : 0) - phoneShow) * 0.2;
  if (phoneShow < 0.02) return false;
  const pw = W * 0.8, ph = H * 0.44, px = (W - pw) / 2, py = H * 0.37 + (1 - ease(phoneShow)) * H * 0.6;   // below the face line
  g.save();
  g.fillStyle = '#111318'; roundRect(g, px - 10, py - 10, pw + 20, ph + 20, 44); g.fill();
  g.fillStyle = '#f2f4f7'; roundRect(g, px, py, pw, ph, 36); g.fill();
  g.fillStyle = '#ffffff'; roundRect(g, px, py, pw, 84, 36); g.fill(); g.fillRect(px, py + 40, pw, 44);
  g.fillStyle = '#2bb3a3'; g.beginPath(); g.arc(px + 50, py + 44, 22, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#0e1a2e'; roundRect(g, px + 35, py + 36, 30, 15, 6); g.fill();
  g.fillStyle = '#8ffcff'; g.fillRect(px + 42, py + 39, 5, 9); g.fillRect(px + 53, py + 39, 5, 9);
  g.fillStyle = '#1b1b1b'; g.font = '800 26px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText('AI Chat', px + 86, py + 36); g.fillStyle = '#2ecc71'; g.font = '700 17px Poppins'; g.fillText('online', px + 88, py + 62);
  // messages (laid out bottom-up so the newest is always visible)
  g.save(); g.beginPath(); g.rect(px, py + 86, pw, ph - 96); g.clip();
  const shown = CHAT.filter(m => t >= m.t0);
  const bw = pw * 0.8, lineH = 32;
  const items = shown.map(m => {
    g.font = (m.from === 'me' ? '700 ' : '600 ') + '24px Poppins';
    let text = m.text, typing = false;
    if (m.from === 'ai') {   // typing dots, then words stream in
      const tt = t - m.t0;
      if (tt < 0.7) typing = true;
      else { const words = m.text.split(' '); text = words.slice(0, Math.max(1, Math.floor((tt - 0.7) * 9))).join(' '); }
    }
    const rows = typing ? [''] : text.split('\n').flatMap(p => wrap(g, p, bw - 36));
    return { m, rows, typing, h: rows.length * lineH + 30 };
  });
  // scroll target grows with each bubble's fade-in; speed capped so text never jumps between frames
  const total = items.reduce((s, it) => s + (it.h + 14) * ease(clamp01((t - it.m.t0) / 0.4)), 0);
  const want = Math.max(0, total - (ph - 110));
  const step = (want - chatScroll) * 0.15;
  chatScroll += Math.max(-9, Math.min(9, step));
  let y = py + 100 - chatScroll;
  for (const it of items) {
    const me = it.m.from === 'me', w = it.typing ? 96 : Math.min(bw, Math.max(...it.rows.map(r => g.measureText(r).width)) + 36);
    const bx = me ? px + pw - w - 18 : px + 18;
    const app = ease(clamp01((t - it.m.t0) / 0.25));
    g.globalAlpha = app;
    g.fillStyle = me ? '#2bb3a3' : '#ffffff'; roundRect(g, bx, y + (1 - app) * 12, w, it.h, 20); g.fill();
    if (!me) { g.strokeStyle = 'rgba(0,0,0,0.08)'; g.lineWidth = 2; roundRect(g, bx, y + (1 - app) * 12, w, it.h, 20); g.stroke(); }
    g.fillStyle = me ? '#ffffff' : '#1b1b1b'; g.font = (me ? '700 ' : '600 ') + '24px Poppins';
    if (it.typing) {
      for (let k = 0; k < 3; k++) { g.globalAlpha = app * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * 7 - k * 0.9))); g.beginPath(); g.arc(bx + 28 + k * 20, y + it.h / 2, 6, 0, Math.PI * 2); g.fill(); }
    } else it.rows.forEach((r, k) => g.fillText(r, bx + 18, y + 15 + lineH / 2 + k * lineH));
    y += it.h + 14;
  }
  g.restore(); g.restore();
  return phoneShow > 0.3;
}

// ---------- call screen, red-flag checklist, tier list ----------
const callLines = lines.filter(l => l.overlay?.type === 'call');
let callAmp = 0;
function drawCall(g, t, f) {
  if (!callLines.length) return false;
  const t0 = callLines[0].start - 0.25, t1 = callLines[callLines.length - 1].end + 0.5;
  if (t < t0 || t > t1) return false;
  const vis = Math.min(ease(clamp01((t - t0) / 0.35)), ease(clamp01((t1 - t) / 0.35)));
  const cur = [...callLines].reverse().find(l => t >= l.start - 0.05) || callLines[0];
  const stage = cur.overlay.stage || 'talk', name = callLines[0].overlay.name || 'Unknown';
  const talkStart = callLines.find(l => (l.overlay.stage || 'talk') === 'talk')?.start ?? t;
  callAmp += ((TL.amp.CALLER?.[f] || 0) - callAmp) * 0.35;
  const pw = W * 0.8, ph = H * 0.44, px = (W - pw) / 2, py = H * 0.37 + (1 - vis) * H * 0.5;
  g.save();
  g.fillStyle = '#111318'; roundRect(g, px - 10, py - 10, pw + 20, ph + 20, 44); g.fill();
  const bg = g.createLinearGradient(0, py, 0, py + ph); bg.addColorStop(0, '#1d2b4f'); bg.addColorStop(1, '#0d1222');
  g.fillStyle = bg; roundRect(g, px, py, pw, ph, 36); g.fill();
  const cx0 = W / 2, cy0 = py + ph * 0.3;
  if (stage === 'ring') for (let k = 0; k < 3; k++) {          // calm ripple rings
    const ph2 = ((t * 0.8 + k / 3) % 1);
    g.strokeStyle = `rgba(120,200,255,${0.5 * (1 - ph2)})`; g.lineWidth = 4;
    g.beginPath(); g.arc(cx0, cy0, 62 + ph2 * 70, 0, Math.PI * 2); g.stroke();
  }
  g.fillStyle = '#e8742c'; g.beginPath(); g.arc(cx0, cy0, 60, 0, Math.PI * 2); g.fill();
  g.fillStyle = '#ffffff'; g.font = '800 54px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(name[0].toUpperCase(), cx0, cy0 + 2);
  g.font = '800 36px Poppins'; g.fillText(name, cx0, cy0 + 105);
  g.fillStyle = 'rgba(255,255,255,0.7)'; g.font = '600 24px Poppins';
  const secs = Math.max(0, Math.floor(t - talkStart));
  g.fillText(stage === 'ring' ? 'Incoming call…' : stage === 'end' ? 'Call ended' : `00:${String(secs).padStart(2, '0')}`, cx0, cy0 + 148);
  if (stage === 'talk') {                                       // voice waveform
    for (let k = 0; k < 21; k++) {
      const hgt = 8 + callAmp * 70 * (0.45 + 0.55 * Math.abs(Math.sin(k * 1.7 + t * 3)));
      g.fillStyle = '#7fd6ff'; roundRect(g, cx0 - 210 + k * 20, cy0 + 205 - hgt / 2, 10, hgt, 5); g.fill();
    }
  }
  const by = py + ph - 70;
  if (stage === 'ring') {
    g.fillStyle = '#e74c3c'; g.beginPath(); g.arc(cx0 - 110, by, 38, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#2ecc71'; g.beginPath(); g.arc(cx0 + 110, by, 38 + 3 * Math.sin(t * 6), 0, Math.PI * 2); g.fill();
  } else if (stage === 'talk') { g.fillStyle = '#e74c3c'; g.beginPath(); g.arc(cx0, by, 38, 0, Math.PI * 2); g.fill(); }
  g.restore();
  return vis > 0.3;
}

const flagLines = lines.filter(l => l.overlay?.type === 'flags');
const FLAGS = [];
for (const l of flagLines) {
  const items = l.overlay.items || [], d = l.end - l.start;
  items.forEach((txt, k) => FLAGS.push({ txt, t0: l.start + ((k + 0.3) / items.length) * d * 0.9 }));
}
// A list card stays up until the CTA, or until a later line brings a different overlay.
function listEnd(type, lastLine) {
  const i = lines.indexOf(lastLine);
  const next = lines.slice(i + 1).find(l => l.overlay && l.overlay.type !== type);
  return Math.min((CTA[0]?.t0 ?? TL.duration) - 0.1, next ? next.start - 0.45 : TL.duration);
}
function drawFlags(g, t) {
  if (!FLAGS.length) return false;
  const endAt = listEnd('flags', flagLines[flagLines.length - 1]), t0 = FLAGS[0].t0 - 0.4;
  if (t < t0 || t > endAt + 0.4) return false;
  const vis = Math.min(ease(clamp01((t - t0) / 0.35)), ease(clamp01((endAt + 0.4 - t) / 0.35)));
  const cw = W * 0.88, x0 = (W - cw) / 2, rowH = 74, title = flagLines[0].overlay.title || 'RED FLAGS';
  const ch = 84 + FLAGS.length * (rowH + 12), y0 = H * 0.44 + (1 - vis) * 200;
  g.save(); g.globalAlpha = vis;
  g.fillStyle = 'rgba(20,12,16,0.9)'; roundRect(g, x0, y0, cw, ch, 26); g.fill();
  g.fillStyle = '#ff5c5c'; g.font = '800 30px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(title, x0 + 26, y0 + 42);
  FLAGS.forEach((it, k) => {
    const a = ease(clamp01((t - it.t0) / 0.3)); if (a <= 0) return;
    const y = y0 + 84 + k * (rowH + 12) + (1 - a) * 16;
    g.globalAlpha = vis * a;
    g.fillStyle = 'rgba(255,92,92,0.16)'; roundRect(g, x0 + 18, y, cw - 36, rowH, 18); g.fill();
    g.fillStyle = '#ff5c5c'; g.fillRect(x0 + 40, y + 16, 5, rowH - 30);            // flag pole + cloth
    g.beginPath(); g.moveTo(x0 + 45, y + 16); g.lineTo(x0 + 78, y + 26); g.lineTo(x0 + 45, y + 37); g.fill();
    g.fillStyle = '#ffffff'; g.font = '700 26px Poppins';
    g.fillText(it.txt, x0 + 96, y + rowH / 2 + 1);
  });
  g.restore();
  return vis > 0.3;
}

const tierLines = lines.filter(l => l.overlay?.type === 'tier');
const TIER_ITEMS = [];
for (const l of tierLines) {
  const adds = l.overlay.add || [], d = l.end - l.start;
  adds.forEach((it, k) => TIER_ITEMS.push({ ...it, t0: l.start + ((k + 0.35) / adds.length) * d * 0.85 }));
}
const TIERS = [['S', '#ff5c7a'], ['A', '#ff9f43'], ['B', '#ffd23f'], ['C', '#7bd88f']];
function drawTier(g, t) {
  if (!TIER_ITEMS.length) return false;
  const t0 = tierLines[0].start - 0.2, endAt = listEnd('tier', tierLines[tierLines.length - 1]);
  if (t < t0 || t > endAt + 0.4) return false;
  const vis = Math.min(ease(clamp01((t - t0) / 0.35)), ease(clamp01((endAt + 0.4 - t) / 0.35)));
  const cw = W * 0.92, x0 = (W - cw) / 2, rh = 92, y0 = H * 0.44 + (1 - vis) * 200;
  g.save(); g.globalAlpha = vis;
  g.fillStyle = 'rgba(15,16,30,0.9)'; roundRect(g, x0, y0, cw, 4 * (rh + 10) + 64, 24); g.fill();
  g.fillStyle = '#ffffff'; g.font = '800 28px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(tierLines[0].overlay.title || 'TIER LIST', x0 + 22, y0 + 32);
  TIERS.forEach(([name, col], r) => {
    const y = y0 + 60 + r * (rh + 10);
    g.fillStyle = col; roundRect(g, x0 + 14, y, 82, rh, 14); g.fill();
    g.fillStyle = '#14141f'; g.font = '800 46px Poppins'; g.textAlign = 'center'; g.fillText(name, x0 + 55, y + rh / 2 + 2);
    g.fillStyle = 'rgba(255,255,255,0.06)'; roundRect(g, x0 + 104, y, cw - 118, rh, 14); g.fill();
    let cx1 = x0 + 116;
    for (const it of TIER_ITEMS.filter(i => i.tier === name)) {
      const a = ease(clamp01((t - it.t0) / 0.35)); if (a <= 0) continue;
      g.font = '700 22px Poppins';
      const w = Math.min(cw - 140, g.measureText(it.name).width + 34);
      const yy = y + 14 + (1 - a) * -120;                     // drops in from above
      g.globalAlpha = vis * a;
      g.fillStyle = '#ffffff'; roundRect(g, cx1, yy, w, rh - 28, 14); g.fill();
      g.fillStyle = '#14141f'; g.textAlign = 'left'; g.fillText(it.name, cx1 + 17, yy + (rh - 28) / 2 + 1);
      g.globalAlpha = vis; cx1 += w + 10;
    }
  });
  g.restore();
  return vis > 0.3;
}

// ---------- court verdict, news lower third + ticker, rapid-fire timer, HR scorecard ----------
function drawVerdict(g, t) {
  const v = [...VERDICTS].reverse().find(v => t >= v.tb - 0.02);
  if (!v) return false;
  const tEnd = v.line.end + (v.hold ?? 0.2);
  if (t > tEnd + 0.3) return false;
  const k = ease(clamp01((t - v.tb + 0.02) / 0.22)), out = ease(clamp01((tEnd + 0.3 - t) / 0.3));
  const sc = 1 + 0.55 * (1 - k), col = v.color || (/NOT/i.test(v.text) ? '#2fbf71' : '#e5262f');
  g.save(); g.globalAlpha = Math.min(k, out);
  g.translate(W / 2, H * 0.47); g.rotate(-0.06); g.scale(sc, sc);
  g.font = '800 92px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
  const w = Math.max(460, g.measureText(v.text).width + 90), h = v.sub ? 250 : 180;
  g.fillStyle = 'rgba(16,12,10,0.88)'; roundRect(g, -w / 2, -h / 2, w, h, 26); g.fill();
  g.strokeStyle = col; g.lineWidth = 8; roundRect(g, -w / 2 + 12, -h / 2 + 12, w - 24, h - 24, 18); g.stroke();
  g.fillStyle = col; g.fillText(v.text, 0, v.sub ? -30 : 4);
  if (v.sub) { g.fillStyle = '#ffffff'; g.font = '700 30px Poppins'; g.fillText(v.sub, 0, 62); }
  g.restore();
  return true;
}

const TICKER = NEWS.map(n => n.ticker || n.headline).filter(Boolean).join('   •   ');
function drawNews(g, t) {
  if (!NEWS.length) return false;
  const t0 = NEWS[0].t0 - 0.2, endAt = (CTA[0]?.t0 ?? TL.duration) - 0.1;
  if (t < t0 || t > endAt + 0.4) return false;
  const vis = Math.min(ease(clamp01((t - t0) / 0.35)), ease(clamp01((endAt + 0.4 - t) / 0.35)));
  const i = NEWS.reduce((k, n, j) => (t >= n.t0 - 0.1 ? j : k), 0), n = NEWS[i];
  const k = ease(clamp01((t - n.t0 + 0.1) / 0.35));
  g.save(); g.globalAlpha = vis;
  // lower third: red BREAKING tag + white headline bar sliding in
  const y = H * 0.625;
  g.font = '800 28px Poppins'; g.textBaseline = 'middle'; g.textAlign = 'left';
  const rows = wrap(g, n.headline, W * 0.86).slice(0, 2), bh = rows.length * 40 + 26;
  g.fillStyle = '#c8102e'; g.fillRect(28, y - 44, 220, 44);
  g.fillStyle = '#ffffff'; g.fillText('BREAKING', 44, y - 21);
  g.globalAlpha = vis * k;
  const sx = (1 - k) * -80;
  g.fillStyle = 'rgba(255,255,255,0.96)'; g.fillRect(28 + sx, y, W - 56, bh);
  g.fillStyle = '#0d1a40'; rows.forEach((r, m) => g.fillText(r, 46 + sx, y + 13 + 20 + m * 40));
  g.globalAlpha = vis;
  // ticker: constant slow crawl (no jumps), below the faces
  const ty = H * 0.735, th = 46;
  g.fillStyle = '#0b1636'; g.fillRect(0, ty, W, th);
  g.save(); g.beginPath(); g.rect(150, ty, W - 150, th); g.clip();
  g.fillStyle = '#ffffff'; g.font = '700 24px Poppins';
  const txt = TICKER + '   •   ', tw = g.measureText(txt).width;
  let x = 150 - (((t - t0) * 80) % tw);
  for (; x < W; x += tw) g.fillText(txt, x, ty + th / 2 + 1);
  g.restore();
  g.fillStyle = '#ffd23f'; g.fillRect(0, ty, 150, th);
  g.fillStyle = '#0b1636'; g.font = '800 24px Poppins'; g.fillText(TL.board_title || 'AI NEWS', 14, ty + th / 2 + 1);
  g.restore();
  return true;
}

function drawRapid(g, t) {
  if (!RAPID.length) return false;
  const t0 = RAPID[0].qStart - 0.2, endAt = (CTA[0]?.t0 ?? TL.duration) - 0.1;
  if (t < t0 || t > endAt + 0.4) return false;
  const vis = Math.min(ease(clamp01((t - t0) / 0.35)), ease(clamp01((endAt + 0.4 - t) / 0.35)));
  const r = [...RAPID].reverse().find(r => t >= r.qStart - 0.1) || RAPID[0];
  const span = Math.max(0.3, r.aEnd - r.qEnd);
  const el = Math.min(r.limit, Math.max(0, t - r.qEnd) * (r.buzz ? r.limit / span : 1));
  const left = r.limit - el, done = t >= r.aEnd;
  const frac = left / r.limit;
  g.save(); g.globalAlpha = vis;
  // question counter pill (top left, under the caption)
  const py = H * 0.29;
  g.fillStyle = 'rgba(16,10,14,0.85)'; roundRect(g, 30, py - 34, 190, 68, 34); g.fill();
  g.fillStyle = '#ffd23f'; g.font = '800 34px Poppins'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(`Q ${r.n}/${r.of}`, 125, py + 2);
  // countdown ring (top right)
  const cxr = W - 92, cyr = py, rad = 54;
  const col = r.buzz && done ? '#e5262f' : frac > 0.5 ? '#2fbf71' : frac > 0.25 ? '#ffb020' : '#e5262f';
  g.fillStyle = 'rgba(16,10,14,0.85)'; g.beginPath(); g.arc(cxr, cyr, rad + 12, 0, Math.PI * 2); g.fill();
  g.strokeStyle = 'rgba(255,255,255,0.15)'; g.lineWidth = 10; g.beginPath(); g.arc(cxr, cyr, rad, 0, Math.PI * 2); g.stroke();
  g.strokeStyle = col; g.lineCap = 'round'; g.beginPath(); g.arc(cxr, cyr, rad, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); g.stroke();
  g.fillStyle = '#ffffff'; g.font = '800 44px Poppins';
  g.fillText(done && !r.buzz ? `${el.toFixed(1)}` : `${Math.ceil(left - 1e-6)}`, cxr, cyr + 2);
  if (done && !r.buzz) { g.fillStyle = '#2fbf71'; g.font = '800 24px Poppins'; g.fillText('✓ sec', cxr, cyr + rad + 34); }
  // TIME UP banner after a buzz (eases in, holds ~1 s)
  if (r.buzz && done) {
    const a = Math.min(ease(clamp01((t - r.aEnd) / 0.18)), ease(clamp01((r.aEnd + 1.4 - t) / 0.3)));
    if (a > 0) {
      g.globalAlpha = vis * a; g.save(); g.translate(W / 2, H * 0.47); g.rotate(-0.05); g.scale(1 + 0.3 * (1 - a), 1 + 0.3 * (1 - a));
      g.fillStyle = '#e5262f'; roundRect(g, -250, -70, 500, 140, 24); g.fill();
      g.fillStyle = '#ffffff'; g.font = '800 78px Poppins'; g.fillText('TIME UP!', 0, 4); g.restore();
    }
  }
  g.restore();
  return true;
}

function drawScore(g, t) {
  const s = [...SCORES].reverse().find(s => t >= s.t0 - 0.05);
  if (!s || t > s.t1 + 0.9) return false;
  const vis = Math.min(ease(clamp01((t - s.t0 + 0.05) / 0.3)), ease(clamp01((s.t1 + 0.9 - t) / 0.3)));
  const max = s.max || 10, fill = ease(clamp01((t - s.t0 - 0.2) / 0.7)) * s.score / max;
  const col = s.score / max < 0.4 ? '#e5262f' : s.score / max < 0.7 ? '#ffb020' : '#2fbf71';
  const cw = W * 0.86, x0 = (W - cw) / 2, y0 = H * 0.655 + (1 - vis) * 120, ch = s.note ? 196 : 150;
  g.save(); g.globalAlpha = vis;
  g.fillStyle = 'rgba(255,255,255,0.95)'; roundRect(g, x0, y0, cw, ch, 24); g.fill();
  g.fillStyle = '#2b3a8c'; g.font = '800 26px Poppins'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(`HR SCORE · ${s.label || ''}`, x0 + 24, y0 + 34);
  g.fillStyle = '#e6e8ef'; roundRect(g, x0 + 24, y0 + 64, cw - 170, 40, 20); g.fill();
  g.fillStyle = col; roundRect(g, x0 + 24, y0 + 64, Math.max(40, (cw - 170) * fill), 40, 20); g.fill();
  g.fillStyle = '#1b1b1b'; g.font = '800 40px Poppins'; g.textAlign = 'right';
  g.fillText(`${Math.round(fill * max)}/${max}`, x0 + cw - 22, y0 + 86);
  if (s.note) { g.textAlign = 'left'; g.fillStyle = col; g.font = '700 26px Poppins'; g.fillText(s.note, x0 + 24, y0 + 148); }
  g.restore();
  return true;
}

function drawOverlay(t) {
  const g = cx;
  // vignette
  const vg = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.75);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.38)');
  g.fillStyle = vg; g.fillRect(0, 0, W, H);
  const busy = drawChat(g, t) | drawQuiz(g, t) | drawCall(g, t, Math.round(t * FPS)) | drawFlags(g, t) | drawTier(g, t)
    | drawNews(g, t) | drawRapid(g, t) | drawScore(g, t) | drawVerdict(g, t);
  // caption
  const c = CAPS.find(c => t >= c.t0 - 0.03 && t < c.t1 + 0.15) ;
  if (c) {
    const age = t - c.t0;
    const s = 0.9 + 0.1 * ease(clamp01(age / 0.12));
    g.save();
    g.font = '700 40px Poppins';
    const rows = wrap(g, c.text, W * 0.72);
    const lh = 52, bw = Math.max(...rows.map(r => g.measureText(r).width)) + 56, bh = rows.length * lh + 30;
    const x = W / 2, y = H * 0.17;
    g.translate(x, y); g.scale(s, s);
    g.fillStyle = (c.who === 'VINEET' || c.who === 'ONE') ? 'rgba(32,40,56,0.86)' : 'rgba(120,28,36,0.9)'; roundRect(g, -bw / 2, -bh / 2, bw, bh, 22); g.fill();
    g.fillStyle = '#ffffff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    rows.forEach((r, i) => g.fillText(r, 0, -((rows.length - 1) * lh) / 2 + i * lh + 2));
    g.restore();
  }
  drawCtaCards(g, t);
  // handle watermark
  g.font = '700 26px Poppins'; g.textAlign = 'center'; g.fillStyle = 'rgba(255,255,255,0.5)';
  if (!busy && (!CTA.length || t < CTA[0].t0 - 0.1)) g.fillText(HANDLE, W / 2, H * 0.71);
}

// ---------- frame entry ----------
window.renderFrame = (f, fmt = 'image/jpeg') => {
  const t = f / FPS;
  scene.updateMatrixWorld(true);
  animate(t, f);
  drawBoard(t);
  scene.updateMatrixWorld(true);
  placeCamera(t);
  bokeh.uniforms.focus.value = camFocus;
  bokeh.uniforms.aperture.value = 0.0022 * Math.min(1.6, 3.2 / camFocus);
  // Software WebGL occasionally hands back an empty (black) buffer for one frame.
  // Check a sparse grid of pixels and re-render (same scene state) if it is blank.
  for (let attempt = 0; attempt < 4; attempt++) {
    composer.render();
    cx.drawImage(renderer.domElement, 0, 0);
    const px = cx.getImageData(0, 0, W, H).data;
    let lit = 0;
    for (let y = 40; y < H; y += 80) for (let x = 20; x < W; x += 60) {
      const i = (y * W + x) * 4; if (px[i] + px[i + 1] + px[i + 2] > 30) lit++;
    }
    if (lit > 20) break;
    console.log(`blank WebGL frame ${f}, re-rendering (attempt ${attempt + 1})`);
  }
  drawOverlay(t);
  return comp.toDataURL(fmt, 0.9);
};
window.stepFrame = (f) => {
  const t = f / FPS;
  scene.updateMatrixWorld(true); animate(t, f); drawBoard(t); scene.updateMatrixWorld(true); placeCamera(t); drawOverlay(t);
  const h = boyHeadW();
  const tip = stick.localToWorld(P(0, 0.5, 0)); const base = stickPivot.getWorldPosition(new THREE.Vector3());
  return { tip: tip.toArray().map(v => +v.toFixed(2)), base: base.toArray().map(v => +v.toFixed(2)), aim: stickAim.toArray().map(v => +v.toFixed(2)), t, cam: camera.position.toArray().map(v => +v.toFixed(2)), fov: +camera.fov.toFixed(1), head: h.toArray().map(v => +v.toFixed(2)), yaw: +boyYaw.toFixed(2) };
};
window.KFDBG = () => KF.map(k => [k.t.toFixed(2), k.blend, k.name]);
window.DBG2 = () => ({ cam: camera.position.toArray().map(v => +v.toFixed(5)), q: camera.quaternion.toArray().map(v => +v.toFixed(5)), fov: +camera.fov.toFixed(4), ob: oneBody.position.y.toFixed(5), os: oneBody.scale.x.toFixed(5), yaw: oneYaw.toFixed(5), env: oneEnv.toFixed(4) });
window.pick = (nx, ny) => {
  const rc = new THREE.Raycaster(); rc.setFromCamera(new THREE.Vector2(nx, ny), camera);
  const hit = rc.intersectObjects(scene.children, true)[0];
  if (!hit) return null;
  const m = hit.object; return { d: +hit.distance.toFixed(2), color: m.material?.color?.getHexString(), geo: m.geometry?.type, pos: m.getWorldPosition(new THREE.Vector3()).toArray().map(v => +v.toFixed(2)), parent: m.parent?.type };
};
window.TOTAL_FRAMES = TL.frames;
window.ready = true;

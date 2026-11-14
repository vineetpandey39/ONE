// Dialogue reel renderer: low-poly classroom + auto-director camera.
// Placeholder characters (VINEET + ONE mascot) built from primitives; the
// final look swaps in real models, while timeline/director/board stay as-is.
import * as THREE from './node_modules/three/build/three.module.js';

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

// ---------- room ----------
mesh(box(10, 0.1, 9), flat('#7a4e33'), 0, -0.05, -1);
// back wall with a big window (frame bars), city outside
const wallMat = flat('#34405e');
mesh(box(1.6, 4.2, 0.15), wallMat, -3.7, 2.1, -4);
mesh(box(1.6, 4.2, 0.15), wallMat, 3.7, 2.1, -4);
mesh(box(10, 0.6, 0.15), wallMat, 0, 0.3, -4);
mesh(box(10, 0.5, 0.15), wallMat, 0, 4.15, -4);
const barMat = flat('#14161c');
for (const x of [-2.9, -1.0, 1.0, 2.9]) mesh(box(0.09, 3.4, 0.12), barMat, x, 2.25, -3.95);
for (const y of [0.6, 2.1, 3.9]) mesh(box(5.9, 0.09, 0.12), barMat, 0, y, -3.95);

// sky + city backdrop
const skyC = document.createElement('canvas'); skyC.width = 512; skyC.height = 512;
{
  const g = skyC.getContext('2d');
  const gr = g.createLinearGradient(0, 0, 0, 512);
  gr.addColorStop(0, '#1f3768'); gr.addColorStop(0.6, '#5a7fb8'); gr.addColorStop(1, '#a9bfdc');
  g.fillStyle = gr; g.fillRect(0, 0, 512, 512);
}
const skyTex = new THREE.CanvasTexture(skyC); skyTex.colorSpace = THREE.SRGBColorSpace;
const sky = new THREE.Mesh(new THREE.PlaneGeometry(26, 14), new THREE.MeshBasicMaterial({ map: skyTex }));
sky.position.set(0, 4, -12); scene.add(sky);
function windowTex(seed) {
  const c = document.createElement('canvas'); c.width = 64; c.height = 128;
  const g = c.getContext('2d'); g.fillStyle = '#2a3550'; g.fillRect(0, 0, 64, 128);
  let s = seed;
  const rnd = () => (s = (s * 9301 + 49297) % 233280) / 233280;
  for (let y = 6; y < 124; y += 10) for (let x = 5; x < 60; x += 11) {
    g.fillStyle = rnd() > 0.55 ? '#ffd27a' : '#1d2640'; g.fillRect(x, y, 6, 6);
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
for (let i = 0; i < 12; i++) {
  const h = 2 + ((i * 37) % 9) * 0.6, w = 1.2 + ((i * 13) % 5) * 0.3;
  const b = new THREE.Mesh(box(w, h, 1), new THREE.MeshBasicMaterial({ map: windowTex(i + 3) }));
  b.position.set(-8 + i * 1.5, h / 2 - 0.5, -9 - (i % 3)); scene.add(b);
}

// bookshelf right
const shelfMat = flat('#6b4630');
mesh(box(1.1, 2.6, 0.45), shelfMat, 3.3, 1.3, -3.4);
const bookCols = ['#e0703a', '#f2c14e', '#3d8b6d', '#c94c4c', '#4f6fb3', '#e8e2d0'];
for (let r = 0; r < 4; r++) for (let i = 0; i < 6; i++) {
  const h = 0.32 + ((i + r) % 3) * 0.04;
  mesh(box(0.11, h, 0.3), flat(bookCols[(i + r * 2) % 6]), 2.85 + i * 0.15, 0.35 + r * 0.6 + h / 2, -3.3);
}

// ---------- whiteboard ----------
const BOARD = { x: -0.35, y: 2.15, z: -3.25, w: 2.7, h: 2.7 / 1.6 };
const boardC = document.createElement('canvas'); boardC.width = 1024; boardC.height = 640;
const bctx = boardC.getContext('2d');
const boardTex = new THREE.CanvasTexture(boardC); boardTex.colorSpace = THREE.SRGBColorSpace;
boardTex.anisotropy = 4;
mesh(box(BOARD.w + 0.12, BOARD.h + 0.12, 0.06), flat('#9aa1ab'), BOARD.x, BOARD.y, BOARD.z - 0.04);
const boardFace = new THREE.Mesh(new THREE.PlaneGeometry(BOARD.w, BOARD.h),
  new THREE.MeshStandardMaterial({ map: boardTex, roughness: 0.6 }));
boardFace.position.set(BOARD.x, BOARD.y, BOARD.z);
scene.add(boardFace);
mesh(box(BOARD.w * 0.8, 0.05, 0.12), flat('#9aa1ab'), BOARD.x, BOARD.y - BOARD.h / 2 - 0.05, BOARD.z + 0.05);
['#2b3a8c', '#c0392b', '#1d6b3a'].forEach((c, i) =>
  mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.16, 6), flat(c), BOARD.x - 0.25 + i * 0.22, BOARD.y - BOARD.h / 2 - 0.01, BOARD.z + 0.07)
    .rotation.z = Math.PI / 2);
mesh(box(0.06, 2.2, 0.06), flat('#7c838c'), BOARD.x - 1.0, 0.6, BOARD.z);
mesh(box(0.06, 2.2, 0.06), flat('#7c838c'), BOARD.x + 1.0, 0.6, BOARD.z);
const boardToWorld = (px, py) => new THREE.Vector3(
  BOARD.x - BOARD.w / 2 + (px / 1024) * BOARD.w, BOARD.y + BOARD.h / 2 - (py / 640) * BOARD.h, BOARD.z + 0.01);

// ---------- desk ----------
const deskMat = flat('#b07a4f');
mesh(box(3.0, 0.08, 1.1), deskMat, 0.15, 0.8, -0.55);
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
const STACK_TOP = sy;

// chair
mesh(box(0.6, 0.07, 0.55), flat('#2c6b6b'), 1.2, 0.5, -0.95);
mesh(box(0.6, 0.7, 0.07), flat('#2c6b6b'), 1.42, 0.85, -1.15).rotation.y = -0.6;
for (const [dx, dz] of [[-0.25, -0.22], [0.25, -0.22], [-0.25, 0.22], [0.25, 0.22]])
  mesh(box(0.05, 0.47, 0.05), flat('#1f4a4a'), 1.2 + dx, 0.24, -0.95 + dz);

// ---------- VINEET (placeholder low-poly boy) ----------
const boy = new THREE.Group();
boy.position.set(1.2, 0, -0.95);
boy.rotation.y = -0.95; // faces the board/ONE (towards -x)
scene.add(boy);
const hoodie = flat('#2f7fbf');
const torso = mesh(new THREE.CylinderGeometry(0.25, 0.31, 0.62, 7), hoodie, 0, 0.86, 0, boy);
mesh(new THREE.TorusGeometry(0.17, 0.06, 5, 8), hoodie, 0, 1.14, -0.06, boy).rotation.x = Math.PI / 2.4;
mesh(box(0.012, 0.16, 0.012), flat('#f3f1ea'), -0.06, 1.0, 0.27, boy);
mesh(box(0.012, 0.16, 0.012), flat('#f3f1ea'), 0.06, 1.0, 0.27, boy);
const armL = mesh(box(0.13, 0.13, 0.48), hoodie, -0.22, 0.88, 0.22, boy);
const armR = mesh(box(0.13, 0.13, 0.48), hoodie, 0.22, 0.88, 0.22, boy);
mesh(box(0.42, 0.16, 0.45), flat('#2e3550'), 0, 0.6, 0.12, boy); // lap
const headPivot = new THREE.Group(); headPivot.position.set(0, 1.22, 0); boy.add(headPivot);
const skin = flat('#c68a5e');
const head = mesh(new THREE.IcosahedronGeometry(0.25, 1), skin, 0, 0.22, 0, headPivot);
head.scale.set(1, 1.08, 1);
mesh(new THREE.CylinderGeometry(0.07, 0.08, 0.12, 6), skin, 0, 0.0, 0, headPivot);
const hairMat = flat('#1a1310');
const hair = mesh(new THREE.SphereGeometry(0.275, 8, 5, 0, Math.PI * 2, 0, Math.PI * 0.42), hairMat, 0, 0.255, -0.015, headPivot);
hair.scale.set(1.0, 1.1, 1.02); hair.rotation.x = -0.32;
mesh(box(0.34, 0.06, 0.1), hairMat, 0.03, 0.41, 0.17, headPivot).rotation.z = -0.15;
mesh(box(0.08, 0.16, 0.12), hairMat, -0.24, 0.27, 0.0, headPivot);
mesh(box(0.08, 0.16, 0.12), hairMat, 0.24, 0.27, 0.0, headPivot);
const ink = new THREE.MeshBasicMaterial({ color: '#15131a' });
const eyeL = mesh(box(0.04, 0.06, 0.02), ink, -0.085, 0.25, 0.235, headPivot);
const eyeR = mesh(box(0.04, 0.06, 0.02), ink, 0.085, 0.25, 0.235, headPivot);
const browL = mesh(box(0.08, 0.016, 0.02), ink, -0.088, 0.325, 0.232, headPivot);
const browR = mesh(box(0.08, 0.016, 0.02), ink, 0.088, 0.325, 0.232, headPivot);
mesh(new THREE.ConeGeometry(0.025, 0.06, 4), flat('#b0734c'), 0, 0.19, 0.255, headPivot).rotation.x = Math.PI / 2;
const mouth = mesh(box(0.08, 0.018, 0.02), new THREE.MeshBasicMaterial({ color: '#4a1c1c' }), 0, 0.105, 0.232, headPivot);
mesh(box(0.02, 0.05, 0.05), skin, -0.255, 0.22, 0, headPivot);
mesh(box(0.02, 0.05, 0.05), skin, 0.255, 0.22, 0, headPivot);

// ---------- ONE (placeholder mascot: teal low-poly orb + antenna bulb) ----------
const one = new THREE.Group();
one.position.set(-0.95, STACK_TOP, -0.45);
scene.add(one);
const oneBody = new THREE.Group(); one.add(oneBody);
const tealMat = flat('#2bb3a3', { emissive: '#0c3b36', emissiveIntensity: 0.6 });
const orb = mesh(new THREE.IcosahedronGeometry(0.2, 1), tealMat, 0, 0.21, 0, oneBody);
orb.scale.set(1.08, 0.95, 1);
mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.14, 5), flat('#1b6f66'), 0, 0.46, 0, oneBody);
const bulbMat = new THREE.MeshStandardMaterial({ color: '#ffb547', emissive: '#ff9a1f', emissiveIntensity: 1.2, flatShading: true });
const bulb = mesh(new THREE.IcosahedronGeometry(0.04, 0), bulbMat, 0, 0.55, 0, oneBody);
const footMat = flat('#1f8f83');
mesh(new THREE.IcosahedronGeometry(0.06, 0), footMat, -0.08, 0.03, 0.05, one).scale.set(1.2, 0.6, 1.3);
mesh(new THREE.IcosahedronGeometry(0.06, 0), footMat, 0.08, 0.03, 0.05, one).scale.set(1.2, 0.6, 1.3);
const oneEyeMat = new THREE.MeshBasicMaterial({ color: '#10213a' });
const oEyeL = mesh(box(0.035, 0.085, 0.02), oneEyeMat, -0.06, 0.24, 0.205, oneBody);
const oEyeR = mesh(box(0.035, 0.085, 0.02), oneEyeMat, 0.06, 0.24, 0.205, oneBody);
const oneGlow = new THREE.PointLight('#5ff2df', 0.0, 1.2); oneGlow.position.set(0, 0.25, 0.3); oneBody.add(oneGlow);
// pointer stick, pivoting at ONE's side
const stickPivot = new THREE.Group(); stickPivot.position.set(0.17, 0.2, 0.02); one.add(stickPivot);
const stick = mesh(new THREE.CylinderGeometry(0.008, 0.012, 1.0, 5), flat('#f1e3b8'), 0, 0.5, 0, stickPivot);
stick.castShadow = false;

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
  const dur = op.op === 'write' ? Math.min(1.3, Math.max(0.5, op.text.length * 0.045)) : op.op === 'strike' ? 0.3 : 0.55;
  ops.push({ ...op, t0, t1: t0 + dur, line: l });
}
const byId = Object.fromEntries(ops.filter(o => o.op === 'write').map(o => [o.id, o]));
function writeFont(o) { return `700 ${o.size}px Kalam`; }
for (const o of Object.values(byId)) { bctx.font = writeFont(o); o.width = bctx.measureText(o.text).width; o.penX = o.x; }
for (const o of ops) if (o.op !== 'write' && byId[o.target]) { o.y = byId[o.target].y; o.size = byId[o.target].size; o.x = byId[o.target].x; o.penX = o.x; }

function drawBoard(t) {
  const g = bctx;
  g.fillStyle = '#f6f5f0'; g.fillRect(0, 0, 1024, 640);
  const vg = g.createRadialGradient(512, 320, 200, 512, 320, 700);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.07)');
  g.fillStyle = vg; g.fillRect(0, 0, 1024, 640);
  g.fillStyle = '#1b1b1b'; g.font = '700 58px Kalam'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
  g.fillText(TL.board_title, 512, 95);
  g.fillRect(260, 118, 504, 6);
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
      g.strokeStyle = '#d0312d'; g.lineWidth = 7; g.lineCap = 'round';
      g.beginPath(); g.moveTo(tg.x - 8, tg.y - tg.size * 0.3);
      g.lineTo(tg.x - 8 + (tg.width + 16) * p, tg.y - tg.size * 0.3 + 4 * p); g.stroke();
      o.penX = tg.x + tg.width * p; o.y = tg.y;
    } else if (o.op === 'circle') {
      const tg = byId[o.target]; if (!tg) continue;
      g.strokeStyle = '#d0312d'; g.lineWidth = 6;
      g.beginPath();
      g.ellipse(tg.x + tg.width / 2, tg.y - tg.size * 0.32, tg.width / 2 + 34, tg.size * 0.85, -0.03,
        -Math.PI * 0.6, -Math.PI * 0.6 + Math.PI * 2.1 * p);
      g.stroke();
      o.penX = tg.x + tg.width / 2; o.y = tg.y;
    }
  }
  boardTex.needsUpdate = true;
  return pen;
}
const activeOp = t => ops.find(o => t >= o.t0 - 0.25 && t <= o.t1 + 0.6);

// ---------- auto-director ----------
const P = (x, y, z) => new THREE.Vector3(x, y, z);
const boyHeadW = () => headPivot.localToWorld(P(0, 0.22, 0));
const oneW = () => one.localToWorld(P(0, 0.25, 0));
const SHOTS = {
  WIDE: () => ({ pos: P(0.2, 2.05, 4.2), tgt: P(0.0, 1.55, -1.6), fov: 56 }),
  BOY_MED: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.75, 0.15, 1.0)), tgt: h.clone().add(P(0, -0.22, 0)), fov: 42 }; },
  BOY_CU: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.2, 0.05, 0.62)), tgt: h.clone().add(P(0, -0.08, 0)), fov: 38 }; },
  BOY_PUNCH: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.1, 0.03, 0.5)), tgt: h.clone().add(P(0, -0.05, 0)), fov: 36 }; },
  BOY_CAM: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-0.55, 0.05, 1.25)), tgt: h.clone().add(P(0, -0.12, 0)), fov: 40 }; },
  ONE_CU: () => { const o = oneW(); return { pos: o.clone().add(P(0.5, 0.12, 1.05)), tgt: o.clone().add(P(0, 0.02, 0)), fov: 38 }; },
  ONE_MED: () => { const o = oneW(); return { pos: o.clone().add(P(0.9, 0.35, 1.7)), tgt: o.clone().add(P(0.15, 0.25, -0.4)), fov: 44 }; },
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
const add = (t, shot, blend = 0.45, drift = 0.04, punch = 0) => KF.push({ t, shot, blend, drift, punch });
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
    case 'realize':
      add(l.start - 0.05, SHOTS.OTS, 0.5, 0.03);
      add(l.start + d * 0.45, SHOTS.BOY_CU, 1.4, 0.07);
      break;
    case 'payoff':
      add(l.start - 0.05, SHOTS.ONE_CU, 0.3, 0.14, 0.5);
      break;
    case 'cta':
      add(l.start - 0.1, SHOTS.WIDE, 0.6, 0.0);
      add(l.start + d * 0.35, SHOTS.BOY_CAM, 0.9, 0.05);
      break;
    default:
      add(l.start, l.who === 'ONE' ? SHOTS.ONE_CU : SHOTS.BOY_CU);
  }
}
KF.sort((a, b) => a.t - b.t);

function shotPose(kf, t) {
  const s = kf.shot();
  const dt = Math.max(0, t - kf.t);
  const dir = s.tgt.clone().sub(s.pos);
  const dist = dir.length();
  const k = Math.min(0.35, kf.drift * Math.min(dt, 6));
  return { pos: s.pos.clone().add(dir.multiplyScalar(k * Math.min(1, 1.2 / dist))), tgt: s.tgt, fov: s.fov * (1 - k * 0.15) };
}
const lerpPose = (a, b, x) => ({ pos: a.pos.clone().lerp(b.pos, x), tgt: a.tgt.clone().lerp(b.tgt, x), fov: a.fov + (b.fov - a.fov) * x });

function placeCamera(t) {
  let i = 0;
  while (i + 1 < KF.length && KF[i + 1].t <= t) i++;
  const cur = KF[i];
  let pose = shotPose(cur, t);
  if (i > 0 && cur.blend > 0 && t - cur.t < cur.blend) pose = lerpPose(shotPose(KF[i - 1], t), pose, ease((t - cur.t) / cur.blend));
  // handheld + punch shake
  const hh = 0.006;
  const n = (f, p) => Math.sin(t * f + p);
  const shake = KF.filter(k => k.punch && t >= k.t && t - k.t < 0.45).reduce((s, k) => s + k.punch * Math.exp(-(t - k.t) * 9), 0);
  const off = P(hh * (n(1.3, 0) + 0.5 * n(3.1, 2)) + shake * 0.02 * n(55, 1), hh * (n(1.7, 1) + 0.5 * n(2.3, 4)) + shake * 0.02 * n(61, 3), 0);
  camera.position.copy(pose.pos).add(off);
  camera.lookAt(pose.tgt.clone().add(off.multiplyScalar(0.5)));
  camera.fov = pose.fov * (1 - shake * 0.03);
  camera.updateProjectionMatrix();
}

// ---------- character behaviour (stateful, frames rendered in order) ----------
let boyYaw = 0.0, boyPitch = 0, oneYaw = 0.5, stickAim = new THREE.Vector3();
const blink = (t, period, phase) => { const x = (t + phase) % period; return x < 0.12 ? 0.15 : 1; };
const tmpQ = new THREE.Quaternion();

function animate(t, f) {
  const l = lineAt(t);
  const speaker = l ? l.who : null;
  const aB = TL.amp.VINEET?.[f] || 0, aO = TL.amp.ONE?.[f] || 0;
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
  headPivot.rotation.set(boyPitch + (speaker === 'VINEET' ? 0.04 * Math.sin(t * 7) * aB : 0), boyYaw, 0.03 * Math.sin(t * 0.9));
  mouth.scale.set(1 - aB * 0.2, 1 + aB * 2.4, 1);
  const bb = blink(t, 3.3, 0.4);
  eyeL.scale.y = eyeR.scale.y = bb;
  const surprise = recent.shot === 'realize' && speaker === 'VINEET' ? 0.03 : 0;
  browL.position.y = browR.position.y = 0.325 + surprise + (speaker === 'VINEET' ? aB * 0.012 : 0);
  torso.rotation.z = 0.015 * Math.sin(t * 1.1);
  armR.rotation.x = speaker === 'VINEET' ? -0.25 * aB : 0;

  // ONE: bounce while talking, glow with voice, face VINEET
  const bounce = 0.012 * Math.sin(t * 2.2) + aO * 0.05;
  oneBody.position.y = bounce;
  oneBody.scale.set(1 + aO * 0.06, 1 - aO * 0.05, 1 + aO * 0.06);
  const toBoy = one.worldToLocal(boyHeadW());
  let wantOne = Math.atan2(toBoy.x, toBoy.z) * 0.55;
  if (speaker === 'ONE' && !writing) wantOne = 0.35;
  oneYaw += (wantOne - oneYaw) * 0.15;
  oneBody.rotation.y = oneYaw;
  const ob = blink(t, 2.7, 1.1);
  oEyeL.scale.y = oEyeR.scale.y = ob;
  bulbMat.emissiveIntensity = 1.0 + aO * 3;
  oneGlow.intensity = aO * 2.5;
  bulb.position.y = 0.55 + 0.01 * Math.sin(t * 6);

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
  return merged.map(c => { const d = (c.length / total) * (line.end - line.start); const r = { text: c, t0: acc, t1: acc + d }; acc += d; return r; });
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
function drawOverlay(t) {
  const g = cx;
  // vignette
  const vg = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.75);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.38)');
  g.fillStyle = vg; g.fillRect(0, 0, W, H);
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
    g.fillStyle = 'rgba(32,40,56,0.86)'; roundRect(g, -bw / 2, -bh / 2, bw, bh, 22); g.fill();
    g.fillStyle = '#ffffff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    rows.forEach((r, i) => g.fillText(r, 0, -((rows.length - 1) * lh) / 2 + i * lh + 2));
    g.restore();
  }
  // handle watermark
  g.font = '700 26px Poppins'; g.textAlign = 'center'; g.fillStyle = 'rgba(255,255,255,0.5)';
  g.fillText(HANDLE, W / 2, H * 0.71);
}

// ---------- frame entry ----------
window.renderFrame = (f, fmt = 'image/jpeg') => {
  const t = f / FPS;
  scene.updateMatrixWorld(true);
  animate(t, f);
  drawBoard(t);
  scene.updateMatrixWorld(true);
  placeCamera(t);
  renderer.render(scene, camera);
  cx.drawImage(renderer.domElement, 0, 0);
  drawOverlay(t);
  return comp.toDataURL(fmt, 0.9);
};
window.stepFrame = (f) => {
  const t = f / FPS;
  scene.updateMatrixWorld(true); animate(t, f); drawBoard(t); scene.updateMatrixWorld(true); placeCamera(t);
  const h = boyHeadW();
  return { t, cam: camera.position.toArray().map(v => +v.toFixed(2)), fov: +camera.fov.toFixed(1), head: h.toArray().map(v => +v.toFixed(2)), yaw: +boyYaw.toFixed(2) };
};
window.TOTAL_FRAMES = TL.frames;
window.ready = true;

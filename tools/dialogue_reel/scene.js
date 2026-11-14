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
// Optional painted backdrop (e.g. a Leonardo/ChatGPT night-city image): assets/backdrop.jpg
{
  const url = params.get('backdrop') || 'assets/backdrop.jpg';
  const ok = await fetch(url, { method: 'HEAD' }).then(r => r.ok).catch(() => false);
  if (ok) {
    const tex = await new THREE.TextureLoader().loadAsync(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    sky.material.map = tex; sky.material.needsUpdate = true;
    sky.userData.painted = true;
  }
}
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
for (let i = 0; i < (sky.userData.painted ? 0 : 12); i++) {
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
  new THREE.MeshStandardMaterial({ map: boardTex, roughness: 0.95 }));
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
const teeth = mesh(box(0.9, 0.22, 0.4), new THREE.MeshBasicMaterial({ color: '#f4efe6' }), 0, 0.36, 0.35, mouth);
const tongue = mesh(box(0.6, 0.25, 0.4), new THREE.MeshBasicMaterial({ color: '#b5524f' }), 0, -0.3, 0.3, mouth);
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
  BOY_CU: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.55, 0.08, 0.85)), tgt: h.clone().add(P(0, -0.13, 0)), fov: 38 }; },
  BOY_PUNCH: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-1.3, 0.04, 0.62)), tgt: h.clone().add(P(0, -0.08, 0)), fov: 36 }; },
  BOY_CAM: () => { const h = boyHeadW(); return { pos: h.clone().add(P(-0.75, 0.08, 1.6)), tgt: h.clone().add(P(0, -0.18, 0)), fov: 40 }; },
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
  const off = P(hh * (n(1.3, 0) + 0.5 * n(3.1, 2)) + shake * 0.02 * n(55, 1), hh * (n(1.7, 1) + 0.5 * n(2.3, 4)) + shake * 0.02 * n(61, 3), 0);
  camera.position.copy(pose.pos).add(off);
  camera.lookAt(pose.tgt.clone().add(off.multiplyScalar(0.5)));
  camera.fov = pose.fov * (1 - shake * 0.03);
  camera.updateProjectionMatrix();
  camFocus = camera.position.distanceTo(pose.tgt);
}

// ---------- character behaviour (stateful, frames rendered in order) ----------
let boyYaw = 0.0, boyPitch = 0, oneYaw = 0.5, stickAim = new THREE.Vector3();
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
  for (const b of BLINKS[which]) { const d = t - b; if (d >= 0 && d < 0.16) v = Math.min(v, 0.1 + 0.9 * Math.abs(Math.cos(Math.PI * d / 0.16))); }
  return v;
}
// Extra blink right after every hard camera cut feels natural on screen.
const isQuestion = l => /\?\s*$/.test(l.caption);
const tmpQ = new THREE.Quaternion();

function animate(t, f) {
  const l = lineAt(t);
  const speaker = l ? l.who : null;
  const aB = TL.amp.VINEET?.[f] || 0, aO = TL.amp.ONE?.[f] || 0;
  const shB = TL.shape?.VINEET?.[f] ?? 0.5, shO = TL.shape?.ONE?.[f] ?? 0.5;
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
  const prevB = TL.amp.VINEET?.[Math.max(0, f - 2)] || 0;
  const nod = speaker === 'VINEET' ? Math.max(0, aB - prevB) * 0.25 : 0;   // nod on stressed syllables
  headPivot.rotation.set(boyPitch + nod, boyYaw, 0.03 * Math.sin(t * 0.9) + (speaker === 'VINEET' ? 0.03 * Math.sin(t * 2.3) : 0));
  // lip sync: open with loudness, width with vowel shape (ee wide / oo round)
  mouth.scale.set(0.75 + shB * 0.55 - aB * 0.15, 1 + aB * 3.0, 1);
  teeth.visible = aB > 0.3 && shB > 0.35;
  tongue.visible = aB > 0.55;
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
  const jump = fl && t > fl.start ? Math.abs(Math.sin((t - fl.start) * 7)) * 0.05 * Math.max(0, 1 - (t - fl.start) / 3) : 0;
  const bounce = 0.012 * Math.sin(t * 2.2) + aO * 0.05 + jump;
  oneBody.position.y = bounce;
  oneBody.scale.set(1 + aO * 0.06, 1 - aO * 0.05, 1 + aO * 0.06);
  const toBoy = one.worldToLocal(boyHeadW());
  let wantOne = Math.atan2(toBoy.x, toBoy.z) * 0.55;
  if (speaker === 'ONE' && !writing) wantOne = 0.35;
  oneYaw += (wantOne - oneYaw) * 0.15;
  oneBody.rotation.y = oneYaw;
  const happy = ['payoff', 'follow'].includes(recent.shot) || (recent.shot === 'reveal' && t > recent.start + 1);
  const ob = blink('one', t);
  oEyeL.scale.y = oEyeR.scale.y = ob * (happy ? 0.38 : 1);
  oEyeL.rotation.z = happy ? 0.35 : 0; oEyeR.rotation.z = happy ? -0.35 : 0;
  bulbMat.emissiveIntensity = 1.0 + aO * 3;
  oneGlow.intensity = aO * 1.2;
  bulb.position.y = 0.55 + 0.01 * Math.sin(t * 6);
  oneMouth.scale.set(0.8 + shO * 0.7 + (happy ? 0.4 : 0), 1 + aO * 3.4, 1);
  armOne.rotation.z = -0.5 - (speaker === 'ONE' ? 0.5 * aO + 0.15 * Math.sin(t * 5) : 0);

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
  drawCtaCards(g, t);
  // handle watermark
  g.font = '700 26px Poppins'; g.textAlign = 'center'; g.fillStyle = 'rgba(255,255,255,0.5)';
  if (!CTA.length || t < CTA[0].t0 - 0.1) g.fillText(HANDLE, W / 2, H * 0.71);
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
  composer.render();
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
window.KFDBG = () => KF.map(k => [k.t.toFixed(2), k.blend, k.name]);
window.TOTAL_FRAMES = TL.frames;
window.ready = true;

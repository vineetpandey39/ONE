/**
 * JarvisCore — 3D holographic AI orb
 * THREE.js is bundled locally (no CDN dependency).
 * Drag to orbit · scroll to zoom · tap to record.
 */
// @ts-ignore — three is in dependencies; types bundled at runtime
import * as THREE from 'three';
import { useCallback, useEffect, useRef } from 'react';

export type CoreState = 'awake' | 'listening' | 'speaking' | 'thinking' | 'offline';

interface JarvisCoreProps {
  state: CoreState;
  memories: number;
  onTap?: () => void;
}

const STATE_PARAMS: Record<CoreState, {
  ringColor: number; coreEmissive: number; pulseSpeed: number; rotSpeed: number;
}> = {
  awake:     { ringColor: 0x00d4ff, coreEmissive: 0x0055cc, pulseSpeed: 1.8, rotSpeed: 0.003 },
  listening: { ringColor: 0x00ffcc, coreEmissive: 0x00aa66, pulseSpeed: 3.2, rotSpeed: 0.006 },
  speaking:  { ringColor: 0xffd700, coreEmissive: 0xaa6600, pulseSpeed: 5.0, rotSpeed: 0.004 },
  thinking:  { ringColor: 0xaa55ff, coreEmissive: 0x6622cc, pulseSpeed: 4.2, rotSpeed: 0.008 },
  offline:   { ringColor: 0x334455, coreEmissive: 0x112233, pulseSpeed: 0.5, rotSpeed: 0.001 },
};

const STATUS_LABELS: Record<CoreState, string> = {
  awake:     'NEURAL CORE ONLINE',
  listening: '■ LISTENING',
  speaking:  '◆ SPEAKING',
  thinking:  '● PROCESSING',
  offline:   'OFFLINE',
};

export function JarvisCore({ state, memories, onTap }: JarvisCoreProps) {
  const mountRef  = useRef<HTMLDivElement>(null);
  const stateRef  = useRef<CoreState>(state);
  const cleanupFn = useRef<(() => void) | null>(null);

  useEffect(() => { stateRef.current = state; }, [state]);

  const buildScene = useCallback(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const W = mount.clientWidth  || 500;
    const H = mount.clientHeight || 500;

    // ── Renderer ──────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);

    // ── Scene / Camera ─────────────────────────────────
    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(48, W / H, 0.1, 100);
    camera.position.z = 8;

    const pivot = new THREE.Group();
    scene.add(pivot);

    // ── Rings ─────────────────────────────────────────
    function mkRing(R: number, tube: number, col: number, alpha: number,
                    rx: number, ry: number, rz: number) {
      const grp  = new THREE.Group();
      grp.rotation.set(rx, ry, rz);
      const mesh = new THREE.Mesh(
        new THREE.TorusGeometry(R, tube, 16, 320),
        new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: alpha }),
      );
      grp.add(mesh);
      pivot.add(grp);
      return { grp, mesh };
    }

    const rings = [
      mkRing(1.9, 0.022, 0x00d4ff, 1.0,  0,            0,            0           ),
      mkRing(1.9, 0.020, 0x0099ff, 1.0,  Math.PI / 2,  0,            0           ),
      mkRing(1.9, 0.016, 0x00ffcc, 0.90, Math.PI / 4,  0,            Math.PI / 4 ),
      mkRing(1.6, 0.012, 0x55aaff, 0.80, Math.PI / 3,  Math.PI / 5, 0           ),
      mkRing(2.3, 0.009, 0x0055cc, 0.65, -Math.PI / 4, Math.PI / 3, 0           ),
    ];

    // ── Orbital markers ───────────────────────────────
    const orbiters: { mesh: THREE.Mesh; R: number; offset: number; speed: number }[] = [];
    function addOrbiters(grp: THREE.Group, R: number, count: number, col: number, speed: number) {
      for (let i = 0; i < count; i++) {
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(0.055, 8, 8),
          new THREE.MeshBasicMaterial({ color: col }),
        );
        grp.add(mesh);
        orbiters.push({ mesh, R, offset: (i / count) * Math.PI * 2, speed });
      }
    }
    addOrbiters(rings[0].grp, 1.9, 3, 0x00ffff, 0.60);
    addOrbiters(rings[1].grp, 1.9, 2, 0xffd700, 0.40);
    addOrbiters(rings[2].grp, 1.9, 2, 0x00ffcc, 0.50);
    addOrbiters(rings[3].grp, 1.6, 2, 0x88ddff, 0.70);

    // ── Core sphere ───────────────────────────────────
    const coreMat = new THREE.MeshPhongMaterial({
      color: 0x0044aa, emissive: 0x0055cc, emissiveIntensity: 2.5,
      shininess: 160, transparent: true, opacity: 0.95,
    });
    pivot.add(new THREE.Mesh(new THREE.SphereGeometry(0.35, 64, 64), coreMat));

    const icoMat = new THREE.MeshBasicMaterial({ color: 0x00d4ff, wireframe: true, transparent: true, opacity: 0.55 });
    const ico = new THREE.Mesh(new THREE.IcosahedronGeometry(0.26, 0), icoMat);
    pivot.add(ico);

    const wfMat = new THREE.MeshBasicMaterial({ color: 0x44aaff, wireframe: true, transparent: true, opacity: 0.35 });
    const wf = new THREE.Mesh(new THREE.SphereGeometry(0.42, 14, 14), wfMat);
    pivot.add(wf);

    const gM0 = new THREE.MeshBasicMaterial({ color: 0x0088ff, transparent: true, opacity: 0.22, side: THREE.BackSide });
    const gM1 = new THREE.MeshBasicMaterial({ color: 0x0055cc, transparent: true, opacity: 0.14, side: THREE.BackSide });
    const gM2 = new THREE.MeshBasicMaterial({ color: 0x002288, transparent: true, opacity: 0.08, side: THREE.BackSide });
    pivot.add(new THREE.Mesh(new THREE.SphereGeometry(0.58, 24, 24), gM0));
    pivot.add(new THREE.Mesh(new THREE.SphereGeometry(0.80, 24, 24), gM1));
    pivot.add(new THREE.Mesh(new THREE.SphereGeometry(1.10, 24, 24), gM2));

    // ── Particles ─────────────────────────────────────
    function mkParticles(count: number, rMin: number, rMax: number, col: number, sz: number, op: number) {
      const pos = new Float32Array(count * 3);
      for (let i = 0; i < count; i++) {
        const r     = rMin + Math.random() * (rMax - rMin);
        const theta = Math.random() * Math.PI * 2;
        const phi   = Math.acos(2 * Math.random() - 1);
        pos[i*3]   = r * Math.sin(phi) * Math.cos(theta);
        pos[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
        pos[i*3+2] = r * Math.cos(phi);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      return new THREE.Points(geo, new THREE.PointsMaterial({
        color: col, size: sz, transparent: true, opacity: op,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
    }
    const p1 = mkParticles(1600, 1.1, 3.0, 0x00d4ff, 0.040, 0.80);
    const p2 = mkParticles(700,  3.0, 5.0, 0x0088ff, 0.025, 0.60);
    const p3 = mkParticles(250,  0.50, 1.0, 0x66eeff, 0.048, 0.95);
    pivot.add(p1, p2, p3);

    // ── Lights ────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x1a4488, 8));
    const pL  = new THREE.PointLight(0x00ddff, 20, 18);
    const pL2 = new THREE.PointLight(0x0044ff,  8, 14);
    pL2.position.set(-4, 2, -4);
    scene.add(pL, pL2);

    // ── Drag / tap ────────────────────────────────────
    let down = false, lx = 0, ly = 0, dragDist = 0;
    let tRX = 0.18, tRY = 0, cRX = 0.18, cRY = 0;
    let vX = 0, vY = 0;
    const cvs = renderer.domElement;

    const onDown = (e: MouseEvent)  => { down = true; dragDist = 0; lx = e.clientX; ly = e.clientY; };
    const onMove = (e: MouseEvent)  => {
      if (!down) return;
      const dx = e.clientX - lx, dy = e.clientY - ly;
      vY += dx * 0.013; vX += dy * 0.013;
      dragDist += Math.sqrt(dx*dx + dy*dy);
      lx = e.clientX; ly = e.clientY;
    };
    const onUp = () => { if (dragDist < 6 && onTap) onTap(); down = false; };

    const onTouchStart = (e: TouchEvent) => { down = true; dragDist = 0; lx = e.touches[0].clientX; ly = e.touches[0].clientY; };
    const onTouchMove  = (e: TouchEvent) => {
      if (!down) return;
      const dx = e.touches[0].clientX - lx, dy = e.touches[0].clientY - ly;
      vY += dx * 0.013; vX += dy * 0.013;
      dragDist += Math.sqrt(dx*dx + dy*dy);
      lx = e.touches[0].clientX; ly = e.touches[0].clientY;
    };
    const onTouchEnd = () => { if (dragDist < 10 && onTap) onTap(); down = false; };

    cvs.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup',   onUp);
    cvs.addEventListener('touchstart', onTouchStart, { passive: true });
    cvs.addEventListener('touchmove',  onTouchMove,  { passive: true });
    cvs.addEventListener('touchend',   onTouchEnd);

    const onWheel = (e: WheelEvent) => {
      camera.position.z = Math.max(4.5, Math.min(14, camera.position.z + e.deltaY * 0.01));
      e.preventDefault();
    };
    cvs.addEventListener('wheel', onWheel, { passive: false });

    // ── Animation ─────────────────────────────────────
    const t0 = performance.now();
    let frameId: number;

    function animate() {
      frameId = requestAnimationFrame(animate);
      const t = (performance.now() - t0) / 1000;
      const p = STATE_PARAMS[stateRef.current];

      // Orbit physics with damping
      if (!down) vY += p.rotSpeed;
      tRY += vY; tRX += vX;
      vX *= 0.90; vY *= 0.95;
      tRX = Math.max(-Math.PI * 0.48, Math.min(Math.PI * 0.48, tRX));
      cRX += (tRX - cRX) * 0.06;
      cRY += (tRY - cRY) * 0.06;
      pivot.rotation.x = cRX;
      pivot.rotation.y = cRY;

      // Orbital markers
      orbiters.forEach(({ mesh, R, offset, speed }) => {
        const a = t * speed + offset;
        mesh.position.set(R * Math.cos(a), R * Math.sin(a), 0);
      });

      // State-driven colours
      rings[0].mesh.material.color.setHex(p.ringColor);
      rings[1].mesh.material.color.setHex(p.ringColor);
      coreMat.emissive.setHex(p.coreEmissive);

      // Pulse
      const pulse = Math.sin(t * p.pulseSpeed) * 0.5 + 0.5;
      coreMat.emissiveIntensity = 1.5 + pulse * 2.5;
      pL.intensity              = 12 + pulse * 16;
      gM0.opacity               = 0.14 + pulse * 0.22;

      ico.rotation.y = t * (0.5 + p.pulseSpeed * 0.08);
      ico.rotation.x = t * 0.3;
      wf.rotation.y  = -t * 0.15;
      wf.rotation.x  =  t * 0.10;
      p1.rotation.y  =  t * 0.04;
      p2.rotation.y  = -t * 0.025;
      p3.rotation.x  =  t * 0.06;

      renderer.render(scene, camera);
    }
    animate();

    // ── Resize ────────────────────────────────────────
    const ro = new ResizeObserver(() => {
      const nW = mount.clientWidth, nH = mount.clientHeight;
      if (!nW || !nH) return;
      camera.aspect = nW / nH;
      camera.updateProjectionMatrix();
      renderer.setSize(nW, nH);
    });
    ro.observe(mount);

    cleanupFn.current = () => {
      cancelAnimationFrame(frameId);
      cvs.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
      cvs.removeEventListener('touchstart', onTouchStart);
      cvs.removeEventListener('touchmove',  onTouchMove);
      cvs.removeEventListener('touchend',   onTouchEnd);
      cvs.removeEventListener('wheel', onWheel);
      ro.disconnect();
      renderer.dispose();
      if (mount.contains(cvs)) mount.removeChild(cvs);
    };
  }, [onTap]);

  useEffect(() => {
    buildScene();
    return () => { cleanupFn.current?.(); cleanupFn.current = null; };
  }, [buildScene]);

  return (
    <div className="jarvis-wrap">
      <div ref={mountRef} className="jarvis-canvas-mount" aria-hidden="true" />

      {/* Scan sweep only — no corner brackets */}
      <div className="jarvis-scan-line" aria-hidden="true" />

      <div className="jarvis-text" aria-live="polite">
        <div className="jarvis-tag">J · A · R · V · I · S</div>
        <div className="jarvis-name">ONE</div>
        <div className={`jarvis-status jarvis-status--${state}`}>{STATUS_LABELS[state]}</div>
        <div className="jarvis-mem">{memories} MEMORIES</div>
      </div>
    </div>
  );
}

/**
 * JarvisCore — circular JARVIS-style HUD ring, "ONE" centered.
 * Pure SVG + CSS (no WebGL) -- lighter than the old THREE.js orb, and
 * matches the dial/tick-mark reference look directly instead of
 * approximating it with 3D torus rings. Pulses like a heartbeat whenever
 * ONE is actively in a discussion (listening/thinking/speaking).
 */
import { useMemo } from 'react';

export type CoreState = 'awake' | 'listening' | 'speaking' | 'thinking' | 'offline';

interface JarvisCoreProps {
  state: CoreState;
  memories: number;
  onTap?: () => void;
}

const STATUS_LABELS: Record<CoreState, string> = {
  awake:     'NEURAL CORE ONLINE',
  listening: '■ LISTENING',
  speaking:  '◆ SPEAKING',
  thinking:  '● PROCESSING',
  offline:   'OFFLINE',
};

// Heartbeat only while an actual exchange is happening -- idle "awake" and
// "offline" stay calm so the wobble reads as "ONE is engaged" not just
// decorative noise.
const DISCUSSING: Record<CoreState, boolean> = {
  awake: false, offline: false, listening: true, speaking: true, thinking: true,
};

const CX = 200;
const CY = 200;

function polar(r: number, deg: number) {
  const rad = (deg - 90) * (Math.PI / 180);
  return { x: CX + r * Math.cos(rad), y: CY + r * Math.sin(rad) };
}

function arcPath(r: number, startDeg: number, endDeg: number) {
  const start = polar(r, startDeg);
  const end = polar(r, endDeg);
  const largeArc = endDeg - startDeg <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

const TICK_DEGREES = Array.from({ length: 72 }, (_, i) => i * 5);
const MARKER_DEGREES = [18, 96, 158, 232, 305];

export function JarvisCore({ state, memories, onTap }: JarvisCoreProps) {
  const ticks = useMemo(
    () =>
      TICK_DEGREES.map((deg) => {
        const major = deg % 30 === 0;
        const outer = polar(186, deg);
        const inner = polar(major ? 168 : 177, deg);
        return { deg, x1: outer.x, y1: outer.y, x2: inner.x, y2: inner.y, major };
      }),
    [],
  );

  const markers = useMemo(
    () =>
      MARKER_DEGREES.map((deg, i) => {
        const p = polar(148, deg);
        return { ...p, deg, gold: i % 2 === 1 };
      }),
    [],
  );

  const discussing = DISCUSSING[state];

  return (
    <div
      className={`jarvis-wrap jarvis-wrap--${state}${discussing ? ' jarvis-wrap--discussing' : ''}`}
      onClick={onTap}
      onKeyDown={(e) => {
        if (onTap && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onTap();
        }
      }}
      role={onTap ? 'button' : undefined}
      tabIndex={onTap ? 0 : undefined}
      aria-label={onTap ? 'Toggle voice recording' : undefined}
    >
      <svg className="jarvis-ring-svg" viewBox="0 0 400 400" aria-hidden="true">
        <circle cx={CX} cy={CY} r={196} className="jarvis-ring-outer" />
        <circle cx={CX} cy={CY} r={162} className="jarvis-ring-mid" />
        <circle cx={CX} cy={CY} r={120} className="jarvis-ring-inner" />

        {ticks.map((t) => (
          <line
            key={t.deg}
            x1={t.x1}
            y1={t.y1}
            x2={t.x2}
            y2={t.y2}
            className={t.major ? 'jarvis-tick jarvis-tick--major' : 'jarvis-tick'}
          />
        ))}

        <g className="jarvis-arc-spin">
          <path d={arcPath(179, 200, 300)} className="jarvis-arc jarvis-arc--accent" />
          <path d={arcPath(179, 20, 68)} className="jarvis-arc jarvis-arc--gold" />
        </g>

        {markers.map((m) => (
          <circle
            key={m.deg}
            cx={m.x}
            cy={m.y}
            r={4.5}
            className={m.gold ? 'jarvis-marker jarvis-marker--gold' : 'jarvis-marker'}
          />
        ))}
      </svg>

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

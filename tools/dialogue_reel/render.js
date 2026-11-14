// Render a dialogue reel: headless Chromium draws each frame, ffmpeg encodes.
// Usage: node render.js out/ep01 [--stills 0,150,400] [--handle @aibyvineet]
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const ROOT = __dirname;
const outDir = path.resolve(process.argv[2]);
const arg = k => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const stills = arg('--stills')?.split(',').map(Number) || null;
const handle = arg('--handle') || '@aibyvineet';

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  const real = p.startsWith(outDir) ? p : p;
  if (!real.startsWith(ROOT) || !fs.existsSync(real) || fs.statSync(real).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(real)] || 'application/octet-stream' });
  fs.createReadStream(real).pipe(res);
});

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 720, height: 1280 } });
  page.on('console', m => console.log('[page]', m.text()));
  page.on('pageerror', e => { console.error('[page error]', e.message); process.exit(1); });
  const tl = path.relative(ROOT, path.join(outDir, 'timeline.json'));
  await page.goto(`http://127.0.0.1:${port}/scene.html?timeline=${encodeURIComponent(tl)}&handle=${encodeURIComponent(handle)}`);
  await page.waitForFunction('window.ready === true', null, { timeout: 60000 });
  const total = await page.evaluate('window.TOTAL_FRAMES');

  if (stills) {
    const last = Math.max(...stills);
    for (let f = 0; f <= last; f++) {
      const want = stills.includes(f);
      const data = await page.evaluate(([f, want]) => want ? window.renderFrame(f, 'image/png') : (window.stepFrame(f), null), [f, want]);
      if (want) fs.writeFileSync(path.join(outDir, `still_${String(f).padStart(5, '0')}.png`), Buffer.from(data.split(',')[1], 'base64'));
    }
    await browser.close(); server.close();
    return console.log('stills done');
  }

  const silent = path.join(outDir, 'video_silent.mp4');
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', '30', '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p', silent], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = 0; f < total; f++) {
    const data = await page.evaluate(f => window.renderFrame(f), f);
    const buf = Buffer.from(data.split(',')[1], 'base64');
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 150 === 0) console.log(`frame ${f}/${total} (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close(); server.close();

  const final = path.join(outDir, 'reel.mp4');
  await new Promise((res, rej) => spawn('ffmpeg', ['-v', 'error', '-y', '-i', silent, '-i', path.join(outDir, 'audio.wav'),
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', final], { stdio: 'inherit' })
    .on('close', c => (c ? rej(new Error('mux failed')) : res())));
  console.log('done', final, `${((Date.now() - t0) / 1000).toFixed(0)}s`);
})();

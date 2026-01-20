// robot.js - manages robot state, movement, rendering
export const ROBOT_MOVE_STEP = 1; // units per move
export const ROBOT_ROT_STEP = 15; // degrees per rotation

export function initRobotMap() {
  const canvas = document.getElementById('robotMap');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const ctx = canvas.getContext('2d');
  canvas._ctx = ctx;
  canvas._dpr = dpr;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(200, rect.width) * dpr;
    canvas.height = Math.max(120, rect.height) * dpr;
    renderRobotMap();
  }

  resize();
  window.addEventListener('resize', resize);
}

export function renderRobotMap() {
  const canvas = document.getElementById('robotMap');
  if (!canvas || !canvas._ctx) {
    console.warn('renderRobotMap: canvas or context missing');
    return;
  }
  const ctx = canvas._ctx;
  const w = canvas.width; const h = canvas.height; const dpr = canvas._dpr || 1;

  // Determine bounds from trail + current
  const pts = (window.state?.robot?.trail || []).concat([{ x: window.state?.robot?.x || 0, y: window.state?.robot?.y || 0 }]);
  let minX = Math.min(...pts.map(p => p.x));
  let maxX = Math.max(...pts.map(p => p.x));
  let minY = Math.min(...pts.map(p => p.y));
  let maxY = Math.max(...pts.map(p => p.y));

  if (minX === maxX) { minX -= 1; maxX += 1; }
  if (minY === maxY) { minY -= 1; maxY += 1; }

  const margin = 20 * dpr;
  const availableW = w - margin * 2;
  const availableH = h - margin * 2;
  const rangeX = maxX - minX;
  const rangeY = maxY - minY;
  const scaleX = availableW / rangeX;
  const scaleY = availableH / rangeY;
  const scale = Math.max( (Math.min(scaleX, scaleY) || 20), 6 );

  const mapToPx = (p) => ({ px: margin + (p.x - minX) * scale, py: h - (margin + (p.y - minY) * scale) });

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(0, 0, w, h);

  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1 * dpr;
  ctx.beginPath();
  for (let gx = Math.ceil(minX); gx <= Math.floor(maxX); gx++) {
    const x = mapToPx({ x: gx, y: minY }).px;
    ctx.moveTo(x, margin);
    ctx.lineTo(x, h - margin);
  }
  for (let gy = Math.ceil(minY); gy <= Math.floor(maxY); gy++) {
    const y = mapToPx({ x: minX, y: gy }).py;
    ctx.moveTo(margin, y);
    ctx.lineTo(w - margin, y);
  }
  ctx.stroke();

  // trail
  const robot = window.state?.robot || { x: 0, y: 0, angle: 0, trail: [] };
  if (robot.trail && robot.trail.length > 0) {
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath();
    const start = mapToPx(robot.trail[0]);
    ctx.moveTo(start.px, start.py);
    for (let i = 1; i < robot.trail.length; i++) {
      const p = mapToPx(robot.trail[i]);
      ctx.lineTo(p.px, p.py);
    }
    const cur = mapToPx({ x: robot.x, y: robot.y });
    ctx.lineTo(cur.px, cur.py);
    ctx.stroke();

    ctx.fillStyle = 'rgba(59,130,246,0.9)';
    for (let p of robot.trail) {
      const pt = mapToPx(p);
      ctx.beginPath();
      ctx.arc(pt.px, pt.py, 3 * dpr, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // draw robot
  const curPx = mapToPx({ x: robot.x, y: robot.y });
  ctx.save();
  ctx.translate(curPx.px, curPx.py);
  ctx.rotate(robot.angle * Math.PI / 180);
  ctx.fillStyle = '#f87171';
  ctx.beginPath();
  const size = 10 * dpr;
  ctx.moveTo(0, -size);
  ctx.lineTo(size * 0.7, size);
  ctx.lineTo(-size * 0.7, size);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  const posEl = document.getElementById('robotPosition');
  if (posEl) posEl.textContent = `Position: (${robot.x.toFixed(2)}, ${robot.y.toFixed(2)}) — Facing: ${getFacingLabel(robot.angle) } (${robot.angle.toFixed(0)}°)`;
}

export function robotMove(step) {
  const r = window.state.robot;
  const rad = r.angle * Math.PI / 180;
  // x increases to the right (sin), y increases to the north (cos)
  const dx = Math.sin(rad) * step;
  const dy = Math.cos(rad) * step; // previously had inverted sign
  r.x = +(r.x + dx).toFixed(4);
  r.y = +(r.y + dy).toFixed(4);
  r.trail.push({ x: r.x, y: r.y });

  // Enforce trail length limit
  const limit = window.state?.robotTrailLimit || 200;
  while (r.trail.length > limit) r.trail.shift();

  window.addLogEntry?.(`Robot moved ${step > 0 ? 'forward' : 'backward'} to (${r.x.toFixed(2)}, ${r.y.toFixed(2)})`);
  console.debug('robotMove: new state', JSON.stringify(r));
  renderRobotMap();
}

export function robotRotate(delta) {
  const r = window.state.robot;
  r.angle = (r.angle + delta + 360) % 360;
  window.addLogEntry?.(`Robot rotated ${delta > 0 ? 'right' : 'left'} to ${r.angle.toFixed(0)}°`);
  const posEl = document.getElementById('robotPosition');
  if (posEl) posEl.textContent = `Position: (${r.x.toFixed(2)}, ${r.y.toFixed(2)}) — Facing: ${getFacingLabel(r.angle)} (${r.angle.toFixed(0)}°)`;
  console.debug('robotRotate: new angle', r.angle);
  renderRobotMap();
}

export function resetRobot() {
  const r = window.state.robot;
  r.x = 0; r.y = 0; r.angle = 0; r.trail = [{ x: 0, y: 0 }];
  window.addLogEntry?.('Robot position reset');
  renderRobotMap();
}

export function setTrailLimit(limit) {
  const n = Math.max(1, Number(limit) || 1);
  window.state.robotTrailLimit = n;
  localStorage.setItem('robotTrailLimit', n);
  const r = window.state.robot;
  while (r.trail.length > n) r.trail.shift();
  window.addLogEntry?.(`Trail limit set to ${n}`);
  renderRobotMap();
}

export function getFacingLabel(angle = (window.state?.robot?.angle || 0)) {
  const a = angle % 360;
  if (a >= 315 || a < 45) return 'N';
  if (a >= 45 && a < 135) return 'E';
  if (a >= 135 && a < 225) return 'S';
  return 'W';
}

// expose for legacy code
window.robot = {
  initRobotMap,
  renderRobotMap,
  robotMove,
  robotRotate,
  resetRobot,
  setTrailLimit,
  getFacingLabel
};
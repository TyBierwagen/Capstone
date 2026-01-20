import { robotMove, robotRotate } from './robot.js';

export function sendOverrideDirection(direction) {
  try {
    const enabled = !!document.getElementById('overrideEnable')?.checked;
    if (!enabled) {
      window.showAlert?.('Enable override first', 'error');
      return;
    }

    if (direction === 'up') {
      robotMove(1);
    } else if (direction === 'down') {
      robotMove(-1);
    } else if (direction === 'left') {
      robotRotate(-15);
    } else if (direction === 'right') {
      robotRotate(15);
    }

    window.addLogEntry?.(`Override command: ${direction}`);
    const statusEl = document.getElementById('overrideStatus');
    if (statusEl) statusEl.textContent = `Last: ${direction.toUpperCase()}`;
    window.showAlert?.(`Override: ${direction}`, 'success');
  } catch (e) {
    console.error(e);
    window.showAlert?.('Could not send override', 'error');
  }
}

export function setupOverrideControls() {
  const arrows = document.getElementById('overrideArrows');
  if (arrows) {
    arrows.addEventListener('click', (e) => {
      const btn = e.target.closest('.arrow-btn');
      if (btn && btn.dataset && btn.dataset.dir) sendOverrideDirection(btn.dataset.dir);
    });
  }

  const ovCheckbox = document.getElementById('overrideEnable');
  if (ovCheckbox) {
    ovCheckbox.addEventListener('change', () => { try { ovCheckbox.blur(); } catch (e) {} });
  }

  window.addEventListener('keydown', (e) => {
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' && active.type !== 'checkbox' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;

    let dir = null;
    if (e.key && e.key.startsWith('Arrow')) dir = e.key.replace('Arrow', '').toLowerCase();
    else {
      const k = (e.key || '').toLowerCase();
      if (k === 'w') dir = 'up';
      else if (k === 'a') dir = 'left';
      else if (k === 's') dir = 'down';
      else if (k === 'd') dir = 'right';
    }

    if (dir) {
      e.preventDefault();
      sendOverrideDirection(dir);
    }
  });
}

window.override = { sendOverrideDirection, setupOverrideControls };
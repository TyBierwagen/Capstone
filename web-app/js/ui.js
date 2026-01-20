import { state } from './state.js';

export function showAlert(message, type = 'success') {
  const alert = document.getElementById('alert');
  if (!alert) return;
  alert.textContent = message;
  alert.className = `alert ${type} show`;
  setTimeout(() => alert.classList.remove('show'), 4500);
}

export function addLogEntry(text) {
  const log = document.getElementById('activityLog');
  if (!log) return;
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  const time = new Date().toLocaleTimeString();
  entry.innerHTML = `<span class="log-time">${time}</span><span>${text}</span>`;
  log.insertBefore(entry, log.firstChild);
  while (log.children.length > 60) log.removeChild(log.lastChild);
}

export function clearLog() {
  const log = document.getElementById('activityLog');
  if (!log) return;
  log.innerHTML = '<div class="log-entry"><span class="log-time">--:--:--</span><span>Log cleared</span></div>';
  addLogEntry('Log cleared');
}

// Expose for legacy code
window.showAlert = showAlert;
window.addLogEntry = addLogEntry;
window.clearLog = clearLog;
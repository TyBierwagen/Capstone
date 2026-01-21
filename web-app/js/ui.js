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

export function setLoading(elementId, isLoading) {
  const el = document.getElementById(elementId);
  if (!el) return;
  
  if (isLoading) {
    el.classList.add('loading');
    // Add skeleton classes to existing values
    el.querySelectorAll('.sensor-value, #lastUpdated, #commandStatus').forEach(v => v.classList.add('skeleton-text'));
  } else {
    el.classList.remove('loading');
    el.querySelectorAll('.skeleton-text').forEach(v => v.classList.remove('skeleton-text'));
  }
}

export function updateSensorDisplay(payload) {
  if (!payload) return;
  state.latestData = payload;

  updateValueIfIdExists('moisture', formatValue(payload.moisture, 1));
  
  const tempValue = (state.tempUnit === 'F' && payload.temperature !== null) 
    ? (payload.temperature * 9 / 5) + 32 
    : payload.temperature;
    
  updateValueIfIdExists('temperature', formatValue(tempValue, 1));
  const tempUnitEl = document.querySelector('#temperature')?.nextElementSibling;
  if (tempUnitEl) tempUnitEl.textContent = state.tempUnit === 'F' ? '°F' : '°C';

  updateValueIfIdExists('humidity', formatValue(payload.humidity, 1));
  updateValueIfIdExists('ph', formatValue(payload.ph, 2));
  updateValueIfIdExists('light', payload.light ?? '--');
  
  // Prefer the 'timestamp' we sent, fall back to internal 'Timestamp' if Azure shifted it
  const ts = payload.timestamp || payload.Timestamp;
  updateValueIfIdExists('lastUpdated', ts, true);
  
  updateValueIfIdExists('commandStatus', payload.commandStatus ?? 'idle');
}

export function updateDeviceInfo(payload) {
  const device = payload.device ?? {};
  updateValueIfIdExists('deviceStatus', device.status ?? 'online');
  updateValueIfIdExists('deviceType', device.type ?? 'soil_sensor');
  
  const ls = device.lastSeen || device.Timestamp;
  updateValueIfIdExists('deviceLastSeen', ls, true);
}

function updateValueIfIdExists(id, value, isTimestamp = false) {
  const el = document.getElementById(id);
  if (!el) return;
  
  if (isTimestamp) {
    el.textContent = formatTimestamp(value);
  } else {
    el.textContent = value;
  }
}

function formatValue(value, precision) {
  if (value === null || value === undefined) return '--';
  return typeof value === 'number' ? value.toFixed(precision) : value;
}

function formatTimestamp(value) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  
  // Added seconds so users can see the 30s updates happening
  return parsed.toLocaleString([], { 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit'
  });
}

// Expose for legacy code
window.showAlert = showAlert;
window.addLogEntry = addLogEntry;
window.clearLog = clearLog;
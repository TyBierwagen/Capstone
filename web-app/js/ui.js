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
  updateValueIfIdExists('battery', formatValue(payload.battery, 2));
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

export function renderDeviceManager(devices, meta = {}) {
  const list = document.getElementById('deviceManagerList');
  if (!list) return;

  const normalizedDevices = Array.isArray(devices) ? devices : [];
  state.deviceDirectory = normalizedDevices;

  const countEl = document.getElementById('deviceCount');
  if (countEl) countEl.textContent = String(normalizedDevices.length);

  const updatedEl = document.getElementById('deviceDirectoryUpdatedAt');
  if (updatedEl) updatedEl.textContent = meta.catalogRefreshedAt ? formatTimestamp(meta.catalogRefreshedAt) : (normalizedDevices.length ? new Date().toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }) : '--');

  list.innerHTML = '';

  if (!normalizedDevices.length) {
    const empty = document.createElement('div');
    empty.className = 'device-empty';
    empty.textContent = 'No devices have been cataloged yet. The backend refreshes this list during daily maintenance bursts.';
    list.appendChild(empty);
    return;
  }

  normalizedDevices.forEach((device) => {
    const row = document.createElement('div');
    row.className = 'device-row';
    const alertsEnabled = device.emailAlertsEnabled !== false && String(device.emailAlertsEnabled).toLowerCase() !== 'false';

    const identity = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'device-title';
    title.textContent = device.deviceName || device.id || device.ip || 'Unknown device';
    const subtitle = document.createElement('div');
    subtitle.className = 'device-subtitle';
    subtitle.textContent = [device.ip || '--', device.type || 'soil_sensor'].filter(Boolean).join(' · ');
    identity.appendChild(title);
    identity.appendChild(subtitle);

    const statusWrap = document.createElement('div');
    const status = document.createElement('span');
    const statusValue = String(device.status || 'unknown').toLowerCase();
    status.className = `device-status-pill ${statusValue.replace(/[^a-z0-9_-]/g, '-')}`;
    status.textContent = statusValue;
    statusWrap.appendChild(status);

    const details = document.createElement('div');
    details.className = 'device-subtitle';
    details.textContent = device.port ? `Port ${device.port}` : 'Port --';

    const lastSeen = document.createElement('div');
    lastSeen.className = 'device-subtitle';
    lastSeen.textContent = `Last seen: ${formatTimestamp(device.lastSeen || device.Timestamp)}`;

    const alertControl = document.createElement('div');
    alertControl.className = 'device-alert-control';

    const alertLabel = document.createElement('div');
    alertLabel.className = 'device-subtitle';
    alertLabel.textContent = alertsEnabled ? 'Email alerts enabled' : 'Excluded from email alerts';

    const alertSwitch = document.createElement('label');
    alertSwitch.className = 'switch small-switch';
    alertSwitch.style.margin = '0';
    alertSwitch.title = alertsEnabled ? 'Disable email alerts for this device' : 'Enable email alerts for this device';

    const alertToggle = document.createElement('input');
    alertToggle.type = 'checkbox';
    alertToggle.checked = alertsEnabled;
    alertToggle.addEventListener('change', async (event) => {
      const nextEnabled = event.target.checked;
      const updater = window.setDeviceEmailAlertsEnabled;

      if (typeof updater !== 'function') {
        event.target.checked = !nextEnabled;
        showAlert('Device alert controls are unavailable right now.', 'error');
        return;
      }

      event.target.disabled = true;
      try {
        await updater(device.ip || device.id || device.RowKey, nextEnabled);
      } catch (error) {
        event.target.checked = !nextEnabled;
        showAlert(error?.message || 'Failed to update device alerts', 'error');
      } finally {
        event.target.disabled = false;
      }
    });

    const alertSlider = document.createElement('span');
    alertSlider.className = 'slider';

    alertSwitch.appendChild(alertToggle);
    alertSwitch.appendChild(alertSlider);
    alertControl.appendChild(alertLabel);
    alertControl.appendChild(alertSwitch);

    row.appendChild(identity);
    row.appendChild(statusWrap);
    row.appendChild(details);
    row.appendChild(lastSeen);
    row.appendChild(alertControl);
    list.appendChild(row);
  });
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

  // Normalize common odd timestamp forms so Date parsing succeeds:
  // - Some backends send `2026-01-21T17:17:33+00:00Z` (both offset and Z)
  // - Others may send unix seconds as a string
  let parsed;
  if (typeof value === 'number') {
    parsed = new Date(value);
  } else if (typeof value === 'string') {
    let cleaned = value.trim();
    // Replace a duplicated timezone ("+00:00Z") with single Z
    cleaned = cleaned.replace(/\+00:00Z$/, 'Z').replace(/\+00:00$/, 'Z');
    // If it's a 10-digit unix timestamp in seconds, convert to ms
    if (/^\d{10}$/.test(cleaned)) cleaned = Number(cleaned) * 1000;
    parsed = new Date(cleaned);
  } else {
    parsed = new Date(value);
  }

  if (Number.isNaN(parsed.getTime())) return value;

  // Show month/day and a 2-digit time with seconds so 30s updates are visible
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
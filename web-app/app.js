const API_BASE_URL = 'https://soilrobot-func-dev.azurewebsites.net/api';

const state = {
  isConnected: false,
  deviceIp: '',
  refreshIntervalId: null,
};

document.addEventListener('DOMContentLoaded', () => {
  const savedIp = localStorage.getItem('deviceIp');
  document.getElementById('deviceIp').value = savedIp || '';
  
  // Update copyright year
  const yearSpan = document.getElementById('copyrightYear');
  if (yearSpan) {
    yearSpan.textContent = new Date().getFullYear();
  }

  updateConnectionStatus(false);
  addLogEntry('Dashboard ready');
});

function toggleIpFilter() {
  const isEnabled = document.getElementById('filterIpToggle').checked;
  const container = document.getElementById('ipInputContainer');
  container.style.display = isEnabled ? 'block' : 'none';
  
  if (!isEnabled) {
    document.getElementById('deviceIp').value = '';
    state.deviceIp = '';
    if (state.isConnected) {
      addLogEntry('Switching to global telemetry');
      refreshData();
    }
  }
}

async function toggleConnection() {
  if (state.isConnected) {
    disconnect();
  } else {
    await connect();
  }
}

async function connect() {
  const isFilterEnabled = document.getElementById('filterIpToggle').checked;
  const ipInput = document.getElementById('deviceIp').value.trim();

  if (isFilterEnabled && !ipInput) {
    showAlert('Please enter an IP or turn off filtering', 'error');
    return;
  }

  state.deviceIp = isFilterEnabled ? ipInput : '';
  state.isConnected = true;

  if (state.deviceIp) {
    localStorage.setItem('deviceIp', ipInput);
    addLogEntry(`Filtering for device ${ipInput}`);
  } else {
    addLogEntry('Watching all device telemetry');
  }

  updateConnectionStatus(true);
  showAlert('Dashboard active', 'success');
  startAutoRefresh();
}

function disconnect() {
  state.isConnected = false;
  stopAutoRefresh();
  updateConnectionStatus(false);
  showAlert('Monitoring paused', 'error');
  addLogEntry('Connection closed');
  resetSensorDisplay();
}

function updateConnectionStatus(connected) {
  const indicator = document.getElementById('statusIndicator');
  const button = document.getElementById('connectBtn');
  indicator.classList.toggle('connected', connected);
  indicator.classList.toggle('disconnected', !connected);
  button.textContent = connected ? 'Disconnect' : 'Connect';
}

async function refreshData() {
  if (!state.isConnected) {
    showAlert('Activate monitoring to refresh', 'error');
    return;
  }

  try {
    let url = `${API_BASE_URL}/sensor-data`;
    if (state.deviceIp) {
      url += `?deviceIp=${encodeURIComponent(state.deviceIp)}`;
    }

    const response = await fetch(url, {
      cache: 'no-store',
    });

    if (response.status === 404) {
      const mode = state.deviceIp ? `device ${state.deviceIp}` : 'any device';
      showAlert(`No data found for ${mode}`, 'warning');
      addLogEntry('Waiting for incoming data...');
      return;
    }

    if (!response.ok) {
      throw new Error('Failed to load sensor data');
    }

    const payload = await response.json();
    updateSensorDisplay(payload);
    updateDeviceInfo(payload);
    addLogEntry('Fresh data pulled from the database');
  } catch (error) {
    console.error('Refresh error', error);
    showAlert('Unable to reach the API', 'error');
    addLogEntry('Refresh failed');
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  refreshData();

  const seconds = 30;
  state.refreshIntervalId = setInterval(refreshData, seconds * 1000);
  addLogEntry(`Auto-refresh active (30s)`);
}

function stopAutoRefresh() {
  if (state.refreshIntervalId) {
    clearInterval(state.refreshIntervalId);
    state.refreshIntervalId = null;
    addLogEntry('Auto-refresh paused');
  }
}

function resetSensorDisplay() {
  ['moisture', 'temperature', 'humidity', 'ph', 'light', 'lastUpdated', 'commandStatus', 'deviceStatus', 'deviceType', 'deviceRegistered', 'deviceLastSeen'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = '--';
    }
  });
}

function updateSensorDisplay(payload) {
  document.getElementById('moisture').textContent = formatValue(payload.moisture, 1);
  document.getElementById('temperature').textContent = formatValue(payload.temperature, 1);
  document.getElementById('humidity').textContent = formatValue(payload.humidity, 1);
  document.getElementById('ph').textContent = formatValue(payload.ph, 2);
  document.getElementById('light').textContent = payload.light ?? '--';
  document.getElementById('lastUpdated').textContent = formatTimestamp(payload.timestamp);
  document.getElementById('commandStatus').textContent = payload.commandStatus ?? 'idle';
}

function updateDeviceInfo(payload) {
  const device = payload.device ?? {};
  document.getElementById('deviceStatus').textContent = device.status ?? 'unknown';
  document.getElementById('deviceType').textContent = device.type ?? 'soil_sensor';
  document.getElementById('deviceRegistered').textContent = device.registeredAt
    ? formatTimestamp(device.registeredAt)
    : '--';
  document.getElementById('deviceLastSeen').textContent = device.lastSeen
    ? formatTimestamp(device.lastSeen)
    : '--';
}

function updateActiveIp() {
  if (state.isConnected) {
    state.deviceIp = document.getElementById('deviceIp').value.trim();
  }
}

function formatValue(value, precision) {
  if (value === null || value === undefined) {
    return '--';
  }
  return typeof value === 'number' ? value.toFixed(precision) : value;
}

function formatTimestamp(value) {
  if (!value) {
    return '--';
  }
  
  // If the value is a number (like the microcontroller's milliseconds), treat it as a relative time from now
  if (typeof value === 'number') {
    return new Date().toLocaleString() + ' (Device uptime: ' + (value/1000).toFixed(0) + 's)';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function showAlert(message, type = 'success') {
  const alert = document.getElementById('alert');
  alert.textContent = message;
  alert.className = `alert ${type} show`;
  setTimeout(() => alert.classList.remove('show'), 4500);
}

function addLogEntry(text) {
  const log = document.getElementById('activityLog');
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  const time = new Date().toLocaleTimeString();
  entry.innerHTML = `<span class="log-time">${time}</span><span>${text}</span>`;
  log.insertBefore(entry, log.firstChild);
  while (log.children.length > 60) {
    log.removeChild(log.lastChild);
  }
}

function clearLog() {
  const log = document.getElementById('activityLog');
  log.innerHTML = '<div class="log-entry"><span class="log-time">--:--:--</span><span>Log cleared</span></div>';
  addLogEntry('Log cleared');
}

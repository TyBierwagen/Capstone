const API_BASE_URL = 'https://soilrobot-func-dev.azurewebsites.net/api';

const state = {
  isConnected: false,
  deviceIp: '',
  refreshIntervalId: null,
};

document.addEventListener('DOMContentLoaded', () => {
  const savedIp = localStorage.getItem('deviceIp');
  const savedInterval = localStorage.getItem('refreshInterval') || '30';
  document.getElementById('deviceIp').value = savedIp || '';
  document.getElementById('refreshInterval').value = savedInterval;
  updateConnectionStatus(false);
  addLogEntry('Dashboard ready');
});

async function toggleConnection() {
  if (state.isConnected) {
    disconnect();
  } else {
    await connect();
  }
}

async function connect() {
  const ipInput = document.getElementById('deviceIp').value.trim();

  if (!ipInput) {
    showAlert('Enter the device IP before connecting', 'error');
    return;
  }

  state.deviceIp = ipInput;
  state.isConnected = true;
  localStorage.setItem('deviceIp', ipInput);
  updateConnectionStatus(true);
  showAlert('Connected to backend', 'success');
  addLogEntry(`Tracking device ${ipInput}`);
  startAutoRefresh();
}

function disconnect() {
  state.isConnected = false;
  state.deviceIp = '';
  stopAutoRefresh();
  updateConnectionStatus(false);
  showAlert('Disconnected', 'error');
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
    showAlert('Connect to a device before refreshing', 'error');
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/sensor-data?deviceIp=${encodeURIComponent(state.deviceIp)}`, {
      cache: 'no-store',
    });

    if (response.status === 404) {
      showAlert('No data yet for that device', 'warning');
      addLogEntry('Waiting for sensor data to arrive');
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

  const intervalInput = document.getElementById('refreshInterval');
  const seconds = Math.max(5, parseInt(intervalInput.value, 10) || 30);
  intervalInput.value = seconds;
  localStorage.setItem('refreshInterval', seconds);

  state.refreshIntervalId = setInterval(refreshData, seconds * 1000);
  addLogEntry(`Auto-refresh every ${seconds}s`);
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

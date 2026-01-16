const PROD_API_URL = 'https://soilrobot-func-dev.azurewebsites.net/api';
const LOCAL_API_URL = 'http://localhost:7071/api';

const state = {
  isConnected: false,
  useProd: true,
  deviceIp: '',
  refreshIntervalId: null,
  chart: null,
  tempUnit: 'C',
  latestData: null,
  historyData: null,
  lastTimescale: '1h'
};

function getApiBaseUrl() {
  return state.useProd ? PROD_API_URL : LOCAL_API_URL;
}

document.addEventListener('DOMContentLoaded', () => {
  const savedIp = localStorage.getItem('deviceIp');
  document.getElementById('deviceIp').value = savedIp || '';
  
  const savedKey = localStorage.getItem('functionKey');
  if (savedKey) {
    document.getElementById('functionKey').value = savedKey;
    updateActiveKey();
  }

  const savedUnit = localStorage.getItem('tempUnit');
  if (savedUnit) {
    state.tempUnit = savedUnit;
    const toggle = document.getElementById('tempUnitToggle');
    if (toggle) toggle.checked = savedUnit === 'F';
    
    // Update UI toggle labels
    const tempUnitEl = document.querySelector('#temperature')?.nextElementSibling;
    if (tempUnitEl) tempUnitEl.textContent = savedUnit === 'F' ? '°F' : '°C';
  }

  const savedUseProd = localStorage.getItem('useProd');
  if (savedUseProd !== null) {
    state.useProd = savedUseProd === 'true';
  }
  const apiToggle = document.getElementById('apiSourceToggle');
  if (apiToggle) apiToggle.checked = state.useProd;

  // Update copyright year
  const yearSpan = document.getElementById('copyrightYear');
  if (yearSpan) {
    yearSpan.textContent = new Date().getFullYear();
  }

  initChart();
  updateConnectionStatus(false);
  addLogEntry('Dashboard ready');
});

function initChart() {
  const ctx = document.getElementById('sensorChart').getContext('2d');
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  state.chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Humidity (%)',
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          data: [],
          tension: 0.3,
          yAxisID: 'y',
        },
        {
          label: `Temp (${unitLabel})`,
          borderColor: '#f87171',
          data: [],
          tension: 0.3,
          yAxisID: 'y1',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#cbd5f5' }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: '#94a3b8' }
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: '#3b82f6' },
          title: { display: true, text: 'Humidity %', color: '#3b82f6' }
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#f87171' },
          title: { display: true, text: `Temp (${unitLabel})`, color: '#f87171' }
        }
      }
    }
  });
}

function updateChart(history, timescale = '1h') {
  if (!state.chart || !history) return;

  state.historyData = history;
  state.lastTimescale = timescale;

  // Sort history by time (ascending) for the chart
  const sorted = [...history].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  state.chart.options.scales.y1.title.text = `Temp (${unitLabel})`;
  state.chart.data.datasets[1].label = `Temp (${unitLabel})`;

  state.chart.data.labels = sorted.map(h => {
    const d = new Date(h.timestamp);
    if (isNaN(d.getTime())) return '';
    
    const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    if (timescale === '1h') {
      return timeStr;
    } else if (timescale === '1d') {
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + timeStr;
    } else {
      // 1m, 1y, all
      return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: '2-digit' }) + ' ' + timeStr;
    }
  });
  
  state.chart.data.datasets[0].data = sorted.map(h => h.humidity);
  state.chart.data.datasets[1].data = sorted.map(h => {
    const temp = h.temperature;
    return (state.tempUnit === 'F' && temp !== null) ? (temp * 9/5) + 32 : temp;
  });
  state.chart.update('none'); // Update without animation for performance
}

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

function toggleTempUnit() {
  state.tempUnit = document.getElementById('tempUnitToggle').checked ? 'F' : 'C';
  localStorage.setItem('tempUnit', state.tempUnit);
  addLogEntry(`Units changed to °${state.tempUnit}`);
  
  // Update unit labels immediately
  const tempValueEl = document.getElementById('temperature');
  if (tempValueEl && tempValueEl.nextElementSibling) {
    tempValueEl.nextElementSibling.textContent = state.tempUnit === 'F' ? '°F' : '°C';
  }

  if (state.latestData) {
    updateSensorDisplay(state.latestData);
  }
  if (state.historyData) {
    updateChart(state.historyData, state.lastTimescale);
  }
}

function toggleApiSource() {
  state.useProd = document.getElementById('apiSourceToggle').checked;
  localStorage.setItem('useProd', state.useProd);
  addLogEntry(`Switched to ${state.useProd ? 'Production' : 'Local'} API`);
  if (state.isConnected) {
    refreshData();
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
    const baseUrl = getApiBaseUrl();
    const timescale = document.getElementById('timeScale')?.value || '1h';
    const params = new URLSearchParams();
    if (state.deviceIp) params.append('deviceIp', state.deviceIp);
    
    const apiKey = localStorage.getItem('functionKey');
    if (apiKey) {
      // Send the function key as a query parameter to satisfy Function auth and avoid CORS preflight
      params.append('code', apiKey);
    }
    const init = { cache: 'no-store' };
    
    // Fetch latest for the top cards
    const latestResponse = await fetch(`${baseUrl}/sensor-data?${params.toString()}`, init);

    // If unauthorized, show a clear message and stop refresh
    if (latestResponse.status === 401) {
      showAlert('Unauthorized: Function key missing or invalid. Enter a valid key in Access Key', 'error');
      addLogEntry('Unauthorized (401) from sensor-data');
      return;
    }
    
    // Fetch history for the graph
    const historyParams = new URLSearchParams(params);
    historyParams.append('history', 'true');
    historyParams.append('timescale', timescale);
    const historyResponse = await fetch(`${baseUrl}/sensor-data?${historyParams.toString()}`, init);

    if (latestResponse.status === 404) {
      const mode = state.deviceIp ? `device ${state.deviceIp}` : 'any device';
      showAlert(`No data found for ${mode}`, 'warning');
      addLogEntry('Waiting for incoming data...');
      return;
    }

    if (!latestResponse.ok) throw new Error('Failed to load latest data');
    
    const latestData = await latestResponse.json();
    updateSensorDisplay(latestData);
    updateDeviceInfo(latestData);

    if (historyResponse.ok) {
      const historyData = await historyResponse.json();
      updateChart(historyData.history, timescale);
    }
    
    const scaleLabel = document.querySelector(`#timeScale option[value="${timescale}"]`)?.textContent || timescale;
    addLogEntry(`Synced data for ${scaleLabel}`);
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

function updateValueIfIdExists(id, value, isTimestamp = false) {
  const el = document.getElementById(id);
  if (!el) return;
  
  if (isTimestamp) {
    el.textContent = formatTimestamp(value);
  } else {
    el.textContent = value;
  }
}

function updateSensorDisplay(payload) {
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
  updateValueIfIdExists('lastUpdated', payload.timestamp, true);
  updateValueIfIdExists('commandStatus', payload.commandStatus ?? 'idle');
}

function updateDeviceInfo(payload) {
  const device = payload.device ?? {};
  updateValueIfIdExists('deviceStatus', device.status ?? 'unknown');
  updateValueIfIdExists('deviceType', device.type ?? 'soil_sensor');
  updateValueIfIdExists('deviceRegistered', device.registeredAt, true);
  updateValueIfIdExists('deviceLastSeen', device.lastSeen, true);
}

function updateActiveIp() {
  if (state.isConnected) {
    state.deviceIp = document.getElementById('deviceIp').value.trim();
  }
}

function updateActiveKey() {
  const key = document.getElementById('functionKey').value.trim();
  localStorage.setItem('functionKey', key);
  const hint = document.getElementById('functionKeyHint');
  const maskedEl = document.getElementById('maskedKey');
  if (key) {
    const masked = '••••••' + key.slice(-4);
    if (maskedEl) maskedEl.textContent = masked;
    if (hint) hint.style.display = 'block';
  } else {
    if (hint) hint.style.display = 'none';
    if (maskedEl) maskedEl.textContent = '';
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
  
  // Handle ISO strings or other string dates
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;

  // Always show month and date for context, plus 2-digit time
  return parsed.toLocaleString([], { 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit', 
    minute: '2-digit' 
  });
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

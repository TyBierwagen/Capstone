// app.js deprecated — functionality has moved to ES modules under js/
// Use <script type="module" src="js/main.js"></script> which loads the modules.
console.warn('app.js (deprecated): functionality moved to modules in js/. Use js/main.js');

// Provide minimal shims for backwards compatibility if anything still references these names.
window.state = window.state || { /* no-op state */ };
window.showAlert = window.showAlert || function(){ console.warn('showAlert called (deprecated)'); };
window.addLogEntry = window.addLogEntry || function(){ console.warn('addLogEntry called (deprecated)'); };
window.clearLog = window.clearLog || function(){ console.warn('clearLog called (deprecated)'); };


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
          // meta used to build axis later
          axisTitle: 'Humidity %',
          axisColor: '#3b82f6'
        },
        {
          label: `Temp (${unitLabel})`,
          borderColor: '#f87171',
          data: [],
          tension: 0.3,
          axisTitle: `Temp (${unitLabel})`,
          axisColor: '#f87171'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: '#cbd5f5',
            // only include legend items for datasets that are currently visible
            filter: function(legendItem, chartData) {
              return !chartData.datasets[legendItem.datasetIndex].hidden;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: '#94a3b8' }
        }
      }
    }
  });
}

// --- Axis helpers: assign axis ids and positions (alternate starting on RIGHT) ---
function getAxisId(index) {
  return index === 0 ? 'y' : 'y' + index;
}

function getAxisPosition(index) {
  // index 0 -> right, index 1 -> left, index 2 -> right, etc.
  return (index % 2 === 0) ? 'right' : 'left';
}

function normalizeAxes() {
  if (!state.chart) return;

  const existingX = state.chart.options?.scales?.x || { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } };
  const scales = { x: existingX };

  // Determine first visible axis for grid drawing (only one axis should draw the grid area)
  let firstVisibleFound = false;

  state.chart.data.datasets.forEach((ds, i) => {
    const axisId = getAxisId(i);
    // prefer an assigned side if present; otherwise fall back to alternating by index
    const pos = ds.assignedSide || getAxisPosition(i);
    const axisColor = ds.axisColor || '#94a3b8';
    const titleText = ds.axisTitle || ds.label || '';

    // default grid drawOnChartArea only for the first visible axis we encounter
    const drawOnChartArea = !firstVisibleFound;
    if (!firstVisibleFound && !ds.hidden) firstVisibleFound = true;

    // ensure dataset points at this axis
    ds.yAxisID = axisId;
    scales[axisId] = {
      type: 'linear',
      display: !ds.hidden,
      position: pos,
      grid: { color: 'rgba(255,255,255,0.05)', drawOnChartArea: drawOnChartArea },
      ticks: { color: axisColor },
      title: { display: !ds.hidden, text: titleText, color: axisColor }
    };
  });

  state.chart.options.scales = scales;
}

function countVisibleSides() {
  let right = 0, left = 0;
  state.chart.data.datasets.forEach((d, i) => {
    if (d.hidden) return;
    const side = d.assignedSide || getAxisPosition(i);
    if (side === 'right') right++; else left++;
  });
  return { right, left };
}

function rebalanceAssignedSides() {
  if (!state.chart) return;

  // Use explicit visibleOrder queue when available
  if (state.visibleOrder && state.visibleOrder.length > 0) {
    // assign sides based on queue order (index 0 -> right, 1 -> left, ...)
    state.visibleOrder.forEach((datasetIndex, queueIdx) => {
      const ds = state.chart.data.datasets[datasetIndex];
      if (ds) ds.assignedSide = (queueIdx % 2 === 0) ? 'right' : 'left';
    });
    return;
  }

  // Fallback: derive from current visible datasets
  const visible = state.chart.data.datasets
    .map((d, i) => ({ d, i }))
    .filter(x => !x.d.hidden);

  // If nothing visible, nothing to do
  if (visible.length === 0) return;

  // Assign sides alternating starting on RIGHT so first visible becomes RIGHT
  visible.forEach((v, idx) => {
    v.d.assignedSide = (idx % 2 === 0) ? 'right' : 'left';
  });
}

function setAxisDisplayByDatasetIndex(index, visible) {
  if (!state.chart) return;

  const ds = state.chart.data.datasets[index];
  if (!ds) return;

  // If making visible, append to visibleOrder queue (don't overwrite existing entries)
  if (visible) {
    if (!state.visibleOrder.includes(index)) state.visibleOrder.push(index);
    ds.hidden = false;
  } else {
    // When hiding, remove from visibleOrder and clear assignedSide
    state.visibleOrder = state.visibleOrder.filter(i => i !== index);
    ds.hidden = true;
    delete ds.assignedSide;
  }

  // After changes, rebalance based on the visibleOrder queue
  rebalanceAssignedSides();

  // Update axes based on datasets and visibility
  normalizeAxes();
  state.chart.update('none');
}

function updateChart(history, timescale = '1h') {
  if (!state.chart || !history) return;

  state.historyData = history;
  state.lastTimescale = timescale;

  // Sort history by time (ascending) for the chart
  const sorted = [...history].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  // Update dataset label and axis title meta (axes rebuilt by normalizeAxes)
  if (state.chart && state.chart.data && state.chart.data.datasets[1]) {
    state.chart.data.datasets[1].label = `Temp (${unitLabel})`;
    state.chart.data.datasets[1].axisTitle = `Temp (${unitLabel})`;
  }

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
  normalizeAxes();
  state.chart.update('none'); // Update without animation for performance
}

function toggleHumidity() {
  const chk = document.getElementById('showHumidity');
  if (!chk || !state.chart) return;
  setAxisDisplayByDatasetIndex(0, chk.checked);
  localStorage.setItem('showHumidity', chk.checked);
  addLogEntry(`${chk.checked ? 'Showing' : 'Hiding'} humidity on chart`);
}

function toggleTemperature() {
  const chk = document.getElementById('showTemperature');
  if (!chk || !state.chart) return;
  setAxisDisplayByDatasetIndex(1, chk.checked);
  localStorage.setItem('showTemperature', chk.checked);
  addLogEntry(`${chk.checked ? 'Showing' : 'Hiding'} temperature on chart`);
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

  const chartError = document.getElementById('chartError');
  if (chartError) chartError.style.display = connected ? 'none' : 'flex';
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
    const fetchOptions = {
      method: 'GET',
      mode: 'cors',
      cache: 'no-store'
    };

    if (apiKey) {
      // Send the function key as a query parameter to avoid CORS preflight
      params.append('code', apiKey);
    }
    
    // Fetch latest for the top cards
    const latestResponse = await fetch(`${baseUrl}/sensor-data?${params.toString()}`, fetchOptions);
    
    // Fetch history for the graph
    const historyParams = new URLSearchParams(params);
    historyParams.append('history', 'true');
    historyParams.append('timescale', timescale);
    const historyResponse = await fetch(`${baseUrl}/sensor-data?${historyParams.toString()}`, fetchOptions);

    if (latestResponse.status === 401) {
      showAlert('Unauthorized: Function key missing or invalid.', 'error');
      addLogEntry('Unauthorized (401) from API');
      return;
    }

    if (latestResponse.status === 403) {
      showAlert('Forbidden: Access denied. Check CORS or API Gateway settings.', 'error');
      addLogEntry('Forbidden (403) from API - check origins');
      return;
    }

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
  ['moisture', 'temperature', 'humidity', 'ph', 'light', 'lastUpdated', 'commandStatus', 'deviceStatus', 'deviceType', 'deviceLastSeen'].forEach((id) => {
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
  updateValueIfIdExists('deviceStatus', device.status ?? 'online');
  updateValueIfIdExists('deviceType', device.type ?? 'soil_sensor');
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

function sendOverrideDirection(direction) {
  if (window.override && typeof window.override.sendOverrideDirection === 'function') {
    return window.override.sendOverrideDirection(direction);
  }
  console.warn('sendOverrideDirection: module not loaded');
}

function setupOverrideControls() {
  if (window.override && typeof window.override.setupOverrideControls === 'function') {
    return window.override.setupOverrideControls();
  }
  console.warn('setupOverrideControls: module not loaded');
}

// --- Robot map & position tracking ---
function initRobotMap() {
  if (window.robot && typeof window.robot.initRobotMap === 'function') return window.robot.initRobotMap();
  console.warn('initRobotMap: module not loaded');
}

function renderRobotMap() {
  if (window.robot && typeof window.robot.renderRobotMap === 'function') return window.robot.renderRobotMap();
  console.warn('renderRobotMap: module not loaded');
}

function robotMove(step) {
  if (window.robot && typeof window.robot.robotMove === 'function') return window.robot.robotMove(step);
  console.warn('robotMove: module not loaded');
}

function robotRotate(delta) {
  if (window.robot && typeof window.robot.robotRotate === 'function') return window.robot.robotRotate(delta);
  console.warn('robotRotate: module not loaded');
}

function getFacingLabel() {
  if (window.robot && typeof window.robot.getFacingLabel === 'function') return window.robot.getFacingLabel();
  const angle = state.robot?.angle || 0;
  if (angle >= 315 || angle < 45) return 'N';
  if (angle >= 45 && angle < 135) return 'E';
  if (angle >= 135 && angle < 225) return 'S';
  return 'W';
}

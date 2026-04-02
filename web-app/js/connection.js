import { state } from './state.js';
import { showAlert, addLogEntry, setLoading, updateSensorDisplay, updateDeviceInfo } from './ui.js';
import { updateChart, initChart } from './chart.js';

const PROD_API_URL = 'https://soilrobot-apim-dev.azure-api.net/api';
const LOCAL_API_URL = 'http://localhost:7071/api';
const ALL_TIMESCALES = ['1h', '1d', '1m', '1y', 'all'];

export function getApiBaseUrl() { return state.useProd ? PROD_API_URL : LOCAL_API_URL; }

async function fetchHistoryByTimescale(baseUrl, params, fetchOptions, timescale) {
  const historyParams = new URLSearchParams(params);
  historyParams.append('history', 'true');
  historyParams.append('timescale', timescale);
  const response = await fetch(`${baseUrl}/sensor-data?${historyParams.toString()}`, fetchOptions);
  if (!response.ok) throw new Error(`History fetch failed for ${timescale}`);
  const body = await response.json();
  const rows = Array.isArray(body?.history) ? body.history : [];
  state.historyCache[timescale] = rows;
  return rows;
}

async function ensureAllTimescalesCached(baseUrl, params, fetchOptions, selectedTimescale) {
  const missingTimescales = ALL_TIMESCALES.filter((ts) => {
    if (ts === selectedTimescale) return false;
    const cached = state.historyCache?.[ts];
    return !(Array.isArray(cached) && cached.length > 0);
  });

  if (missingTimescales.length === 0) return;

  try {
    await Promise.all(missingTimescales.map((ts) => fetchHistoryByTimescale(baseUrl, params, fetchOptions, ts)));
    addLogEntry(`Cached chart ranges: ${missingTimescales.join(', ')}`);
  } catch (error) {
    console.warn('Background cache prefetch failed', error);
    addLogEntry('Some chart ranges could not be cached yet');
  }
}

export async function refreshData(showLoading = false) {
  if (!state.isConnected) { showAlert('Activate monitoring to refresh', 'error'); return; }
  
  // Only show loading if forced (manual refresh) OR if we have no data yet (initial connect)
  const shouldShowLive = showLoading || !state.latestData;
  const shouldShowTrends = showLoading || !state.historyData;
  const timescale = document.getElementById('timeScale')?.value || '1h';
  const isAllTime = timescale === 'all';

  if (shouldShowLive) setLoading('liveSensorsCard', true);
  if (shouldShowTrends) setLoading('trendsCard', true);
  if (isAllTime && (showLoading || !state.historyData)) {
    const chartContainer = document.querySelector('[style*="height: 300px"]');
    if (chartContainer) {
      chartContainer.style.position = 'relative';
      let loader = chartContainer.querySelector('.chart-loading-overlay');
      if (!loader) {
        loader = document.createElement('div');
        loader.className = 'chart-loading-overlay';
        loader.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(5,7,15,0.7);display:flex;align-items:center;justify-content:center;z-index:10;border-radius:6px;';
        loader.innerHTML = '<div style="text-align:center;"><div style="font-size:14px;color:#cbd5f5;margin-bottom:12px;">Loading historical data...</div><div style="width:30px;height:30px;border:3px solid rgba(99,102,241,0.3);border-top:3px solid #6366f1;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto;"></div></div>';
        chartContainer.appendChild(loader);
      }
      loader.style.display = 'flex';
    }
  }

  try {
    const baseUrl = getApiBaseUrl();
    const timescale = document.getElementById('timeScale')?.value || '1h';
    const params = new URLSearchParams();
    if (state.deviceIp) params.append('deviceIp', state.deviceIp);
    const apiKey = localStorage.getItem('functionKey');
    const fetchOptions = { method: 'GET', mode: 'cors', cache: 'no-store' };
    if (apiKey) params.append('code', apiKey);

    // Fetch latest telemetry plus currently selected chart range.
    const latestPromise = fetch(`${baseUrl}/sensor-data?${params.toString()}`, fetchOptions);
    const selectedHistoryPromise = fetchHistoryByTimescale(baseUrl, params, fetchOptions, timescale);

    const [latestResponse, selectedHistoryRows] = await Promise.all([
      latestPromise,
      selectedHistoryPromise
    ]);

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
    updateChart(selectedHistoryRows, timescale);

    // Warm remaining ranges in background so all timeframe switches work offline.
    ensureAllTimescalesCached(baseUrl, params, fetchOptions, timescale);
    const scaleLabel = document.querySelector(`#timeScale option[value="${timescale}"]`)?.textContent || timescale;
    addLogEntry(`Synced data for ${scaleLabel}`);
  } catch (error) { 
    console.error('Refresh error', error); 
    showAlert('Unable to reach the API', 'error'); 
    addLogEntry('Refresh failed'); 
  } finally {
    if (shouldShowLive) setLoading('liveSensorsCard', false);
    if (shouldShowTrends) setLoading('trendsCard', false);
    // Hide chart loading overlay
    const loader = document.querySelector('.chart-loading-overlay');
    if (loader) loader.style.display = 'none';
  }
}

export async function checkApiHealth() {
  const baseUrl = getApiBaseUrl();
  const statusEl = document.getElementById('healthStatus');

  try {
    const response = await fetch(`${baseUrl}/health`, { method: 'GET', mode: 'cors', cache: 'no-store' });
    const text = await response.text();
    const message = `API health: ${response.status} ${response.statusText} (${text || 'no body'})`;

    if (statusEl) statusEl.textContent = message;
    if (response.ok) {
      showAlert(`API health check passed (${baseUrl})`, 'success');
      addLogEntry(message);
      return true;
    }

    showAlert(`API health check failed: ${response.status} (${baseUrl})`, 'error');
    addLogEntry(message);
    return false;
  } catch (error) {
    const msg = `API health check error: ${error?.message ?? error}`;
    if (statusEl) statusEl.textContent = msg;
    showAlert('Unable to reach API health endpoint', 'error');
    addLogEntry(msg);
    console.error(msg);
    return false;
  }
}

export function startAutoRefresh() { stopAutoRefresh(); refreshData(); const seconds = 30; state.refreshIntervalId = setInterval(refreshData, seconds * 1000); addLogEntry(`Auto-refresh active (30s)`); }
export function stopAutoRefresh() { if (state.refreshIntervalId) { clearInterval(state.refreshIntervalId); state.refreshIntervalId = null; addLogEntry('Auto-refresh paused'); } }

export function toggleConnection() { if (state.isConnected) disconnect(); else connect(); }

function hasCachedChartData() {
  const selectedTimescale = document.getElementById('timeScale')?.value || state.lastTimescale || '1h';
  const selectedCache = state.historyCache?.[selectedTimescale];
  if (Array.isArray(selectedCache) && selectedCache.length > 0) {
    const hasTimestampedRows = selectedCache.some((r) => r && r.timestamp);
    if (hasTimestampedRows) return true;
  }

  if (Array.isArray(state.historyData) && state.historyData.length > 0) {
    const hasTimestampedRows = state.historyData.some((r) => r && r.timestamp);
    if (hasTimestampedRows) return true;
  }

  const datasets = state.chart?.data?.datasets;
  if (!Array.isArray(datasets) || datasets.length === 0) return false;

  return datasets.some((ds) => Array.isArray(ds.data) && ds.data.some((p) => {
    if (!p || typeof p.x !== 'number') return false;
    if (p.y === null || p.y === undefined) return false;
    return !Number.isNaN(Number(p.y));
  }));
}

export async function connect() {
  console.log('Connecting...');
  const isFilterEnabled = !!document.getElementById('filterIpToggle')?.checked;
  const ipInput = document.getElementById('deviceIp')?.value.trim() || '';

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

  // Force overlay removal immediately
  updateConnectionStatus(true); 
  showAlert('Dashboard active', 'success'); 
  
  // Start data sync
  startAutoRefresh();
}

export function disconnect() { 
  state.isConnected = false; 
  stopAutoRefresh(); 
  updateConnectionStatus(false); 
  showAlert('Monitoring paused','error'); 
  addLogEntry('Connection closed'); 
  resetSensorDisplay(); 
}

export function updateConnectionStatus(connected) {
  console.log('Updating connection status UI:', connected);
  const indicator = document.getElementById('statusIndicator'); 
  const button = document.getElementById('connectBtn');
  if (indicator) { 
    indicator.classList.toggle('connected', connected); 
    indicator.classList.toggle('disconnected', !connected); 
  }
  if (button) button.textContent = connected ? 'Disconnect' : 'Connect';
  
  const chartError = document.getElementById('chartError'); 
  if (chartError) {
    const shouldShowOverlay = !connected && !hasCachedChartData();
    chartError.style.display = shouldShowOverlay ? 'flex' : 'none';
  }

  const cachedDataNote = document.getElementById('cachedDataNote');
  if (cachedDataNote) {
    cachedDataNote.style.display = connected ? 'none' : 'block';
  }
}

export function resetSensorDisplay() {
  ['moisture','temperature','humidity','ph','light','lastUpdated','commandStatus','deviceStatus','deviceType','deviceLastSeen'].forEach((id) => {
    const el = document.getElementById(id); 
    if (el) el.textContent = '--';
  });
}

export function updateActiveIp() { if (state.isConnected) state.deviceIp = document.getElementById('deviceIp').value.trim(); }
export function updateActiveKey() { 
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

export function toggleIpFilter() { 
  const isEnabled = document.getElementById('filterIpToggle').checked; 
  const container = document.getElementById('ipInputContainer'); 
  if (container) container.style.display = isEnabled ? 'block' : 'none'; 
  if (!isEnabled) { 
    document.getElementById('deviceIp').value = ''; 
    state.deviceIp = ''; 
    if (state.isConnected) { 
      addLogEntry('Switching to global telemetry'); 
      refreshData(); 
    } 
  } 
}

export function toggleTempUnit() { 
  state.tempUnit = document.getElementById('tempUnitToggle').checked ? 'F' : 'C'; 
  localStorage.setItem('tempUnit', state.tempUnit); 
  addLogEntry(`Units changed to °${state.tempUnit}`); 
  const tempValueEl = document.getElementById('temperature'); 
  if (tempValueEl && tempValueEl.nextElementSibling) tempValueEl.nextElementSibling.textContent = state.tempUnit === 'F' ? '°F' : '°C'; 
  if (state.latestData) updateSensorDisplay(state.latestData); 
  const selectedTimescale = document.getElementById('timeScale')?.value || state.lastTimescale || '1h';
  const cached = state.historyCache?.[selectedTimescale];
  if (Array.isArray(cached) && cached.length > 0) {
    updateChart(cached, selectedTimescale);
  } else if (state.historyData) {
    updateChart(state.historyData, state.lastTimescale);
  }
}

export function toggleApiSource() { 
  state.useProd = document.getElementById('apiSourceToggle').checked; 
  localStorage.setItem('useProd', state.useProd); 
  addLogEntry(`Switched to ${state.useProd ? 'Production' : 'Local'} API`); 
  if (state.isConnected) refreshData(); 
}

// Expose functions for legacy callers
window.refreshData = refreshData; 
window.toggleConnection = toggleConnection; 
window.updateActiveIp = updateActiveIp; 
window.updateActiveKey = updateActiveKey; 
window.toggleIpFilter = toggleIpFilter; 
window.toggleTempUnit = toggleTempUnit; 
window.toggleApiSource = toggleApiSource; 
window.initChart = initChart;
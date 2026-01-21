import { state } from './state.js';
import { showAlert, addLogEntry, setLoading, updateSensorDisplay, updateDeviceInfo } from './ui.js';
import { updateChart, initChart } from './chart.js';

const PROD_API_URL = 'https://soilrobot-apim-dev.azure-api.net/api';
const LOCAL_API_URL = 'http://localhost:7071/api';

export function getApiBaseUrl() { return state.useProd ? PROD_API_URL : LOCAL_API_URL; }

export async function refreshData(showLoading = false) {
  if (!state.isConnected) { showAlert('Activate monitoring to refresh', 'error'); return; }
  
  // Only show loading if forced (manual refresh) OR if we have no data yet (initial connect)
  const shouldShowLive = showLoading || !state.latestData;
  const shouldShowTrends = showLoading || !state.historyData;

  if (shouldShowLive) setLoading('liveSensorsCard', true);
  if (shouldShowTrends) setLoading('trendsCard', true);

  try {
    const baseUrl = getApiBaseUrl();
    const timescale = document.getElementById('timeScale')?.value || '1h';
    const params = new URLSearchParams();
    if (state.deviceIp) params.append('deviceIp', state.deviceIp);
    const apiKey = localStorage.getItem('functionKey');
    const fetchOptions = { method: 'GET', mode: 'cors', cache: 'no-store' };
    if (apiKey) params.append('code', apiKey);

    // Fetch both in parallel to save time
    const historyParams = new URLSearchParams(params);
    historyParams.append('history', 'true');
    historyParams.append('timescale', timescale);

    const [latestResponse, historyResponse] = await Promise.all([
      fetch(`${baseUrl}/sensor-data?${params.toString()}`, fetchOptions),
      fetch(`${baseUrl}/sensor-data?${historyParams.toString()}`, fetchOptions)
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
  } finally {
    if (shouldShowLive) setLoading('liveSensorsCard', false);
    if (shouldShowTrends) setLoading('trendsCard', false);
  }
}

export function startAutoRefresh() { stopAutoRefresh(); refreshData(); const seconds = 30; state.refreshIntervalId = setInterval(refreshData, seconds * 1000); addLogEntry(`Auto-refresh active (30s)`); }
export function stopAutoRefresh() { if (state.refreshIntervalId) { clearInterval(state.refreshIntervalId); state.refreshIntervalId = null; addLogEntry('Auto-refresh paused'); } }

export function toggleConnection() { if (state.isConnected) disconnect(); else connect(); }

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
    chartError.style.display = connected ? 'none' : 'flex';
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
  if (state.historyData) updateChart(state.historyData, state.lastTimescale); 
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
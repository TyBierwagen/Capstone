import { state } from './state.js';
import { showAlert, addLogEntry, setLoading, updateSensorDisplay, updateDeviceInfo } from './ui.js';
import { updateChart, initChart } from './chart.js';

const PROD_API_URL = 'https://soilrobot-apim-dev.azure-api.net/api';
const LOCAL_API_URL = 'http://localhost:7071/api';
const ALL_TIMESCALES = ['1h', '1d', '1m', '1y', 'all'];
const PREFETCH_TIMESCALES = {
  '1h': ['1d'],
  '1d': ['1h'],
  '1m': ['1d'],
  '1y': [],
  'all': []
};

function setChartLoadingOverlay(visible) {
  const chartContainer = document.querySelector('[style*="height: 300px"]');
  if (!chartContainer) return;
  chartContainer.style.position = 'relative';
  let loader = chartContainer.querySelector('.chart-loading-overlay');
  if (!loader) {
    loader = document.createElement('div');
    loader.className = 'chart-loading-overlay';
    loader.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(5,7,15,0.7);display:flex;align-items:center;justify-content:center;z-index:10;border-radius:6px;';
    loader.innerHTML = '<div style="text-align:center;"><div style="font-size:14px;color:#cbd5f5;margin-bottom:12px;">Loading historical data...</div><div style="width:30px;height:30px;border:3px solid rgba(99,102,241,0.3);border-top:3px solid #6366f1;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto;"></div></div>';
    chartContainer.appendChild(loader);
  }
  loader.style.display = visible ? 'flex' : 'none';
}

export function getApiBaseUrl() { return state.useProd ? PROD_API_URL : LOCAL_API_URL; }

async function fetchHistoryByTimescale(baseUrl, params, fetchOptions, timescale, rawHistory = false) {
  const historyParams = new URLSearchParams(params);
  historyParams.append('history', 'true');
  historyParams.append('timescale', timescale);
  if (rawHistory) historyParams.append('raw', 'true');
  const base = getApiBaseUrl();
  const response = await fetch(`${base.replace(/\/$/, '')}/sensor-data?${historyParams.toString()}`, fetchOptions);
  if (!response.ok) throw new Error(`History fetch failed for ${timescale}`);
  const body = await response.json();
  const rows = Array.isArray(body?.history) ? body.history : [];
  try {
    const humCount = rows.filter(r => r && r.humidity !== null && r.humidity !== undefined).length;
    const tempCount = rows.filter(r => r && r.temperature !== null && r.temperature !== undefined && r.temperature !== '').length;
    const battCount = rows.filter(r => r && r.battery !== null && r.battery !== undefined && r.battery !== '').length;
    console.debug(`Fetched ${rows.length} rows for timescale=${timescale} (hum:${humCount}, temp:${tempCount}, batt:${battCount})`, rows.slice(0,5));
    addLogEntry(`Fetched ${rows.length} rows for ${timescale} (hum:${humCount}, temp:${tempCount}, batt:${battCount})`);
    if (battCount === 0) addLogEntry('Warning: No battery values returned for this timescale');
  } catch (e) { console.debug('history diagnostics failed', e); }
  state.historyCache[timescale] = rows;
  // If battery values are missing for aggregated timescales, attempt a raw-range fallback
  try {
    if (rawHistory) return rows;
    const battCount = rows.filter(r => r && r.battery !== null && r.battery !== undefined && r.battery !== '').length;
    const aggregatedTimes = ['1d','1m','1y','all'];
    const allowRawFallback = timescale === '1d' || timescale === '1h';
    if (battCount === 0 && aggregatedTimes.includes(timescale) && allowRawFallback && rows.length > 0) {
      try {
        addLogEntry(`No battery in aggregated ${timescale} — fetching raw range fallback`);
        // Compute approximate start for the timescale
        const now = new Date();
        let start = new Date(now);
        if (timescale === '1d') start.setDate(now.getDate() - 1);
        else if (timescale === '1m') start.setMonth(now.getMonth() - 1);
        else if (timescale === '1y') start.setFullYear(now.getFullYear() - 1);
        else if (timescale === 'all') start = new Date(0);

        const rawParams = new URLSearchParams(params);
        rawParams.append('history','true');
        rawParams.append('timescale','all');
        rawParams.append('raw','true');
        rawParams.append('start', start.toISOString());
        rawParams.append('end', now.toISOString());

        const base = getApiBaseUrl();
        const resp = await fetch(`${base.replace(/\/$/, '')}/sensor-data?${rawParams.toString()}`, fetchOptions);
        if (resp.ok) {
          const rawBody = await resp.json();
          const rawRows = Array.isArray(rawBody?.history) ? rawBody.history : [];
          const rawBatt = rawRows.filter(r => r && r.battery !== null && r.battery !== undefined && r.battery !== '').length;
          console.debug(`Raw fallback returned ${rawRows.length} rows (batt:${rawBatt})`);
          if (rawRows.length > 0 && rawBatt > 0) {
            state.historyCache[timescale] = rawRows;
            return rawRows;
          }
        } else {
          console.debug('Raw fallback fetch failed', resp.status);
        }
      } catch (fbErr) {
        console.debug('raw fallback error', fbErr);
      }
    }
  } catch (e) { console.debug('post-fetch fallback check failed', e); }

  return rows;
}

async function ensureAllTimescalesCached(baseUrl, params, fetchOptions, selectedTimescale, rawHistory = false) {
  if (rawHistory) return;
  const prefetchTargets = PREFETCH_TIMESCALES[selectedTimescale] || [];
  const missingTimescales = prefetchTargets.filter((ts) => {
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

export async function fetchCustomDateRange(startDate, endDate) {
  if (!state.isConnected) { 
    showAlert('Connect to sensor database to fetch custom date range', 'error'); 
    return null; 
  }

  try {
    const baseUrl = getApiBaseUrl();
    const params = new URLSearchParams();
    // If no explicit device filter, resolve the latest active device first
    if (state.deviceIp) {
      params.append('deviceIp', state.deviceIp);
    } else {
      try {
        const apiKey = localStorage.getItem('functionKey');
        const fetchOptions = { method: 'GET', mode: 'cors', cache: 'no-store' };
        const latestResp = await fetch(`${baseUrl.replace(/\/$/, '')}/sensor-data${apiKey ? `?code=${apiKey}` : ''}`, fetchOptions);
        if (latestResp.ok) {
          const latest = await latestResp.json();
          const resolved = latest?.deviceIp || latest?.device?.deviceIp;
          if (resolved) params.append('deviceIp', resolved);
        }
      } catch (e) {
        console.debug('Failed to resolve latest device for custom range', e);
      }
    }
    const apiKey = localStorage.getItem('functionKey');
    const fetchOptions = { method: 'GET', mode: 'cors', cache: 'no-store' };
    if (apiKey) params.append('code', apiKey);

    // Fetch raw data for custom date range from API
    setLoading('trendsCard', true);
    setChartLoadingOverlay(true);
    params.append('history', 'true');
    params.append('timescale', 'all');
    params.append('raw', 'true'); // Request unaggregated data
    params.append('start', startDate.toISOString()); // ISO format with Z
    params.append('end', endDate.toISOString());
    
    const base = getApiBaseUrl();
    const response = await fetch(`${base.replace(/\/$/, '')}/sensor-data?${params.toString()}`, fetchOptions);
    if (!response.ok) throw new Error(`Fetch failed with status ${response.status}`);
    
    const body = await response.json();
    const filteredData = Array.isArray(body?.history) ? body.history : [];

    console.debug(`Custom range fetch: received ${filteredData.length} raw rows from API`);
    console.debug(`Date range: ${startDate.toLocaleString()} to ${endDate.toLocaleString()}`);
    
    if (filteredData.length > 0) {
      console.debug(`First point: ${filteredData[0].timestamp}`, new Date(filteredData[0].timestamp).toLocaleString());
      console.debug(`Last point: ${filteredData[filteredData.length - 1].timestamp}`, new Date(filteredData[filteredData.length - 1].timestamp).toLocaleString());
    }

    if (filteredData.length === 0) {
      showAlert('No data found in the selected time range', 'warning');
      addLogEntry(`No data points found between ${startDate.toLocaleString()} and ${endDate.toLocaleString()}`);
      return null;
    }

    // Store custom date range in state
    state.customDateRange = { start: startDate, end: endDate };
    updateChart(filteredData, 'custom');
    const startStr = startDate.toLocaleString();
    const endStr = endDate.toLocaleString();
    addLogEntry(`Fetched ${filteredData.length} raw data points for ${startStr} to ${endStr}`);
    return filteredData;
  } catch (error) {
    console.error('Custom date range fetch failed', error);
    showAlert(`Failed to fetch custom date range: ${error.message}`, 'error');
    addLogEntry('Custom date range fetch failed');
    return null;
  } finally {
    setLoading('trendsCard', false);
    setChartLoadingOverlay(false);
  }
}

export async function refreshData(showLoading = false) {
  if (!state.isConnected) { showAlert('Activate monitoring to refresh', 'error'); return; }
  if (state.refreshInProgress) {
    console.debug('Refresh already in progress; skipping overlapping request');
    return;
  }
  state.refreshInProgress = true;
  
  // Only show loading if forced (manual refresh) OR if we have no data yet (initial connect)
  const shouldShowLive = showLoading || !state.latestData;
  const shouldShowTrends = showLoading || !state.historyData;
  let timescale = document.getElementById('timeScale')?.value || '1h';
  // If in custom mode, fetch full data and filter client-side
  const inCustomMode = timescale === 'custom';
  if (inCustomMode) timescale = 'all';
  const isAllTime = timescale === 'all';

  if (shouldShowLive) setLoading('liveSensorsCard', true);
  if (shouldShowTrends) setLoading('trendsCard', true);
  if (isAllTime && (showLoading || !state.historyData)) {
    setChartLoadingOverlay(true);
  }
  if (inCustomMode && state.customDateRange) {
    setChartLoadingOverlay(true);
  }

  try {
    const baseUrl = getApiBaseUrl();
    const selectedTimescale = document.getElementById('timeScale')?.value || '1h';
    const rawHistoryRequested = !!document.getElementById('rawHistoryToggle')?.checked;
    const isInitialHistoryLoad = !Array.isArray(state.historyData) || state.historyData.length === 0;
    const shouldRefreshHistory = showLoading || isInitialHistoryLoad || selectedTimescale === '1h';
    const params = new URLSearchParams();
    if (state.deviceIp) params.append('deviceIp', state.deviceIp);
    const apiKey = localStorage.getItem('functionKey');
    const fetchOptions = { method: 'GET', mode: 'cors', cache: 'no-store' };
    if (apiKey) params.append('code', apiKey);

    // Fetch latest telemetry first so unfiltered history requests can target a concrete device partition.
    const base = getApiBaseUrl();
    const latestResponse = await fetch(`${base.replace(/\/$/, '')}/sensor-data?${params.toString()}`, fetchOptions);
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
    if (shouldShowLive) setLoading('liveSensorsCard', false);

    const effectiveDeviceIp = state.deviceIp || latestData?.deviceIp || state.latestData?.deviceIp;
    const historyParams = new URLSearchParams();
    if (effectiveDeviceIp) historyParams.append('deviceIp', effectiveDeviceIp);
    if (apiKey) historyParams.append('code', apiKey);

    let selectedHistoryPromise;
    let historyFetchError = null;
    if (inCustomMode && state.customDateRange && (showLoading || isInitialHistoryLoad)) {
      const customParams = new URLSearchParams(historyParams);
      customParams.append('history', 'true');
      customParams.append('timescale', 'all');
      customParams.append('raw', 'true');
      customParams.append('start', state.customDateRange.start.toISOString());
      customParams.append('end', state.customDateRange.end.toISOString());
      selectedHistoryPromise = fetch(`${base.replace(/\/$/, '')}/sensor-data?${customParams.toString()}`, fetchOptions)
        .then(async (res) => {
          if (!res.ok) throw new Error(`History fetch failed for custom range (${res.status})`);
          const body = await res.json();
          return Array.isArray(body?.history) ? body.history : [];
        })
        .catch((error) => {
          historyFetchError = error;
          return [];
        });
    } else if (shouldRefreshHistory) {
      selectedHistoryPromise = fetchHistoryByTimescale(baseUrl, historyParams, fetchOptions, selectedTimescale, rawHistoryRequested)
        .catch((error) => {
          historyFetchError = error;
          return [];
        });
    } else {
      selectedHistoryPromise = Promise.resolve(null);
    }
    
    let chartData = [];
    let chartTimescale = selectedTimescale;

    const selectedHistoryRows = await selectedHistoryPromise;
    if (Array.isArray(selectedHistoryRows)) {
      chartData = selectedHistoryRows;
      if (historyFetchError) {
        console.warn('History fetch failed', historyFetchError);
        addLogEntry('Chart history is still loading or unavailable');
      } else if (inCustomMode && state.customDateRange) {
        // Already server-filtered and raw when in custom mode.
        chartTimescale = 'custom';
        addLogEntry(`Updated chart with ${chartData.length} points in custom range`);
      }
      updateChart(chartData, chartTimescale);
    }

    // Warm remaining ranges in background so all timeframe switches work offline.
    if (shouldRefreshHistory && !inCustomMode) {
      ensureAllTimescalesCached(baseUrl, historyParams, fetchOptions, selectedTimescale, rawHistoryRequested);
    }
    const displayTimescale = inCustomMode ? 'custom range' : timescale;
    const scaleLabel = document.querySelector(`#timeScale option[value="${document.getElementById('timeScale')?.value || '1h'}"]`)?.textContent || displayTimescale;
    addLogEntry(shouldRefreshHistory ? `Synced data for ${scaleLabel}` : 'Synced latest telemetry');
  } catch (error) { 
    console.error('Refresh error', error); 
    showAlert('Unable to reach the API', 'error'); 
    addLogEntry('Refresh failed'); 
  } finally {
    if (shouldShowLive) setLoading('liveSensorsCard', false);
    if (shouldShowTrends) setLoading('trendsCard', false);
    // Hide chart loading overlay
    setChartLoadingOverlay(false);
    state.refreshInProgress = false;
  }
}

export async function checkApiHealth() {
  const baseUrl = getApiBaseUrl();
  const statusEl = document.getElementById('healthStatus');

  try {
    const url = `${baseUrl.replace(/\/$/, '')}/health`;
    console.debug('Checking API health at', url);
    const response = await fetch(url, { method: 'GET', mode: 'cors', cache: 'no-store' });
    const text = await response.text();
    const message = `API health: ${response.status} ${response.statusText} (${text || 'no body'}) -- ${baseUrl}`;

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
  ['moisture','temperature','humidity','battery','ph','light','lastUpdated','commandStatus','deviceStatus','deviceType','deviceLastSeen'].forEach((id) => {
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
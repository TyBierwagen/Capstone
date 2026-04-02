import './robot.js';
import { setupOverrideControls } from './override.js';
import { state } from './state.js';
import { showAlert, addLogEntry, clearLog } from './ui.js';
import { initChart, toggleHumidity, toggleTemperature, updateChart, rebalanceAssignedSides, normalizeAxes, downloadCurrentTimeframeCsv } from './chart.js';
import { refreshData, toggleConnection, updateActiveIp, updateActiveKey, toggleIpFilter, toggleTempUnit, toggleApiSource, checkApiHealth, updateConnectionStatus, fetchCustomDateRange } from './connection.js';

// Wire UI controls and initialize modules
document.addEventListener('DOMContentLoaded', () => {
  // Restore simple persisted settings
  const savedIp = localStorage.getItem('deviceIp');
  if (savedIp) document.getElementById('deviceIp').value = savedIp;

  const savedKey = localStorage.getItem('functionKey');
  if (savedKey) { document.getElementById('functionKey').value = savedKey; updateActiveKey(); }

  const savedUnit = localStorage.getItem('tempUnit');
  if (savedUnit) { state.tempUnit = savedUnit; const toggle = document.getElementById('tempUnitToggle'); if (toggle) toggle.checked = savedUnit === 'F'; const tempUnitEl = document.querySelector('#temperature')?.nextElementSibling; if (tempUnitEl) tempUnitEl.textContent = savedUnit === 'F' ? '°F' : '°C'; }

  const savedUseProd = localStorage.getItem('useProd'); if (savedUseProd !== null) state.useProd = savedUseProd === 'true'; const apiToggle = document.getElementById('apiSourceToggle'); if (apiToggle) apiToggle.checked = state.useProd;

  // Chart init
  initChart();

  // Restore chart visibility
  const showHumiditySaved = localStorage.getItem('showHumidity'); const showTempSaved = localStorage.getItem('showTemperature'); const humidityCheckbox = document.getElementById('showHumidity'); const tempCheckbox = document.getElementById('showTemperature'); if (humidityCheckbox) humidityCheckbox.checked = (showHumiditySaved !== 'false'); if (tempCheckbox) tempCheckbox.checked = (showTempSaved !== 'false');
  if (state.chart) { state.visibleOrder = []; if (humidityCheckbox && humidityCheckbox.checked) state.visibleOrder.push(0); if (tempCheckbox && tempCheckbox.checked) state.visibleOrder.push(1); state.chart.data.datasets.forEach((d, i) => { d.hidden = !state.visibleOrder.includes(i); if (i === 1) { const unitLabel = state.tempUnit === 'F' ? '°F' : '°C'; d.axisTitle = `Temp (${unitLabel})`; } });
    rebalanceAssignedSides();
    normalizeAxes();
    state.chart.update('none');
  }

  // Wire UI elements
  const connectBtn = document.getElementById('connectBtn'); if (connectBtn) connectBtn.addEventListener('click', toggleConnection);
  const refreshBtn = document.getElementById('refreshNowBtn'); if (refreshBtn) refreshBtn.addEventListener('click', () => refreshData(true));
  const healthBtn = document.getElementById('healthCheckBtn'); if (healthBtn) healthBtn.addEventListener('click', () => checkApiHealth());
  const downloadBtn = document.getElementById('downloadTimeframeBtn'); if (downloadBtn) downloadBtn.addEventListener('click', () => {
    const result = downloadCurrentTimeframeCsv();
    if (!result?.ok) {
      showAlert(result?.message || 'Nothing to download yet.', 'error');
      return;
    }
    showAlert(`Downloaded ${result.rows} rows`, 'success');
  });
  const clearLogBtn = document.getElementById('clearLogBtn'); if (clearLogBtn) clearLogBtn.addEventListener('click', clearLog);

  // Helper to format date in local timezone for datetime-local input
  function formatDateTimeLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hour}:${min}`;
  }

  // Helper to parse datetime-local input as local time (not UTC)
  function parseDateTimeLocal(dateTimeLocalString) {
    // Format: "2026-04-02T05:13"
    const [datePart, timePart] = dateTimeLocalString.split('T');
    const [year, month, day] = datePart.split('-').map(Number);
    const [hour, minute] = timePart.split(':').map(Number);
    // Create date in local timezone
    return new Date(year, month - 1, day, hour, minute, 0, 0);
  }

  // time scale changes should always fetch fresh history immediately
  document.getElementById('timeScale')?.addEventListener('change', (e) => {
    const timescale = e.target.value;
    const customContainer = document.getElementById('customTimeRangeContainer');
    
    // Show custom date inputs if Custom Range is selected
    if (timescale === 'custom') {
      customContainer.style.display = 'grid';
      // Set default to past 24 hours (using local timezone)
      const now = new Date();
      const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      document.getElementById('customStartDate').value = formatDateTimeLocal(yesterday);
      document.getElementById('customEndDate').value = formatDateTimeLocal(now);
      return;
    } else {
      customContainer.style.display = 'none';
    }
    
    if (state.isConnected) {
      refreshData(true);
      return;
    }
    const cached = state.historyCache?.[timescale];
    if (Array.isArray(cached) && cached.length > 0) {
      updateChart(cached, timescale);
      return;
    }
    if (state.historyData) updateChart(state.historyData, timescale);
  });

  // Handle custom date range apply button
  document.getElementById('applyCustomRangeBtn')?.addEventListener('click', async () => {
    const startDateStr = document.getElementById('customStartDate').value;
    const endDateStr = document.getElementById('customEndDate').value;
    
    if (!startDateStr || !endDateStr) {
      showAlert('Please select both start and end dates', 'error');
      return;
    }
    
    const startDate = parseDateTimeLocal(startDateStr);
    const endDate = parseDateTimeLocal(endDateStr);
    
    if (startDate >= endDate) {
      showAlert('Start date must be before end date', 'error');
      return;
    }
    
    // Fetch data for custom date range from API
    await fetchCustomDateRange(startDate, endDate);
  });

  // toggles and inputs
  document.getElementById('apiSourceToggle')?.addEventListener('change', toggleApiSource);
  document.getElementById('filterIpToggle')?.addEventListener('change', toggleIpFilter);
  document.getElementById('tempUnitToggle')?.addEventListener('change', toggleTempUnit);
  document.getElementById('showHumidity')?.addEventListener('change', (e) => toggleHumidity(e.target.checked));
  document.getElementById('showTemperature')?.addEventListener('change', (e) => toggleTemperature(e.target.checked));

  document.getElementById('deviceIp')?.addEventListener('input', updateActiveIp);
  document.getElementById('functionKey')?.addEventListener('input', updateActiveKey);

  // Initialize override and robot modules
  if (window.override && typeof window.override.setupOverrideControls === 'function') window.override.setupOverrideControls();
  if (window.robot && typeof window.robot.initRobotMap === 'function') window.robot.initRobotMap();

  // Wire Reset Position and Trail Limit UI
  const resetBtn = document.getElementById('resetPositionBtn');
  if (resetBtn) resetBtn.addEventListener('click', () => { if (window.robot && typeof window.robot.resetRobot === 'function') window.robot.resetRobot(); });

  const trailInput = document.getElementById('trailLimitInput');
  if (trailInput) {
    // restore saved limit if present
    const savedLimit = localStorage.getItem('robotTrailLimit');
    if (savedLimit !== null) window.state.robotTrailLimit = Number(savedLimit) || window.state.robotTrailLimit;
    trailInput.value = window.state?.robotTrailLimit || 200;
    trailInput.addEventListener('change', (e) => {
      const v = Math.max(1, Number(e.target.value) || 1);
      if (window.robot && typeof window.robot.setTrailLimit === 'function') window.robot.setTrailLimit(v);
    });
  }

  // Keep chart controls disabled until connected.
  updateConnectionStatus(state.isConnected);

  addLogEntry('Dashboard ready');
});

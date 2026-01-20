import './robot.js';
import { setupOverrideControls } from './override.js';
import { state } from './state.js';
import { showAlert, addLogEntry, clearLog } from './ui.js';
import { initChart, toggleHumidity, toggleTemperature } from './chart.js';
import { refreshData, toggleConnection, updateActiveIp, updateActiveKey, toggleIpFilter, toggleTempUnit, toggleApiSource } from './connection.js';

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

  }

  // Wire UI elements
  const connectBtn = document.getElementById('connectBtn'); if (connectBtn) connectBtn.addEventListener('click', toggleConnection);
  const refreshBtn = document.getElementById('refreshNowBtn'); if (refreshBtn) refreshBtn.addEventListener('click', refreshData);
  const clearLogBtn = document.getElementById('clearLogBtn'); if (clearLogBtn) clearLogBtn.addEventListener('click', clearLog);

  // time scale changes refresh chart data
  document.getElementById('timeScale')?.addEventListener('change', () => refreshData());

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

  addLogEntry('Dashboard ready');
});

import { state } from './state.js';
import { addLogEntry } from './ui.js';

// Controls tick label format without touching Chart.js' scriptable option evaluation
let tickFormatMode = '1h';

// Remove date-fns guard — we don't rely on the adapter; use numeric linear axis instead

function getAxisId(index) { return index === 0 ? 'y' : 'y' + index; }
function getAxisPosition(index) { return (index % 2 === 0) ? 'right' : 'left'; }

function ensureDatasetAxisMeta() {
  if (!state.chart?.data?.datasets) return;
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  const defaults = [
    { axisColor: '#3b82f6', axisTitle: 'Humidity %', label: 'Humidity (%)' },
    { axisColor: '#f87171', axisTitle: `Temp (${unitLabel})`, label: `Temp (${unitLabel})` }
  ];
  state.chart.data.datasets.forEach((ds, i) => {
    const d = defaults[i] || { axisColor: '#94a3b8', axisTitle: String(ds.label || ''), label: String(ds.label || '') };
    if (!ds.axisColor) ds.axisColor = d.axisColor;
    if (!ds.axisTitle) ds.axisTitle = d.axisTitle;
    if (!ds.label) ds.label = d.label;
  });
}

function syncVisibleOrderFromDatasets() {
  if (!state.chart?.data?.datasets) return;
  const visible = state.chart.data.datasets
    .map((ds, i) => ({ ds, i }))
    .filter(x => !x.ds.hidden)
    .map(x => x.i);
  state.visibleOrder = visible;
}

// Defensive sanitizer for Chart.js options: coerce common string fields to strings
function sanitizeChartOptions(opts) {
  if (!opts || typeof opts !== 'object') return;
  const walk = (obj, path = []) => {
    if (!obj || typeof obj !== 'object') return;
    for (const [k, v] of Object.entries(obj)) {
      const curPath = path.concat(k).join('.');
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        walk(v, path.concat(k));
      } else {
        // Coerce typical fields that Chart.js expects as strings
        if (v !== null && typeof v !== 'function' && typeof v !== 'string') {
          const key = k.toLowerCase();
          if (key.includes('color') || key.includes('label') || key === 'text' || key === 'position' || key === 'type' || key === 'fontfamily') {
            try { obj[k] = String(v); console.warn('sanitizeChartOptions coerced', curPath, 'to string'); } catch (e) { /* ignore */ }
          }
        } else if ((v === null || v === undefined) && (k.toLowerCase().includes('text') || k === 'label' || k === 'title')) {
          // Replace null/undefined text/label fields with empty string
          try { obj[k] = ''; console.warn('sanitizeChartOptions coerced', curPath, 'null/undefined to empty string'); } catch (e) { /* ignore */ }
        }
      }
    }
  };
  try { walk(opts); } catch (e) { console.debug('sanitizeChartOptions failed', e); }
}

export function initChart() {

  const ctx = document.getElementById('sensorChart').getContext('2d');
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  state.chart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Humidity (%)', borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', data: [], tension: 0.3, axisTitle: 'Humidity %', axisColor: '#3b82f6', xAxisID: 'x', pointRadius: 2, spanGaps: false },
      { label: `Temp (${unitLabel})`, borderColor: '#f87171', data: [], tension: 0.3, axisTitle: `Temp (${unitLabel})`, axisColor: '#f87171', xAxisID: 'x', pointRadius: 2, spanGaps: false }
    ]},
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#cbd5f5' } } },
      scales: { x: { type: 'linear', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } } }
    }
  });
}

export function normalizeAxes() {
  if (!state.chart) return;
  ensureDatasetAxisMeta();
  syncVisibleOrderFromDatasets();
  // Always ensure fresh date formatter for X axis
  const dateFormatter = (value) => {
    if (typeof value !== 'number') return '';
    const d = new Date(value);
    if (isNaN(d.getTime())) return '';
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const year = d.getFullYear();
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    // Show date + time for shorter timescales, date only for longer ones
    if (state.lastTimescale === '1h' || state.lastTimescale === '24h') {
      return `${month}/${day} ${hour}:${min}`;
    }
    return `${month}/${day}/${year}`;
  };
  const scales = { x: { type: 'linear', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', callback: dateFormatter } } };
  let firstVisibleFound = false;
  state.chart.data.datasets.forEach((ds, i) => {
    const axisId = getAxisId(i);
    // Determine position based on visible order and current state
    let pos = 'right'; // default
    if (state.visibleOrder.length > 0) {
      const visibleIndex = state.visibleOrder.indexOf(i);
      if (visibleIndex >= 0) pos = (visibleIndex % 2 === 0) ? 'right' : 'left';
    } else if (!ds.hidden) {
      pos = getAxisPosition(i);
    }
    ds.assignedSide = pos;
    const axisColor = String(ds.axisColor || '#94a3b8');
    const titleText = String(ds.axisTitle || ds.label || '');
    const drawOnChartArea = !firstVisibleFound;
    if (!firstVisibleFound && !ds.hidden) firstVisibleFound = true;
    ds.yAxisID = axisId;
    scales[axisId] = { type: 'linear', display: !ds.hidden, position: pos, grid: { color: 'rgba(255,255,255,0.05)', drawOnChartArea: drawOnChartArea }, ticks: { color: axisColor }, title: { display: !ds.hidden, text: titleText, color: axisColor } };
  });
  state.chart.options.scales = scales;
}

export function rebalanceAssignedSides() {
  if (!state.chart) return;
  if (state.visibleOrder && state.visibleOrder.length > 0) {
    state.visibleOrder.forEach((datasetIndex, queueIdx) => {
      const ds = state.chart.data.datasets[datasetIndex]; if (ds) ds.assignedSide = (queueIdx % 2 === 0) ? 'right' : 'left';
    });
    return;
  }
  const visible = state.chart.data.datasets.map((d, i) => ({ d, i })).filter(x => !x.d.hidden);
  if (visible.length === 0) return;
  visible.forEach((v, idx) => { v.d.assignedSide = (idx % 2 === 0) ? 'right' : 'left'; });
}

export function setAxisDisplayByDatasetIndex(index, visible) {
  if (!state.chart) return;
  const ds = state.chart.data.datasets[index]; if (!ds) return;
  if (visible) { if (!state.visibleOrder.includes(index)) state.visibleOrder.push(index); ds.hidden = false; } else { state.visibleOrder = state.visibleOrder.filter(i => i !== index); ds.hidden = true; delete ds.assignedSide; }
  rebalanceAssignedSides(); normalizeAxes(); state.chart.update('none');
}

export function updateChart(history, timescale = '1h') {
  try {
  if (!state.chart || !history) return;
  state.historyData = history; state.lastTimescale = timescale; tickFormatMode = timescale;
  ensureDatasetAxisMeta();
  syncVisibleOrderFromDatasets();

  // Safety: apply a minimal safe options set before mutating scales/other options
  // Start with fresh options to avoid circular references from previous chart updates
  const dateFormatter = (value) => {
    if (typeof value !== 'number') return '';
    const d = new Date(value);
    if (isNaN(d.getTime())) return '';
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const year = d.getFullYear();
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    // Show date + time for shorter timescales, date only for longer ones
    if (timescale === '1h' || timescale === '24h') {
      return `${month}/${day} ${hour}:${min}`;
    }
    return `${month}/${day}/${year}`;
  };
  state.chart.options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#cbd5f5' } } },
    scales: { x: { type: 'linear', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', callback: dateFormatter } } }
  };
  const sorted = [...history].sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  if (state.chart && state.chart.data && state.chart.data.datasets[0]) {
    state.chart.data.datasets[0].label = String(state.chart.data.datasets[0].label || 'Humidity (%)');
    state.chart.data.datasets[0].axisTitle = 'Humidity %';
    state.chart.data.datasets[0].axisColor = '#3b82f6';
  }
  if (state.chart && state.chart.data && state.chart.data.datasets[1]) {
    state.chart.data.datasets[1].label = `Temp (${unitLabel})`;
    state.chart.data.datasets[1].axisTitle = `Temp (${unitLabel})`;
    state.chart.data.datasets[1].axisColor = '#f87171';
  }
  // Sanitize timestamps to handle variants like '+00:00Z' or '+00:00' that some browsers parse inconsistently
  const sanitizeTs = (ts) => {
    if (!ts) return null;
    let v = String(ts).trim();
    v = v.replace(/\+00:00Z$/, 'Z').replace(/\+00:00$/, 'Z');
    return v;
  };

  // Build point arrays using timestamps (ms) so X spacing is linear with time
  const pointsHum = [];
  const pointsTemp = [];
  sorted.forEach(h => {
    const raw = sanitizeTs(h.timestamp);
    const d = new Date(raw);
    if (isNaN(d.getTime())) return;
    const x = d.getTime();
    const hum = (h.humidity === null || h.humidity === undefined) ? null : Number(h.humidity);
    pointsHum.push({ x, y: hum });
    const tRaw = h.temperature;
    const tVal = (tRaw === null || tRaw === undefined || tRaw === '') ? null : Number(tRaw);
    const tFinal = (tVal === null) ? null : ((state.tempUnit === 'F') ? (tVal * 9/5) + 32 : tVal);
    pointsTemp.push({ x, y: tFinal });
  });

  state.chart.data.labels = [];
  state.chart.data.datasets[0].data = pointsHum;
  state.chart.data.datasets[1].data = pointsTemp;

  // Hide overlay if we have any valid points
  const humValid = pointsHum.some(p => p.y !== null && !Number.isNaN(p.y));
  const tempValid = pointsTemp.some(p => p.y !== null && !Number.isNaN(p.y));
  const chartError = document.getElementById('chartError');
  if (!humValid && !tempValid) {
    if (chartError) {
      chartError.style.display = 'flex';
      chartError.innerHTML = '<div><div style="font-size:16px;">No numeric data for selected timescale</div><div style="font-size:13px; color:#cbd5f5; margin-top:6px;">Try a different timescale or ensure sensor data exists</div></div>';
    }
  } else if (chartError) {
    chartError.style.display = 'none';
  }

  // Set explicit X axis bounds
  const firstValid = sorted.find(h => !isNaN(new Date(sanitizeTs(h.timestamp)).getTime()));
  const lastValid = [...sorted].reverse().find(h => !isNaN(new Date(sanitizeTs(h.timestamp)).getTime()));
  if (firstValid && lastValid) {
    const min = new Date(sanitizeTs(firstValid.timestamp)).getTime();
    const max = new Date(sanitizeTs(lastValid.timestamp)).getTime();
    state.chart.options.scales.x.min = min;
    state.chart.options.scales.x.max = max;

    // Debug: show samples and computed range after first/last determination
    console.debug('updateChart samples:', { pointsHum: pointsHum.slice(0,5), pointsTemp: pointsTemp.slice(0,5), first: new Date(min).toISOString(), last: new Date(max).toISOString(), tickFormatMode });
  }

  // Sanitize options before normalizing axes / updating chart to avoid Chart.js scriptable errors
  try { sanitizeChartOptions(state.chart.options); } catch (e) { console.debug('sanitizeChartOptions threw', e); }

  normalizeAxes();
  try { 
    try { sanitizeChartOptions(state.chart.options); } catch (e) { console.debug('sanitizeChartOptions threw', e); }
    state.chart.update('none'); 
  } catch (e) {
    console.error('chart.update failed', e);
    try {
      console.debug('chart.options snapshot:', JSON.parse(JSON.stringify(state.chart.options, (k,v) => (typeof v === 'function') ? `[Function:${v.name||'anonymous'}]` : v)));
    } catch (jsonErr) {
      console.debug('Could not JSON.stringify chart.options, dumping shallow entries:');
      for (const k of Object.keys(state.chart.options || {})) console.debug('option key:', k, 'type:', typeof state.chart.options[k]);
      if (state.chart.options && state.chart.options.scales) {
        for (const [k,v] of Object.entries(state.chart.options.scales)) console.debug('scale', k, 'valueType:', typeof v, v);
      }
    }

    // Attempt a safe fallback by replacing options with a minimal safe configuration then retry
    try {
      const safeOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#cbd5f5' } } },
        scales: { x: { type: 'linear', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } } }
      };
      console.warn('chart.update failed - applying fresh safe options and retrying');
      state.chart.options = safeOptions;
      ensureDatasetAxisMeta();
      syncVisibleOrderFromDatasets();
      rebalanceAssignedSides();
      normalizeAxes();
      state.chart.update('none');
      console.warn('chart.update retry succeeded with safe options');
      addLogEntry('Chart updated with safe options after error');
    } catch (retryErr) {
      console.error('chart.update retry failed', retryErr);
      addLogEntry('Chart update retry failed');
      // Attempt to recreate the chart from scratch with minimal options as a last-resort fallback
      try {
        console.warn('Attempting chart recreate fallback');
        const ctx = document.getElementById('sensorChart').getContext('2d');
        if (state.chart) { try { state.chart.destroy(); } catch (_) { /* ignore */ } }
        const allX = [].concat(pointsHum.map(p=>p.x), pointsTemp.map(p=>p.x)).filter(x => typeof x === 'number');
        const minX = allX.length ? Math.min(...allX) : undefined;
        const maxX = allX.length ? Math.max(...allX) : undefined;
        state.chart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: [],
            datasets: [
              { label: 'Humidity (%)', borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', data: pointsHum, tension: 0.3, spanGaps: false, yAxisID: 'y', axisTitle: 'Humidity %', axisColor: '#3b82f6' },
              { label: `Temp (${unitLabel})`, borderColor: '#f87171', data: pointsTemp, tension: 0.3, spanGaps: false, yAxisID: 'y1', axisTitle: `Temp (${unitLabel})`, axisColor: '#f87171' }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#cbd5f5' } } },
            scales: { 
              x: { type: 'linear', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' }, ...(minX !== undefined && maxX !== undefined ? { min: minX, max: maxX } : {}) },
              y: { type: 'linear', display: true, position: 'right', grid: { color: 'rgba(255,255,255,0.05)', drawOnChartArea: true }, ticks: { color: '#3b82f6' }, title: { display: true, text: 'Humidity %', color: '#3b82f6' } },
              y1: { type: 'linear', display: true, position: 'left', grid: { color: 'rgba(255,255,255,0.05)', drawOnChartArea: false }, ticks: { color: '#f87171' }, title: { display: true, text: `Temp (${unitLabel})`, color: '#f87171' } }
            }
          }
        });
        syncVisibleOrderFromDatasets();
        addLogEntry('Chart recreated after error');
      } catch (recreateErr) {
        console.error('chart recreate failed', recreateErr);
        addLogEntry('Chart recreate failed');
      }
    }
  }

    const scaleLabel = document.querySelector(`#timeScale option[value="${timescale}"]`)?.textContent || timescale;
    addLogEntry(`Synced data for ${scaleLabel}`);
  } catch (e) {
    console.error('updateChart error', e);
    addLogEntry('Chart update failed');
    const chartErrorEl = document.getElementById('chartError');
    if (chartErrorEl) {
      chartErrorEl.style.display = 'flex';
      chartErrorEl.innerHTML = `<div><div style="font-size:16px;">Chart update error</div><div style="font-size:13px; color:#cbd5f5; margin-top:6px;">${String(e && e.message)}</div></div>`;
    }
  }
}

export function toggleHumidity(checked) { setAxisDisplayByDatasetIndex(0, checked); localStorage.setItem('showHumidity', checked); addLogEntry(`${checked ? 'Showing' : 'Hiding'} humidity on chart`); }
export function toggleTemperature(checked) { setAxisDisplayByDatasetIndex(1, checked); localStorage.setItem('showTemperature', checked); addLogEntry(`${checked ? 'Showing' : 'Hiding'} temperature on chart`); }

// Expose for legacy calls
window.initChart = initChart; window.updateChart = updateChart;
window.toggleHumidity = (el) => toggleHumidity(el.checked);
window.toggleTemperature = (el) => toggleTemperature(el.checked);
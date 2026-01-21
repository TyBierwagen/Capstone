import { state } from './state.js';
import { addLogEntry } from './ui.js';

function getAxisId(index) { return index === 0 ? 'y' : 'y' + index; }
function getAxisPosition(index) { return (index % 2 === 0) ? 'right' : 'left'; }

export function initChart() {
  const ctx = document.getElementById('sensorChart').getContext('2d');
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  state.chart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Humidity (%)', borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', data: [], tension: 0.3, axisTitle: 'Humidity %', axisColor: '#3b82f6' },
      { label: `Temp (${unitLabel})`, borderColor: '#f87171', data: [], tension: 0.3, axisTitle: `Temp (${unitLabel})`, axisColor: '#f87171' }
    ]},
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#cbd5f5', filter: function(legendItem, chartData) { return !chartData.datasets[legendItem.datasetIndex].hidden; } } } },
      scales: { x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } } }
    }
  });
}

export function normalizeAxes() {
  if (!state.chart) return;
  const existingX = state.chart.options?.scales?.x || { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } };
  const scales = { x: existingX };
  let firstVisibleFound = false;
  state.chart.data.datasets.forEach((ds, i) => {
    const axisId = getAxisId(i);
    const pos = ds.assignedSide || getAxisPosition(i);
    const axisColor = ds.axisColor || '#94a3b8';
    const titleText = ds.axisTitle || ds.label || '';
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
  if (!state.chart || !history) return;
  state.historyData = history; state.lastTimescale = timescale;
  const sorted = [...history].sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
  const unitLabel = state.tempUnit === 'F' ? '°F' : '°C';
  if (state.chart && state.chart.data && state.chart.data.datasets[1]) { state.chart.data.datasets[1].label = `Temp (${unitLabel})`; state.chart.data.datasets[1].axisTitle = `Temp (${unitLabel})`; }
  // Sanitize timestamps to handle variants like '+00:00Z' or '+00:00' that some browsers parse inconsistently
  const sanitizeTs = (ts) => {
    if (!ts) return null;
    let v = String(ts).trim();
    v = v.replace(/\+00:00Z$/, 'Z').replace(/\+00:00$/, 'Z');
    return v;
  };

  state.chart.data.labels = sorted.map(h => {
    const raw = sanitizeTs(h.timestamp);
    const d = new Date(raw);
    if (isNaN(d.getTime())) return '';
    const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (timescale === '1h') return timeStr;
    if (timescale === '1d') return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + timeStr;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: '2-digit' }) + ' ' + timeStr;
  });
  state.chart.data.datasets[0].data = sorted.map(h => h.humidity);
  state.chart.data.datasets[1].data = sorted.map(h => { const temp = h.temperature; return (state.tempUnit === 'F' && temp !== null) ? (temp * 9/5) + 32 : temp; });
  normalizeAxes(); state.chart.update('none');
  const scaleLabel = document.querySelector(`#timeScale option[value="${timescale}"]`)?.textContent || timescale;
  addLogEntry(`Synced data for ${scaleLabel}`);
}

export function toggleHumidity(checked) { setAxisDisplayByDatasetIndex(0, checked); localStorage.setItem('showHumidity', checked); addLogEntry(`${checked ? 'Showing' : 'Hiding'} humidity on chart`); }
export function toggleTemperature(checked) { setAxisDisplayByDatasetIndex(1, checked); localStorage.setItem('showTemperature', checked); addLogEntry(`${checked ? 'Showing' : 'Hiding'} temperature on chart`); }

// Expose for legacy calls
window.initChart = initChart; window.updateChart = updateChart;
window.toggleHumidity = (el) => toggleHumidity(el.checked);
window.toggleTemperature = (el) => toggleTemperature(el.checked);
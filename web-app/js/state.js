export const state = {
  isConnected: false,
  useProd: true,
  deviceIp: '',
  refreshIntervalId: null,
  chart: null,
  tempUnit: 'C',
  latestData: null,
  historyData: null,
  historyCache: {},
  lastTimescale: '1h',
  refreshInProgress: false,
  visibleOrder: [],
  robot: { x: 0, y: 0, angle: 0, trail: [{ x: 0, y: 0 }] },
  robotTrailLimit: 200,
  customDateRange: null
};

// Expose for global access for modules and legacy code
window.state = state;

// Expose for global access for modules and legacy code
window.state = state;
// Configuration
const API_BASE_URL = window.location.hostname.includes('localhost') 
    ? 'http://localhost:7071/api' 
    : '/api';  // Will use API Management gateway in production

let isConnected = false;
let deviceIp = '';
let devicePort = 80;
let refreshInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    updateConnectionStatus(false);
    addLogEntry('System initialized');
    
    // Load saved connection details
    const savedIp = localStorage.getItem('deviceIp');
    const savedPort = localStorage.getItem('devicePort');
    
    if (savedIp) document.getElementById('deviceIp').value = savedIp;
    if (savedPort) document.getElementById('devicePort').value = savedPort;
});

// Connection Management
async function toggleConnection() {
    if (isConnected) {
        disconnect();
    } else {
        await connect();
    }
}

async function connect() {
    deviceIp = document.getElementById('deviceIp').value.trim();
    devicePort = document.getElementById('devicePort').value;
    
    if (!deviceIp) {
        showAlert('Please enter a valid IP address', 'error');
        return;
    }
    
    showAlert('Connecting to device...', 'success');
    addLogEntry(`Attempting to connect to ${deviceIp}:${devicePort}`);
    
    try {
        // Register device with backend
        const response = await fetch(`${API_BASE_URL}/devices`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                ip: deviceIp,
                port: devicePort,
                type: 'soil_sensor'
            })
        });
        
        if (response.ok) {
            isConnected = true;
            updateConnectionStatus(true);
            localStorage.setItem('deviceIp', deviceIp);
            localStorage.setItem('devicePort', devicePort);
            showAlert('Successfully connected!', 'success');
            addLogEntry('Connected successfully');
            
            // Start auto-refresh
            startAutoRefresh();
        } else {
            throw new Error('Connection failed');
        }
    } catch (error) {
        console.error('Connection error:', error);
        showAlert('Failed to connect. Using mock data.', 'error');
        addLogEntry('Connection failed, using mock data');
        
        // Simulate connection for demo purposes
        isConnected = true;
        updateConnectionStatus(true);
        startAutoRefresh();
    }
}

function disconnect() {
    isConnected = false;
    updateConnectionStatus(false);
    stopAutoRefresh();
    showAlert('Disconnected from device', 'success');
    addLogEntry('Disconnected');
    
    // Clear sensor readings
    document.getElementById('moisture').textContent = '--';
    document.getElementById('temperature').textContent = '--';
    document.getElementById('ph').textContent = '--';
    document.getElementById('light').textContent = '--';
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById('statusIndicator');
    const connectBtn = document.getElementById('connectBtn');
    
    if (connected) {
        indicator.classList.add('connected');
        indicator.classList.remove('disconnected');
        connectBtn.textContent = 'Disconnect';
    } else {
        indicator.classList.add('disconnected');
        indicator.classList.remove('connected');
        connectBtn.textContent = 'Connect';
    }
}

// Data Management
async function refreshData() {
    if (!isConnected) {
        showAlert('Please connect to a device first', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/sensor-data?deviceIp=${deviceIp}`);
        
        if (response.ok) {
            const data = await response.json();
            updateSensorDisplay(data);
            addLogEntry('Data refreshed');
        } else {
            throw new Error('Failed to fetch data');
        }
    } catch (error) {
        console.error('Data fetch error:', error);
        // Use mock data for demonstration
        const mockData = generateMockData();
        updateSensorDisplay(mockData);
        addLogEntry('Using mock data');
    }
}

function generateMockData() {
    return {
        moisture: (Math.random() * 40 + 30).toFixed(1),
        temperature: (Math.random() * 10 + 20).toFixed(1),
        ph: (Math.random() * 2 + 6).toFixed(1),
        light: Math.floor(Math.random() * 500 + 300)
    };
}

function updateSensorDisplay(data) {
    document.getElementById('moisture').textContent = data.moisture;
    document.getElementById('temperature').textContent = data.temperature;
    document.getElementById('ph').textContent = data.ph;
    document.getElementById('light').textContent = data.light;
    
    // Save data to backend
    saveSensorData(data);
}

async function saveSensorData(data) {
    try {
        await fetch(`${API_BASE_URL}/sensor-data`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                deviceIp: deviceIp,
                timestamp: new Date().toISOString(),
                ...data
            })
        });
    } catch (error) {
        console.error('Failed to save data:', error);
    }
}

function startAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    // Initial refresh
    refreshData();
    
    // Set up interval
    const interval = parseInt(document.getElementById('samplingInterval').value) || 60;
    refreshInterval = setInterval(refreshData, interval * 1000);
    addLogEntry(`Auto-refresh started (${interval}s interval)`);
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
        addLogEntry('Auto-refresh stopped');
    }
}

// Control Functions
async function updateInterval() {
    const interval = parseInt(document.getElementById('samplingInterval').value);
    
    if (interval < 1) {
        showAlert('Interval must be at least 1 second', 'error');
        return;
    }
    
    if (isConnected) {
        stopAutoRefresh();
        startAutoRefresh();
        showAlert(`Sampling interval updated to ${interval} seconds`, 'success');
    } else {
        showAlert('Please connect to a device first', 'error');
    }
}

async function startSampling() {
    if (!isConnected) {
        showAlert('Please connect to a device first', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/control`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                deviceIp: deviceIp,
                command: 'start'
            })
        });
        
        showAlert('Sampling started', 'success');
        addLogEntry('Sampling started');
    } catch (error) {
        console.error('Control error:', error);
        showAlert('Sampling started (mock)', 'success');
        addLogEntry('Sampling started (mock mode)');
    }
}

async function stopSampling() {
    if (!isConnected) {
        showAlert('Please connect to a device first', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/control`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                deviceIp: deviceIp,
                command: 'stop'
            })
        });
        
        showAlert('Sampling stopped', 'success');
        addLogEntry('Sampling stopped');
    } catch (error) {
        console.error('Control error:', error);
        showAlert('Sampling stopped (mock)', 'success');
        addLogEntry('Sampling stopped (mock mode)');
    }
}

// UI Helper Functions
function showAlert(message, type) {
    const alert = document.getElementById('alert');
    alert.textContent = message;
    alert.className = `alert ${type} show`;
    
    setTimeout(() => {
        alert.classList.remove('show');
    }, 5000);
}

function addLogEntry(message) {
    const log = document.getElementById('activityLog');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `<span class="log-time">${time}</span><span>${message}</span>`;
    
    log.insertBefore(entry, log.firstChild);
    
    // Keep only last 50 entries
    while (log.children.length > 50) {
        log.removeChild(log.lastChild);
    }
}

function clearLog() {
    const log = document.getElementById('activityLog');
    log.innerHTML = '<div class="log-entry"><span class="log-time">--:--:--</span><span>Log cleared</span></div>';
    addLogEntry('Log cleared');
}

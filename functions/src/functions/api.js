const { app } = require('@azure/functions');

// Register a new device
app.http('registerDevice', {
    methods: ['POST'],
    authLevel: 'anonymous',
    route: 'devices',
    handler: async (request, context) => {
        context.log('Registering new device');
        
        try {
            const device = await request.json();
            
            // Validate input
            if (!device.ip || !device.port) {
                return {
                    status: 400,
                    jsonBody: {
                        error: 'IP address and port are required'
                    }
                };
            }
            
            // In production, this would save to database
            // For now, return success
            const deviceInfo = {
                id: generateDeviceId(),
                ip: device.ip,
                port: device.port,
                type: device.type || 'unknown',
                registeredAt: new Date().toISOString(),
                status: 'active'
            };
            
            context.log('Device registered:', deviceInfo);
            
            return {
                status: 200,
                jsonBody: deviceInfo
            };
        } catch (error) {
            context.log.error('Error registering device:', error);
            return {
                status: 500,
                jsonBody: {
                    error: 'Failed to register device'
                }
            };
        }
    }
});

// Get sensor data
app.http('getSensorData', {
    methods: ['GET'],
    authLevel: 'anonymous',
    route: 'sensor-data',
    handler: async (request, context) => {
        context.log('Getting sensor data');
        
        try {
            const deviceIp = request.query.get('deviceIp');
            
            if (!deviceIp) {
                return {
                    status: 400,
                    jsonBody: {
                        error: 'Device IP is required'
                    }
                };
            }
            
            // In production, this would fetch from database
            // For now, return mock data
            const sensorData = {
                deviceIp: deviceIp,
                timestamp: new Date().toISOString(),
                moisture: (Math.random() * 40 + 30).toFixed(1),
                temperature: (Math.random() * 10 + 20).toFixed(1),
                ph: (Math.random() * 2 + 6).toFixed(1),
                light: Math.floor(Math.random() * 500 + 300)
            };
            
            context.log('Sensor data retrieved:', sensorData);
            
            return {
                status: 200,
                jsonBody: sensorData
            };
        } catch (error) {
            context.log.error('Error getting sensor data:', error);
            return {
                status: 500,
                jsonBody: {
                    error: 'Failed to retrieve sensor data'
                }
            };
        }
    }
});

// Save sensor data
app.http('saveSensorData', {
    methods: ['POST'],
    authLevel: 'anonymous',
    route: 'sensor-data',
    handler: async (request, context) => {
        context.log('Saving sensor data');
        
        try {
            const data = await request.json();
            
            // Validate input
            if (!data.deviceIp || !data.timestamp) {
                return {
                    status: 400,
                    jsonBody: {
                        error: 'Device IP and timestamp are required'
                    }
                };
            }
            
            // In production, this would save to database
            context.log('Sensor data saved:', data);
            
            return {
                status: 201,
                jsonBody: {
                    message: 'Data saved successfully',
                    id: generateDataId()
                }
            };
        } catch (error) {
            context.log.error('Error saving sensor data:', error);
            return {
                status: 500,
                jsonBody: {
                    error: 'Failed to save sensor data'
                }
            };
        }
    }
});

// Control device
app.http('controlDevice', {
    methods: ['POST'],
    authLevel: 'anonymous',
    route: 'control',
    handler: async (request, context) => {
        context.log('Controlling device');
        
        try {
            const control = await request.json();
            
            // Validate input
            if (!control.deviceIp || !control.command) {
                return {
                    status: 400,
                    jsonBody: {
                        error: 'Device IP and command are required'
                    }
                };
            }
            
            // In production, this would send command to device
            context.log('Control command sent:', control);
            
            return {
                status: 200,
                jsonBody: {
                    message: 'Command sent successfully',
                    command: control.command,
                    deviceIp: control.deviceIp,
                    timestamp: new Date().toISOString()
                }
            };
        } catch (error) {
            context.log.error('Error controlling device:', error);
            return {
                status: 500,
                jsonBody: {
                    error: 'Failed to send command'
                }
            };
        }
    }
});

// Helper functions
function generateDeviceId() {
    return 'dev_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

function generateDataId() {
    return 'data_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

# Pi Zero Sensor Node

EdgeX-powered sensor nodes for Raspberry Pi Zero 2W with real-time dashboard.

## Components

| Component | Description |
|-----------|-------------|
| `sensor_node.py` | System metrics collector with edge processing (MQTT → EdgeX) |
| `dashboard_server.py` | Python HTTP server serving dashboard + proxying EdgeX API |
| `dashboard.html` | PWA-enabled real-time dashboard with chart modal |
| `manifest.json` | PWA manifest for mobile install |
| `sw.js` | Service worker for offline/PWA support |

## Features

- **Edge Processing**: Deadband filtering, moving average, SQLite buffer, emergency priority
- **Real-time Dashboard**: Dark theme, glassmorphism, SVG gauges, sparklines
- **Full-screen Charts**: Tap sparkline → modal with Canvas chart, time filters (1h/2h/5h/1d/7d), hover tooltips
- **PWA**: Installable on phone/tablet, standalone mode, dark status bar
- **Mobile-first**: Responsive layout, touch-optimized, safe-area-aware
- **Auto-refresh**: Every 10 seconds with live connection indicator

## Quick Start

1. Deploy `sensor_node.py` to each Pi Zero
2. Set `MQTT_BROKER` to your MQTT broker IP
3. Run `dashboard_server.py` on the EdgeX gateway machine
4. Open http://<gateway-ip>:9090

## Dashboard Details

- Live status with pulsing indicator
- Temperature gauge (color-coded: cyan/amber/red)
- CPU Load & Memory usage bars
- WiFi signal strength with quality indicator
- Uptime tracking
- 30-point mini sparklines for Temp/CPU/Memory
- **Full-screen chart modal**: tap any sparkline
- Time ranges: 1h, 2h, 5h, 1d, 7d
- Resource tabs: Temp, CPU, Memory, Uptime, WiFi
- Hover/pointer tooltips on chart
- Stats: Average, Min, Max, Data Points
- PWA installable on mobile

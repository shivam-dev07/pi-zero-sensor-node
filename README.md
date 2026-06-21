# Pi Zero Sensor Node

> **MQTT sensor agent for Raspberry Pi Zero 2W** — publishes system metrics to an EdgeX Foundry IoT Gateway.

[![Python](https://img.shields.io/badge/python-3.7+-blue.svg)](https://python.org)
[![MQTT](https://img.shields.io/badge/MQTT-v3.1.1-orange)](https://mqtt.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 📋 Overview

This project turns a **Raspberry Pi Zero 2W** into a remote IoT sensor node that streams system metrics over **MQTT** to an **EdgeX Foundry** gateway. It's designed for low-power, headless deployments where the Pi Zero is distributed across a facility or campus and reports back to a central gateway (e.g., a Raspberry Pi 5 running the full EdgeX stack).

### Architecture

```
┌─────────────────────────┐          MQTT           ┌─────────────────────────────┐
│  Pi Zero 2W (Sensor)    │  ────────────────►      │  EdgeX Gateway (Pi 5)       │
│                         │  incoming/data/{device_name}/  │                             │
│  sensor_node.py         │     cpu_temp_c           │  edgex-device-mqtt          │
│  ▼                      │     cpu_load            │  ├─ Core Data (:59880)      │
│  ┌─────────────────┐    │     memory_used_pct     │  ├─ eKuiper  (:59720)       │
│  │ CPU Temp        │    │     uptime_s            │  ├─ Alerts  (MQTT)          │
│  │ CPU Load        │    │     wifi_signal_dbm     │  └─ UI Dashboard (:4000)    │
│  │ Memory Used %   │    │     status              │                             │
│  │ Uptime          │    │                         │                             │
│  │ WiFi Signal     │    │                         │                             │
│  └─────────────────┘    │                         │                             │
│                         │      MQTT Broker        │                             │
│  sensor_node.py ──────► │  (Mosquitto / NanoMQ)   │ ──► EdgeX Core Data         │
│                         │   Port 1883              │      │                      │
│                         │                         │      ▼                      │
│                         │                         │  eKuiper Rules Engine       │
│                         │                         │  ┌────────────────────┐     │
│                         │                         │  │ cpu_temp > 55°C   │     │
│                         │                         │  │ memory > 80%      │     │
│                         │                         │  │ heartbeat timeout │     │
│                         │                         │  └────────┬───────────┘     │
│                         │                         │           ▼                  │
│                         │                         │     Alert (MQTT / Telegram) │
└─────────────────────────┘                         └─────────────────────────────┘
```

### Metrics Collected

| Metric | Resource Name | Example |
|--------|--------------|---------|
| CPU Temperature | `cpu_temp_c` | `45.2` |
| CPU Load Average (1min) | `cpu_load` | `{"1min": 0.85}` |
| Memory Used % | `memory_used_pct` | `67.3` |
| System Uptime | `uptime_s` | `284731.5` |
| WiFi Signal Level | `wifi_signal_dbm` | `-67` |
| Node Status | `status` | `online` |

---

## 🚀 Quick Start

### Prerequisites
- Raspberry Pi Zero 2W (any Pi running Raspberry Pi OS)
- Python 3.7+
- Network connectivity to EdgeX Gateway (MQTT port 1883)
- MQTT broker running on the gateway (Mosquitto / NanoMQ)

### 1. Installation

```bash
# Clone this repo
git clone https://github.com/shivam-dev07/pi-zero-sensor-node.git
cd pi-zero-sensor-node

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `sensor_node.py` and set the following variables at the top:

```python
MQTT_HOST = "10.0.0.1"     # Your EdgeX gateway IP or hostname
MQTT_PORT = 1883                # MQTT broker port
DEVICE = "pizero1"              # Unique device name (change per node)
INTERVAL = 10                   # Seconds between publish cycles
```

> **💡 Tip:** For multiple nodes, set `DEVICE` to a unique name per Pi Zero. EdgeX auto-creates device entries based on this name.

### 3. Run

```bash
# Test run
python3 sensor_node.py

# Expected output:
# [sensor] Connected to 10.0.0.1:1883 as 'pizero1'
#   [cpu_temp_c] 42.8
#   [cpu_load] {"1min": 0.12}
#   [memory_used_pct] 34.1
#   ...
```

### 4. Auto-start with systemd

```bash
# Install the systemd service
sudo cp sensor-node.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sensor-node.service
sudo systemctl start sensor-node.service

# Check status
sudo systemctl status sensor-node.service
```

---

## ⚙️ Systemd Service

The included `sensor-node.service` ensures the sensor runs automatically at boot and restarts if it crashes.

```ini
[Unit]
Description=Pi Zero Sensor Node — publishes system stats to EdgeX
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 -u /home/shivam/sensor_node.py
Restart=always
RestartSec=5
User=shivam

[Install]
WantedBy=multi-user.target
```

### Useful systemd commands

```bash
# View live logs
journalctl -u sensor-node.service -f

# Restart the service
sudo systemctl restart sensor-node.service

# Check recent logs
journalctl -u sensor-node.service --since "1 hour ago"
```

---

## 🔌 EdgeX Gateway Setup

Your EdgeX gateway (e.g., Raspberry Pi 5) needs:

1. **MQTT Broker** running on port 1883 (Mosquitto or NanoMQ)
2. **edgex-device-mqtt** service enabled
3. **PiZero-Sensor-Profile** registered in EdgeX Metadata (port 59881)

### Device Profile (auto-created)

The sensor publishes to topics matching the EdgeX format:
```
incoming/data/{DEVICE}/{resource_name}
```

EdgeX's `device-mqtt` service maps these topics to the `PiZero-Sensor-Profile` which defines these resources.

### Verify data flow

```bash
# On the EdgeX gateway, check readings
curl http://localhost:59880/api/v3/reading/deviceName/pizero1?limit=3 | jq .
```

---

## 🔄 Deploying to Multiple Pi Zeros

Use the `deploy.sh` script for batch deployment:

```bash
# For a single device
./deploy.sh pizero1 10.0.0.101

# The script will:
# 1. Copy sensor_node.py via SSH
# 2. Install the systemd service
# 3. Start the sensor
```

**Manual per-node config:**
Edit `DEVICE = "pizero2"` in `sensor_node.py` before deploying to each node.

---

## 📊 EdgeX Rules (eKuiper)

Example eKuiper SQL rules that work with this sensor data:

```sql
-- Alert if CPU exceeds 55°C
SELECT device_name, cpu_temp
FROM sensors
WHERE cpu_temp > 55

-- Alert if memory exceeds 80%
SELECT device_name, memory_used_pct
FROM sensors
WHERE memory_used_pct > 80

-- Alert if no data for 5 minutes (heartbeat)
SELECT device_name,
       lag(recorded_at) as last_seen
FROM sensors
GROUP BY device_name
HAVING DATEDIFF_MS(latest_recorded_at, lag_recorded_at) > 300000
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Check if MQTT broker is running on the gateway: `netstat -tlnp \| grep 1883` |
| Auth failed | No auth needed by default; ensure no credentials required on broker |
| No readings in EdgeX | Check `device-mqtt` logs: `docker logs edgex-device-mqtt` |
| WiFi drops | The script auto-reconnects; check WiFi with `iwconfig` |
| High memory usage | Ensure `google-api-python-client` is not installed (can bloat to 95MB on Pi Zero) |

---

## 📁 Project Structure

```
pi-zero-sensor-node/
├── sensor_node.py          # MQTT sensor agent (Python 3)
├── sensor-node.service     # systemd auto-start config
├── requirements.txt        # Python dependencies
├── deploy.sh               # Remote deployment script
├── README.md               # This file
└── LICENSE                 # MIT License
```

---

## 🧪 Dependencies

- [`paho-mqtt`](https://pypi.org/project/paho-mqtt/) — MQTT client library

Only ~350KB installed. No heavy dependencies.

---

## 📄 License

MIT License — feel free to use, modify, and share.

---

## 👨‍💻 Author

**Shivam Vishwakarma**  
IoT Solutions Engineer | Embedded Systems  
[GitHub](https://github.com/shivam-dev07)

---

> Built for the [EdgeX Foundry](https://www.edgexfoundry.org/) IoT ecosystem.

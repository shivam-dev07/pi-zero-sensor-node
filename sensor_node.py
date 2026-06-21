#!/usr/bin/env python3
"""
Pi Zero Sensor Node — EdgeX MQTT Publisher
===========================================
Publishes system metrics from a Raspberry Pi Zero 2W to an EdgeX Foundry
IoT gateway via MQTT. Auto-reconnects on network failure.

Metrics Published:
  - cpu_temp_c       (°C)
  - cpu_load         (JSON: {1min: float})
  - memory_used_pct  (%)
  - uptime_s         (seconds)
  - wifi_signal_dbm  (dBm)
  - status           ("online")

Architecture:
  Pi Zero 2W  ──MQTT──►  EdgeX Gateway (Pi 5)
                              │
                              ├── Core Data (store)
                              ├── eKuiper (rules engine)
                              └── Alerts / Dashboard
"""

import json
import os
import re
import time

import paho.mqtt.client as mqtt

# ═══════════════════════════════════════════════
# CONFIGURATION — Edit these for your setup
# ═══════════════════════════════════════════════

MQTT_HOST = "10.0.0.1"  # Change to your gateway IP       # EdgeX gateway IP
MQTT_PORT = 1883                    # MQTT broker port
DEVICE = "pizero1"                  # Unique device name (change per node)
INTERVAL = 10                       # Seconds between publish cycles

# EdgeX device profile resource names — one MQTT topic per resource
RESOURCES = [
    "cpu_temp_c",
    "cpu_load",
    "memory_used_pct",
    "uptime_s",
    "wifi_signal_dbm",
    "status",
]

# ═══════════════════════════════════════════════
# SENSOR READERS
# ═══════════════════════════════════════════════


def get_cpu_temp() -> str:
    """Read CPU temperature from /sys/class/thermal."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return str(round(float(f.read().strip()) / 1000, 1))
    except Exception:
        return "0.0"


def get_cpu_load() -> str:
    """Read 1-minute CPU load average."""
    try:
        return json.dumps({"1min": round(os.getloadavg()[0], 2)})
    except Exception:
        return json.dumps({"1min": 0.0})


def get_memory_used() -> str:
    """Calculate memory usage % from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            data = f.read()
        total_m = int(re.search(r"MemTotal:\s+(\d+)", data).group(1))
        free_m = int(re.search(r"MemAvailable:\s+(\d+)", data).group(1))
        return str(round(100 - (free_m / total_m * 100), 1))
    except Exception:
        return "0.0"


def get_uptime() -> str:
    """Read system uptime in seconds."""
    try:
        with open("/proc/uptime") as f:
            return str(round(float(f.read().split()[0]), 1))
    except Exception:
        return "0.0"


def get_wifi_signal() -> str:
    """Read WiFi signal level from iwconfig."""
    try:
        out = os.popen(
            'iwconfig 2>/dev/null | grep -o "Signal level=[^ ]*" | cut -d= -f2'
        ).read().strip()
        return out if out else "-300"
    except Exception:
        return "-300"


def get_status() -> str:
    """Always reports online while the process is running."""
    return "online"


# Map resource names to reader functions
READINGS = {
    "cpu_temp_c": get_cpu_temp,
    "cpu_load": get_cpu_load,
    "memory_used_pct": get_memory_used,
    "uptime_s": get_uptime,
    "wifi_signal_dbm": get_wifi_signal,
    "status": get_status,
}

# ═══════════════════════════════════════════════
# MQTT CLIENT
# ═══════════════════════════════════════════════

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"{DEVICE}-sensor",
)


def publish(topic: str, payload: str) -> None:
    """Publish with auto-reconnect on failure (2 attempts)."""
    if not client.is_connected():
        print("[reconnecting]")
        client.reconnect()
        time.sleep(1)

    info = client.publish(topic, payload, qos=1)
    try:
        info.wait_for_publish(timeout=5)
    except RuntimeError:
        print("[publish failed, reconnecting]")
        try:
            client.reconnect()
            time.sleep(1)
            info = client.publish(topic, payload, qos=1)
            info.wait_for_publish(timeout=5)
        except Exception as e:
            print(f"[fatal] {e}")
            time.sleep(5)


# ═══════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════

def main():
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    print(f"[sensor] Connected to {MQTT_HOST}:{MQTT_PORT} as '{DEVICE}'")

    while True:
        for res in RESOURCES:
            val = READINGS[res]()
            topic = f"incoming/data/{DEVICE}/{res}"
            publish(topic, val)
            print(f"  [{res}] {val}")

        print(f"  --- {time.ctime()} ---")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[sensor] Shutting down.")
        client.disconnect()

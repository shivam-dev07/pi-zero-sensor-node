#!/usr/bin/env python3
"""
Pi Zero Sensor Node — EdgeX MQTT Publisher v2.0
================================================
Publishes system metrics from Raspberry Pi Zero 2W to EdgeX Foundry IoT gateway.

v2.0 Features:
  - Per-resource EdgeX topics: each reading published to its own topic
  - Deadband filtering: only publish when value changes significantly
  - Moving average: smooth noisy readings before publishing
  - SQLite offline buffer: store readings when MQTT is down
  - Offline replay: send buffered data when broker reconnects
  - Emergency priority: publish immediately on anomaly detection

Minimal RAM: ~5 MB + sensor readings buffer
Device:      Pi Zero 2W (512 MB RAM recommended)
"""

import json
import os
import platform
import sqlite3
import sys
import time
import re
from collections import deque
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

# --- MQTT ---
MQTT_HOST = "10.0.0.1"  # EdgeX gateway / MQTT broker
MQTT_PORT = 1883
MQTT_TOPIC_PREFIX = "incoming/data"  # EdgeX device-mqtt incoming prefix
MQTT_KEEPALIVE = 60

# --- Device Identity ---
# Auto-detects from hostname. Override by creating /home/shivam/device_name file
DEVICE_NAME_FILE = "/home/shivam/device_name"

# --- Collection ---
PUBLISH_INTERVAL = 10  # seconds

# === EDGE PROCESSING ===

# 1. Deadband thresholds per resource
DEADBAND = {
    "temp": 0.5,        # °C
    "load": 5.0,        # %
    "memory": 3.0,      # %
    "uptime": 0.5,      # hours
    "wifi": 2,          # dBm
    "disk": 2.0,        # %
}
HEARTBEAT_CYCLES = 3  # every 6 cycles, publish even if no change

# 2. Moving average
MOVING_AVG_WINDOW = 3  # number of readings (1 = disabled)

# 3. SQLite offline buffer
SQLITE_DB = "/home/shivam/sensor_buffer.db"
MAX_BUFFER_SIZE = 10000

# 4. Emergency thresholds
EMERGENCY_TEMP_MAX = 80.0   # °C
EMERGENCY_MEM_MAX = 90.0    # %
EMERGENCY_COOLDOWN = 30     # seconds between emergency publishes

# ═══════════════════════════════════════════════════════════════════
# RESOURCE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════
# Maps our internal keys to EdgeX device profile resource names
# and their MQTT topic suffix.
# Value must match the EdgeX device profile PiZero-Sensor-Profile.

RESOURCES = {
    "cpu_temp_c": {
        "topic_suffix": "cpu_temp_c",
        "getter": None,  # filled below
        "deadband_key": "temp",
        "unit": "C",
        "precision": 1,
    },
    "cpu_load": {
        "topic_suffix": "cpu_load",
        "getter": None,
        "deadband_key": "load",
        "unit": "%",
        "precision": 1,
    },
    "memory_used_pct": {
        "topic_suffix": "memory_used_pct",
        "getter": None,
        "deadband_key": "memory",
        "unit": "%",
        "precision": 1,
    },
    "uptime_s": {
        "topic_suffix": "uptime_s",
        "getter": None,
        "deadband_key": "uptime",
        "unit": "hours",
        "precision": 1,
    },
    "wifi_signal_dbm": {
        "topic_suffix": "wifi_signal_dbm",
        "getter": None,
        "deadband_key": "wifi",
        "unit": "dBm",
        "precision": 0,
    },
    "status": {
        "topic_suffix": "status",
        "getter": None,
        "deadband_key": None,  # always publishes
        "unit": "",
        "precision": 0,
    },
}

# Moving average buffers per resource
_buffers = {key: deque(maxlen=MOVING_AVG_WINDOW) for key in RESOURCES}

# Deadband tracking
_last_sent = {}
_cycle = 0
_last_emergency = 0

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def get_device_name():
    try:
        if os.path.exists(DEVICE_NAME_FILE):
            with open(DEVICE_NAME_FILE) as f:
                name = f.read().strip()
                if name:
                    return name
    except Exception:
        pass
    return platform.node()


def read_sysfs(path, default=0.0):
    try:
        with open(path) as f:
            return float(f.read().strip())
    except Exception:
        return default


def get_cpu_temp():
    temp_raw = read_sysfs("/sys/class/thermal/thermal_zone0/temp")
    return round(temp_raw / 1000.0, 1)


def get_cpu_load():
    try:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return round((load / cores) * 100, 1)
    except Exception:
        return 0.0


def get_memory():
    try:
        with open("/proc/meminfo") as f:
            data = f.read()
        total = int(re.search(r"MemTotal:\s+(\d+)", data).group(1))
        free = int(re.search(r"MemAvailable:\s+(\d+)", data).group(1))
        return round((1 - free / total) * 100, 1)
    except Exception:
        return 0.0


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.read().split()[0])
        return round(uptime_sec / 3600, 1)
    except Exception:
        return 0.0


def get_wifi_dbm():
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                parts = line.strip().split()
                if len(parts) >= 4:
                    return int(parts[3].rstrip("."))
    except Exception:
        pass
    return 0


def get_status():
    return "online"


# Wire up getters
RESOURCES["cpu_temp_c"]["getter"] = get_cpu_temp
RESOURCES["cpu_load"]["getter"] = get_cpu_load
RESOURCES["memory_used_pct"]["getter"] = get_memory
RESOURCES["uptime_s"]["getter"] = get_uptime
RESOURCES["wifi_signal_dbm"]["getter"] = get_wifi_dbm
RESOURCES["status"]["getter"] = get_status


def format_value(value, precision):
    """Format value for MQTT — simple string that EdgeX can parse."""
    if precision == 0:
        return str(int(value))
    return f"{value:.{precision}f}"


# ═══════════════════════════════════════════════════════════════════
# EDGE PROCESSING: MOVING AVERAGE
# ═══════════════════════════════════════════════════════════════════

def moving_average(buffer, new_value):
    """Simple moving average. For numeric values only; strings pass through."""
    if not isinstance(new_value, (int, float)):
        return new_value
    buffer.append(new_value)
    if MOVING_AVG_WINDOW <= 1:
        return new_value
    return round(sum(buffer) / len(buffer), 1)


# ═══════════════════════════════════════════════════════════════════
# EDGE PROCESSING: DEADBAND FILTERING
# ═══════════════════════════════════════════════════════════════════

def should_publish(key, value):
    """
    Per-resource deadband check.
    Publishes if:
      - First time seeing this resource
      - Value changed beyond threshold
      - Heartbeat cycle reached
    """
    global _cycle
    _cycle += 1

    if key not in _last_sent:
        _last_sent[key] = (value, _cycle)
        return True

    last_val, last_cycle = _last_sent[key]
    deadband_def = DEADBAND

    if isinstance(deadband_def, dict):
        db = deadband_def.get(key, 0)
    else:
        db = 0

    if abs(value - last_val) >= db:
        _last_sent[key] = (value, _cycle)
        return True

    if (_cycle - last_cycle) >= HEARTBEAT_CYCLES:
        _last_sent[key] = (value, _cycle)
        return True

    return False


# ═══════════════════════════════════════════════════════════════════
# EDGE PROCESSING: EMERGENCY PRIORITY
# ═══════════════════════════════════════════════════════════════════

def is_emergency(temp, mem_pct):
    global _last_emergency
    now = time.time()
    if now - _last_emergency < EMERGENCY_COOLDOWN:
        return False
    if temp >= EMERGENCY_TEMP_MAX or mem_pct >= EMERGENCY_MEM_MAX:
        _last_emergency = now
        return True
    return False


# ═══════════════════════════════════════════════════════════════════
# EDGE PROCESSING: SQLITE OFFLINE BUFFER
# ═══════════════════════════════════════════════════════════════════

def init_buffer():
    conn = sqlite3.connect(SQLITE_DB, timeout=2)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()


def buffer_store(topic, payload_str):
    try:
        conn = sqlite3.connect(SQLITE_DB, timeout=2)
        conn.execute(
            "INSERT INTO sensor_buffer (topic, payload) VALUES (?, ?)",
            (topic, payload_str)
        )
        conn.execute(
            "DELETE FROM sensor_buffer WHERE id <= (SELECT id FROM sensor_buffer ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (MAX_BUFFER_SIZE,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[BUFFER] Write error: {e}", file=sys.stderr)


def buffer_replay(mqtt_client):
    count = 0
    try:
        conn = sqlite3.connect(SQLITE_DB, timeout=2)
        rows = conn.execute(
            "SELECT id, topic, payload FROM sensor_buffer ORDER BY id ASC"
        ).fetchall()
        if not rows:
            conn.close()
            return 0
        for row_id, topic, payload_str in rows:
            try:
                mqtt_client.publish(topic, payload_str, qos=1)
                count += 1
            except Exception:
                continue
        conn.execute("DELETE FROM sensor_buffer")
        conn.commit()
        conn.close()
        if count > 0:
            print(f"[BUFFER] Replayed {count} readings", file=sys.stderr)
    except Exception as e:
        print(f"[BUFFER] Replay error: {e}", file=sys.stderr)
    return count


# ═══════════════════════════════════════════════════════════════════
# MQTT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def mqtt_connect(client):
    try:
        client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        client.loop_start()
        return True
    except Exception as e:
        print(f"[MQTT] Connection failed: {e}", file=sys.stderr)
        return False


def mqtt_publish(client, topic, payload_str):
    try:
        result = client.publish(topic, payload_str, qos=1)
        if result.rc == 0:
            return True
        else:
            print(f"[MQTT] Publish rc={result.rc}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[MQTT] Publish error: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════

def main():
    import paho.mqtt.client as mqtt

    device = get_device_name()
    print(f"[START] Pi Zero Sensor Node v2 — EdgeX Resource Topics")
    print(f"[START] Device: {device} | Broker: {MQTT_HOST}:{MQTT_PORT}")
    print(f"[START] Moving Avg: {MOVING_AVG_WINDOW} | Buffer: {SQLITE_DB}")

    init_buffer()

    client = mqtt.Client(
        client_id=f"pizero-{device}-{os.getpid()}",
        protocol=mqtt.MQTTv311
    )
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    mqtt_connected = mqtt_connect(client)

    resource_keys = list(RESOURCES.keys())

    while True:
        try:
            # === COLLECT RAW DATA ===
            raw = {}
            for key in resource_keys:
                getter = RESOURCES[key]["getter"]
                raw[key] = getter()

            # === MOVING AVERAGE ===
            smoothed = {}
            for key in resource_keys:
                smoothed[key] = moving_average(_buffers[key], raw[key])

            # === EMERGENCY CHECK ===
            emergency = is_emergency(smoothed["cpu_temp_c"], smoothed["memory_used_pct"])

            # === PUBLISH PER-RESOURCE TOPICS ===
            if emergency:
                print(f"[EMERGENCY] temp={smoothed['cpu_temp_c']}°C, "
                      f"mem={smoothed['memory_used_pct']}%")

            for key in resource_keys:
                r = RESOURCES[key]
                value = smoothed[key]
                formatted = format_value(value, r["precision"])

                # Deadband check (skip for status and emergency)
                if r["deadband_key"] and not emergency:
                    if not should_publish(r["deadband_key"], value):
                        continue

                topic = f"{MQTT_TOPIC_PREFIX}/{device}/{r['topic_suffix']}"

                if mqtt_connected:
                    ok = mqtt_publish(client, topic, formatted)
                    if not ok:
                        mqtt_connected = False
                        buffer_store(topic, formatted)
                        print(f"[BUFFER] Stored {topic} (MQTT down)")
                else:
                    buffer_store(topic, formatted)

            # After publishing, replay buffer if connected
            if mqtt_connected:
                buffer_replay(client)

            # Try reconnect if needed
            if not mqtt_connected:
                mqtt_connected = mqtt_connect(client)

        except KeyboardInterrupt:
            print("\n[STOP] Shutting down...")
            break
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

        time.sleep(PUBLISH_INTERVAL)

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()

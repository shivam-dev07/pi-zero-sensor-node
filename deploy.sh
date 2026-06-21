#!/usr/bin/env bash
# ═══════════════════════════════════════════════
# Pi Zero Sensor Node — Remote Deploy Script
# ═══════════════════════════════════════════════
# Usage:
#   ./deploy.sh <device_name> <pi_zero_ip> [password]
#
# Examples:
#   ./deploy.sh pizero1 10.0.0.101
#   ./deploy.sh pizero2 10.0.0.102 your_password
#
# This script:
#   1. Copies sensor_node.py to the Pi Zero via SCP
#   2. Installs the systemd service
#   3. Starts the sensor node
# ═══════════════════════════════════════════════

set -euo pipefail

DEVICE_NAME="${1:?Usage: $0 <device_name> <pi_zero_ip> [password]}"
PI_IP="${2:?Usage: $0 <device_name> <pi_zero_ip> [password]}"
PI_PASS="${3:-}"
PI_USER="shivam"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deploying sensor node: $DEVICE_NAME"
echo "  Target: $PI_USER@$PI_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Copy sensor_node.py with DEVICE name configured
echo "→ Configuring device name..."
sed "s/^DEVICE = \".*\"/DEVICE = \"$DEVICE_NAME\"/" sensor_node.py > "/tmp/sensor_node_${DEVICE_NAME}.py"

echo "→ Copying files to Pi Zero..."
sshpass -p "$PI_PASS" scp $SSH_OPTS \
    "/tmp/sensor_node_${DEVICE_NAME}.py" \
    "${PI_USER}@${PI_IP}:/home/shivam/sensor_node.py"

sshpass -p "$PI_PASS" scp $SSH_OPTS \
    sensor-node.service \
    "${PI_USER}@${PI_IP}:/tmp/sensor-node.service"

# 2. Install dependencies (skip if already installed)
echo "→ Installing dependencies..."
sshpass -p "$PI_PASS" ssh $SSH_OPTS "${PI_USER}@${PI_IP}" \
    "pip3 install --user paho-mqtt -q 2>/dev/null || true"

# 3. Install systemd service
echo "→ Installing systemd service..."
sshpass -p "$PI_PASS" ssh $SSH_OPTS "${PI_USER}@${PI_IP}" \
    "sudo cp /tmp/sensor-node.service /etc/systemd/system/ && \
     sudo systemctl daemon-reload && \
     sudo systemctl enable sensor-node.service && \
     sudo systemctl restart sensor-node.service"

# 4. Verify
echo "→ Verifying..."
sleep 2
sshpass -p "$PI_PASS" ssh $SSH_OPTS "${PI_USER}@${PI_IP}" \
    "sudo systemctl is-active sensor-node.service"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Deployment complete!"
echo "  Check logs: journalctl -u sensor-node.service -f"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Cleanup
rm -f "/tmp/sensor_node_${DEVICE_NAME}.py"

#!/bin/bash
# ╔═══════════════════════════════════════════════════════════════╗
# ║   🚀 GANDIVE BOT — One-Command Startup Script              ║
# ║   Run this to restore everything after a server reboot.     ║
# ╚═══════════════════════════════════════════════════════════════╝
# Usage: bash startup.sh

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║   🚀 GandiveBot Startup                      ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

# ─── Step 1: Start all PM2 processes ───
echo "📦 Step 1/4: Restoring PM2 processes..."
cd "$BASE_DIR"
pm2 resurrect 2>/dev/null || pm2 start ecosystem.config.js 2>/dev/null || {
    # Manual start if no config file
    echo "   Starting processes manually..."
    source venv/bin/activate 2>/dev/null || true
    
    pm2 start venv/bin/python --name gandive-bot -- bot.py 2>/dev/null || pm2 start python3 --name gandive-bot -- bot.py
    sleep 2
    
    pm2 start python3 --name gandive-webhook -- webhook_server.py
    sleep 2
    
    pm2 start python3 --name gandive-dashboard -- dashboard.py
    sleep 2
}
echo "   ✅ Bot processes started"
echo ""

# ─── Step 2: Start AISAMACHAR ───
echo "📰 Step 2/4: Starting AISAMACHAR news bot..."
cd /home/enishshah2/freebuff 2>/dev/null && {
    pm2 start ecosystem.config.cjs --only aisamachar 2>/dev/null || {
        node src/server.js &
        echo "   AISAMACHAR started manually"
    }
    echo "   ✅ AISAMACHAR started"
} || echo "   ⚠️ AISAMACHAR directory not found"
cd "$BASE_DIR"
echo ""

# ─── Step 3: Start cloudflared tunnel ───
echo "🌐 Step 3/4: Starting cloudflared tunnel..."
TUNNEL_URL=$(cat /home/enishshah2/.pm2/logs/gandive-tunnel-error.log 2>/dev/null | grep -oP 'https://[a-z-]+\.trycloudflare\.com' | tail -1)
# Also check out.log if error.log was empty
if [ -z "$TUNNEL_URL" ]; then
    TUNNEL_URL=$(cat /home/enishshah2/.pm2/logs/gandive-tunnel-out.log 2>/dev/null | grep -oP 'https://[a-z-]+\.trycloudflare\.com' | tail -1)
fi

# Kill old tunnel if running
pm2 delete gandive-tunnel 2>/dev/null || true
pm2 delete gandive-dash-tunnel 2>/dev/null || true

# Start new tunnel
pm2 start /usr/local/bin/cloudflared --name gandive-tunnel -- tunnel --url http://localhost:5000 --no-autoupdate
sleep 8

# Get new URL
NEW_URL=$(cat /home/enishshah2/.pm2/logs/gandive-tunnel-error.log 2>/dev/null | grep -oP 'https://[a-z-]+\.trycloudflare\.com' | tail -1)
echo "   ✅ Tunnel started"
echo "   📌 NEW WEBHOOK URL: ${NEW_URL:-CHECK PM2 LOGS}/kofi-webhook"
echo ""

# ─── Step 4: Verify everything ───
echo "🔍 Step 4/4: Verification..."
sleep 3

echo "   Checking services..."
pm2 status 2>/dev/null | head -10

echo ""
echo "   Checking webhook health..."
curl -s -o /dev/null -w "   Webhook: HTTP %{http_code}\n" http://localhost:5000/health 2>/dev/null || echo "   Webhook: OFFLINE"

echo ""
echo "   Testing tunnel via internet..."
if [ -n "$NEW_URL" ]; then
    TUNNEL_HTTP=$(curl -s -o /dev/null -w '%{http_code}' "${NEW_URL}/health" 2>/dev/null || echo "000")
    echo "   Tunnel: HTTP ${TUNNEL_HTTP}"
    if [ "$TUNNEL_HTTP" = "200" ]; then
        echo "   ✅ Tunnel is publicly reachable!"
    else
        echo "   ⚠️ Tunnel not reachable yet — wait 10s and retry"
    fi
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   ✅ STARTUP COMPLETE                        ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "⚠️  IMPORTANT: The tunnel URL changed!"
echo "   Go to https://ko-fi.com/manage/webhooks"
echo "   Update Webhook URL to: ${NEW_URL:-SEE ABOVE}/kofi-webhook"
echo ""
echo "📌 Useful commands:"
echo "   pm2 status              — View all processes"
echo "   pm2 logs gandive-bot    — View bot logs"
echo "   pm2 logs gandive-tunnel — View tunnel URL"
echo "   curl localhost:5000/health — Test webhook"

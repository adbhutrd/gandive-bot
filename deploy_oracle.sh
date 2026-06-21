#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════╗"
echo "║   🚀 GANDIVE BOT — Oracle Cloud Deploy Script       ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${YELLOW}What is your Oracle VM public IP?${NC}"
read -p "IP: " VM_IP

echo -e "${YELLOW}What is your Telegram bot token?${NC}"
read -p "Token: " BOT_TOKEN

echo -e "${YELLOW}What is your Telegram admin user ID?${NC}"
read -p "Admin ID: " ADMIN_ID

echo -e "${YELLOW}What is your Ko-fi verification token? (Create one in Ko-fi Settings → Webhooks)${NC}"
read -p "Token (or press Enter to skip): " KOFI_TOKEN

echo -e "${YELLOW}Twitter/X API Key? (optional — press Enter to skip)${NC}"
read -p "API Key: " TWITTER_KEY

echo -e "${YELLOW}Twitter/X API Secret?${NC}"
read -p "API Secret: " TWITTER_SECRET

echo -e "${YELLOW}Twitter/X Access Token?${NC}"
read -p "Access Token: " TWITTER_ACCESS

echo -e "${YELLOW}Twitter/X Access Token Secret?${NC}"
read -p "Token Secret: " TWITTER_TOKEN_SECRET

echo -e "${YELLOW}SMTP Host? (default: smtp.gmail.com — press Enter to skip)${NC}"
read -p "SMTP Host: " SMTP_HOST
SMTP_HOST=${SMTP_HOST:-}

echo -e "${YELLOW}SMTP Port? (default: 587)${NC}"
read -p "SMTP Port: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}

echo -e "${YELLOW}SMTP User (email)?${NC}"
read -p "SMTP User: " SMTP_USER

echo -e "${YELLOW}SMTP Password (app password)?${NC}"
read -p "SMTP Pass: " SMTP_PASS

echo -e "${YELLOW}Email From address?${NC}"
read -p "From: " EMAIL_FROM
EMAIL_FROM=${EMAIL_FROM:-$SMTP_USER}

echo ""
echo -e "${GREEN}Deploying to $VM_IP...${NC}"

ssh -o StrictHostKeyChecking=accept-new ubuntu@$VM_IP << 'REMOTE'
    set -e
    echo "📦 Updating system..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

    echo "🤖 Cloning GandiveBot..."
    cd ~
    git clone https://github.com/adbhutrd/gandive-bot.git
    cd gandive-bot

    echo "📚 Installing dependencies..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt

    echo "🔧 Installing PM2..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
    sudo npm install -g pm2

    echo "" > .env
REMOTE

# Send env vars securely
ssh ubuntu@$VM_IP "cat > ~/gandive-bot/.env << 'EOF'
GANDIVE_BOT_TOKEN=$BOT_TOKEN
ADMIN_USER_ID=$ADMIN_ID
KO_FI_VERIFICATION_TOKEN=${KOFI_TOKEN:-}
BOT_NAME=GandiveBot
BOT_USERNAME=GandiveBot
SCAN_INTERVAL=300
VOLUME_SPIKE_MULTIPLIER=3.0
PRICE_BREAKOUT_PCT=0.05
MIN_SIGNAL_CONFIDENCE=60
KO_FI_URL=https://ko-fi.com/adbhutrd
WEBHOOK_PORT=5000
DASHBOARD_PORT=8000

# Twitter/X API (optional - remove # to activate)
#TWITTER_API_KEY=$TWITTER_KEY
#TWITTER_API_SECRET=$TWITTER_SECRET
#TWITTER_ACCESS_TOKEN=$TWITTER_ACCESS
#TWITTER_ACCESS_TOKEN_SECRET=$TWITTER_TOKEN_SECRET

# SMTP Email (optional - remove # to activate)
#SMTP_HOST=$SMTP_HOST
#SMTP_PORT=$SMTP_PORT
#SMTP_USER=$SMTP_USER
#SMTP_PASS=$SMTP_PASS
#EMAIL_FROM=$EMAIL_FROM
EOF
chmod 600 ~/gandive-bot/.env"

# Launch all processes with PM2
ssh ubuntu@$VM_IP "cd ~/gandive-bot && source venv/bin/activate && \
pm2 start bot.py --interpreter python3 --name gandive-bot && \
pm2 start webhook_server.py --interpreter python3 --name gandive-webhook && \
pm2 start dashboard.py --interpreter python3 --name gandive-dashboard && \
pm2 save && \
pm2 startup"

# Open ports in firewall
ssh ubuntu@$VM_IP "sudo ufw allow 5000/tcp 2>/dev/null || true && sudo ufw allow 8000/tcp 2>/dev/null || true"

echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║   📋 POST-DEPLOYMENT CHECKLIST                      ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "1️⃣  CHECK ALL PROCESSES ARE RUNNING:"
echo "   ssh ubuntu@$VM_IP 'pm2 status'"
echo "   Should show: gandive-bot, gandive-webhook, gandive-dashboard"
echo ""
echo "2️⃣  CHECK LOGS:"
echo "   ssh ubuntu@$VM_IP 'pm2 logs gandive-bot --lines 20'"
echo "   ssh ubuntu@$VM_IP 'pm2 logs gandive-webhook --lines 10'"
echo "   ssh ubuntu@$VM_IP 'pm2 logs gandive-dashboard --lines 10'"
echo ""
echo "3️⃣  ACCESS DASHBOARD:"
echo "   http://$VM_IP:8000/ — Live signals, charts, performance stats"
echo "   http://$VM_IP:8000/api/data — JSON API for developers"
echo ""
echo "4️⃣  SET UP KO-FI WEBHOOK:"
echo "   - Go to: https://ko-fi.com/manage/webhooks"
echo "   - Add webhook URL: http://$VM_IP:5000/kofi-webhook"
echo "   - Set verification token (same as you entered above)"
echo ""
echo "5️⃣  ACTIVATE TWITTER/X (if you provided keys):"
echo "   ssh ubuntu@$VM_IP \"sed -i 's/^#TWITTER_/TWITTER_/g' ~/gandive-bot/.env && pm2 restart gandive-bot\""
echo "   Verifies on next scan cycle — auto-posts signals >= 80% confidence"
echo ""
echo "6️⃣  ACTIVATE EMAIL NEWSLETTER (if you provided SMTP):"
echo "   ssh ubuntu@$VM_IP \"sed -i 's/^#SMTP_/SMTP_/g; s/^#EMAIL_FROM/EMAIL_FROM/g' ~/gandive-bot/.env && pm2 restart all\""
echo "   Sends daily digest to all subscribers automatically"
echo ""
echo "7️⃣  SET UP LANDING PAGE:"
echo "   Deploy to GitHub Pages for the public-facing site:"
echo "   - Go to github.com/adbhutrd/gandive-bot → Settings → Pages"
echo "   - Set source to 'main' branch, folder '/website'"
echo "   - Your page will be at: https://adbhutrd.github.io/gandive-bot/"
echo ""
echo "   OR serve the website from your VM for email subscribe to work:"
echo "   - The webhook server handles email signups at http://$VM_IP:5000/subscribe"
echo "   - Update the landing page JS to POST to http://$VM_IP:5000/subscribe"
echo ""
echo "6️⃣  TEST THE BOT:"
echo "   - Open Telegram and message @GandiveBot"
echo "   - Send /start to see commands (referral deep links work!)"
echo "   - Send /signals to get your first signals"
echo "   - Send /perf to see signal win rate"
echo "   - Send /referral to get your referral link"
echo ""
echo "7️⃣  TEST PREMIUM:"
echo "   - Send /addpremium YOUR_ID 30 to test premium"
echo "   - Then /signals again (should show unlimited)"
echo "   - Test /report for detailed performance (premium only)"
echo ""
echo "8️⃣  MONITORING:"
echo "  pm2 logs gandive-bot       # Bot logs"
echo "  pm2 logs gandive-webhook   # Webhook logs (payments)"
echo "  pm2 logs gandive-dashboard # Dashboard logs"
echo "  pm2 monit                  # CPU/RAM dashboard"
echo "  pm2 restart all            # Restart all processes"
echo ""
echo "💰 REVENUE CHANNELS:"
echo "  • Ko-fi: https://ko-fi.com/adbhutrd"
echo "  • Premium: $9.99/mo (unlimited signals)"
echo "  • Elite: $24.99/mo (custom alerts + API)"
echo "  • Referrals: 7 free days per referral"
echo "  • Email: Daily digest newsletter"
echo ""

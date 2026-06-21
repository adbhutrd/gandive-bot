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

echo ""
echo -e "${GREEN}Deploying to $VM_IP...${NC}"

# Create deploy commands for the remote server
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

# Send env vars securely via SSH
ssh ubuntu@$VM_IP "cat > ~/gandive-bot/.env << 'EOF'
GANDIVE_BOT_TOKEN=$BOT_TOKEN
ADMIN_USER_ID=$ADMIN_ID
BOT_NAME=GandiveBot
BOT_USERNAME=GandiveBot
SCAN_INTERVAL=300
VOLUME_SPIKE_MULTIPLIER=3.0
PRICE_BREAKOUT_PCT=0.05
MIN_SIGNAL_CONFIDENCE=60
KO_FI_URL=https://ko-fi.com/adbhutrd
EOF
chmod 600 ~/gandive-bot/.env"

# Start the bot with PM2
ssh ubuntu@$VM_IP "cd ~/gandive-bot && source venv/bin/activate && pm2 start bot.py --interpreter python3 --name gandive-bot && pm2 save && pm2 startup"

echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Bot is running 24/7 on Oracle Cloud!"
echo ""
echo "Commands:"
echo "  Check logs: pm2 logs gandive-bot"
echo "  Restart:    pm2 restart gandive-bot"
echo "  Monitor:    pm2 monit"

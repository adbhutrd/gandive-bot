#!/bin/bash
#
# ═══════════════════════════════════════════════════════════════
# 🤖 GANDIVE BOT — Auto Setup Script
# Premium Crypto Signal Telegram Bot
# ═══════════════════════════════════════════════════════════════
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════╗"
echo "║   🤖 GANDIVE BOT — Premium Crypto Signal Bot        ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed. Please install Python 3.10+.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python $(python3 --version)${NC}"

# Check pip
if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}📦 Installing pip...${NC}"
    sudo apt-get install -y python3-pip
fi

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}📦 Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}📚 Installing Python packages...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}📝 Creating .env file from template...${NC}"
    cp .env.example .env
    chmod 600 .env
    echo -e "${RED}⚠️  Edit .env with your bot token and admin ID before starting!${NC}"
fi

# Create log directory
mkdir -p logs

echo ""
echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env:  nano .env"
echo "  2. Run bot:    python bot.py"
echo "  3. Or deploy as service:"
echo "     sudo cp gandive-bot.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable gandive-bot"
echo "     sudo systemctl start gandive-bot"
echo ""
echo "Check logs: journalctl -u gandive-bot -f"

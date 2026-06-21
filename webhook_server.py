#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   💰 GANDIVE BOT — Ko-fi Webhook Server                    ║
║   Auto-activates premium when users pay via Ko-fi.          ║
╚═══════════════════════════════════════════════════════════════╝

Setup:
  1. Run: python webhook_server.py
  2. Expose via: ssh -R 80:localhost:5000 localhost.run
  3. Add webhook URL in Ko-fi: Settings → Webhooks → https://your-url/kofi-webhook

  4. Users include their Telegram user ID in their Ko-fi payment message.
  5. Bot auto-activates premium for the user.
"""

import os
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ─── Setup logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("kofi-webhook")

# ─── Import premium system ───
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

# ─── Load .env ───
ENV_PATH = BASE_DIR / ".env"
def _load_env():
    """Load environment variables from .env file."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
        logger.info("✅ .env file loaded")
    except ImportError:
        logger.warning("⚠️ python-dotenv not installed, relying on system env vars")
    except Exception as e:
        logger.warning(f"⚠️ Could not load .env: {e}")

_load_env()

try:
    from premium import add_premium_user, get_premium_stats, save_state
    logger.info("✅ Premium system loaded")
except ImportError as e:
    logger.error(f"❌ Failed to load premium module: {e}")
    logger.error("Make sure premium.py is in the same directory.")
    sys.exit(1)

try:
    from email_service import add_subscriber, get_subscriber_count
    logger.info("✅ Email service loaded")
except ImportError as e:
    logger.warning(f"Email service not available: {e}")
    def add_subscriber(email, name="", source="webhook"): return True
    def get_subscriber_count(): return 0

# ─── Config ───
KO_FI_VERIFICATION_TOKEN = os.getenv("KO_FI_VERIFICATION_TOKEN", "")

# Warn if verification token is not set
if not KO_FI_VERIFICATION_TOKEN:
    logger.warning("⚠️  KO_FI_VERIFICATION_TOKEN not set! Anyone can activate premium via webhook.")
    logger.warning("   Set it in .env: KO_FI_VERIFICATION_TOKEN=your_verification_token_from_kofi")
PORT = int(os.getenv("WEBHOOK_PORT", "5000"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# ─── Telegram notification helper ───
BOT_TOKEN = os.getenv("GANDIVE_BOT_TOKEN", "")

def telegram_send(chat_id: int, text: str):
    """Send a Telegram message."""
    if not BOT_TOKEN:
        return
    import requests
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# ─── Webhook handler ───

class KoFiHandler(BaseHTTPRequestHandler):
    """HTTP handler for Ko-fi webhook callbacks."""
    
    def do_GET(self):
        """Health check."""
        path = urlparse(self.path).path
        
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            stats = get_premium_stats()
            self.wfile.write(json.dumps({
                "status": "ok",
                "service": "gandive-bot-webhook",
                "premium_users": stats["active"],
                "email_subscribers": get_subscriber_count(),
            }).encode())
            return
        
        # Redirect root to health
        self.send_response(302)
        self.send_header("Location", "/health")
        self.end_headers()
    
    def do_POST(self):
        """Handle Ko-fi webhook POST."""
        path = urlparse(self.path).path
        
        # Read body first (needed by all POST handlers)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        if path == "/subscribe":
            self._handle_subscribe(body)
            return
        
        if path != "/kofi-webhook":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')
            return
        
        # Ko-fi sends form-encoded data in a 'data' field
        try:
            raw_data = body.decode("utf-8")
            logger.info(f"Raw webhook received: {raw_data[:200]}")
            
            # Parse form-encoded payload
            import urllib.parse
            parsed = urllib.parse.parse_qs(raw_data)
            json_str = parsed.get("data", [None])[0]
            
            if not json_str:
                self._respond(400, "Missing data field")
                return
            
            data = json.loads(json_str)
            
        except Exception as e:
            logger.error(f"Failed to parse webhook: {e}")
            self._respond(400, "Invalid payload")
            return
        
        # Verify verification token if configured
        verify_token = data.get("verification_token", "")
        if KO_FI_VERIFICATION_TOKEN and verify_token != KO_FI_VERIFICATION_TOKEN:
            logger.warning(f"Invalid verification token: {verify_token}")
            self._respond(403, "Invalid verification token")
            return
        
        # Extract payment details
        email = data.get("email", "unknown")
        amount = data.get("amount", "0")
        currency = data.get("currency", "USD")
        message = data.get("message", "") or ""
        from_name = data.get("from_name", email)
        timestamp = data.get("timestamp", datetime.now().isoformat())
        
        logger.info(f"💰 Ko-fi payment received: {amount} {currency} from {from_name} ({email})")
        
        # Try to extract Telegram user ID from message
        user_id = self._extract_user_id(message)
        
        if user_id:
            # Determine tier based on amount
            amount_float = float(amount) if amount else 0
            days, tier = self._determine_tier(amount_float, currency)
            
            if days > 0:
                # Activate premium
                note = f"kofi_{from_name}_{email}"
                user_info = add_premium_user(user_id, tier, days, note)
                
                expiry = datetime.fromtimestamp(user_info["expires_at"])
                success_msg = (
                    f"🎉 <b>PREMIUM ACTIVATED!</b>\n\n"
                    f"👤 User: <code>{user_id}</code>\n"
                    f"💰 Amount: {amount} {currency}\n"
                    f"⭐ Tier: {tier.upper()}\n"
                    f"📅 Duration: {days} days\n"
                    f"⏳ Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}\n"
                    f"💳 Source: Ko-fi ({from_name})\n\n"
                    f"Thank you for supporting GandiveBot! 🚀"
                )
                
                # Notify user
                telegram_send(user_id,
                    f"🎉 <b>Welcome to GandiveBot Premium!</b>\n\n"
                    f"Thank you for subscribing! Your {tier.upper()} plan has been activated.\n"
                    f"Duration: {days} days\n\n"
                    f"Use /signals to start receiving premium signals instantly!\n"
                    f"/myplan to check your subscription.\n\n"
                    f"<i>Thanks for supporting GandiveBot!</i> 🚀"
                )
                
                logger.info(f"✅ Premium activated: user={user_id}, tier={tier}, days={days}")
            else:
                success_msg = (
                    f"⚠️ <b>Ko-fi payment received but amount too low for premium.</b>\n"
                    f"Amount: {amount} {currency}\n"
                    f"From: {from_name} ({email})\n"
                    f"Minimum: $9.99 / €9.99 for Premium\n\n"
                    f"No premium activated. Please contact the user."
                )
                user_id = None
        else:
            success_msg = (
                f"⚠️ <b>Ko-fi payment received but NO USER ID in message!</b>\n"
                f"Amount: {amount} {currency}\n"
                f"From: {from_name} ({email})\n"
                f"Message: {message}\n\n"
                f"Ask the user to message @GandiveBot with their Ko-fi transaction ID."
            )
        
        # Always notify admin
        if ADMIN_USER_ID:
            telegram_send(ADMIN_USER_ID, success_msg)
        
        self._respond(200, {
            "status": "ok",
            "user_id": user_id,
            "tier": tier if user_id else None,
            "days": days if user_id else 0,
        })
    
    def _handle_subscribe(self, body: bytes):
        """Handle email subscription from landing page."""
        try:
            data = json.loads(body.decode("utf-8"))
            email = data.get("email", "").strip()
            name = data.get("name", "").strip()
            
            if not email or "@" not in email:
                self._respond(400, {"success": False, "message": "Invalid email"})
                return
            
            add_subscriber(email, name, "landing_page")
            
            # Notify admin
            if ADMIN_USER_ID:
                telegram_send(ADMIN_USER_ID,
                    f"📧 <b>New Subscriber!</b>\n\n"
                    f"Email: {email}\n"
                    f"Name: {name or 'N/A'}\n"
                    f"Total subscribers: {get_subscriber_count()}"
                )
            
            logger.info(f"📧 New subscriber via webhook: {email}")
            self._respond(200, {
                "success": True,
                "message": "Subscribed! Welcome to GandiveBot.",
            })
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            self._respond(500, {"success": False, "message": str(e)[:100]})

    def _extract_user_id(self, message: str) -> int:
        """Extract Telegram user ID from Ko-fi payment message.
        
        Users MUST put their Telegram user ID in the payment message
        in one of these formats:
          - "ID: 123456789"
          - "User ID: 123456789"
          - "user_id=123456789"
          - "UID: 123456789"
        """
        if not message:
            return 0
        
        import re
        # Require an explicit prefix to avoid matching dates, amounts, etc.
        id_patterns = [
            r'(?:USER|UID|ID|TELEGRAM)[_\s]*(?:ID)?\s*[:=]\s*(\d{6,})',
            r'(?:user|uid|id|telegram)[_\s]*(?:id)?\s*[:=]\s*(\d{6,})',
        ]
        
        for pattern in id_patterns:
            match = re.search(pattern, message)
            if match:
                uid = int(match.group(1))
                if 1000000 <= uid <= 9999999999:
                    return uid
        
        return 0
    
    def _determine_tier(self, amount: float, currency: str) -> tuple:
        """Determine tier and days based on payment amount."""
        # Convert to USD roughly
        usd_amount = amount
        if currency == "EUR":
            usd_amount = amount * 1.08
        elif currency == "GBP":
            usd_amount = amount * 1.27
        elif currency == "INR":
            usd_amount = amount * 0.012
        
        # Pricing tiers
        if usd_amount >= 24.99:
            return 30, "elite"
        elif usd_amount >= 19.99:
            return 90, "premium"  # Quarterly
        elif usd_amount >= 9.99:
            return 30, "premium"  # Monthly
        elif usd_amount >= 5.0:
            return 14, "premium"  # 2-week trial
        else:
            return 0, "premium"  # Too low
    
    def _respond(self, code: int, data):
        """Send JSON response."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if isinstance(data, str):
            self.wfile.write(json.dumps({"status": "error", "message": data}).encode())
        else:
            self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")


# ─── Main ───

def main():
    server = HTTPServer(("0.0.0.0", PORT), KoFiHandler)
    logger.info(f"💰 Ko-fi webhook server running on http://0.0.0.0:{PORT}")
    logger.info(f"   Webhook endpoint: POST /kofi-webhook")
    logger.info(f"   Health check:      GET /")
    logger.info(f"")
    logger.info(f"   To expose publicly, run in another terminal:")
    logger.info(f"     ssh -R 80:localhost:{PORT} localhost.run")
    logger.info(f"")
    logger.info(f"   Then add this URL in Ko-fi → Settings → Webhooks:")
    logger.info(f"     https://your-url.koyeb.app/kofi-webhook")
    logger.info(f"")
    logger.info(f"   Users must include their Telegram user ID")
    logger.info(f"   in their Ko-fi payment message!")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()

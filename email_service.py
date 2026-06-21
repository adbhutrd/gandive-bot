#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   📧 GANDIVE BOT — Email Service                           ║
║   Collect emails & send daily signal digest emails          ║
╚═══════════════════════════════════════════════════════════════╝

Setup:
  1. Add email settings to .env:
       EMAIL_FROM=your@email.com
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=your@email.com
       SMTP_PASS=your_app_password
  
  2. Users subscribe via landing page email form
  3. Daily digest sent automatically
"""

import os
import json
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger("gandive-email")

BASE_DIR = Path(__file__).parent.resolve()
EMAIL_FILE = BASE_DIR / "email_subscribers.json"

# ─── Subscriber Management ────────────────────────────────────────

def load_subscribers() -> Dict[str, dict]:
    """Load email subscribers."""
    if not EMAIL_FILE.exists():
        return {}
    try:
        return json.loads(EMAIL_FILE.read_text())
    except Exception:
        return {}


def save_subscribers(subscribers: dict):
    """Save email subscribers."""
    EMAIL_FILE.write_text(json.dumps(subscribers, indent=2))


def add_subscriber(email: str, name: str = "", source: str = "website") -> bool:
    """Add an email subscriber. Returns True if new, False if already exists."""
    subscribers = load_subscribers()
    email_lower = email.lower().strip()
    
    if email_lower in subscribers:
        # Update existing
        subscribers[email_lower]["updated_at"] = time.time()
        subscribers[email_lower]["source"] = source
        if name:
            subscribers[email_lower]["name"] = name
        save_subscribers(subscribers)
        return False
    
    subscribers[email_lower] = {
        "email": email_lower,
        "name": name or "",
        "subscribed_at": time.time(),
        "updated_at": time.time(),
        "source": source,
        "digest_preference": "daily",
        "unsubscribed": False,
    }
    save_subscribers(subscribers)
    logger.info(f"📧 New subscriber: {email_lower}")
    return True


def remove_subscriber(email: str) -> bool:
    """Remove an email subscriber (unsubscribe)."""
    subscribers = load_subscribers()
    email_lower = email.lower().strip()
    if email_lower in subscribers:
        subscribers[email_lower]["unsubscribed"] = True
        subscribers[email_lower]["updated_at"] = time.time()
        save_subscribers(subscribers)
        logger.info(f"📧 Unsubscribed: {email_lower}")
        return True
    return False


def get_active_subscribers() -> List[dict]:
    """Get list of active subscribers."""
    subscribers = load_subscribers()
    return [s for s in subscribers.values() if not s.get("unsubscribed", False)]


def get_subscriber_count() -> int:
    """Get total subscriber count."""
    return len(get_active_subscribers())


# ─── Email Sending ────────────────────────────────────────────────

def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send an email via SMTP."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("EMAIL_FROM", "gandive@bot.com")

    if not all([smtp_host, smtp_user, smtp_pass]):
        # In dev mode, just log and save to file
        logger.info(f"📧 [DEV] Would send email to {to_email}: {subject}")
        _save_email_draft(to_email, subject, html_body)
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info(f"📧 Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        _save_email_draft(to_email, subject, html_body)
        return False


def _save_email_draft(to_email: str, subject: str, html_body: str):
    """Save email as draft file (for dev/debugging)."""
    drafts_dir = BASE_DIR / "email_drafts"
    drafts_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_email = to_email.replace("@", "_at_").replace(".", "_")
    draft_file = drafts_dir / f"{timestamp}_{safe_email}.html"
    draft_file.write_text(
        f"<!-- To: {to_email} | Subject: {subject} -->\n{html_body}"
    )


# ─── Email Templates ──────────────────────────────────────────────

def build_daily_digest(signals: list, performance: dict = None) -> str:
    """Build a daily signal digest HTML email."""
    now = datetime.now().strftime("%B %d, %Y")

    # Signal items
    signal_items = ""
    for s in signals[:5]:
        emoji = {"BUY": "🟢", "SELL": "🔴", "WHALE": "🐋", "MOMENTUM": "⚡"}.get(s.get("type", ""), "📊")
        signal_items += f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #2a2a3a;">
            <span style="font-size:18px;">{emoji}</span>
            <strong style="color:#e8e8f0;margin-left:8px;">{s.get('pair', 'N/A')}</strong>
            <span style="color:{'#22c55e' if s.get('type') in ('BUY','MOMENTUM') else '#ef4444'};margin-left:8px;">{s.get('type', '')}</span>
          </td>
          <td style="padding:12px;border-bottom:1px solid #2a2a3a;color:#e8e8f0;">
            ${s.get('price', 0):,.4f}
          </td>
          <td style="padding:12px;border-bottom:1px solid #2a2a3a;color:#8888a0;font-size:13px;">
            {s.get('reason', '')[:60]}
          </td>
        </tr>"""

    if performance:
        perf_html = f"""
        <div style="background:#1a1a26;border:1px solid #2a2a3a;border-radius:12px;padding:16px;margin:24px 0;">
          <h3 style="color:#f7931a;margin:0 0 12px;">📊 Performance Summary</h3>
          <table style="width:100%;">
            <tr>
              <td style="padding:8px;color:#8888a0;">Win Rate</td>
              <td style="padding:8px;text-align:right;color:#22c55e;font-weight:700;">{performance.get('win_rate', 0)}%</td>
            </tr>
            <tr>
              <td style="padding:8px;color:#8888a0;">Total P&L</td>
              <td style="padding:8px;text-align:right;color:#22c55e;font-weight:700;">{performance.get('total_pnl_pct', 0):+.2f}%</td>
            </tr>
            <tr>
              <td style="padding:8px;color:#8888a0;">Signals Today</td>
              <td style="padding:8px;text-align:right;color:#e8e8f0;font-weight:700;">{performance.get('total_signals', 0)}</td>
            </tr>
          </table>
        </div>"""
    else:
        perf_html = ""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background:#0a0a0f;font-family:-apple-system,sans-serif;padding:24px;margin:0;">
      <div style="max-width:600px;margin:0 auto;">
        <div style="text-align:center;padding:32px 0;">
          <h1 style="color:#e8e8f0;margin:0;">🤖 GandiveBot</h1>
          <p style="color:#8888a0;margin:4px 0 0;">Daily Signal Digest — {now}</p>
        </div>

        {perf_html}

        <div style="background:#1a1a26;border:1px solid #2a2a3a;border-radius:12px;overflow:hidden;">
          <div style="padding:16px;border-bottom:1px solid #2a2a3a;">
            <h2 style="color:#e8e8f0;margin:0;font-size:18px;">📡 Latest Signals</h2>
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#12121a;">
                <th style="padding:10px 12px;text-align:left;color:#8888a0;font-size:12px;">Pair</th>
                <th style="padding:10px 12px;text-align:left;color:#8888a0;font-size:12px;">Price</th>
                <th style="padding:10px 12px;text-align:left;color:#8888a0;font-size:12px;">Signal</th>
              </tr>
            </thead>
            <tbody>
              {signal_items if signal_items else '<tr><td colspan="3" style="padding:24px;text-align:center;color:#8888a0;">No signals yet today</td></tr>'}
            </tbody>
          </table>
        </div>

        <div style="text-align:center;padding:32px 0;">
          <p style="color:#8888a0;font-size:13px;">
            💎 <a href="https://ko-fi.com/adbhutrd" style="color:#f7931a;">Upgrade to Premium</a> for unlimited instant signals
          </p>
          <p style="color:#8888a0;font-size:12px;margin-top:16px;">
            <a href="#" style="color:#8888a0;">Unsubscribe</a> • Not financial advice
          </p>
        </div>
      </div>
    </body>
    </html>"""


# ─── Email Webhook Endpoint ───────────────────────────────────────

# This gets integrated into webhook_server.py
EMAIL_ENDPOINT = "/subscribe"


def handle_subscribe_request(data: dict) -> dict:
    """Handle a subscription request from the landing page."""
    email = data.get("email", "").strip()
    name = data.get("name", "").strip()
    
    if not email or "@" not in email:
        return {"success": False, "message": "Invalid email address"}
    
    is_new = add_subscriber(email, name)
    
    # Send welcome email
    welcome_html = f"""
    <div style="background:#0a0a0f;font-family:-apple-system,sans-serif;padding:24px;">
      <div style="max-width:500px;margin:0 auto;background:#1a1a26;border:1px solid #2a2a3a;border-radius:12px;padding:32px;">
        <h1 style="color:#e8e8f0;margin:0 0 8px;">🤖 Welcome to GandiveBot!</h1>
        <p style="color:#8888a0;margin:0 0 24px;">You're now subscribed to daily crypto signal digests.</p>
        <p style="color:#e8e8f0;">Every day you'll receive:<br>
        📈 Top crypto signals<br>
        📊 Performance analytics<br>
        🐋 Whale movement alerts</p>
        <div style="margin-top:24px;padding-top:24px;border-top:1px solid #2a2a3a;">
          <p style="color:#8888a0;font-size:12px;">
            💎 <a href="https://ko-fi.com/adbhutrd" style="color:#f7931a;">Upgrade to Premium</a> for instant signals
          </p>
        </div>
      </div>
    </div>"""
    
    send_email(email, "Welcome to GandiveBot! 🚀", welcome_html,
               "Welcome to GandiveBot! You're subscribed to daily signal digests.")
    
    return {"success": True, "message": "Subscribed! Check your inbox for confirmation."}


def send_daily_digest():
    """Send daily signal digest to all subscribers."""
    from signals import get_cached_signals
    from performance import get_performance_stats
    
    signals = get_cached_signals(max_age_seconds=86400) or []
    perf = get_performance_stats(days=1)
    
    subscribers = get_active_subscribers()
    if not subscribers:
        logger.info("No subscribers for daily digest")
        return 0
    
    html = build_daily_digest(
        [{"type": s.type, "pair": s.pair, "price": s.price, "reason": s.reason} for s in signals],
        perf
    )
    
    sent = 0
    for sub in subscribers:
        if send_email(sub["email"], f"🤖 GandiveBot Daily Digest", html):
            sent += 1
        time.sleep(0.5)  # Rate limiting
    
    logger.info(f"📧 Daily digest sent to {sent}/{len(subscribers)} subscribers")
    return sent

#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   🤖 GANDIVE BOT — Premium Crypto Signal Telegram Bot       ║
║                                                              ║
║   Commands:                                                  ║
║     /start     — Welcome + help                              ║
║     /signals   — Get latest trading signals (rate-limited)   ║
║     /subscribe — Premium pricing & payment                   ║
║     /pricing   — Same as /subscribe                          ║
║     /pairs     — Show monitored crypto pairs                 ║
║     /trending  — Show trending coins (premium)               ║
║     /alert     — Set custom price alert (elite)              ║
║     /status    — Bot status                                  ║
║     /help      — Show all commands                           ║
║                                                              ║
║   Admin Commands:                                            ║
║     /addpremium <user_id> <days> [tier]  — Grant premium     ║
║     /removepremium <user_id>             — Revoke premium    ║
║     /listpremium                         — List premium users║
║     /premiumstats                        — Premium stats     ║
║     /broadcast <msg>                     — Message all users ║
╚═══════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

import requests
from dotenv import load_dotenv

# ─── Project imports ──────────────────────────────────────────────
from premium import (
    add_premium_user, remove_premium_user, get_user_tier,
    get_premium_users_list, get_premium_stats, get_subscribe_message,
    get_signal_delay, get_signal_pairs, check_rate_limit,
    increment_signal_usage, increment_signal_count,
    get_active_user_ids, get_user_info,
    cleanup_expired, save_state,
)
from signals import (
    scan_all_pairs, cache_signals, get_cached_signals,
    fetch_trending_coins, DEFAULT_PAIRS, Signal,
)
from performance import (
    get_performance_stats, get_performance_message, get_detailed_report,
    record_signal, report_outcome, auto_resolve_signals,
)
from referral import (
    generate_referral_code, apply_referral, get_referral_stats,
    get_referral_message, get_admin_referral_stats,
)
from social_poster import try_post_signals
from email_service import get_subscriber_count

# ─── Setup ────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.resolve()
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

# Telegram config
BOT_TOKEN = os.getenv("GANDIVE_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "")

# Convert admin ID to int for comparison
try:
    ADMIN_ID = int(ADMIN_USER_ID) if ADMIN_USER_ID else None
except ValueError:
    ADMIN_ID = None

# Bot info
BOT_NAME = os.getenv("BOT_NAME", "GandiveBot")
BOT_USERNAME = os.getenv("BOT_USERNAME", "GandiveBot")
BOT_VERSION = "1.0.0"

# Scan interval (seconds)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))  # 5 minutes

# Telegram API base
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(BASE_DIR / "bot.log")),
    ],
)
logger = logging.getLogger("gandive-bot")


# ─── Telegram Helpers ─────────────────────────────────────────────

def telegram_send(chat_id: int, text: str, parse_mode: str = "HTML",
                  disable_preview: bool = True,
                  reply_markup: dict = None) -> Optional[Dict]:
    """Send a message to a Telegram chat."""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"Telegram send failed ({r.status_code}): {r.text[:100]}")
        return None
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return None


def send_typing(chat_id: int):
    """Show typing indicator."""
    url = f"{TELEGRAM_API}/sendChatAction"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "action": "typing",
        }, timeout=5)
    except Exception:
        pass


def send_alert_to_admin(message: str):
    """Send an alert to the bot admin."""
    if ADMIN_ID:
        telegram_send(ADMIN_ID, f"<b>🤖 GandiveBot Alert</b>\n\n{message}")


# ─── Command Handlers ─────────────────────────────────────────────

def cmd_start(chat_id: int, user_id: int, args: List[str] = None):
    """Welcome message with bot overview. Handles referral deep links."""
    
    # Check for referral code (format: /start ref_CODE)
    if args and args[0].startswith("ref_"):
        code = args[0][4:]  # Strip "ref_" prefix
        logger.info(f"Referral deep link: user {user_id} using code {code}")
        try:
            from referral import apply_referral
            success, ref_msg = apply_referral(user_id, code)
            if success:
                telegram_send(chat_id, ref_msg)
            # Still show welcome even if referral fails
        except Exception as e:
            logger.error(f"Referral error: {e}")
    
    tier = get_user_tier(user_id)
    tier_icon = "👑" if tier == "elite" else "⭐" if tier == "premium" else "🆓"
    tier_name = tier.capitalize()

    msg = (
        f"<b>🚀 Welcome to {BOT_NAME}!</b>\n\n"
        f"<i>Your personal crypto signal bot — powered by AI.</i>\n\n"
        f"👤 <b>Your tier:</b> {tier_icon} {tier_name}\n\n"
        f"<b>📊 What I do:</b>\n"
        f"• 📈 Detect volume spikes on top meme coins\n"
        f"• 🚀 Identify price breakouts in real-time\n"
        f"• 🐋 Track whale transactions\n"
        f"• ⚡ Catch momentum shifts early\n\n"
        f"<b>🤖 Commands:</b>\n"
        f"/signals  — Latest trading signals\n"
        f"/perf     — Signal win rate & performance\n"
        f"/referral — Get your referral link & earn free premium\n"
        f"/subscribe — Premium pricing & tiers\n"
        f"/pairs    — Monitored crypto pairs\n"
        f"/trending — Hot trending coins\n"
        f"/status   — Bot status\n"
        f"/help     — Full command list\n\n"
        f"<i>Not financial advice. Always DYOR.</i>"
    )

    telegram_send(chat_id, msg)


def cmd_help(chat_id: int, user_id: int):
    """Show all available commands based on user tier."""
    tier = get_user_tier(user_id)
    is_admin = user_id == ADMIN_ID

    msg = (
        f"<b>📋 {BOT_NAME} Commands</b>\n\n"
        f"<b>📊 Signals:</b>\n"
        f"/signals   — Get latest trading signals\n"
        f"/pairs     — Show monitored crypto pairs\n"
        f"/trending  — 🔥 Hot trending coins\n"
        f"/alert     — ⭐ Set custom price alert (Elite)\n\n"
        f"<b>💎 Premium:</b>\n"
        f"/subscribe — View pricing & subscribe\n"
        f"/pricing   — Same as /subscribe\n"
        f"/myplan    — Check your current plan\n\n"
        f"<b>ℹ️ Info:</b>\n"
        f"/start     — Welcome screen\n"
        f"/status    — Bot health & stats\n"
        f"/help      — This message\n"
    )

    if is_admin:
        msg += (
            f"\n<b>🔧 Admin Commands:</b>\n"
            f"/addpremium &lt;id&gt; &lt;days&gt; [tier]\n"
            f"/removepremium &lt;id&gt;\n"
            f"/listpremium\n"
            f"/premiumstats\n"
            f"/broadcast &lt;msg&gt;\n"
        )

    telegram_send(chat_id, msg)


def cmd_signals(chat_id: int, user_id: int):
    """Get latest trading signals with rate limiting for free users."""
    send_typing(chat_id)

    tier = get_user_tier(user_id)
    is_premium = tier in ("premium", "elite")

    # Rate limit check (does NOT increment counter — just checks)
    allowed, reason = check_rate_limit(user_id)
    if not allowed:
        telegram_send(chat_id, f"⏳ {reason}")
        return

    # Only read from cache — never scan directly on user request.
    # Background scanner handles caching every SCAN_INTERVAL seconds.
    signals = get_cached_signals(max_age_seconds=SCAN_INTERVAL + 60)
    if not signals:
        telegram_send(chat_id, "🔍 Scanner is warming up — signals will be available within a few minutes. Check back soon!")
        return

    # Filter and limit signals based on tier
    delay = get_signal_delay(user_id)
    max_signals = 5 if is_premium else 3

    # Filter by confidence
    high_confidence = [s for s in signals if s.confidence >= 70]
    medium = [s for s in signals if s.confidence >= 50 and s not in high_confidence]

    selected = high_confidence[:max_signals]
    if len(selected) < max_signals:
        selected.extend(medium[:max_signals - len(selected)])

    if not selected:
        telegram_send(chat_id, "📭 No high-confidence signals right now. Markets are quiet. Check back soon!")
        return

    # Send signals
    header = f"<b>📊 Latest Signals</b>\n"
    header += f"<i>Tier: {'💎 Premium' if is_premium else '🆓 Free'}</i>\n\n"
    telegram_send(chat_id, header)

    sent_count = 0
    for signal in selected:
        msg = signal.format_message(delay_minutes=delay)
        result = telegram_send(chat_id, msg)
        if result:
            sent_count += 1
        time.sleep(0.3)  # Avoid flood limits

    # Increment counter ONLY after signals were actually sent
    if sent_count > 0:
        increment_signal_usage(user_id)
        increment_signal_count()

    # Footer with upgrade prompt for free users
    if not is_premium:
        footer = (
            f"\n<i>💡 Get instant signals, whale alerts, and all 20+ pairs with Premium!</i>\n"
            f"/subscribe"
        )
        telegram_send(chat_id, footer)


def cmd_subscribe(chat_id: int, user_id: int):
    """Show premium pricing and subscription info."""
    tier = get_user_tier(user_id)
    is_premium = tier in ("premium", "elite")

    msg = get_subscribe_message()

    if is_premium:
        user_info = get_user_info(user_id)
        if user_info:
            expiry = user_info.get("expires_at", 0)
            if expiry > time.time():
                remaining = int((expiry - time.time()) / 86400)
                msg += f"\n\n<b>✅ Your Plan:</b> {tier.upper()}\n"
                msg += f"⏳ Expires in {remaining} days"
            else:
                msg += f"\n\n<b>⚠️ Your premium has expired.</b> Renew to continue!"

    telegram_send(chat_id, msg)


def cmd_pairs(chat_id: int, user_id: int):
    """Show monitored crypto pairs."""
    tier = get_user_tier(user_id)
    is_premium = tier in ("premium", "elite")

    pairs = DEFAULT_PAIRS if is_premium else DEFAULT_PAIRS[:5]

    msg = f"<b>📊 Monitored Pairs</b>\n\n"
    msg += f"<i>We scan {len(pairs)} pairs for signals</i>\n\n"

    for pair in pairs:
        msg += f"• <code>{pair}</code>\n"

    if not is_premium:
        msg += f"\n<i>💎 Premium users get all {len(DEFAULT_PAIRS)} pairs + whale alerts!</i>\n"
        msg += f"/subscribe"

    telegram_send(chat_id, msg)


def cmd_trending(chat_id: int, user_id: int):
    """Show trending coins (premium feature for instant, free gets delayed)."""
    send_typing(chat_id)

    tier = get_user_tier(user_id)
    is_premium = tier in ("premium", "elite")

    trending = fetch_trending_coins()
    if not trending:
        telegram_send(chat_id, "Could not fetch trending data. Try again later.")
        return

    msg = "<b>🔥 Trending Coins Right Now</b>\n\n"
    for i, coin in enumerate(trending[:10], 1):
        rank = coin.get("market_cap_rank", "N/A")
        msg += f"{i}. <b>{coin['name']}</b> (<code>{coin['symbol']}</code>) — Rank #{rank}\n"

    if not is_premium:
        msg += f"\n<i>💎 Premium users get real-time tracking + alerts on trending coins!</i>\n"
        msg += f"/subscribe"

    telegram_send(chat_id, msg)


def cmd_status(chat_id: int, user_id: int):
    """Show bot status and stats."""
    stats = get_premium_stats()
    from signals import CACHE_FILE

    signals_cached = 0
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            signals_cached = len(data.get("signals", []))
        except Exception:
            pass

    uptime_seconds = time.time() - bot_start_time

    msg = (
        f"<b>🤖 {BOT_NAME} Status</b>\n\n"
        f"<b>Version:</b> {BOT_VERSION}\n"
        f"<b>Uptime:</b> {format_uptime(uptime_seconds)}\n"
        f"<b>Scan interval:</b> Every {SCAN_INTERVAL}s\n\n"
        f"<b>📊 Stats:</b>\n"
        f"• Active premium users: {stats['active']}\n"
        f"• Total signals cached: {signals_cached}\n"
        f"• Monitored pairs: {len(DEFAULT_PAIRS)}\n"
        f"• Newsletter subscribers: {get_subscriber_count()}\n\n"
        f"<b>💎 Premium:</b>\n"
        f"• Total users: {stats['total_users']}\n"
        f"• Active: {stats['active']}\n"
        f"• By tier: {stats['by_tier']}\n"
    )

    telegram_send(chat_id, msg)


def cmd_myplan(chat_id: int, user_id: int):
    """Show current plan details."""
    tier = get_user_tier(user_id)

    if tier == "free":
        msg = (
            f"<b>🆓 Your Plan: Free</b>\n\n"
            f"<b>Limits:</b>\n"
            f"• 3 signals/day\n"
            f"• 1 hour signal delay\n"
            f"• 5 basic pairs only\n"
            f"• No whale alerts\n\n"
            f"💎 <b>Upgrade to Premium ($9.99/mo):</b>\n"
            f"• Unlimited signals\n"
            f"• Instant — no delay\n"
            f"• All 20+ pairs\n"
            f"• Whale transaction alerts\n\n"
            f"/subscribe"
        )
    else:
        user_info = get_user_info(user_id)
        if user_info:
            remaining = int((user_info["expires_at"] - time.time()) / 86400)
            msg = (
                f"<b>👑 Your Plan: {tier.upper()}</b>\n\n"
                f"• Status: ✅ Active\n"
                f"• Expires: {user_info['expires_at']}\n"
                f"• Days remaining: {remaining}\n"
                f"• All premium features unlocked!\n\n"
                f"<i>Thanks for supporting GandiveBot!</i> 🚀"
            )
        else:
            msg = (
                f"<b>⚠️ Your premium has expired.</b>\n\n"
                f"Renew to unlock premium features again!\n"
                f"/subscribe"
            )

    telegram_send(chat_id, msg)


# ─── Admin Commands ───────────────────────────────────────────────

def cmd_addpremium(chat_id: int, user_id: int, args: List[str]):
    """Add premium to a user. Usage: /addpremium <user_id> <days> [tier]"""
    if user_id != ADMIN_ID:
        telegram_send(chat_id, "⛔ This command is only available to the bot admin.")
        return

    if len(args) < 2:
        telegram_send(chat_id, "Usage: /addpremium <user_id> <days> [tier]\nTiers: premium (default), elite")
        return

    try:
        target_id = int(args[0])
        days = int(args[1])
        tier = args[2].lower() if len(args) > 2 else "premium"

        if tier not in ("premium", "elite"):
            telegram_send(chat_id, f"Invalid tier: {tier}. Use 'premium' or 'elite'.")
            return

        if days < 1 or days > 9999:
            telegram_send(chat_id, "Days must be between 1 and 9999.")
            return

        user_info = add_premium_user(target_id, tier, days, f"admin_{user_id}")
        expiry = datetime.fromtimestamp(user_info["expires_at"])
        msg = (
            f"✅ <b>Premium Activated!</b>\n"
            f"User: <code>{target_id}</code>\n"
            f"Tier: {tier.upper()}\n"
            f"Duration: {days} days\n"
            f"Expires: {expiry.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        telegram_send(chat_id, msg)

        # Notify the target user
        telegram_send(target_id,
            f"🎉 <b>Congratulations!</b>\n\n"
            f"You've been granted <b>{tier.upper()}</b> access to GandiveBot!\n"
            f"Duration: {days} days\n\n"
            f"Use /signals to start receiving premium signals!"
        )

    except ValueError:
        telegram_send(chat_id, "Invalid arguments. Usage: /addpremium <user_id> <days> [tier]")
    except Exception as e:
        logger.error(f"Error adding premium: {e}")
        telegram_send(chat_id, f"Error adding premium: {str(e)[:100]}")


def cmd_removepremium(chat_id: int, user_id: int, args: List[str]):
    """Remove premium from a user."""
    if user_id != ADMIN_ID:
        telegram_send(chat_id, "⛔ Admin only.")
        return

    if len(args) < 1:
        telegram_send(chat_id, "Usage: /removepremium <user_id>")
        return

    try:
        target_id = int(args[0])
        if remove_premium_user(target_id):
            telegram_send(chat_id, f"✅ Removed premium from <code>{target_id}</code>")
            telegram_send(target_id, "Your premium subscription has ended.")
        else:
            telegram_send(chat_id, f"❌ User <code>{target_id}</code> not found in premium list.")
    except ValueError:
        telegram_send(chat_id, "Invalid user ID.")


def cmd_listpremium(chat_id: int, user_id: int):
    """List all active premium users."""
    if user_id != ADMIN_ID:
        telegram_send(chat_id, "⛔ Admin only.")
        return

    users = get_premium_users_list()
    if not users:
        telegram_send(chat_id, "📭 No active premium users.")
        return

    msg = f"<b>💎 Premium Users ({len(users)})</b>\n\n"
    for u in users:
        msg += (
            f"• <code>{u['user_id']}</code> | {u['tier'].upper()}\n"
            f"  Expires: {u['expires_at']} ({u['days_left']}d left)\n\n"
        )

    # Send in chunks if too long
    if len(msg) > 4000:
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for chunk in chunks:
            telegram_send(chat_id, chunk)
    else:
        telegram_send(chat_id, msg)


def cmd_premiumstats(chat_id: int, user_id: int):
    """Show premium statistics."""
    if user_id != ADMIN_ID:
        telegram_send(chat_id, "⛔ Admin only.")
        return

    stats = get_premium_stats()
    msg = (
        f"<b>📊 Premium Statistics</b>\n\n"
        f"<b>Total users:</b> {stats['total_users']}\n"
        f"<b>Active:</b> {stats['active']}\n"
        f"<b>Expired:</b> {stats['expired']}\n"
        f"<b>By tier:</b>\n"
    )
    for tier, count in stats['by_tier'].items():
        msg += f"  • {tier.capitalize()}: {count}\n"

    telegram_send(chat_id, msg)


# ─── Performance Commands ───────────────────────────────────────

def cmd_performance(chat_id: int, user_id: int):
    """Show signal performance stats (win rate, P&L)."""
    send_typing(chat_id)
    try:
        auto_resolve_signals()
        stats = get_performance_stats(days=30)
        msg = get_performance_message(stats)
        telegram_send(chat_id, msg)
    except Exception as e:
        logger.error(f"Performance error: {e}")
        telegram_send(chat_id, "📊 Performance data is still accumulating. Check back after we've sent more signals!")


def cmd_report(chat_id: int, user_id: int):
    """Show detailed performance report (premium only)."""
    tier = get_user_tier(user_id)
    if tier not in ("premium", "elite"):
        telegram_send(chat_id, "💎 <b>Premium Feature</b>\n\nDetailed performance reports are available for Premium and Elite subscribers.\n/subscribe to upgrade!")
        return
    send_typing(chat_id)
    try:
        auto_resolve_signals()
        stats = get_performance_stats(days=90)
        msg = get_detailed_report(stats)
        telegram_send(chat_id, msg)
    except Exception as e:
        logger.error(f"Report error: {e}")
        telegram_send(chat_id, "📊 Not enough data for a detailed report yet.")


# ─── Referral Commands ────────────────────────────────────────────

def cmd_referral(chat_id: int, user_id: int):
    """Show referral link."""
    msg = get_referral_message(user_id)
    telegram_send(chat_id, msg)


def cmd_myrefs(chat_id: int, user_id: int):
    """Show referral stats."""
    stats = get_referral_stats(user_id)
    msg = (
        f"<b>🔗 Your Referral Stats</b>\n\n"
        f"• Referral code: <code>{stats['code']}</code>\n"
        f"• Total referrals: <b>{stats['total_referrals']}</b>\n"
        f"• Premium days earned: <b>{stats['reward_days_earned']}</b>\n"
    )
    if stats.get("referred_by"):
        msg += f"• You were referred by: <code>{stats['referred_by']}</code>\n"
    msg += f"\n/referral to get your shareable link!"
    telegram_send(chat_id, msg)


def cmd_refclaim(chat_id: int, user_id: int, args: List[str]):
    """Claim a referral code."""
    if not args:
        telegram_send(chat_id, "Usage: /refclaim <CODE>\nEnter the referral code you received from a friend.")
        return
    success, message = apply_referral(user_id, args[0])
    telegram_send(chat_id, message)


def cmd_broadcast(chat_id: int, user_id: int, args: List[str]):
    """Broadcast message to all active premium users."""
    if user_id != ADMIN_ID:
        telegram_send(chat_id, "⛔ Admin only.")
        return

    if not args:
        telegram_send(chat_id, "Usage: /broadcast <message>")
        return

    message = " ".join(args)
    user_ids = get_active_user_ids()

    if not user_ids:
        telegram_send(chat_id, "📭 No active premium users to broadcast to.")
        return

    success = 0
    failed = 0

    for uid in user_ids:
        try:
            result = telegram_send(uid, f"<b>📢 Broadcast</b>\n\n{message}")
            if result:
                success += 1
            else:
                failed += 1
            time.sleep(0.05)  # Rate limiting
        except Exception:
            failed += 1

    telegram_send(chat_id, f"📢 Broadcast sent to {success}/{len(user_ids)} users. Failed: {failed}")


# ─── Signal Deduplication ────────────────────────────────────────

# Track previously pushed signal hashes to avoid sending duplicates
_signal_dedup_cache: Dict[str, float] = {}
_DEDUP_TTL = 3600  # Don't repeat same signal within 1 hour


def _is_duplicate_signal(signal: Signal) -> bool:
    """Check if a signal was already pushed recently. Returns True if duplicate."""
    global _signal_dedup_cache
    h = signal.get_signal_hash()
    now = time.time()
    
    # Clean old entries
    _signal_dedup_cache = {k: v for k, v in _signal_dedup_cache.items() if now - v < _DEDUP_TTL}
    
    if h in _signal_dedup_cache:
        return True
    
    _signal_dedup_cache[h] = now
    return False


# ─── Background Signal Scanner ────────────────────────────────────

def background_scanner():
    """Background thread that periodically scans for signals and caches them."""
    logger.info("🔄 Background signal scanner started")

    while True:
        try:
            cleanup_expired()
            signals = scan_all_pairs(DEFAULT_PAIRS)
            if signals:
                cache_signals(signals)
                logger.info(f"✅ Cached {len(signals)} signals")
                
                # Record all signals for performance tracking
                for s in signals:
                    try:
                        record_signal(s.pair, s.type, s.price, s.confidence, s.source, s.timestamp)
                    except Exception as e:
                        logger.warning(f"Failed to record signal: {e}")
                
                # Auto-resolve old signals
                try:
                    auto_resolve_signals()
                except Exception as e:
                    logger.warning(f"Auto-resolve error: {e}")
                
                # Post to social media (Twitter/X)
                try:
                    try_post_signals(signals)
                except Exception as e:
                    logger.warning(f"Social post error: {e}")
            else:
                logger.info("📭 No signals detected this cycle")
                # Still try to auto-resolve
                try:
                    auto_resolve_signals()
                except Exception:
                    pass

            # Push high-confidence NEW signals to premium users
            push_signals_to_premium(signals)

        except Exception as e:
            logger.error(f"Scanner error: {e}")

        time.sleep(SCAN_INTERVAL)


def push_signals_to_premium(signals: List[Signal]):
    """Push high-confidence NEW signals to all active premium users.
    Uses deduplication to avoid sending the same signal twice."""
    if not signals:
        return

    # Filter to high-confidence, non-duplicate signals
    new_signals = [s for s in signals if s.confidence >= 75 and not _is_duplicate_signal(s)][:3]
    if not new_signals:
        logger.debug("No new high-confidence signals to push")
        return

    user_ids = get_active_user_ids()
    if not user_ids:
        return

    logger.info(f"Pushing {len(new_signals)} new signals to {len(user_ids)} premium users")

    for uid in user_ids:
        for signal in new_signals:
            msg = (
                f"<b>⚡ LIVE SIGNAL PUSH</b>\n\n"
                f"{signal.format_message(delay_minutes=0)}"
            )
            try:
                telegram_send(uid, msg)
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Failed to push to {uid}: {e}")


# ─── Message Handler ──────────────────────────────────────────────

def handle_message(update: dict):
    """Process an incoming Telegram update."""
    message = update.get("message", {})
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return

    is_admin = user_id == ADMIN_ID

    # Early return for non-command messages from non-admin users
    if not text.startswith("/") and user_id != ADMIN_ID:
        return

    # Parse command and arguments
    parts = text.split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    # Strip bot username from command (e.g., /signals@GandiveBot -> /signals)
    if "@" in command:
        command = command.split("@")[0]

    logger.info(f"Command: {command} from user {user_id}")

    # ─── Public Commands ──────────────────────────────────────────
    if command in ("/start", "/help"):
        if command == "/start":
            cmd_start(chat_id, user_id, args)
        else:
            cmd_help(chat_id, user_id)

    elif command in ("/signals", "/signal"):
        cmd_signals(chat_id, user_id)

    elif command in ("/subscribe", "/pricing", "/premium"):
        cmd_subscribe(chat_id, user_id)

    elif command == "/pairs":
        cmd_pairs(chat_id, user_id)

    elif command == "/trending":
        cmd_trending(chat_id, user_id)

    elif command == "/status":
        cmd_status(chat_id, user_id)

    elif command == "/myplan":
        cmd_myplan(chat_id, user_id)

    # ─── Admin Commands ───────────────────────────────────────────
    elif command == "/addpremium":
        cmd_addpremium(chat_id, user_id, args)

    elif command == "/removepremium":
        cmd_removepremium(chat_id, user_id, args)

    elif command == "/listpremium":
        cmd_listpremium(chat_id, user_id)

    elif command in ("/premiumstats", "/premstats"):
        cmd_premiumstats(chat_id, user_id)

    elif command == "/broadcast":
        cmd_broadcast(chat_id, user_id, args)

    # ─── Performance Commands ──────────────────────────────────────
    elif command in ("/perf", "/performance"):
        cmd_performance(chat_id, user_id)

    elif command == "/report":
        cmd_report(chat_id, user_id)

    # ─── Referral Commands ─────────────────────────────────────────
    elif command == "/referral":
        cmd_referral(chat_id, user_id)

    elif command == "/myrefs":
        cmd_myrefs(chat_id, user_id)

    elif command == "/refclaim":
        cmd_refclaim(chat_id, user_id, args)

    else:
        telegram_send(chat_id, f"🤷 Unknown command: <code>{command}</code>\n/help for available commands.")


# ─── Main Loop ────────────────────────────────────────────────────

bot_start_time = time.time()


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def start_polling():
    """Start the bot polling loop."""
    offset = 0
    logger.info(f"🤖 {BOT_NAME} v{BOT_VERSION} starting up...")
    logger.info(f"Admin ID: {ADMIN_ID}")

    # Start background scanner thread
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()
    logger.info("🔄 Background scanner started")

    # Notify admin (skip if admin ID matches bot ID to avoid 403 error)
    if ADMIN_ID and BOT_TOKEN:
        try:
            bot_id_from_token = int(BOT_TOKEN.split(":")[0])
            is_bot_self = (bot_id_from_token == ADMIN_ID)
        except (ValueError, IndexError):
            is_bot_self = False
        
        if is_bot_self:
            logger.info("Admin ID matches bot ID — skipping admin notification")
        else:
            send_alert_to_admin(
                f"🤖 <b>{BOT_NAME} is ONLINE</b>\n"
                f"Version: {BOT_VERSION}\n"
                f"Scanning {len(DEFAULT_PAIRS)} pairs every {SCAN_INTERVAL}s\n"
                f"💎 Premium system active"
            )

    while True:
        try:
            url = f"{TELEGRAM_API}/getUpdates"
            params = {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message"],
            }

            r = requests.get(url, params=params, timeout=35)
            if r.status_code != 200:
                logger.warning(f"Poll error: {r.status_code}")
                time.sleep(5)
                continue

            updates = r.json().get("result", [])
            for update in updates:
                try:
                    handle_message(update)
                except Exception as e:
                    logger.exception(f"Error handling update {update.get('update_id')}: {e}")
                    # Try to notify admin
                    try:
                        chat_id = update.get("message", {}).get("chat", {}).get("id")
                        if chat_id:
                            telegram_send(chat_id, "⚠️ An error occurred processing your request. Please try again.")
                    except Exception:
                        pass

                offset = update["update_id"] + 1

        except requests.exceptions.Timeout:
            # Timeout is normal with long polling — just continue
            pass
        except requests.exceptions.ConnectionError:
            logger.error("Connection error, retrying in 10s...")
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Bot shutting down...")
            send_alert_to_admin(f"🤖 <b>{BOT_NAME} is SHUTTING DOWN</b>")
            break
        except Exception as e:
            logger.exception(f"Poll loop error: {e}")
            time.sleep(5)


# ─── Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ GANDIVE_BOT_TOKEN not set! Check your .env file.")
        print("❌ GANDIVE_BOT_TOKEN not set! Create a .env file with your bot token.")
        print("   Copy from .env.example: cp .env.example .env")
        sys.exit(1)

    start_polling()

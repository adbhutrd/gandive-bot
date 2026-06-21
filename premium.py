#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   💎 GANDIVE BOT — Premium Membership System                ║
║   Crypto Signal Bot with Tiered Subscriptions                ║
╚═══════════════════════════════════════════════════════════════╝

TIERS:
  Free   — 3 signals/day, basic pairs, 1h delay
  Premium — $9.99/mo — Unlimited signals, instant, all pairs, whale alerts
  Elite   — $24.99/mo — Everything + custom alerts, alpha calls, API access
"""

import os
import json
import time
import logging
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows: no file locking, atomic writes still work
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger("gandive-premium")


# ─── File Locking (prevents race conditions with webhook) ────────

def _lock_file(fd, exclusive: bool = True):
    """Lock file. Exclusive for writes, shared for reads."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    except Exception:
        pass  # Non-blocking on systems without flock (Windows)

def _unlock_file(fd):
    """Unlock file."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:
        pass

# ─── File Paths ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
USERS_FILE = BASE_DIR / "premium_users.json"
STATE_FILE = BASE_DIR / "bot_state.json"

# ─── Tiers ────────────────────────────────────────────────────────
TIERS = {
    "free": {
        "name": "Free",
        "price": 0,
        "price_label": "Free",
        "currency": "USD",
        "signals_per_day": 3,
        "signal_delay_minutes": 60,
        "pairs": ["BTC/USDT", "ETH/USDT", "DOGE/USDT"],
        "whale_alerts": False,
        "priority": 0,
    },
    "premium": {
        "name": "Premium",
        "price": 9.99,
        "price_label": "$9.99",
        "currency": "USD",
        "signals_per_day": 999,  # unlimited
        "signal_delay_minutes": 0,
        "pairs": "all",
        "whale_alerts": True,
        "priority": 1,
    },
    "elite": {
        "name": "Elite",
        "price": 24.99,
        "price_label": "$24.99",
        "currency": "USD",
        "signals_per_day": 999,
        "signal_delay_minutes": 0,
        "pairs": "all",
        "whale_alerts": True,
        "priority": 2,
    },
}

SUBSCRIPTION_DURATIONS = {
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}

# ─── User Store ───────────────────────────────────────────────────

def load_users() -> dict:
    """Load premium users from JSON file with shared lock."""
    if not USERS_FILE.exists():
        return {}
    try:
        fd = os.open(str(USERS_FILE), os.O_RDONLY)
        _lock_file(fd, exclusive=False)
        try:
            with os.fdopen(fd, 'r') as f:
                return json.load(f)
        finally:
            _unlock_file(fd)
    except (json.JSONDecodeError, OSError, Exception) as e:
        logger.warning(f"Failed to load users file: {e}")
        return {}

def _save_users_atomic(users: dict):
    """Save users with exclusive lock and atomic write."""
    tmp_file = USERS_FILE.with_suffix(".json.tmp")
    try:
        fd = os.open(str(tmp_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        _lock_file(fd, exclusive=True)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(users, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        finally:
            _unlock_file(fd)
        tmp_file.replace(USERS_FILE)
        logger.debug(f"Saved {len(users)} users")
    except Exception as e:
        logger.error(f"Failed to save users: {e}")
        raise

def save_users(users: dict):
    """Save premium users to JSON file."""
    _save_users_atomic(users)
    logger.info(f"Saved {len(users)} users to {USERS_FILE}")

def load_state() -> dict:
    """Load bot state with shared lock."""
    if not STATE_FILE.exists():
        return {"total_signals_sent": 0, "total_earnings": 0.0}
    try:
        fd = os.open(str(STATE_FILE), os.O_RDONLY)
        _lock_file(fd, exclusive=False)
        try:
            with os.fdopen(fd, 'r') as f:
                return json.load(f)
        finally:
            _unlock_file(fd)
    except Exception:
        return {"total_signals_sent": 0, "total_earnings": 0.0}

def save_state(state: dict):
    """Save bot state with exclusive lock."""
    tmp_file = STATE_FILE.with_suffix(".json.tmp")
    try:
        fd = os.open(str(tmp_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        _lock_file(fd, exclusive=True)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        finally:
            _unlock_file(fd)
        tmp_file.replace(STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
        raise


# ─── User Management ─────────────────────────────────────────────

def add_premium_user(user_id: int, tier: str, days: int, admin_note: str = ""):
    """Add or extend premium for a user."""
    users = load_users()
    user_key = str(user_id)
    now = time.time()
    expiry = now + (days * 86400)

    if user_key in users:
        # Extend existing subscription
        existing_expiry = users[user_key].get("expires_at", 0)
        if existing_expiry > now:
            expiry = existing_expiry + (days * 86400)

    users[user_key] = {
        "user_id": user_id,
        "tier": tier,
        "activated_at": now,
        "expires_at": expiry,
        "source": admin_note or "admin",
        "signals_today": 0,
        "signal_reset_date": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    save_users(users)
    logger.info(f"Premium added: user={user_id}, tier={tier}, days={days}")
    return users[user_key]

def remove_premium_user(user_id: int) -> bool:
    """Remove a premium user."""
    users = load_users()
    user_key = str(user_id)
    if user_key in users:
        del users[user_key]
        save_users(users)
        logger.info(f"Premium removed: user={user_id}")
        return True
    return False

def get_user_tier(user_id: int) -> str:
    """Get the current tier for a user. Returns 'free' if not premium."""
    users = load_users()
    user_key = str(user_id)
    if user_key not in users:
        return "free"

    user = users[user_key]
    if time.time() > user.get("expires_at", 0):
        # Expired — clean up
        del users[user_key]
        save_users(users)
        return "free"

    return user.get("tier", "free")

def get_user_info(user_id: int) -> Optional[Dict]:
    """Get full user info. Returns None if not premium."""
    users = load_users()
    user_key = str(user_id)
    user = users.get(user_key)
    if not user:
        return None
    if time.time() > user.get("expires_at", 0):
        del users[user_key]
        save_users(users)
        return None
    return user

def get_tier_config(tier: str) -> Dict:
    """Get configuration for a tier."""
    return TIERS.get(tier, TIERS["free"])

def check_rate_limit(user_id: int) -> Tuple[bool, str]:
    """
    Check if user is within rate limits WITHOUT incrementing the counter.
    Returns (allowed, reason). Call increment_signal_usage() AFTER sending.
    """
    tier_name = get_user_tier(user_id)
    config = get_tier_config(tier_name)

    if tier_name == "free":
        state = load_state()
        today = datetime.now().strftime("%Y-%m-%d")

        free_signals = state.get("free_signals", {})
        user_key = str(user_id)

        if free_signals.get("date") != today:
            return True, ""

        used_today = free_signals.get(user_key, 0)
        if used_today >= config["signals_per_day"]:
            return False, f"Daily limit reached ({config['signals_per_day']}/day). Upgrade to Premium for unlimited signals!"

    return True, ""


def increment_signal_usage(user_id: int):
    """
    Increment daily signal usage counter for a user.
    Call this ONLY after a signal was successfully sent.
    """
    tier_name = get_user_tier(user_id)
    if tier_name != "free":
        return  # Only free users have limits

    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")

    free_signals = state.setdefault("free_signals", {})
    user_key = str(user_id)

    if free_signals.get("date") != today:
        free_signals["date"] = today
        free_signals[user_key] = 0

    free_signals[user_key] = free_signals.get(user_key, 0) + 1
    state["free_signals"] = free_signals
    save_state(state)


def get_premium_users_list() -> List[Dict]:
    """Get list of active premium users."""
    users = load_users()
    now = time.time()
    active = []
    for uid, info in users.items():
        if info.get("expires_at", 0) > now:
            expires = datetime.fromtimestamp(info["expires_at"])
            active.append({
                "user_id": info["user_id"],
                "tier": info["tier"],
                "expires_at": expires.strftime("%Y-%m-%d %H:%M UTC"),
                "days_left": int((info["expires_at"] - now) / 86400),
            })
    return active

def get_premium_stats() -> Dict:
    """Get premium statistics."""
    users = load_users()
    now = time.time()
    active = sum(1 for u in users.values() if u.get("expires_at", 0) > now)
    expired = sum(1 for u in users.values() if u.get("expires_at", 0) <= now)
    tiers = {}
    for u in users.values():
        t = u.get("tier", "free")
        tiers[t] = tiers.get(t, 0) + 1

    return {
        "total_users": len(users),
        "active": active,
        "expired": expired,
        "by_tier": tiers,
    }


# ─── Signal Rate Limiting ─────────────────────────────────────────

def get_signal_delay(user_id: int) -> int:
    """Get signal delay in minutes for a user."""
    tier_name = get_user_tier(user_id)
    return get_tier_config(tier_name)["signal_delay_minutes"]

def get_signal_pairs(user_id: int) -> list:
    """Get the list of pairs available to a user."""
    tier_name = get_user_tier(user_id)
    return get_tier_config(tier_name)["pairs"]

def increment_signal_count():
    """Increment total signals sent counter."""
    state = load_state()
    state["total_signals_sent"] = state.get("total_signals_sent", 0) + 1
    save_state(state)


# ─── Cleanup ──────────────────────────────────────────────────────

def cleanup_expired():
    """Remove expired premium users."""
    users = load_users()
    now = time.time()
    expired = [uid for uid, info in users.items() if info.get("expires_at", 0) <= now]
    for uid in expired:
        del users[uid]
    if expired:
        save_users(users)
        logger.info(f"Cleaned up {len(expired)} expired premium users")
    return len(expired)


# ─── Payment Links ────────────────────────────────────────────────

# Update this to your Ko-fi page
KO_FI_URL = "https://ko-fi.com/adbhutrd"
KO_FI_NAME = "Adbhut_RD"

def get_subscribe_message() -> str:
    """Get formatted subscription message with payment links."""
    msg = (
        "<b>💎 GandiveBot Premium</b>\n\n"
        "Unlock the full power of crypto signals:\n\n"
    )

    for tier_key in ["premium", "elite"]:
        config = TIERS[tier_key]
        features = []
        if config["signals_per_day"] > 100:
            features.append("✅ <b>Unlimited</b> daily signals")
        else:
            features.append(f"✅ {config['signals_per_day']} signals/day")
        features.append("✅ <b>Instant</b> signals — no delay")
        features.append(f"✅ <b>All pairs</b> (100+ crypto)")
        if config["whale_alerts"]:
            features.append("🐋 <b>Whale transaction alerts</b>")
        if tier_key == "elite":
            features.append("🔔 <b>Custom price alerts</b>")
            features.append("🔌 <b>API access</b> for your own apps")

        tier_name = config["name"]
        tier_price = config["price_label"]

        msg += f"\n<b>{'👑' if tier_key == 'elite' else '⭐'} {tier_name}</b> — {tier_price}/mo\n"
        for f in features:
            msg += f"  {f}\n"

    msg += f"\n\n<b>📅 Subscription Options:</b>\n"
    msg += f"• Monthly — from $9.99\n"
    msg += f"• Quarterly (save 15%) — from $25.49\n"
    msg += f"• Yearly (save 30%) — from $83.99\n"

    msg += f"\n\n<b>💳 Pay via Ko-fi:</b>\n"
    msg += f"{KO_FI_URL}\n\n"
    msg += f"After payment, message me your transaction ID and I'll activate your premium instantly!"

    return msg


# ─── Broadcast ────────────────────────────────────────────────────

def get_active_user_ids() -> List[int]:
    """Get list of active premium user IDs."""
    users = load_users()
    now = time.time()
    return [
        int(uid) for uid, info in users.items()
        if info.get("expires_at", 0) > now
    ]

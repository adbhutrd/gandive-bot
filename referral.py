#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   🔗 GANDIVE BOT — Referral System                         ║
║   Users earn free premium days for referring others.        ║
╚═══════════════════════════════════════════════════════════════╝

How it works:
  1. User runs /referral → gets a unique referral link
  2. New user starts bot via referral link
  3. Referrer gets 7 free premium days
  4. New user gets 3 free premium days (trial)

Commands:
  /referral  — Get your referral link
  /myrefs    — See your referral stats
  /refclaim <code> — Claim a referral code
"""

import os
import json
import time
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from premium import add_premium_user, get_user_tier

logger = logging.getLogger("gandive-referral")

BASE_DIR = Path(__file__).parent.resolve()
REFERRAL_FILE = BASE_DIR / "referral_data.json"

# ─── Rewards ───────────────────────────────────────────────────────
REFERRER_REWARD_DAYS = 7  # Free premium days for the referrer
NEW_USER_REWARD_DAYS = 3  # Free premium days for the new user


def _load_data() -> dict:
    """Load referral data."""
    if not REFERRAL_FILE.exists():
        return {"referrals": {}, "codes": {}, "stats": {"total_referrals": 0, "total_reward_days": 0}}
    try:
        return json.loads(REFERRAL_FILE.read_text())
    except Exception:
        return {"referrals": {}, "codes": {}, "stats": {"total_referrals": 0, "total_reward_days": 0}}


def _save_data(data: dict):
    """Save referral data."""
    REFERRAL_FILE.write_text(json.dumps(data, indent=2))


def generate_referral_code(user_id: int) -> str:
    """Generate a unique referral code for a user. Returns existing code if already generated."""
    data = _load_data()
    user_key = str(user_id)

    # Check if user already has a code
    for code, uid in data.get("codes", {}).items():
        if uid == user_key:
            return code

    # Generate new unique code
    while True:
        code = secrets.token_hex(4).upper()  # 8-char hex code
        if code not in data.get("codes", {}):
            break

    data.setdefault("codes", {})[code] = user_key
    data.setdefault("referrals", {}).setdefault(user_key, {
        "user_id": user_id,
        "code": code,
        "total_referrals": 0,
        "reward_days_earned": 0,
        "referred_users": [],
    })

    _save_data(data)
    logger.info(f"🔗 Referral code generated: {code} for user {user_id}")
    return code


def apply_referral(new_user_id: int, code: str) -> Tuple[bool, str]:
    """Apply a referral code for a new user.
    Returns (success, message).
    """
    data = _load_data()
    
    if not code:
        return False, "Please provide a referral code. Usage: /refclaim <CODE>"

    code = code.upper()
    referrer_key = data.get("codes", {}).get(code)
    
    if not referrer_key:
        return False, f"❌ Invalid referral code: <code>{code}</code>. Check the code and try again."

    referrer_id = int(referrer_key)
    new_user_key = str(new_user_id)

    # Prevent self-referral
    if referrer_id == new_user_id:
        return False, "❌ You can't refer yourself! Share your code with friends."

    # Check if new user was already referred
    referrer_data = data["referrals"].get(referrer_key, {})
    if new_user_key in referrer_data.get("referred_users", []):
        return False, "❌ This referral code has already been used by you. Each user can only use one code."

    # Check if new user already has a code (already in system)
    if new_user_key in data.get("referrals", {}):
        return False, "❌ You already have a referral account. You can only use one referral code."

    # Process referral
    data["referrals"].setdefault(referrer_key, {
        "user_id": referrer_id,
        "code": code,
        "total_referrals": 0,
        "reward_days_earned": 0,
        "referred_users": [],
    })

    data["referrals"][referrer_key]["total_referrals"] += 1
    data["referrals"][referrer_key]["reward_days_earned"] += REFERRER_REWARD_DAYS
    data["referrals"][referrer_key]["referred_users"].append(new_user_key)

    # Setup new user's referral tracking
    new_user_code = generate_referral_code(new_user_id)
    data["referrals"][new_user_key] = {
        "user_id": new_user_id,
        "code": new_user_code,
        "total_referrals": 0,
        "reward_days_earned": 0,
        "referred_by": referrer_key,
        "referred_users": [],
    }

    data["stats"]["total_referrals"] += 1
    data["stats"]["total_reward_days"] += REFERRER_REWARD_DAYS + NEW_USER_REWARD_DAYS
    _save_data(data)

    # Grant rewards
    try:
        # Give referrer free premium days
        add_premium_user(referrer_id, "premium", REFERRER_REWARD_DAYS, 
                         f"referral_new_user_{new_user_id}")
        
        # Give new user free trial
        if get_user_tier(new_user_id) == "free":
            add_premium_user(new_user_id, "premium", NEW_USER_REWARD_DAYS,
                             f"referral_welcome_{referrer_id}")
    except Exception as e:
        logger.error(f"Failed to grant referral rewards: {e}")

    logger.info(f"✅ Referral applied: {new_user_id} used code {code} from {referrer_id}")
    return True, (
        f"🎉 <b>Referral Activated!</b>\n\n"
        f"You've been referred by user <code>{referrer_id}</code>!\n"
        f"You get <b>{NEW_USER_REWARD_DAYS} days</b> of free Premium!\n"
        f"Your referrer gets <b>{REFERRER_REWARD_DAYS} days</b> too!\n\n"
        f"Your referral code: <code>{new_user_code}</code>\n"
        f"Share it with friends to earn more free days!\n"
        f"/referral to see your link."
    )


def get_referral_stats(user_id: int) -> Dict:
    """Get referral statistics for a user."""
    data = _load_data()
    user_key = str(user_id)
    ref_data = data.get("referrals", {}).get(user_key)

    if not ref_data:
        code = generate_referral_code(user_id)
        ref_data = data["referrals"].get(user_key, {
            "user_id": user_id,
            "code": code,
            "total_referrals": 0,
            "reward_days_earned": 0,
            "referred_users": [],
        })

    return {
        "code": ref_data.get("code", ""),
        "total_referrals": ref_data.get("total_referrals", 0),
        "reward_days_earned": ref_data.get("reward_days_earned", 0),
        "referred_by": ref_data.get("referred_by"),
        "total_rewards_available": REFERRER_REWARD_DAYS,
    }


def get_referral_message(user_id: int) -> str:
    """Generate a referral message for Telegram."""
    stats = get_referral_stats(user_id)
    code = stats["code"]
    bot_username = os.getenv("BOT_USERNAME", "GandiveBot")

    referral_link = f"https://t.me/{bot_username}?start=ref_{code}"

    msg = (
        f"<b>🔗 Your Referral Link</b>\n\n"
        f"Share this link with friends who trade crypto:\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"<b>🎁 Rewards:</b>\n"
        f"• You get <b>{REFERRER_REWARD_DAYS} days</b> free Premium per referral\n"
        f"• Your friend gets <b>{NEW_USER_REWARD_DAYS} days</b> free trial\n"
        f"No limit — refer as many as you want!\n\n"
        f"<b>📊 Your Stats:</b>\n"
        f"• Referrals: <b>{stats['total_referrals']}</b>\n"
        f"• Reward days earned: <b>{stats['reward_days_earned']}</b>\n\n"
        f"<i>Already have a friend's code? Use /refclaim YOUR_CODE to activate!</i>"
    )

    return msg


def get_admin_referral_stats() -> Dict:
    """Get overall referral system stats (admin)."""
    data = _load_data()
    stats = data.get("stats", {})
    
    # Calculate active referrers
    referrers_with_refs = sum(
        1 for r in data.get("referrals", {}).values()
        if r.get("total_referrals", 0) > 0
    )

    return {
        "total_referrals": stats.get("total_referrals", 0),
        "total_reward_days": stats.get("total_reward_days", 0),
        "total_users_with_codes": len(data.get("referrals", {})),
        "active_referrers": referrers_with_refs,
        "top_referrer": _get_top_referrer(data),
    }


def _get_top_referrer(data: dict) -> Optional[Dict]:
    """Get the user with the most referrals."""
    best = None
    best_count = 0
    for uid, ref in data.get("referrals", {}).items():
        count = ref.get("total_referrals", 0)
        if count > best_count:
            best_count = count
            best = {"user_id": ref["user_id"], "count": count}
    return best

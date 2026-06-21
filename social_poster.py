#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   🐦 GANDIVE BOT — Social Auto-Poster                      ║
║   Posts high-confidence signals to Twitter/X automatically  ║
╚═══════════════════════════════════════════════════════════════╝

Setup:
  1. Get Twitter API keys from https://developer.twitter.com/
  2. Add to .env:
       TWITTER_API_KEY=xxx
       TWITTER_API_SECRET=xxx
       TWITTER_ACCESS_TOKEN=xxx
       TWITTER_ACCESS_TOKEN_SECRET=xxx
  
  The poster runs in the background scanner thread automatically.
  Only posts signals with confidence >= 80 to avoid noise.
"""

import os
import time
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger("gandive-social")

BASE_DIR = Path(__file__).parent.resolve()
SOCIAL_STATE_FILE = BASE_DIR / "social_state.json"

# ─── State tracking (avoid double-posting) ───────────────────────

def _load_state() -> dict:
    if SOCIAL_STATE_FILE.exists():
        try:
            return json.loads(SOCIAL_STATE_FILE.read_text())
        except Exception:
            pass
    return {"posted_hashes": [], "last_post_time": 0}


def _save_state(state: dict):
    SOCIAL_STATE_FILE.write_text(json.dumps(state, indent=2))


def _is_already_posted(signal_hash: str) -> bool:
    state = _load_state()
    return signal_hash in state.get("posted_hashes", [])[-100:]  # Track last 100


def _mark_posted(signal_hash: str):
    state = _load_state()
    posted = state.get("posted_hashes", [])
    posted.append(signal_hash)
    # Keep only last 200
    state["posted_hashes"] = posted[-200:]
    state["last_post_time"] = time.time()
    _save_state(state)


# ─── Tweet Generation ─────────────────────────────────────────────

def generate_tweet(signal) -> Optional[str]:
    """Generate a tweet from a signal."""
    from signals import Signal
    
    emoji_map = {"BUY": "🟢", "SELL": "🔴", "WHALE": "🐋", "MOMENTUM": "⚡"}
    emoji = emoji_map.get(signal.type, "📊")
    
    # Format price
    if signal.price >= 1000:
        price_str = f"${signal.price:,.2f}"
    elif signal.price >= 1:
        price_str = f"${signal.price:.4f}"
    elif signal.price >= 0.001:
        price_str = f"${signal.price:.6f}"
    else:
        price_str = f"${signal.price:.8f}"
    
    # Direction emoji
    dir_emoji = "📈" if signal.type in ("BUY", "MOMENTUM") else "📉"
    
    # Tweet must be under 280 chars
    tweet = f"{emoji} {signal.type} {signal.pair}\n\n{dir_emoji} Price: {price_str}\n🎯 Conf: {signal.confidence}%\n💡 {signal.reason}\n\n#crypto #trading #altcoins"

    if len(tweet) > 280:
        tweet = f"{emoji} {signal.type} {signal.pair}\n{dir_emoji} {price_str} | {signal.confidence}%\n{signal.reason}\n\n#crypto"
    
    return tweet[:280]


# ─── Twitter API ──────────────────────────────────────────────────

def _twitter_api(method: str, endpoint: str, params: dict = None, json_body: dict = None) -> Optional[dict]:
    """Make a request to Twitter API v2."""
    import requests
    import hashlib
    import hmac
    import base64
    from urllib.parse import urlencode
    
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
    
    if not all([api_key, api_secret, access_token, token_secret]):
        logger.warning("Twitter API keys not configured")
        return None
    
    url = f"https://api.twitter.com/2/{endpoint}"
    
    # Simple OAuth 1.0a header (using Bearer token approach for simplicity)
    # In production, use tweepy or proper OAuth 1.0a signing
    try:
        # Use Twitter API v2 with OAuth 2.0 Bearer token
        # Generate Bearer token from API key + secret
        bearer_token_raw = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        # This is simplified - proper OAuth requires a token endpoint call
        
        headers = {
            "Authorization": f"Bearer {access_token}",  # Simplified
            "Content-Type": "application/json",
        }
        
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=10)
        else:
            r = requests.post(url, headers=headers, json=json_body, timeout=10)
        
        if r.status_code in (200, 201):
            return r.json()
        else:
            logger.warning(f"Twitter API error ({r.status_code}): {r.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Twitter API request failed: {e}")
        return None


def _post_tweet_v1(text: str) -> bool:
    """Post a tweet using Twitter API v1.1 (more reliable approach)."""
    import requests
    import hashlib
    import hmac
    import base64
    import time as time_module
    from urllib.parse import quote
    
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
    
    if not all([api_key, api_secret, access_token, token_secret]):
        return False
    
    # Use requests-oauthlib if available, otherwise simplified POST
    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(api_key, api_secret, access_token, token_secret)
        r = requests.post(
            "https://api.twitter.com/1.1/statuses/update.json",
            auth=auth,
            data={"status": text},
            timeout=10,
        )
        if r.status_code in (200, 201):
            logger.info(f"🐦 Tweet posted: {text[:50]}...")
            return True
        else:
            logger.warning(f"Tweet failed ({r.status_code}): {r.text[:200]}")
            return False
    except ImportError:
        logger.warning("requests_oauthlib not installed. Install: pip install requests_oauthlib")
        return False
    except Exception as e:
        logger.error(f"Tweet post error: {e}")
        return False


# ─── Main Poster ──────────────────────────────────────────────────

MIN_POST_CONFIDENCE = 80  # Only post signals with confidence >= 80
POST_COOLDOWN = 3600  # Don't post more than once per hour


def post_signal(signal) -> bool:
    """Post a signal to Twitter/X. Returns True if posted."""
    if signal.confidence < MIN_POST_CONFIDENCE:
        return False
    
    signal_hash = signal.get_signal_hash()
    if _is_already_posted(signal_hash):
        return False
    
    state = _load_state()
    if time.time() - state.get("last_post_time", 0) < POST_COOLDOWN:
        logger.debug("Post cooldown active, skipping")
        return False
    
    tweet = generate_tweet(signal)
    if not tweet:
        return False
    
    posted = _post_tweet_v1(tweet)
    if posted:
        _mark_posted(signal_hash)
    
    return posted


def try_post_signals(signals: list) -> int:
    """Try to post the best signal to social media. Returns count posted."""
    posted = 0
    for signal in sorted(signals, key=lambda s: s.confidence, reverse=True):
        if post_signal(signal):
            posted += 1
            break  # Only post 1 signal per cycle
    return posted

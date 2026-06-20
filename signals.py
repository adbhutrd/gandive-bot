#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   📊 GANDIVE BOT — Crypto Signal Engine                     ║
║   Generates trading signals: volume spikes, breakouts,      ║
║   whale alerts, and momentum shifts.                        ║
╚═══════════════════════════════════════════════════════════════╝
"""

import os
import time
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import requests

logger = logging.getLogger("gandive-signals")

# ─── Config ───────────────────────────────────────────────────────

# Default pairs to monitor
DEFAULT_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "PEPE/USDT",
    "WIF/USDT", "BONK/USDT", "SHIB/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "DOT/USDT", "LINK/USDT", "MATIC/USDT", "ARB/USDT",
    "OP/USDT", "INJ/USDT", "TIA/USDT", "SEI/USDT", "SUI/USDT",
]

# Binance public API (no key needed for ticker data)
BINANCE_BASE = "https://api.binance.com"
BINANCE_TICKER = f"{BINANCE_BASE}/api/v3/ticker/24hr"
BINANCE_KLINES = f"{BINANCE_BASE}/api/v3/klines"

# CoinGecko free API
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_TRENDING = f"{COINGECKO_BASE}/search/trending"
COINGECKO_SIMPLE = f"{COINGECKO_BASE}/simple/price"

# Whale Alert API (optional — free tier available)
WHALE_ALERT_URL = "https://api.whale-alert.io/v1/transactions"

# Signal thresholds
VOLUME_SPIKE_MULTIPLIER = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "3.0"))
PRICE_BREAKOUT_PCT = float(os.getenv("PRICE_BREAKOUT_PCT", "0.05"))  # 5%
MIN_SIGNAL_CONFIDENCE = float(os.getenv("MIN_SIGNAL_CONFIDENCE", "60"))  # 60%


# ─── Data Types ───────────────────────────────────────────────────

@dataclass
class Signal:
    type: str  # "BUY", "SELL", "WHALE", "MOMENTUM"
    pair: str
    price: float
    confidence: int  # 0-100
    reason: str
    details: Dict
    timestamp: float
    source: str  # "volume_spike", "breakout", "whale", "momentum"

    def format_price(self) -> str:
        """Format price with adaptive decimal places based on value."""
        p = self.price
        if p >= 1000:
            return f"${p:,.2f}"
        elif p >= 1:
            return f"${p:.4f}"
        elif p >= 0.001:
            return f"${p:.6f}"
        else:
            return f"${p:.8f}"

    def format_message(self, delay_minutes: int = 0) -> str:
        """Format signal as Telegram message."""
        now = datetime.now(timezone.utc)

        # Signal type emoji
        emoji_map = {
            "BUY": "🟢",
            "SELL": "🔴",
            "WHALE": "🐋",
            "MOMENTUM": "⚡",
        }
        emoji = emoji_map.get(self.type, "📊")

        # Confidence bar
        conf_bar = "▓" * (self.confidence // 20) + "░" * (5 - self.confidence // 20)

        msg = (
            f"{emoji} <b>{self.type} SIGNAL</b>\n"
            f"<code>{self.pair}</code>\n\n"
            f"💰 <b>Price:</b> {self.format_price()}\n"
            f"📊 <b>Confidence:</b> {conf_bar} {self.confidence}%\n"
            f"💡 <b>Reason:</b> {self.reason}\n"
        )

        # Add details
        if self.details:
            if "volume_change" in self.details:
                msg += f"📈 <b>Volume surge:</b> {abs(self.details['volume_change']):,.0f}%\n"
            if "price_change" in self.details:
                arrow = "📈" if self.details['price_change'] > 0 else "📉"
                msg += f"{arrow} <b>Price change:</b> {self.details['price_change']:.2f}%\n"
            if "whale_amount" in self.details:
                msg += f"🐋 <b>Whale tx:</b> ${self.details['whale_amount']:,.0f}\n"
            if "fast_ma" in self.details and "slow_ma" in self.details:
                msg += f"📊 <b>MA:</b> Fast={self.details['fast_ma']:.8f} / Slow={self.details['slow_ma']:.8f}\n"

        # Delay notice for free users
        if delay_minutes > 0:
            msg += f"\n⏳ <i>Signal available to you in {delay_minutes}min (upgrade for instant ➡️ /subscribe)</i>\n"

        msg += f"\n🕐 {now.strftime('%H:%M UTC')}\n"
        msg += f"<i>Not financial advice. DYOR.</i>"

        return msg

    def get_signal_hash(self) -> str:
        """Get a unique hash for this signal (for deduplication)."""
        import hashlib
        raw = f"{self.pair}:{self.type}:{self.reason}:{int(self.timestamp / 300)}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


# ─── Multi-Exchange Support ─────────────────────────────────────
# Falls back through exchanges if one is unavailable/blocked

EXCHANGES = []


def _check_exchange_api(name: str, url: str, timeout: int = 5) -> bool:
    """Check if an exchange API is reachable."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _init_exchanges():
    """Initialize exchange list based on reachability."""
    global EXCHANGES
    if EXCHANGES:
        return

    exchanges_to_try = [
        ("kucoin", KUCKOIN_TICKER, _kucoin_ticker, _kucoin_klines),
        ("coingecko", COINGECKO_SIMPLE, _coingecko_ticker, None),
        ("binance", BINANCE_TICKER, _binance_ticker, _binance_klines),
    ]

    available = []
    for name, url, ticker_fn, klines_fn in exchanges_to_try:
        if _check_exchange_api(name, url):
            available.append((ticker_fn, klines_fn))
            logger.info(f"✅ Exchange available: {name}")
        else:
            logger.warning(f"❌ Exchange unavailable: {name}")

    if not available:
        # Default to all — let each request handle errors
        for _, _, ticker_fn, klines_fn in exchanges_to_try:
            available.append((ticker_fn, klines_fn))

    EXCHANGES = available


# ─── Exchange: KuCoin (public, no key needed) ────────────────────

KUCKOIN_BASE = "https://api.kucoin.com"
KUCKOIN_TICKER = f"{KUCKOIN_BASE}/api/v1/market/orderbook/level1"
KUCKOIN_STATS = f"{KUCKOIN_BASE}/api/v1/market/stats"
KUCKOIN_KLINES = f"{KUCKOIN_BASE}/api/v1/market/candles"


def _kucoin_get(path: str, params: dict = None) -> Optional[Dict]:
    """Make request to KuCoin public API."""
    try:
        r = requests.get(path, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _kucoin_ticker(pair: str) -> Optional[Dict]:
    """Fetch ticker from KuCoin."""
    symbol = pair.replace("/", "-")
    
    # Get current price
    ticker_data = _kucoin_get(KUCKOIN_TICKER, {"symbol": symbol})
    if not ticker_data or not ticker_data.get("data"):
        return None
    
    price = float(ticker_data["data"].get("price", 0))
    
    # Get 24h stats
    stats = _kucoin_get(KUCKOIN_STATS, {"symbol": symbol})
    if not stats or not stats.get("data"):
        return None
    
    s = stats["data"]
    high = float(s.get("high", 0))
    low = float(s.get("low", 0))
    vol = float(s.get("vol", 0))
    vol_quote = float(s.get("volValue", 0))
    change = float(s.get("changeRate", 0)) * 100
    
    return {
        "symbol": pair,
        "price": price,
        "volume_24h": vol,
        "quote_volume_24h": vol_quote,
        "high_24h": high,
        "low_24h": low,
        "change_24h": change,
    }


def _kucoin_klines(pair: str, interval: str = "1hour", limit: int = 24) -> Optional[List[Dict]]:
    """Fetch klines from KuCoin."""
    symbol = pair.replace("/", "-")
    
    interval_map = {
        "1h": "1hour",
        "4h": "4hour",
        "1d": "1day",
    }
    k_interval = interval_map.get(interval, interval)
    
    data = _kucoin_get(KUCKOIN_KLINES, {
        "symbol": symbol,
        "type": k_interval,
    })
    if not data or not isinstance(data.get("data"), list):
        return None
    
    candles = data["data"][-limit:]  # Take last N
    klines = []
    for k in candles:
        # KuCoin format: [time, open, close, high, low, volume, turnover]
        klines.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "close": float(k[2]),
            "high": float(k[3]),
            "low": float(k[4]),
            "volume": float(k[5]),
            "quote_volume": float(k[6]),
        })
    return klines


# ─── Exchange: Binance ────────────────────────────────────────────

def _binance_get(path: str, params: dict = None) -> Optional[Dict]:
    """Make request to Binance public API."""
    try:
        r = requests.get(path, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _binance_ticker(pair: str) -> Optional[Dict]:
    """Fetch 24hr ticker from Binance."""
    symbol = pair.replace("/", "")
    data = _binance_get(BINANCE_TICKER, {"symbol": symbol})
    if not data:
        return None
    return {
        "symbol": pair,
        "price": float(data.get("lastPrice", 0)),
        "volume_24h": float(data.get("volume", 0)),
        "quote_volume_24h": float(data.get("quoteVolume", 0)),
        "high_24h": float(data.get("highPrice", 0)),
        "low_24h": float(data.get("lowPrice", 0)),
        "change_24h": float(data.get("priceChangePercent", 0)),
    }


def _binance_klines(pair: str, interval: str = "1h", limit: int = 24) -> Optional[List[Dict]]:
    """Fetch kline/candlestick data from Binance."""
    symbol = pair.replace("/", "")
    data = _binance_get(BINANCE_KLINES, {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    })
    if not data or not isinstance(data, list):
        return None

    klines = []
    for k in data:
        klines.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return klines


# ─── Exchange: CoinGecko (fallback for prices only) ───────────────

def _coingecko_ticker(pair: str) -> Optional[Dict]:
    """Fetch price from CoinGecko (no klines available on free tier)."""
    symbol_map = {
        "BTC/USDT": "bitcoin",
        "ETH/USDT": "ethereum",
        "SOL/USDT": "solana",
        "DOGE/USDT": "dogecoin",
        "PEPE/USDT": "pepe",
        "WIF/USDT": "dogwifhat",
        "BONK/USDT": "bonk",
        "SHIB/USDT": "shiba-inu",
        "XRP/USDT": "ripple",
        "ADA/USDT": "cardano",
        "AVAX/USDT": "avalanche-2",
        "DOT/USDT": "polkadot",
        "LINK/USDT": "chainlink",
        "MATIC/USDT": "matic-network",
        "ARB/USDT": "arbitrum",
        "OP/USDT": "optimism",
        "INJ/USDT": "injective-protocol",
        "TIA/USDT": "celestia",
        "SEI/USDT": "sei-network",
        "SUI/USDT": "sui",
    }
    
    coin_id = symbol_map.get(pair)
    if not coin_id:
        return None
    
    try:
        params = {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        }
        r = requests.get(COINGECKO_SIMPLE, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        coin_data = data.get(coin_id)
        if not coin_data:
            return None
        
        price = coin_data.get("usd", 0)
        change = coin_data.get("usd_24h_change", 0)
        vol = coin_data.get("usd_24h_vol", 0)
        
        return {
            "symbol": pair,
            "price": price,
            "volume_24h": 0,
            "quote_volume_24h": vol,
            "high_24h": price * (1 + abs(change) / 10000),
            "low_24h": price / (1 + abs(change) / 10000),
            "change_24h": change,
        }
    except Exception:
        return None


def _coingecko_klines(pair: str, interval: str = "1h", limit: int = 24) -> Optional[List[Dict]]:
    """CoinGecko doesn't provide klines on free tier. Fallback to generated data."""
    return None


# ─── Unified Exchange Functions ──────────────────────────────────

def fetch_ticker(pair: str) -> Optional[Dict]:
    """Fetch 24hr ticker from any available exchange."""
    _init_exchanges()
    
    for ticker_fn, _ in EXCHANGES:
        try:
            data = ticker_fn(pair)
            if data and data.get("price", 0) > 0:
                logger.debug(f"Got ticker for {pair} from {ticker_fn.__name__}")
                return data
        except Exception as e:
            logger.debug(f"{ticker_fn.__name__} failed for {pair}: {e}")
            continue
    
    logger.warning(f"All exchanges failed for {pair}")
    return None


def fetch_klines(pair: str, interval: str = "1h", limit: int = 24) -> Optional[List[Dict]]:
    """Fetch kline data from any available exchange."""
    _init_exchanges()
    
    for _, klines_fn in EXCHANGES:
        if klines_fn is None:
            continue
        try:
            data = klines_fn(pair, interval, limit)
            if data and len(data) >= 4:  # Need at least 4 candles for detection
                return data
        except Exception:
            continue
    
    return None


# ─── Signal Detection ─────────────────────────────────────────────

def check_volume_spike(pair: str, ticker: Dict, klines: List[Dict]) -> Optional[Signal]:
    """
    Detect volume spikes — current volume > multiplier * average volume.
    """
    if not klines or len(klines) < 6:
        return None

    current_volume = ticker.get("quote_volume_24h", 0)
    # Calculate average hourly volume from last 24 candles
    volumes = [k["volume"] * k["close"] for k in klines[-24:]]  # quote volume
    if not volumes:
        return None

    avg_hourly = sum(volumes) / len(volumes)
    if avg_hourly == 0:
        return None

    # Compare current hour's volume to hourly average
    current_hourly = klines[-1]["volume"] * klines[-1]["close"]
    if current_hourly == 0:
        return None

    ratio = current_hourly / avg_hourly

    if ratio >= VOLUME_SPIKE_MULTIPLIER:
        confidence = min(int(ratio * 25), 95)
        price_change = ticker.get("change_24h", 0)
        signal_type = "BUY" if price_change > 0 else "SELL"

        return Signal(
            type=signal_type,
            pair=pair,
            price=ticker["price"],
            confidence=confidence,
            reason=f"Volume spike: {ratio:.1f}x average",
            details={
                "volume_change": (ratio - 1) * 100,
                "price_change": price_change,
            },
            timestamp=time.time(),
            source="volume_spike",
        )

    return None


def check_price_breakout(pair: str, ticker: Dict, klines: List[Dict]) -> Optional[Signal]:
    """
    Detect price breakouts — significant price movement with momentum.
    """
    if not klines or len(klines) < 4:
        return None

    # Compare current price to recent range
    recent = klines[-4:]
    high = max(k["high"] for k in recent)
    low = min(k["low"] for k in recent)
    current = ticker["price"]
    range_size = high - low if high > low else 1

    # Check if price broke above recent range
    if current > high * (1 + PRICE_BREAKOUT_PCT):
        # Check if volume confirms
        avg_volume = sum(k["volume"] for k in klines[:-1]) / (len(klines) - 1)
        current_vol = klines[-1]["volume"]
        vol_confirmation = current_vol > avg_volume * 1.5

        confidence = 70 if vol_confirmation else 55
        change_pct = ((current - klines[-2]["close"]) / klines[-2]["close"]) * 100

        return Signal(
            type="BUY",
            pair=pair,
            price=current,
            confidence=confidence,
            reason=f"Breakout above resistance! +{change_pct:.1f}%",
            details={
                "price_change": change_pct,
                "volume_confirmed": vol_confirmation,
            },
            timestamp=time.time(),
            source="breakout",
        )

    # Check if price broke below recent range
    if current < low * (1 - PRICE_BREAKOUT_PCT):
        avg_volume = sum(k["volume"] for k in klines[:-1]) / (len(klines) - 1)
        current_vol = klines[-1]["volume"]
        vol_confirmation = current_vol > avg_volume * 1.5

        confidence = 65 if vol_confirmation else 50
        change_pct = ((current - klines[-2]["close"]) / klines[-2]["close"]) * 100

        return Signal(
            type="SELL",
            pair=pair,
            price=current,
            confidence=confidence,
            reason=f"Breakdown below support! {change_pct:.1f}%",
            details={
                "price_change": change_pct,
                "volume_confirmed": vol_confirmation,
            },
            timestamp=time.time(),
            source="breakout",
        )

    return None


def check_momentum_shift(pair: str, ticker: Dict, klines: List[Dict]) -> Optional[Signal]:
    """
    Detect momentum shifts using simple moving average crossover logic.
    """
    if not klines or len(klines) < 12:
        return None

    closes = [k["close"] for k in klines]

    # Simple MA crossover: fast MA (3 periods) vs slow MA (12 periods)
    fast_ma = sum(closes[-3:]) / 3
    slow_ma = sum(closes[-12:]) / 12

    # Previous values for crossover detection
    prev_fast = sum(closes[-4:-1]) / 3
    prev_slow = sum(closes[-13:-1]) / 12 if len(closes) >= 13 else slow_ma

    current_price = ticker["price"]

    # Bullish crossover: fast MA crosses above slow MA
    if prev_fast <= prev_slow and fast_ma > slow_ma:
        confidence = min(int((fast_ma / slow_ma - 1) * 1000), 80)
        return Signal(
            type="BUY",
            pair=pair,
            price=current_price,
            confidence=confidence,
            reason=f"Bullish momentum shift (MA crossover)",
            details={
                "fast_ma": round(fast_ma, 8),
                "slow_ma": round(slow_ma, 8),
                "price_change": ticker.get("change_24h", 0),
            },
            timestamp=time.time(),
            source="momentum",
        )

    # Bearish crossover: fast MA crosses below slow MA
    if prev_fast >= prev_slow and fast_ma < slow_ma:
        confidence = min(int((prev_fast / prev_slow - 1) * 1000), 75)
        return Signal(
            type="SELL",
            pair=pair,
            price=current_price,
            confidence=confidence,
            reason=f"Bearish momentum shift (MA crossover)",
            details={
                "fast_ma": round(fast_ma, 8),
                "slow_ma": round(slow_ma, 8),
                "price_change": ticker.get("change_24h", 0),
            },
            timestamp=time.time(),
            source="momentum",
        )

    return None


def check_whale_transactions(pair: str) -> Optional[Signal]:
    """
    Check for large whale transactions using Whale Alert API.
    """
    whale_api_key = os.getenv("WHALE_ALERT_API_KEY")
    if not whale_api_key:
        return None

    # Extract the base symbol (e.g., "BTC" from "BTC/USDT")
    symbol = pair.split("/")[0].lower()

    try:
        params = {
            "api_key": whale_api_key,
            "min_value": 500000,  # $500k minimum
            "limit": 5,
        }
        r = requests.get(WHALE_ALERT_URL, params=params, timeout=10)
        if r.status_code != 200:
            return None

        data = r.json()
        transactions = data.get("transactions", [])
        for tx in transactions:
            if symbol in tx.get("symbol", "").lower():
                amount_usd = float(tx.get("amount_usd", 0))
                return Signal(
                    type="WHALE",
                    pair=pair,
                    price=0,  # Not directly available
                    confidence=85,
                    reason=f"Whale transaction: ${amount_usd:,.0f}",
                    details={
                        "whale_amount": amount_usd,
                        "hash": tx.get("hash", "")[:16],
                    },
                    timestamp=time.time(),
                    source="whale",
                )
    except Exception as e:
        logger.error(f"Whale check failed: {e}")

    return None


# ─── Trending Coins (Bonus Signals) ───────────────────────────────

def fetch_trending_coins() -> List[Dict]:
    """Fetch trending coins from CoinGecko."""
    try:
        r = requests.get(COINGECKO_TRENDING, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        coins = data.get("coins", [])
        trending = []
        for coin in coins[:10]:
            item = coin.get("item", {})
            trending.append({
                "name": item.get("name", ""),
                "symbol": item.get("symbol", ""),
                "market_cap_rank": item.get("market_cap_rank", 0),
            })
        return trending
    except Exception as e:
        logger.error(f"Failed to fetch trending: {e}")
        return []


# ─── Main Signal Scanner ──────────────────────────────────────────

def scan_pair(pair: str) -> List[Signal]:
    """Scan a single pair for all signal types."""
    signals = []

    try:
        ticker = fetch_ticker(pair)
        if not ticker:
            return signals

        klines = fetch_klines(pair, "1h", 24)
        if not klines:
            return signals

        # Run all detectors
        for detector in [check_volume_spike, check_price_breakout, check_momentum_shift]:
            signal = detector(pair, ticker, klines)
            if signal and signal.confidence >= MIN_SIGNAL_CONFIDENCE:
                signals.append(signal)

        # Whale check (separate API)
        whale = check_whale_transactions(pair)
        if whale:
            signals.append(whale)

    except Exception as e:
        logger.error(f"Error scanning {pair}: {e}")

    return signals


def scan_all_pairs(pairs: List[str] = None) -> List[Signal]:
    """Scan all configured pairs for signals."""
    if pairs is None:
        pairs = DEFAULT_PAIRS

    all_signals = []
    for pair in pairs:
        signals = scan_pair(pair)
        all_signals.extend(signals)
        # Rate limit: 1200 requests per minute for Binance public API
        time.sleep(0.1)

    # Sort by confidence (highest first)
    all_signals.sort(key=lambda s: s.confidence, reverse=True)

    return all_signals


# ─── Signal Caching ───────────────────────────────────────────────

CACHE_FILE = Path(__file__).parent / "signal_cache.json"

def cache_signals(signals: List[Signal]):
    """Cache latest signals to file."""
    data = {
        "generated_at": time.time(),
        "signals": [asdict(s) for s in signals],
    }
    CACHE_FILE.write_text(json.dumps(data, indent=2))

def get_cached_signals(max_age_seconds: int = 300) -> List[Signal]:
    """Get cached signals if fresh enough."""
    if not CACHE_FILE.exists():
        return []

    try:
        data = json.loads(CACHE_FILE.read_text())
        age = time.time() - data.get("generated_at", 0)
        if age > max_age_seconds:
            return []

        signals = []
        for s in data.get("signals", []):
            signals.append(Signal(**s))
        return signals
    except Exception:
        return []

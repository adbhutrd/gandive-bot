#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   📈 GANDIVE BOT — Signal Performance Tracker               ║
║   Tracks every signal's outcome, win rate, and P&L.        ║
║   This is the #1 selling point for premium subscriptions.   ║
╚═══════════════════════════════════════════════════════════════╝

Commands:
  /perf     — Show performance summary (win rate, P&L, best/worst)
  /signals  — Now includes performance badges on past signals
  /report   — Detailed performance report (premium)
"""

import os
import json
import time
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Imported lazily inside auto_resolve_signals to avoid circular import

logger = logging.getLogger("gandive-performance")

BASE_DIR = Path(__file__).parent.resolve()
PERF_FILE = BASE_DIR / "signal_performance.json"

# ─── Data Types ───────────────────────────────────────────────────

@dataclass
class SignalRecord:
    """Record of a signal with its outcome."""
    signal_id: str  # Unique hash
    pair: str
    signal_type: str  # BUY, SELL, WHALE, MOMENTUM
    entry_price: float
    timestamp: float
    confidence: int
    source: str  # volume_spike, breakout, etc.
    direction: str  # LONG (BUY) or SHORT (SELL)
    
    # Outcome (filled later)
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None
    outcome: Optional[str] = None  # "win", "loss", "open"
    pnl_percentage: Optional[float] = None
    pnl_usd: Optional[float] = None  # Simulated $100 position

    def calculate_pnl(self, exit_price: float) -> Tuple[float, float]:
        """Calculate P&L percentage and USD (simulated $100 position)."""
        if self.direction == "LONG":
            pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100
        else:
            pnl_pct = ((self.entry_price - exit_price) / self.entry_price) * 100
        return pnl_pct, pnl_pct * 100  # $100 position → same as pct

    def get_outcome(self, exit_price: float) -> str:
        """Determine if signal was a win or loss."""
        pnl_pct, _ = self.calculate_pnl(exit_price)
        if pnl_pct >= 2.0:
            return "win"
        elif pnl_pct <= -2.0:
            return "loss"
        else:
            return "breakeven"


# ─── Storage ──────────────────────────────────────────────────────

def _load_records() -> List[dict]:
    """Load signal records from file."""
    if not PERF_FILE.exists():
        return []
    try:
        data = json.loads(PERF_FILE.read_text())
        return data.get("records", [])
    except Exception as e:
        logger.warning(f"Failed to load performance data: {e}")
        return []


def _save_records(records: List[dict]):
    """Save signal records to file."""
    data = {
        "last_updated": time.time(),
        "total_records": len(records),
        "records": records,
    }
    PERF_FILE.write_text(json.dumps(data, indent=2))


def generate_signal_id(pair: str, signal_type: str, price: float, timestamp: float) -> str:
    """Generate a unique signal ID."""
    raw = f"{pair}:{signal_type}:{price:.4f}:{int(timestamp / 60)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ─── Recording ────────────────────────────────────────────────────

def record_signal(pair: str, signal_type: str, entry_price: float, 
                   confidence: int, source: str, timestamp: float = None) -> str:
    """Record a signal being sent. Returns the signal ID."""
    records = _load_records()
    timestamp = timestamp or time.time()
    signal_id = generate_signal_id(pair, signal_type, entry_price, timestamp)

    # Don't duplicate
    for r in records:
        if r["signal_id"] == signal_id:
            return signal_id

    direction = "LONG" if signal_type in ("BUY", "MOMENTUM") else "SHORT"

    record = {
        "signal_id": signal_id,
        "pair": pair,
        "signal_type": signal_type,
        "entry_price": entry_price,
        "timestamp": timestamp,
        "confidence": confidence,
        "source": source,
        "direction": direction,
        "exit_price": None,
        "exit_time": None,
        "outcome": "open",
        "pnl_percentage": None,
        "pnl_usd": None,
    }

    records.append(record)
    _save_records(records)
    logger.info(f"📝 Recorded signal: {pair} {signal_type} @ ${entry_price:.4f}")
    return signal_id


def report_outcome(signal_id: str, exit_price: float) -> Optional[Dict]:
    """Report the outcome of a signal. Returns the updated record."""
    records = _load_records()
    for record in records:
        if record["signal_id"] == signal_id:
            if record["outcome"] != "open":
                logger.info(f"Signal {signal_id} already resolved: {record['outcome']}")
                return record

            pnl_pct, pnl_usd = _calculate_pnl(
                record["direction"], record["entry_price"], exit_price
            )
            record["exit_price"] = exit_price
            record["exit_time"] = time.time()
            record["outcome"] = "win" if pnl_pct >= 2 else ("loss" if pnl_pct <= -2 else "breakeven")
            record["pnl_percentage"] = round(pnl_pct, 2)
            record["pnl_usd"] = round(pnl_usd, 2)
            _save_records(records)
            logger.info(f"📊 Signal resolved: {record['outcome']} ({pnl_pct:+.2f}%)")
            return record

    logger.warning(f"Signal not found: {signal_id}")
    return None


def _calculate_pnl(direction: str, entry: float, exit: float) -> Tuple[float, float]:
    """Calculate P&L for a position."""
    if direction == "LONG":
        pnl_pct = ((exit - entry) / entry) * 100
    else:
        pnl_pct = ((entry - exit) / entry) * 100
    pnl_usd = pnl_pct * 100  # Simulated $100 position
    return pnl_pct, pnl_usd


# ─── Auto-Resolution ─────────────────────────────────────────────

def auto_resolve_signals():
    """Auto-resolve open signals by checking current market price.
    
    Uses simple logic: if price moved 2%+ in signal direction = win,
    if 2%- in opposite = loss, otherwise stays open.
    """
    from signals import fetch_ticker
    
    records = _load_records()
    updated = 0
    now = time.time()

    for record in records:
        if record["outcome"] != "open":
            continue

        # Only check signals that are 1-24 hours old
        age_hours = (now - record["timestamp"]) / 3600
        if age_hours < 1 or age_hours > 24:
            continue

        ticker = fetch_ticker(record["pair"])
        if not ticker or ticker["price"] == 0:
            continue

        current_price = ticker["price"]
        pnl_pct, pnl_usd = _calculate_pnl(record["direction"], record["entry_price"], current_price)

        # Auto-resolve only for clear moves (or old signals)
        age_hours = (now - record["timestamp"]) / 3600
        if abs(pnl_pct) >= 2 or age_hours >= 12:
            record["exit_price"] = current_price
            record["exit_time"] = now
            record["outcome"] = "win" if pnl_pct >= 2 else ("loss" if pnl_pct <= -2 else "breakeven")
            record["pnl_percentage"] = round(pnl_pct, 2)
            record["pnl_usd"] = round(pnl_usd, 2)
            updated += 1

    if updated:
        _save_records(records)
        logger.info(f"Auto-resolved {updated} signals")

    return updated


# ─── Analytics ────────────────────────────────────────────────────

def get_performance_stats(days: int = 30) -> Dict:
    """Get performance statistics for the given time period."""
    records = _load_records()
    now = time.time()
    cutoff = now - (days * 86400)

    # Filter by time
    recent = [r for r in records if r["timestamp"] >= cutoff]
    
    total = len(recent)
    resolved = [r for r in recent if r["outcome"] in ("win", "loss", "breakeven")]
    open_signals = [r for r in recent if r["outcome"] == "open"]
    
    wins = len([r for r in resolved if r["outcome"] == "win"])
    losses = len([r for r in resolved if r["outcome"] == "loss"])
    breakevens = len([r for r in resolved if r["outcome"] == "breakeven"])

    win_rate = (wins / resolved * 100) if resolved else 0

    # P&L
    total_pnl = sum(r.get("pnl_percentage", 0) or 0 for r in resolved)
    avg_pnl = total_pnl / resolved if resolved else 0
    total_pnl_usd = sum(r.get("pnl_usd", 0) or 0 for r in resolved)

    # Best/worst signals
    winning_signals = [r for r in resolved if r.get("pnl_percentage", 0) or 0 > 0]
    losing_signals = [r for r in resolved if r.get("pnl_percentage", 0) or 0 < 0]
    best = max(winning_signals, key=lambda r: r.get("pnl_percentage", 0)) if winning_signals else None
    worst = min(losing_signals, key=lambda r: r.get("pnl_percentage", 0)) if losing_signals else None

    # Best pair
    pair_perf = {}
    for r in resolved:
        pnl = r.get("pnl_percentage", 0) or 0
        pair_perf.setdefault(r["pair"], {"signals": 0, "wins": 0, "total_pnl": 0})
        pair_perf[r["pair"]]["signals"] += 1
        pair_perf[r["pair"]]["total_pnl"] += pnl
        if r["outcome"] == "win":
            pair_perf[r["pair"]]["wins"] += 1

    best_pair = max(pair_perf, key=lambda p: pair_perf[p]["total_pnl"]) if pair_perf else None

    # Source breakdown
    source_perf = {}
    for r in resolved:
        src = r.get("source", "unknown")
        pnl = r.get("pnl_percentage", 0) or 0
        source_perf.setdefault(src, {"signals": 0, "wins": 0, "total_pnl": 0})
        source_perf[src]["signals"] += 1
        source_perf[src]["total_pnl"] += pnl
        if r["outcome"] == "win":
            source_perf[src]["wins"] += 1

    for src in source_perf:
        s = source_perf[src]
        s["win_rate"] = round((s["wins"] / s["signals"]) * 100, 1) if s["signals"] else 0

    return {
        "period_days": days,
        "total_signals": total,
        "resolved": len(resolved),
        "open": len(open_signals),
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl, 2),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "avg_pnl_pct": round(avg_pnl, 2),
        "best_signal": {
            "pair": best["pair"],
            "pnl": best.get("pnl_percentage", 0),
        } if best else None,
        "worst_signal": {
            "pair": worst["pair"],
            "pnl": worst.get("pnl_percentage", 0),
        } if worst else None,
        "best_pair": best_pair,
        "pair_performance": pair_perf,
        "source_performance": source_perf,
        "win_streak": _get_current_streak(resolved),
        "profit_factor": _get_profit_factor(resolved),
    }


def _get_current_streak(resolved: List[dict]) -> int:
    """Get the current win/loss streak."""
    streak = 0
    for r in reversed(resolved):
        if r["outcome"] == "win":
            streak = streak + 1 if streak >= 0 else 1
        elif r["outcome"] == "loss":
            streak = streak - 1 if streak <= 0 else -1
        else:
            break
    return streak


def _get_profit_factor(resolved: List[dict]) -> float:
    """Calculate profit factor (gross wins / gross losses)."""
    gross_wins = sum(r.get("pnl_percentage", 0) or 0 for r in resolved if r.get("pnl_percentage", 0) or 0 > 0)
    gross_losses = abs(sum(r.get("pnl_percentage", 0) or 0 for r in resolved if r.get("pnl_percentage", 0) or 0 < 0))
    if gross_losses == 0:
        return float('inf') if gross_wins > 0 else 0
    return round(gross_wins / gross_losses, 2)


def get_performance_message(stats: Dict = None) -> str:
    """Generate a Telegram message from performance stats."""
    if stats is None:
        stats = get_performance_stats()

    win_emoji = "🟢" if stats["win_rate"] >= 60 else ("🟡" if stats["win_rate"] >= 40 else "🔴")
    
    msg = (
        f"<b>📈 GandiveBot Performance</b>\n\n"
        f"<b>📅 Period:</b> Last {stats['period_days']} days\n\n"
        f"<b>🎯 Win Rate:</b> {win_emoji} <b>{stats['win_rate']}%</b>\n"
        f"<b>📊 Total Signals:</b> {stats['total_signals']}\n"
        f"<b>✅ Wins:</b> {stats['wins']}\n"
        f"<b>❌ Losses:</b> {stats['losses']}\n"
        f"<b>➖ Breakeven:</b> {stats['breakevens']}\n"
        f"<b>🔄 Open:</b> {stats['open']}\n\n"
        f"<b>💰 P&L:</b>\n"
        f"• Total return: <b>{stats['total_pnl_pct']:+.2f}%</b>\n"
        f"• Simulated P&L ($100/trade): <b>${stats['total_pnl_usd']:+.2f}</b>\n"
        f"• Avg return/trade: {stats['avg_pnl_pct']:+.2f}%\n"
        f"• Profit factor: {stats.get('profit_factor', 0):.2f}x\n"
    )

    if stats.get("win_streak", 0) > 2:
        msg += f"\n<b>🔥 Win streak:</b> {stats['win_streak']} 🚀\n"
    elif stats.get("win_streak", 0) < -2:
        msg += f"\n<b>📉 Loss streak:</b> {abs(stats['win_streak'])}\n"

    if stats.get("best_pair"):
        bp = stats["pair_performance"].get(stats["best_pair"], {})
        msg += f"\n<b>🏆 Best pair:</b> <code>{stats['best_pair']}</code> ({bp.get('total_pnl', 0):+.1f}%)\n"

    if stats.get("best_signal"):
        msg += f"<b>⭐ Best signal:</b> <code>{stats['best_signal']['pair']}</code> ({stats['best_signal']['pnl']:+.1f}%)\n"

    msg += f"\n<i>💎 Premium users get detailed reports with /report</i>"

    return msg


def get_detailed_report(stats: Dict = None) -> str:
    """Generate a detailed performance report (premium feature)."""
    if stats is None:
        stats = get_performance_stats()

    msg = (
        f"<b>📊 Detailed Performance Report</b>\n\n"
        f"<b>🎯 Win Rate:</b> {stats['win_rate']}%\n"
        f"<b>💰 Total P&L:</b> {stats['total_pnl_pct']:+.2f}%\n"
        f"<b>💵 Simulated P&L:</b> ${stats['total_pnl_usd']:+.2f}\n"
        f"<b>📈 Avg Return/Trade:</b> {stats['avg_pnl_pct']:+.2f}%\n"
        f"<b>🔄 Profit Factor:</b> {stats.get('profit_factor', 0):.2f}x\n\n"
    )

    # Source breakdown
    msg += "<b>📊 By Signal Type:</b>\n"
    for src, perf in sorted(stats.get("source_performance", {}).items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        emoji = {"volume_spike": "📈", "breakout": "🚀", "momentum": "⚡", "whale": "🐋"}.get(src, "📊")
        msg += f"{emoji} {src.replace('_',' ').title()}: {perf['signals']} sigs, {perf['win_rate']}% WR, {perf['total_pnl']:+.1f}%\n"

    msg += "\n<b>📊 By Pair:</b>\n"
    for pair, perf in sorted(stats.get("pair_performance", {}).items(), key=lambda x: x[1]["total_pnl"], reverse=True)[:5]:
        msg += f"<code>{pair}</code>: {perf['signals']} sigs, {perf['wins']}W, {perf['total_pnl']:+.1f}%\n"

    if stats.get("best_signal"):
        msg += f"\n<b>⭐ All-Time Best:</b> <code>{stats['best_signal']['pair']}</code> ({stats['best_signal']['pnl']:+.1f}%)\n"
    if stats.get("worst_signal"):
        msg += f"<b>💩 All-Time Worst:</b> <code>{stats['worst_signal']['pair']}</code> ({stats['worst_signal']['pnl']:+.1f}%)\n"

    return msg

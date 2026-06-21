#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║   📊 GANDIVE BOT — Web Dashboard                           ║
║   Real-time signal dashboard, performance charts, admin     ║
╚═══════════════════════════════════════════════════════════════╝

Run: python dashboard.py
Then open: http://localhost:8000
"""

import os
import json
import time
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

from premium import get_premium_stats, get_premium_users_list
from signals import get_cached_signals, DEFAULT_PAIRS, Signal
from performance import get_performance_stats

logger = logging.getLogger("gandive-dashboard")


# ─── HTML Template ────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GandiveBot Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
      --bg: #0a0a0f; --surface: #12121a; --card: #1a1a26;
      --border: #2a2a3a; --text: #e8e8f0; --muted: #8888a0;
      --primary: #f7931a; --buy: #22c55e; --sell: #ef4444;
      --accent: #10b981; --radius: 12px;
    }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: var(--bg); color: var(--text); padding: 24px; }
    .container { max-width: 1400px; margin: 0 auto; }
    h1 { font-size: 28px; margin-bottom: 4px; }
    .subtitle { color: var(--muted); margin-bottom: 32px; font-size: 14px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 32px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
    .card h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 8px; }
    .card .value { font-size: 28px; font-weight: 800; }
    .card .value.green { color: var(--buy); }
    .card .value.red { color: var(--sell); }
    .card .value.orange { color: var(--primary); }
    .card .value.accent { color: var(--accent); }
    .card .sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
    .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 32px; }
    .chart-container { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
    .chart-container h3 { margin-bottom: 16px; font-size: 14px; color: var(--muted); }
    .chart-container canvas { max-height: 250px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
    th { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 1px; }
    td .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
    .badge.buy { background: rgba(34,197,94,0.15); color: var(--buy); }
    .badge.sell { background: rgba(239,68,68,0.15); color: var(--sell); }
    .badge.whale { background: rgba(139,92,246,0.15); color: #8b5cf6; }
    .badge.win { background: rgba(34,197,94,0.15); color: var(--buy); }
    .badge.loss { background: rgba(239,68,68,0.15); color: var(--sell); }
    .badge.open { background: rgba(247,147,26,0.15); color: var(--primary); }
    .row { display: flex; gap: 24px; margin-bottom: 32px; }
    .col { flex: 1; }
    @media (max-width: 768px) { .charts { grid-template-columns: 1fr; } .row { flex-direction: column; } }
    .refresh { display: inline-block; padding: 8px 16px; background: var(--primary); color: #fff;
               border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600;
               text-decoration: none; margin-bottom: 16px; }
    .refresh:hover { opacity: 0.9; }
    .signal-type { font-family: monospace; font-size: 12px; }
  </style>
</head>
<body>
  <div class="container">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div>
        <h1>🤖 GandiveBot Dashboard</h1>
        <p class="subtitle">Live signal monitoring &bull; <span id="lastUpdate">updating...</span></p>
      </div>
      <a href="/" class="refresh">🔄 Refresh</a>
    </div>

    <!-- Stats Cards -->
    <div class="grid" id="statsCards"></div>

    <!-- Charts -->
    <div class="charts">
      <div class="chart-container"><h3>Win Rate Over Time</h3><canvas id="winRateChart"></canvas></div>
      <div class="chart-container"><h3>Signals by Type</h3><canvas id="signalTypeChart"></canvas></div>
    </div>

    <div class="row">
      <div class="col">
        <div class="card">
          <h3>📡 Live Signals</h3>
          <div id="liveSignals"><p style="color: var(--muted);">Loading...</p></div>
        </div>
      </div>
      <div class="col">
        <div class="card">
          <h3>📈 Recent Performance</h3>
          <div id="recentPerformance"><p style="color: var(--muted);">Loading...</p></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    let winRateChartInstance = null;
    let signalTypeChartInstance = null;

    async function loadData() {
      try {
        const res = await fetch('/api/data');
        const data = await res.json();
        render(data);
      } catch (e) {
        document.getElementById('statsCards').innerHTML = '<p style="color: var(--sell);">Failed to load data</p>';
      }
    }

    function render(data) {
      document.getElementById('lastUpdate').textContent = 'Updated ' + new Date().toLocaleTimeString();

      // Stats cards
      document.getElementById('statsCards').innerHTML = `
        <div class="card"><h3>Win Rate</h3><div class="value ${data.performance.win_rate >= 50 ? 'green' : 'red'}">${data.performance.win_rate}%</div><div class="sub">${data.performance.wins}W / ${data.performance.losses}L</div></div>
        <div class="card"><h3>Total P&L</h3><div class="value ${data.performance.total_pnl_usd >= 0 ? 'green' : 'red'}">${data.performance.total_pnl_usd >= 0 ? '+' : ''}$${data.performance.total_pnl_usd.toFixed(2)}</div><div class="sub">Simulated $100/trade</div></div>
        <div class="card"><h3>Active Premium</h3><div class="value accent">${data.premium.active}</div><div class="sub">${data.premium.total_users} total users</div></div>
        <div class="card"><h3>Live Signals</h3><div class="value orange">${data.signals_count}</div><div class="sub">${data.pairs_monitored} pairs</div></div>
        <div class="card"><h3>Total Signals Sent</h3><div class="value">${data.performance.total_signals}</div><div class="sub">All time</div></div>
        <div class="card"><h3>Profit Factor</h3><div class="value ${(data.performance.profit_factor || 0) >= 1.5 ? 'green' : 'orange'}">${data.performance.profit_factor || 0}x</div><div class="sub">${(data.performance.profit_factor || 0) >= 1.5 ? 'Profitable' : 'Needs improvement'}</div></div>
      `;

      // Destroy old chart instances to prevent memory leaks
      if (winRateChartInstance) winRateChartInstance.destroy();
      if (signalTypeChartInstance) signalTypeChartInstance.destroy();

      // Win rate chart
      winRateChartInstance = new Chart(document.getElementById('winRateChart'), {
        type: 'doughnut',
        data: {
          labels: ['Wins', 'Losses', 'Breakeven'],
          datasets: [{
            data: [data.performance.wins, data.performance.losses, data.performance.breakevens],
            backgroundColor: ['#22c55e', '#ef4444', '#8888a0'],
            borderWidth: 0,
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { position: 'bottom', labels: { color: '#8888a0' } } }
        }
      });

      // Signal type chart
      const sources = data.performance.source_performance || {};
      const srcLabels = Object.keys(sources);
      const srcData = srcLabels.map(s => sources[s].signals);
      const srcColors = { volume_spike: '#22c55e', breakout: '#f7931a', momentum: '#8b5cf6', whale: '#ef4444' };

      signalTypeChartInstance = new Chart(document.getElementById('signalTypeChart'), {
        type: 'bar',
        data: {
          labels: srcLabels.map(s => s.replace('_', ' ').replace('\\b(\\w)', c => c.toUpperCase())),
          datasets: [{
            label: 'Signals',
            data: srcData,
            backgroundColor: srcLabels.map(s => srcColors[s] || '#8888a0'),
            borderRadius: 6,
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: '#8888a0' } },
            y: { ticks: { color: '#8888a0' }, beginAtZero: true }
          }
        }
      });

      // Live signals
      const signalsHtml = data.signals.length > 0
        ? '<table><tr><th>Type</th><th>Pair</th><th>Price</th><th>Conf</th><th>Reason</th></tr>' +
          data.signals.slice(0, 10).map(s => `
            <tr>
              <td><span class="badge ${s.type.toLowerCase()}">${s.type}</span></td>
              <td><code>${s.pair}</code></td>
              <td>$${s.price.toFixed(s.price > 100 ? 2 : 4)}</td>
              <td>${s.confidence}%</td>
              <td style="color:var(--muted);font-size:12px;">${s.reason}</td>
            </tr>
          `).join('') + '</table>'
        : '<p style="color: var(--muted);">No signals yet. Scanner warming up...</p>';
      document.getElementById('liveSignals').innerHTML = signalsHtml;

      // Recent performance
      const perfRows = data.recent_signals.slice(0, 10).map(s => `
        <tr>
          <td><span class="badge ${s.signal_type.toLowerCase()}">${s.signal_type}</span></td>
          <td><code>${s.pair}</code></td>
          <td>$${s.entry_price.toFixed(4)}</td>
          <td><span class="badge ${s.outcome}">${s.outcome}</span></td>
          <td style="color: ${(s.pnl_percentage || 0) >= 0 ? 'var(--buy)' : 'var(--sell)'}">${s.pnl_percentage ? (s.pnl_percentage >= 0 ? '+' : '') + s.pnl_percentage.toFixed(2) + '%' : '-'}</td>
        </tr>
      `).join('');

      document.getElementById('recentPerformance').innerHTML = perfRows
        ? '<table><tr><th>Type</th><th>Pair</th><th>Entry</th><th>Result</th><th>P&L</th></tr>' + perfRows + '</table>'
        : '<p style="color: var(--muted);">No performance data yet.</p>';
    }

    loadData();
    setInterval(loadData, 30000);
  </script>
</body>
</html>"""


# ─── API Data ─────────────────────────────────────────────────────

def get_dashboard_data() -> dict:
    """Get all data for the dashboard."""
    signals = get_cached_signals(max_age_seconds=600) or []
    premium = get_premium_stats()
    perf = get_performance_stats(days=30)

    # Recent signals from performance tracker
    try:
        from performance import _load_records
        records = _load_records()
        recent = sorted(records, key=lambda r: r.get("timestamp", 0), reverse=True)[:20]
    except Exception:
        recent = []

    return {
        "signals": [{"type": s.type, "pair": s.pair, "price": s.price,
                      "confidence": s.confidence, "reason": s.reason} for s in signals],
        "signals_count": len(signals),
        "pairs_monitored": len(DEFAULT_PAIRS),
        "premium": premium,
        "performance": perf,
        "recent_signals": recent,
    }


# ─── HTTP Server ──────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/data":
            data = get_dashboard_data()
            self._json(200, data)
        elif path == "/" or path == "/dashboard":
            self._html(200, HTML)
        else:
            self._html(404, "<h1>404 Not Found</h1>")

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, code, html):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, fmt, *args):
        logger.info(f"{self.address_string()} - {fmt % args}")


def main():
    port = int(os.getenv("DASHBOARD_PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"📊 GandiveBot Dashboard: http://localhost:{port}")
    print(f"   API: http://localhost:{port}/api/data")
    print(f"   Admin: Set up a reverse proxy for public access")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()

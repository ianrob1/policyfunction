"""
Vercel serverless function: GET /api/backtest?start=...&end=...&strategy=...
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

# Ensure project root is on path so we can import backtest
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            start = (qs.get("start") or [None])[0]
            end = (qs.get("end") or [None])[0]
            if not start or not end:
                self.wfile.write(json.dumps({"error": "start and end (YYYY-MM-DD) required"}).encode("utf-8"))
                return
            strategy = (qs.get("strategy") or ["sma200"])[0]
            if strategy not in ("sma200", "sma50", "vix", "sma50_200_tbill", "all_weather"):
                strategy = "sma200"
            capital = int((qs.get("capital") or ["10000"])[0])
            sma_period = int((qs.get("sma_period") or ["200"])[0])
            vix_threshold = int((qs.get("vix_threshold") or ["30"])[0])
            buy_dollars = int((qs.get("buy_dollars") or ["1000"])[0])
            tbill_pct = float((qs.get("tbill_annual_rate") or ["4"])[0])
            tbill_annual_rate = tbill_pct / 100.0 if tbill_pct > 1 else tbill_pct
            from backtest import run_backtest_custom
            result = run_backtest_custom(
                start, end,
                strategy=strategy,
                initial_capital=capital,
                sma_period=sma_period,
                vix_threshold=vix_threshold,
                buy_dollars=buy_dollars,
                tbill_annual_rate=tbill_annual_rate,
            )
            self.wfile.write(json.dumps(result).encode("utf-8"))
        except ValueError as e:
            self.wfile.write(json.dumps({"error": "Invalid parameter: " + str(e)}).encode("utf-8"))
        except Exception as e:
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

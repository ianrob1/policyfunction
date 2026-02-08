"""
Vercel serverless function: GET /api/earnings_check?ticker=AAPL
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

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
            ticker = (qs.get("ticker") or [""])[0]
            if not ticker or not str(ticker).strip():
                self.wfile.write(json.dumps({"error": "ticker required"}).encode("utf-8"))
                return
            from earnings_checker import compute_recommendation
            result = compute_recommendation(str(ticker).strip())
            self.wfile.write(json.dumps(result).encode("utf-8"))
        except Exception as e:
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

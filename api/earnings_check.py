"""
Vercel serverless: GET /api/earnings_check?ticker=AAPL
"""
import json
import os
import sys
import urllib.parse

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


def handler(req, context=None):
    parsed = urllib.parse.urlparse(req.get("path", req.get("url", "")))
    qs = urllib.parse.parse_qs(parsed.query)
    ticker = (qs.get("ticker") or [""])[0]
    if not ticker or not str(ticker).strip():
        return {"statusCode": 200, "body": json.dumps({"error": "ticker required"})}
    try:
        from earnings_checker import compute_recommendation
        result = compute_recommendation(str(ticker).strip())
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        return {"statusCode": 200, "body": json.dumps({"error": str(e)})}

#!/usr/bin/env python3
"""
Serve the dashboard and regenerate backtest on request.
GET /regenerate -> run backtest, write backtest_results.json, return {"ok": true}
GET /* -> serve static files (index.html, backtest_results.json, etc.)
"""
import http.server
import json
import os
import subprocess
import sys
import urllib.parse

PORT = int(os.environ.get("PORT", "8080"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_backtest():
    """Run backtest.py (VIX); return (success, json_string or error_message)."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "backtest.py"), "5"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=SCRIPT_DIR,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout or "backtest failed"
        out = result.stdout.strip()
        if not out:
            return False, "empty output"
        json.loads(out)
        path = os.path.join(SCRIPT_DIR, "backtest_results.json")
        with open(path, "w") as f:
            f.write(out)
        return True, out
    except subprocess.TimeoutExpired:
        return False, "backtest timed out"
    except Exception as e:
        return False, str(e)


def run_backtest_sma200():
    """Run backtest.py sma200; return (success, json_string or error_message)."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "backtest.py"), "5", "sma200"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=SCRIPT_DIR,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout or "sma200 backtest failed"
        out = result.stdout.strip()
        if not out:
            return False, "empty output"
        json.loads(out)
        return True, out
    except subprocess.TimeoutExpired:
        return False, "backtest timed out"
    except Exception as e:
        return False, str(e)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/index.html"

        if path == "/regenerate":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            ok, msg = run_backtest()
            body = json.dumps({"ok": ok, "message": str(msg) if not ok else "ok"})
            self.wfile.write(body.encode("utf-8"))
            return

        if path == "/strategy-study":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                result = subprocess.run(
                    [sys.executable, os.path.join(SCRIPT_DIR, "strategy_study.py"), "--json"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=SCRIPT_DIR,
                )
                if result.returncode == 0 and result.stdout.strip():
                    self.wfile.write(result.stdout.strip().encode("utf-8"))
                else:
                    self.wfile.write(json.dumps({"error": result.stderr or "Strategy study failed"}).encode("utf-8"))
            except subprocess.TimeoutExpired:
                self.wfile.write(json.dumps({"error": "Strategy study timed out"}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if path == "/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            ok, msg = run_backtest()
            if ok:
                self.wfile.write(msg.encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"error": str(msg)}).encode("utf-8"))
            return

        if path == "/data-sma200":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            ok, msg = run_backtest_sma200()
            if ok:
                self.wfile.write(msg.encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"error": str(msg)}).encode("utf-8"))
            return

        if path == "/backtest":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                qs = urllib.parse.parse_qs(parsed.query)
                start = (qs.get("start") or [None])[0]
                end = (qs.get("end") or [None])[0]
                if not start or not end:
                    self.wfile.write(json.dumps({"error": "start and end (YYYY-MM-DD) required"}).encode("utf-8"))
                    return
                strategy = (qs.get("strategy") or ["sma200"])[0]
                if strategy not in ("sma200", "sma50", "vix"):
                    strategy = "sma200"
                capital = int((qs.get("capital") or ["10000"])[0])
                sma_period = int((qs.get("sma_period") or ["200"])[0])
                vix_threshold = int((qs.get("vix_threshold") or ["30"])[0])
                buy_dollars = int((qs.get("buy_dollars") or ["1000"])[0])
                from backtest import run_backtest_custom
                result = run_backtest_custom(
                    start, end,
                    strategy=strategy,
                    initial_capital=capital,
                    sma_period=sma_period,
                    vix_threshold=vix_threshold,
                    buy_dollars=buy_dollars,
                )
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except ValueError as e:
                self.wfile.write(json.dumps({"error": "Invalid parameter: " + str(e)}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        # Serve files (default behavior)
        if path == "/" or path == "":
            path = "/index.html"
        self.path = path
        return http.server.SimpleHTTPRequestHandler.do_GET(self)


def main():
    for try_port in range(PORT, min(PORT + 3, 65536)):
        try:
            httpd = http.server.HTTPServer(("", try_port), Handler)
            break
        except OSError as e:
            if e.errno != 48:  # Address already in use
                raise
            if try_port == PORT + 2:
                raise SystemExit("Ports {}–{} in use. Set PORT=8083 (or another free port) and try again.".format(PORT, try_port))
    print("Server at http://127.0.0.1:{}".format(try_port))
    if try_port != PORT:
        print("(Port {} was in use.)".format(PORT))
    print("GET /regenerate to run backtest and refresh data.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

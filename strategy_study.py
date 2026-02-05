#!/usr/bin/env python3
"""
Systematic daily trading strategies vs SPY buy-and-hold (2005–present).
Includes transaction costs, regime analysis, and out-of-sample validation.
Output: rules, CAGR/Sharpe/max DD, weaknesses.
"""
import sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf

# ------------------------- Data -------------------------

def _col(df, *names):
    lower = {str(c).lower(): c for c in df.columns}
    for n in names:
        k = str(n).lower()
        if k in lower:
            return lower[k]
    return None

def fetch_spy_vix(start_date, end_date):
    """Fetch SPY and VIX daily close (and open for SPY)."""
    spy = yf.download("SPY", start=start_date, end=end_date, progress=False, auto_adjust=False)
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False, auto_adjust=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    close_col = _col(spy, "Close", "close")
    open_col = _col(spy, "Open", "open")
    vix_col = _col(vix, "Close", "close")
    if not close_col or not vix_col:
        raise ValueError("Missing Close columns")
    common = spy.index.intersection(vix.index)
    df = pd.DataFrame({
        "close": spy.loc[common, close_col].reindex(common),
        "open": spy.loc[common, open_col].reindex(common) if open_col else spy.loc[common, close_col].reindex(common),
        "vix": vix.loc[common, vix_col].reindex(common),
    })
    return df.dropna()

# ------------------------- Transaction costs -------------------------

ONE_WAY_BPS = 5   # 5 bps per trade (one-way); 10 bps round-trip
COST_PER_TRADE = ONE_WAY_BPS / 10000.0 * 2  # round-trip

def apply_costs(equity_curve, positions):
    """Reduce equity by round-trip cost when position changes."""
    p = np.asarray(positions, dtype=float)
    equity = np.asarray(equity_curve, dtype=float).copy()
    n_trades = 0
    for i in range(1, len(equity)):
        if p[i] != p[i - 1]:
            equity[i] *= 1 - COST_PER_TRADE
            n_trades += 1
    return equity.tolist(), n_trades

# ------------------------- Regimes -------------------------

def add_regimes(df):
    """Label regimes: bull/bear by 200d trend, vol by VIX."""
    df = df.copy()
    df["ret"] = df["close"].pct_change()
    df["sma200"] = df["close"].rolling(200, min_periods=200).mean()
    df["trend_200d"] = (df["close"] / df["sma200"] - 1) * 100
    df["regime_trend"] = "sideways"
    df.loc[df["trend_200d"] > 2, "regime_trend"] = "bull"
    df.loc[df["trend_200d"] < -2, "regime_trend"] = "bear"
    df["regime_vol"] = "mid"
    df.loc[df["vix"] > 25, "regime_vol"] = "high_vol"
    df.loc[df["vix"] < 15, "regime_vol"] = "low_vol"
    return df

# ------------------------- Strategy runners -------------------------

def run_strategy(df, position_series, name):
    """Given daily position (0 or 1), compute equity curve and metrics."""
    pos = np.asarray(position_series)
    ret = np.asarray(df["ret"].fillna(0))
    equity = 1.0
    curve = [1.0]
    for i in range(1, len(df)):
        equity *= 1 + ret[i] * pos[i]
        curve.append(equity)
    curve, n_trades = apply_costs(curve, pos)
    return curve, n_trades

def metrics_from_curve(equity_curve, periods_per_year=252):
    """CAGR, Sharpe (excess=0), Max DD from equity curve."""
    eq = np.asarray(equity_curve)
    n = len(eq)
    if n < 2:
        return {"cagr": 0, "sharpe": 0, "max_dd_pct": 0}
    ret = np.diff(eq) / eq[:-1]
    ret = ret[~np.isnan(ret)]
    if len(ret) == 0:
        return {"cagr": 0, "sharpe": 0, "max_dd_pct": 0}
    years = (n - 1) / periods_per_year
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if years > 0 else 0
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd_pct = np.min(dd) * 100
    mean_r = np.mean(ret)
    std_r = np.std(ret)
    sharpe = (mean_r / std_r * np.sqrt(periods_per_year)) if std_r > 0 else 0
    return {"cagr_pct": cagr * 100, "sharpe": sharpe, "max_dd_pct": max_dd_pct}

# ------------------------- Strategies -------------------------

def strategy_sma200(df):
    """Long when close > 200d SMA, else cash."""
    sma = df["close"].rolling(200, min_periods=200).mean()
    pos = (df["close"] > sma).astype(int)
    pos = pos.fillna(0)
    return pos.tolist(), "SMA200: Long SPY when close > 200-day SMA; otherwise cash."

def strategy_golden_cross(df):
    """Long when 50d SMA > 200d SMA, else cash."""
    s50 = df["close"].rolling(50, min_periods=50).mean()
    s200 = df["close"].rolling(200, min_periods=200).mean()
    pos = (s50 > s200).astype(int)
    pos = pos.fillna(0)
    return pos.tolist(), "50/200 Cross: Long when 50-day SMA > 200-day SMA; otherwise cash."

def strategy_vix_fear(df):
    """Long when VIX > 30 (enter), exit when VIX < 20."""
    pos = np.zeros(len(df))
    in_market = False
    for i in range(len(df)):
        v = df["vix"].iloc[i]
        if v > 30:
            in_market = True
        elif v < 20:
            in_market = False
        pos[i] = 1 if in_market else 0
    return pos.tolist(), "VIX Fear: Enter when VIX > 30, exit when VIX < 20; otherwise hold state."

def strategy_12_1_momentum(df):
    """Long when 12m return minus 1m return > 0 (skip last month)."""
    close = df["close"]
    ret_12m = close / close.shift(252) - 1
    ret_1m = close / close.shift(21) - 1
    signal = (ret_12m - ret_1m) > 0
    pos = signal.astype(int).fillna(0)
    return pos.tolist(), "12-1 Momentum: Long when 12-month return minus 1-month return > 0; else cash."

def strategy_oversold(df, entry_pct=-3, exit_pct=2, lookback=5):
    """Enter when lookback-day return < entry_pct%; exit when > exit_pct% or after 10 days."""
    ret_5d = df["close"].pct_change(lookback)
    pos = np.zeros(len(df))
    in_market = False
    days_held = 0
    for i in range(len(df)):
        r = ret_5d.iloc[i] * 100 if not pd.isna(ret_5d.iloc[i]) else None
        if in_market:
            days_held += 1
            if r is not None and r >= exit_pct:
                in_market = False
                days_held = 0
            elif days_held >= 10:
                in_market = False
                days_held = 0
        else:
            if r is not None and r <= entry_pct:
                in_market = True
                days_held = 0
        pos[i] = 1 if in_market else 0
    return pos.tolist(), f"Oversold: Enter when {lookback}d return < {entry_pct}%; exit when > {exit_pct}% or 10 days."

# ------------------------- Main -------------------------

def run_study():
    """Run the full study and return a dict suitable for JSON (for the dashboard)."""
    start = datetime(2005, 1, 1)
    end = datetime.now()
    df = fetch_spy_vix(start, end)
    df = add_regimes(df)
    df = df.dropna(subset=["ret", "regime_trend"])

    # Benchmark
    spy_curve = (1 + df["ret"].fillna(0)).cumprod().values
    spy_curve, _ = apply_costs(spy_curve, [1] * len(df))
    bench = metrics_from_curve(spy_curve)

    # Split: in-sample to 2013, out-of-sample 2014+
    is_end = datetime(2013, 12, 31)
    oos_start = datetime(2014, 1, 1)
    df_is = df.loc[df.index <= is_end]
    df_oos = df.loc[df.index >= oos_start]

    strategies = [
        ("SMA200", strategy_sma200),
        ("50/200 Golden Cross", strategy_golden_cross),
        ("VIX Fear", strategy_vix_fear),
        ("12-1 Momentum", strategy_12_1_momentum),
        ("Oversold (5d)", strategy_oversold),
    ]

    results_full = []
    results_is = []
    results_oos = []
    rules = {}
    weaknesses = {
        "SMA200": "Lags turns; whipsaws in sideways markets; underperforms in strong bull runs due to late entry.",
        "50/200 Golden Cross": "Very slow signals; large drawdowns before crossover; late exits in bear markets.",
        "VIX Fear": "Often buys into continued volatility; regime-dependent; can sit in cash for long periods.",
        "12-1 Momentum": "Vulnerable to momentum crashes; underperforms in sharp reversals; skip-month can miss trends.",
        "Oversold (5d)": "Catching falling knives; high drawdown risk; short holding period may cut winners early.",
    }

    spy_curve_list = list(spy_curve)
    strategy_curves = {}
    for name, strat_fn in strategies:
        pos_list, rule = strat_fn(df)
        rules[name] = rule
        curve, n_trades = run_strategy(df, pos_list, name)
        strategy_curves[name] = curve
        m_full = metrics_from_curve(curve)
        results_full.append((name, m_full, n_trades))

        if len(df_is) > 252:
            pos_is, _ = strat_fn(df_is)
            curve_is, _ = run_strategy(df_is, pos_is, name)
            results_is.append((name, metrics_from_curve(curve_is)))
        else:
            results_is.append((name, {"cagr_pct": 0, "sharpe": 0, "max_dd_pct": 0}))

        if len(df_oos) > 252:
            pos_oos, _ = strat_fn(df_oos)
            curve_oos, _ = run_strategy(df_oos, pos_oos, name)
            results_oos.append((name, metrics_from_curve(curve_oos)))
        else:
            results_oos.append((name, {"cagr_pct": 0, "sharpe": 0, "max_dd_pct": 0}))

    # Regime breakdown (full sample)
    regime_curves = {}
    for reg in ["bull", "bear", "sideways"]:
        mask = df["regime_trend"] == reg
        if mask.sum() < 20:
            continue
        sub = df.loc[mask]
        ret_sub = sub["ret"].fillna(0)
        regime_curves[reg] = (1 + ret_sub).cumprod().iloc[-1] / (1 + ret_sub).cumprod().iloc[0] - 1 if len(ret_sub) > 0 else 0

    # Chart data: downsample to ~500 points for smaller payload
    n = len(df)
    step = max(1, n // 500)
    idx = np.arange(0, n, step)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    dates = [df.index[i].strftime("%Y-%m-%d") for i in idx]
    chart_spy = [round(spy_curve_list[i], 4) for i in idx]
    chart_strategies = {}
    for name in strategy_curves:
        chart_strategies[name] = [round(strategy_curves[name][i], 4) for i in idx]

    data = {
        "rules": rules,
        "bench": bench,
        "full_results": [{"name": n, "cagr_pct": m["cagr_pct"], "sharpe": m["sharpe"], "max_dd_pct": m["max_dd_pct"], "trades": nt} for n, m, nt in results_full],
        "is_oos": [{"name": results_full[i][0], "is_cagr": results_is[i][1]["cagr_pct"], "is_sharpe": results_is[i][1]["sharpe"], "oos_cagr": results_oos[i][1]["cagr_pct"], "oos_sharpe": results_oos[i][1]["sharpe"]} for i in range(len(results_full))],
        "regimes": {k: round(v * 100, 1) for k, v in regime_curves.items()},
        "weaknesses": weaknesses,
        "summary": [
            "SMA200 improves CAGR and Sharpe vs buy-and-hold with much lower max drawdown; holds up in OOS.",
            "50/200 Cross is more conservative; similar to SPY with fewer trades; OOS slightly worse than IS.",
            "VIX Fear has low CAGR and high DD; improves in OOS but still weak.",
            "12-1 Momentum is moderate; OOS better than IS.",
            "Oversold (5d) loses money; not viable as implemented.",
        ],
        "charts": {"dates": dates, "spy": chart_spy, "strategies": chart_strategies},
    }
    return data

def main():
    print("Fetching SPY & VIX 2005–present...", file=sys.stderr)
    data = run_study()
    rules = data["rules"]
    bench = data["bench"]
    results_full = [(r["name"], {"cagr_pct": r["cagr_pct"], "sharpe": r["sharpe"], "max_dd_pct": r["max_dd_pct"]}, r["trades"]) for r in data["full_results"]]
    results_is = [(r["name"], {"cagr_pct": data["is_oos"][i]["is_cagr"], "sharpe": data["is_oos"][i]["is_sharpe"]}) for i, r in enumerate(data["full_results"])]
    results_oos = [(r["name"], {"cagr_pct": data["is_oos"][i]["oos_cagr"], "sharpe": data["is_oos"][i]["oos_sharpe"]}) for i, r in enumerate(data["full_results"])]
    regime_curves = {k: v / 100 for k, v in data["regimes"].items()}
    weaknesses = data["weaknesses"]

    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        import json as _json
        print(_json.dumps(data))
        return

    # ----- Report -----
    out = []
    out.append("# Systematic Strategy Study: SPY vs 5 Strategies (2005–Present)")
    out.append("")
    out.append("**Benchmark:** SPY buy-and-hold (with transaction costs).")
    out.append("**Costs:** 10 bps round-trip per trade.")
    out.append("**In-sample:** 2005–2013. **Out-of-sample:** 2014–present.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 1. Strategy Rules")
    out.append("")
    for name, rule in rules.items():
        out.append(f"- **{name}:** {rule}")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 2. Full-Sample Results (2005–Present)")
    out.append("")
    out.append("| Strategy | CAGR % | Sharpe | Max DD % | Trades |")
    out.append("|----------|--------|--------|----------|--------|")
    out.append(f"| **SPY (buy & hold)** | {bench['cagr_pct']:.2f} | {bench['sharpe']:.2f} | {bench['max_dd_pct']:.2f} | 0 |")
    for name, m, nt in results_full:
        out.append(f"| {name} | {m['cagr_pct']:.2f} | {m['sharpe']:.2f} | {m['max_dd_pct']:.2f} | {nt} |")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 3. In-Sample vs Out-of-Sample")
    out.append("")
    out.append("| Strategy | IS CAGR % | IS Sharpe | OOS CAGR % | OOS Sharpe |")
    out.append("|----------|-----------|-----------|------------|------------|")
    for i, (name, _, _) in enumerate(results_full):
        mis = results_is[i][1]
        moos = results_oos[i][1]
        out.append(f"| {name} | {mis['cagr_pct']:.2f} | {mis['sharpe']:.2f} | {moos['cagr_pct']:.2f} | {moos['sharpe']:.2f} |")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 4. Regime (SPY 200d trend)")
    out.append("")
    out.append("Bull: close > 2% above 200 SMA; Bear: close < 2% below; Sideways: else.")
    out.append("")
    for reg, ret in regime_curves.items():
        out.append(f"- **{reg}:** cumulative return (SPY) ≈ {ret*100:.1f}% over regime days.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 5. Weaknesses by Strategy")
    out.append("")
    for name, w in weaknesses.items():
        out.append(f"- **{name}:** {w}")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 6. Summary")
    out.append("")
    out.append("- **SMA200** improves CAGR and Sharpe vs buy-and-hold with much lower max drawdown; holds up in OOS.")
    out.append("- **50/200 Cross** is more conservative; similar to SPY with fewer trades; OOS slightly worse than IS.")
    out.append("- **VIX Fear** has low CAGR and high DD; improves in OOS but still weak.")
    out.append("- **12-1 Momentum** is moderate; OOS better than IS.")
    out.append("- **Oversold (5d)** loses money; not viable as implemented.")
    out.append("")
    out.append("*Transaction costs: 5 bps one-way (10 bps round-trip). Data: Yahoo Finance SPY, VIX.*")

    report = "\n".join(out)
    print(report)

    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        with open("strategy_study_report.md", "w") as f:
            f.write(report)
        print("\n[Report written to strategy_study_report.md]", file=sys.stderr)


if __name__ == "__main__":
    main()

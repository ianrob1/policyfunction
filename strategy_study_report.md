# Systematic Strategy Study: SPY vs 5 Strategies (2005–Present)

**Benchmark:** SPY buy-and-hold (with transaction costs).
**Costs:** 10 bps round-trip per trade.
**In-sample:** 2005–2013. **Out-of-sample:** 2014–present.

---

## 1. Strategy Rules

- **SMA200:** SMA200: Long SPY when close > 200-day SMA; otherwise cash.
- **50/200 Golden Cross:** 50/200 Cross: Long when 50-day SMA > 200-day SMA; otherwise cash.
- **VIX Fear:** VIX Fear: Enter when VIX > 30, exit when VIX < 20; otherwise hold state.
- **12-1 Momentum:** 12-1 Momentum: Long when 12-month return minus 1-month return > 0; else cash.
- **Oversold (5d):** Oversold: Enter when 5d return < -3%; exit when > 2% or 10 days.

---

## 2. Full-Sample Results (2005–Present)

| Strategy | CAGR % | Sharpe | Max DD % | Trades |
|----------|--------|--------|----------|--------|
| **SPY (buy & hold)** | 8.69 | 0.53 | -56.47 | 0 |
| SMA200 | 18.13 | 1.58 | -10.10 | 133 |
| 50/200 Golden Cross | 6.99 | 0.57 | -34.10 | 21 |
| VIX Fear | 1.98 | 0.20 | -46.47 | 34 |
| 12-1 Momentum | 7.31 | 0.56 | -34.10 | 115 |
| Oversold (5d) | -11.09 | -0.84 | -92.08 | 252 |

---

## 3. In-Sample vs Out-of-Sample

| Strategy | IS CAGR % | IS Sharpe | OOS CAGR % | OOS Sharpe |
|----------|-----------|-----------|------------|------------|
| SMA200 | 16.52 | 1.52 | 18.93 | 1.64 |
| 50/200 Golden Cross | 7.25 | 0.65 | 6.72 | 0.53 |
| VIX Fear | 0.33 | 0.11 | 3.22 | 0.31 |
| 12-1 Momentum | 5.53 | 0.49 | 7.69 | 0.57 |
| Oversold (5d) | -14.53 | -1.03 | -8.45 | -0.68 |

---

## 4. Regime (SPY 200d trend)

Bull: close > 2% above 200 SMA; Bear: close < 2% below; Sideways: else.

- **bull:** cumulative return (SPY) ≈ 3894.2% over regime days.
- **bear:** cumulative return (SPY) ≈ -80.7% over regime days.
- **sideways:** cumulative return (SPY) ≈ -24.8% over regime days.

---

## 5. Weaknesses by Strategy

- **SMA200:** Lags turns; whipsaws in sideways markets; underperforms in strong bull runs due to late entry.
- **50/200 Golden Cross:** Very slow signals; large drawdowns before crossover; late exits in bear markets.
- **VIX Fear:** Often buys into continued volatility; regime-dependent; can sit in cash for long periods.
- **12-1 Momentum:** Vulnerable to momentum crashes; underperforms in sharp reversals; skip-month can miss trends.
- **Oversold (5d):** Catching falling knives; high drawdown risk; short holding period may cut winners early.

---

## 6. Summary

- **SMA200** improves CAGR and Sharpe vs buy-and-hold with much lower max drawdown; holds up in OOS.
- **50/200 Cross** is more conservative; similar to SPY with fewer trades; OOS slightly worse than IS.
- **VIX Fear** has low CAGR and high DD; improves in OOS but still weak.
- **12-1 Momentum** is moderate; OOS better than IS.
- **Oversold (5d)** loses money; not viable as implemented.

*Transaction costs: 5 bps one-way (10 bps round-trip). Data: Yahoo Finance SPY, VIX.*
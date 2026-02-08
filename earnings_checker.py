"""
Earnings position checker: uses options IV term structure and realized vol
to recommend whether to consider an options/earnings position.
Not financial advice. For educational use only.
"""
from datetime import datetime, timedelta
import numpy as np
import yfinance as yf
from scipy.interpolate import interp1d


def filter_dates(dates):
    today = datetime.today().date()
    cutoff_date = today + timedelta(days=45)
    sorted_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
    arr = []
    for i, date in enumerate(sorted_dates):
        if date >= cutoff_date:
            arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[:i + 1]]
            break
    if len(arr) > 0:
        if arr[0] == today.strftime("%Y-%m-%d"):
            return arr[1:]
        return arr
    raise ValueError("No date 45 days or more in the future found.")


def yang_zhang(price_data, window=30, trading_periods=252, return_last_only=True):
    log_ho = (price_data['High'] / price_data['Open']).apply(np.log)
    log_lo = (price_data['Low'] / price_data['Open']).apply(np.log)
    log_co = (price_data['Close'] / price_data['Open']).apply(np.log)
    log_oc = (price_data['Open'] / price_data['Close'].shift(1)).apply(np.log)
    log_oc_sq = log_oc ** 2
    log_cc = (price_data['Close'] / price_data['Close'].shift(1)).apply(np.log)
    log_cc_sq = log_cc ** 2
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
    close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
    open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
    window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
    k = 0.34 / (1.34 + ((window + 1) / (window - 1)))
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(trading_periods)
    if return_last_only:
        return result.iloc[-1]
    return result.dropna()


def build_term_structure(days, ivs):
    days = np.array(days)
    ivs = np.array(ivs)
    sort_idx = days.argsort()
    days = days[sort_idx]
    ivs = ivs[sort_idx]
    spline = interp1d(days, ivs, kind='linear', fill_value='extrapolate')

    def term_spline(dte):
        if dte < days[0]:
            return float(ivs[0])
        if dte > days[-1]:
            return float(ivs[-1])
        return float(spline(dte))

    return term_spline


def get_current_price(ticker_obj):
    todays_data = ticker_obj.history(period='1d')
    if todays_data.empty:
        return None
    return todays_data['Close'].iloc[0]


def compute_recommendation(ticker):
    """Return dict with avg_volume (bool), iv30_rv30 (bool), ts_slope_0_45 (bool), expected_move (str or None), recommendation ('Recommended'|'Consider'|'Avoid')."""
    ticker = ticker.strip().upper()
    if not ticker:
        return {"error": "No stock symbol provided."}

    try:
        stock = yf.Ticker(ticker)
        if not getattr(stock, 'options', None) or len(stock.options) == 0:
            return {"error": f"No options found for '{ticker}'."}
    except Exception:
        return {"error": f"Error loading options for '{ticker}'."}

    try:
        exp_dates = filter_dates(list(stock.options))
    except ValueError:
        return {"error": "Not enough option data (need expirations 45+ days out)."}

    options_chains = {}
    for exp_date in exp_dates:
        try:
            options_chains[exp_date] = stock.option_chain(exp_date)
        except Exception:
            continue

    if not options_chains:
        return {"error": "Could not load options chains."}

    try:
        underlying_price = get_current_price(stock)
        if underlying_price is None:
            return {"error": "Unable to retrieve underlying stock price."}
    except Exception:
        return {"error": "Unable to retrieve underlying stock price."}

    atm_iv = {}
    straddle = None
    i = 0
    for exp_date, chain in options_chains.items():
        calls = chain.calls
        puts = chain.puts
        if calls.empty or puts.empty:
            continue
        call_diffs = (calls['strike'] - underlying_price).abs()
        call_idx = call_diffs.idxmin()
        call_iv = calls.loc[call_idx, 'impliedVolatility']
        put_diffs = (puts['strike'] - underlying_price).abs()
        put_idx = put_diffs.idxmin()
        put_iv = puts.loc[put_idx, 'impliedVolatility']
        atm_iv_value = (call_iv + put_iv) / 2.0
        atm_iv[exp_date] = atm_iv_value
        if i == 0:
            call_bid = calls.loc[call_idx, 'bid']
            call_ask = calls.loc[call_idx, 'ask']
            put_bid = puts.loc[put_idx, 'bid']
            put_ask = puts.loc[put_idx, 'ask']
            call_mid = (call_bid + call_ask) / 2.0 if call_bid is not None and call_ask is not None else None
            put_mid = (put_bid + put_ask) / 2.0 if put_bid is not None and put_ask is not None else None
            if call_mid is not None and put_mid is not None:
                straddle = call_mid + put_mid
        i += 1

    if not atm_iv:
        return {"error": "Could not determine ATM IV for any expiration dates."}

    today = datetime.today().date()
    dtes = []
    ivs = []
    for exp_date, iv in atm_iv.items():
        exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
        days_to_expiry = (exp_date_obj - today).days
        dtes.append(days_to_expiry)
        ivs.append(iv)

    term_spline = build_term_structure(dtes, ivs)
    ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45 - dtes[0]) if (45 - dtes[0]) != 0 else 0

    try:
        price_history = stock.history(period='3mo')
        if price_history is None or len(price_history) < 31:
            rv30 = np.nan
        else:
            rv30 = yang_zhang(price_history)
        iv30_rv30 = term_spline(30) / rv30 if rv30 and not np.isnan(rv30) and rv30 > 0 else 0
    except Exception:
        iv30_rv30 = 0

    try:
        price_history = stock.history(period='3mo')
        if price_history is not None and len(price_history) >= 30:
            avg_volume = price_history['Volume'].rolling(30).mean().dropna().iloc[-1]
        else:
            avg_volume = 0
    except Exception:
        avg_volume = 0

    expected_move = None
    if straddle is not None and underlying_price and underlying_price > 0:
        expected_move = str(round(straddle / underlying_price * 100, 2)) + "%"

    avg_volume_ok = avg_volume >= 1500000
    iv30_rv30_ok = iv30_rv30 >= 1.25
    ts_slope_ok = ts_slope_0_45 <= -0.00406

    if avg_volume_ok and iv30_rv30_ok and ts_slope_ok:
        recommendation = "Recommended"
    elif ts_slope_ok and ((avg_volume_ok and not iv30_rv30_ok) or (iv30_rv30_ok and not avg_volume_ok)):
        recommendation = "Consider"
    else:
        recommendation = "Avoid"

    return {
        "ticker": ticker,
        "recommendation": recommendation,
        "avg_volume": avg_volume_ok,
        "iv30_rv30": iv30_rv30_ok,
        "ts_slope_0_45": ts_slope_ok,
        "expected_move": expected_move,
        "avg_volume_raw": int(avg_volume) if avg_volume else None,
        "iv30_rv30_raw": round(iv30_rv30, 4) if iv30_rv30 else None,
        "ts_slope_raw": round(ts_slope_0_45, 6) if ts_slope_0_45 is not None else None,
    }

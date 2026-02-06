import json
import sys
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def _get_col(df, *names):
    """Return first column name that exists (case-insensitive)."""
    lower = {str(c).lower(): c for c in df.columns}
    for n in names:
        k = str(n).lower()
        if k in lower:
            return lower[k]
    return None


def fetch_data(start_date, end_date, ticker='SPY'):
    """Fetch ticker (default SPY) and VIX data"""
    asset = yf.download(ticker, start=start_date, end=end_date, progress=False, multi_level_index=False)
    vix = yf.download('^VIX', start=start_date, end=end_date, progress=False, multi_level_index=False)

    # If we still have MultiIndex, flatten to OHLC names (ticker is usually level 0, OHLC level 1)
    if isinstance(asset.columns, pd.MultiIndex):
        for lev in range(asset.columns.nlevels):
            vals = asset.columns.get_level_values(lev)
            if _get_col(pd.DataFrame(columns=vals), "Close", "close"):
                asset.columns = vals
                break
    if isinstance(vix.columns, pd.MultiIndex):
        for lev in range(vix.columns.nlevels):
            vals = vix.columns.get_level_values(lev)
            if _get_col(pd.DataFrame(columns=vals), "Close", "close"):
                vix.columns = vals
                break

    close_col = _get_col(asset, "Close", "close")
    open_col = _get_col(asset, "Open", "open")
    vix_close_col = _get_col(vix, "Close", "close")
    if not close_col or not open_col or not vix_close_col:
        raise ValueError("Expected Close/Open columns from yfinance; got %s" % list(asset.columns))

    common = asset.index.intersection(vix.index)
    if len(common) == 0:
        raise ValueError("No overlapping %s/VIX data for the requested dates" % ticker)

    df = pd.DataFrame(
        {
            "spy_close": asset.loc[common, close_col].reindex(common),
            "spy_open": asset.loc[common, open_col].reindex(common),
            "vix_close": vix.loc[common, vix_close_col].reindex(common),
        }
    )
    return df.dropna()

def backtest_vix_strategy(df, initial_capital=100000, vix_buy_above=30, buy_dollars=1000):
    """
    Every day VIX (prior close) > threshold, buy $buy_dollars at next open. No selling.
    No lookahead: use VIX[t-1] to decide buy at open[t]. Cost applied on each buy.
    """
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    cash = float(initial_capital)
    spy_value = 0.0
    pending_buy = 0.0  # decided yesterday, invested at open today
    strategy_values = []
    positions = []

    for i in range(len(df)):
        # Pending buy from yesterday gets invested at open today and earns today's return
        if pending_buy > 0:
            spy_value += pending_buy
            spy_value -= (COST_BPS_ROUND_TRIP / 10000) * pending_buy  # one-way cost on buy
            pending_buy = 0
        spy_ret = df['spy_returns'].iloc[i]
        if spy_value > 0:
            spy_value = spy_value * (1 + spy_ret)
        # Decision at end of day: use today's VIX to decide buy at next open
        vix_today = df['vix_close'].iloc[i]
        if vix_today > vix_buy_above:
            amount = min(float(buy_dollars), cash)
            cash -= amount
            pending_buy = amount  # will be added at start of next day
        total = cash + spy_value + pending_buy  # pending_buy committed but not yet invested
        strategy_values.append(total)
        positions.append(1 if spy_value > 0 else 0)

    df['strategy_portfolio'] = strategy_values
    df['position'] = positions
    df['spy_cumulative'] = (1 + df['spy_returns']).cumprod()
    df['spy_portfolio'] = initial_capital * df['spy_cumulative']
    df['strategy_returns'] = pd.Series(strategy_values, index=df.index).pct_change().fillna(0)
    df['spy_peak'] = df['spy_portfolio'].cummax()
    df['strategy_peak'] = df['strategy_portfolio'].cummax()
    df['spy_drawdown'] = (df['spy_portfolio'] - df['spy_peak']) / df['spy_peak'] * 100
    df['strategy_drawdown'] = (df['strategy_portfolio'] - df['strategy_peak']) / df['strategy_peak'] * 100
    df['spy_pct_from_ath'] = (df['spy_close'] - df['spy_close'].cummax()) / df['spy_close'].cummax() * 100
    return df


# Realism: round-trip cost in bps (spread + slippage + commission proxy)
COST_BPS_ROUND_TRIP = 10


def _rsi(close_series, period=14):
    """RSI(period). Returns Series; first (period+1) values are NaN."""
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(100)  # avg_loss=0 -> RSI=100
    return rsi.fillna(50)  # insufficient data -> neutral


def backtest_sma_strategy(df, period=200, initial_capital=10000):
    """
    Go With the Flow: Long SPY when close > period-day SMA; otherwise cash.
    Dip-buy: When bearish (Close < SMA50), allocate 50% SPY when RSI(14)<30 or price >10% below SMA50.
    Exit dip-buy when RSI>50 or price crosses back above SMA50.
    No lookahead: signals from close[t-1] -> position at open[t]. Frictions applied.
    """
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    sma = df['spy_close'].rolling(period, min_periods=period).mean()
    sma50 = df['spy_close'].rolling(50, min_periods=50).mean()
    rsi = _rsi(df['spy_close'], 14)
    # All signals from prior close (shift 1)
    cl = df['spy_close'].shift(1)
    sma_prev = sma.shift(1)
    sma50_prev = sma50.shift(1)
    rsi_prev = rsi.shift(1)
    trend_long = (cl > sma_prev).fillna(False)
    bearish = (cl < sma50_prev).fillna(False)
    dip_trigger = bearish & ((rsi_prev < 30) | (cl < 0.9 * sma50_prev))
    dip_exit = (rsi_prev > 50) | (cl > sma50_prev)
    # State machine: in_dip_buy at start of day t
    in_dip = []
    for i in range(len(df)):
        if i == 0:
            in_dip.append(False)
            continue
        was_dip = in_dip[-1]
        if trend_long.iloc[i]:
            in_dip.append(False)
        elif was_dip and dip_exit.iloc[i]:
            in_dip.append(False)
        elif dip_trigger.iloc[i]:
            in_dip.append(True)
        elif was_dip:
            in_dip.append(True)
        else:
            in_dip.append(False)
    # Position: 1.0 = 100% SPY, 0.5 = 50% dip-buy, 0.0 = cash
    position = np.where(trend_long.values, 1.0, np.where(in_dip, 0.5, 0.0))
    df['position'] = position.astype(float)

    strategy_values = [float(initial_capital)]
    for i in range(1, len(df)):
        prev = strategy_values[-1]
        ret = df['spy_returns'].iloc[i]
        pos = df['position'].iloc[i]
        pos_prev = df['position'].iloc[i - 1]
        new_val = prev * (1 + ret * pos)
        if pos != pos_prev:
            new_val -= (COST_BPS_ROUND_TRIP / 10000) * new_val
        strategy_values.append(max(0, new_val))
    df['strategy_portfolio'] = strategy_values
    df['spy_cumulative'] = (1 + df['spy_returns']).cumprod()
    df['spy_portfolio'] = initial_capital * df['spy_cumulative']
    df['strategy_returns'] = pd.Series(strategy_values, index=df.index).pct_change().fillna(0)
    df['spy_peak'] = df['spy_portfolio'].cummax()
    df['strategy_peak'] = df['strategy_portfolio'].cummax()
    df['spy_drawdown'] = (df['spy_portfolio'] - df['spy_peak']) / df['spy_peak'] * 100
    df['strategy_drawdown'] = (df['strategy_portfolio'] - df['strategy_peak']) / df['strategy_peak'] * 100
    df['spy_pct_from_ath'] = (df['spy_close'] - df['spy_close'].cummax()) / df['spy_close'].cummax() * 100
    return df


def backtest_sma200_strategy(df, initial_capital=10000):
    """Convenience wrapper for 200-day SMA."""
    return backtest_sma_strategy(df, period=200, initial_capital=initial_capital)


def backtest_sma50_200_tbill(df, initial_capital=10000, tbill_annual_rate=0.04):
    """
    Stay In or Step Out:
    Entry: 100% SPY when Close > SMA(50) and SMA(50) > SMA(200); sticky 100% when long and Close > SMA(100).
            75% SPY when bearish and RSI < 35; 50% SPY when bearish and (RSI < 30 or Close >10% below SMA50).
    Exit: From 100% only when Close < SMA(100). From dip-buy when RSI > 55.
    Cash: T-bills when no long conditions met. No lookahead; frictions applied.
    """
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    sma50 = df['spy_close'].rolling(50, min_periods=50).mean()
    sma100 = df['spy_close'].rolling(100, min_periods=100).mean()
    sma200 = df['spy_close'].rolling(200, min_periods=200).mean()
    rsi = _rsi(df['spy_close'], 14)
    cl = df['spy_close'].shift(1)
    sma50_prev = sma50.shift(1)
    sma100_prev = sma100.shift(1)
    sma200_prev = sma200.shift(1)
    rsi_prev = rsi.shift(1)
    bearish = (cl < sma50_prev).fillna(True)
    primary_trend = (cl > sma50_prev) & (sma50_prev > sma200_prev)
    primary_trend = primary_trend.fillna(False)
    # Position: 0, 0.5, 0.75, 1.0
    positions = [0.0]
    for i in range(1, len(df)):
        prev_pos = positions[-1]
        c = cl.iloc[i]
        s50 = sma50_prev.iloc[i]
        s100 = sma100_prev.iloc[i]
        s200 = sma200_prev.iloc[i]
        r = rsi_prev.iloc[i]
        be = bearish.iloc[i]
        pt = primary_trend.iloc[i]
        # Sticky 100%: was long and Close > SMA(100)
        if prev_pos == 1.0 and c >= s100:
            positions.append(1.0)
        # Primary trend entry
        elif pt:
            positions.append(1.0)
        # Exit from dip-buy when RSI > 55
        elif (prev_pos == 0.5 or prev_pos == 0.75) and r > 55:
            positions.append(0.0)
        # 75%: bearish and RSI < 35
        elif be and r < 35:
            positions.append(0.75)
        # 50%: bearish and (RSI < 30 or Close >10% below SMA50)
        elif be and (r < 30 or c < 0.9 * s50):
            positions.append(0.5)
        else:
            positions.append(0.0)
    df['position'] = np.array(positions, dtype=float)

    daily_tbill = (1 + float(tbill_annual_rate)) ** (1 / 252) - 1
    strategy_values = [float(initial_capital)]
    for i in range(1, len(df)):
        prev = strategy_values[-1]
        ret = df['spy_returns'].iloc[i]
        pos = df['position'].iloc[i]
        pos_prev = df['position'].iloc[i - 1]
        strategy_ret = ret * pos + daily_tbill * (1 - pos)
        new_val = prev * (1 + strategy_ret)
        if pos != pos_prev:
            new_val -= (COST_BPS_ROUND_TRIP / 10000) * new_val
        strategy_values.append(max(0, new_val))
    df['strategy_portfolio'] = strategy_values
    df['spy_cumulative'] = (1 + df['spy_returns']).cumprod()
    df['spy_portfolio'] = initial_capital * df['spy_cumulative']
    df['strategy_returns'] = pd.Series(strategy_values, index=df.index).pct_change().fillna(0)
    df['spy_peak'] = df['spy_portfolio'].cummax()
    df['strategy_peak'] = df['strategy_portfolio'].cummax()
    df['spy_drawdown'] = (df['spy_portfolio'] - df['spy_peak']) / df['spy_peak'] * 100
    df['strategy_drawdown'] = (df['strategy_portfolio'] - df['strategy_peak']) / df['strategy_peak'] * 100
    df['spy_pct_from_ath'] = (df['spy_close'] - df['spy_close'].cummax()) / df['spy_close'].cummax() * 100
    return df


def calculate_metrics(df):
    """Calculate performance metrics including cost-to-run and risk/stability."""
    years = max((df.index[-1] - df.index[0]).days / 365.25, 0.01)

    # Total returns
    spy_total_return = (df['spy_portfolio'].iloc[-1] / df['spy_portfolio'].iloc[0] - 1) * 100
    strategy_total_return = (df['strategy_portfolio'].iloc[-1] / df['strategy_portfolio'].iloc[0] - 1) * 100

    # CAGR
    spy_annual = ((df['spy_portfolio'].iloc[-1] / df['spy_portfolio'].iloc[0]) ** (1 / years) - 1) * 100
    strategy_annual = ((df['strategy_portfolio'].iloc[-1] / df['strategy_portfolio'].iloc[0]) ** (1 / years) - 1) * 100

    # Volatility (annualized %)
    spy_vol = df['spy_returns'].std() * np.sqrt(252) * 100
    strategy_vol = df['strategy_returns'].std() * np.sqrt(252) * 100
    if np.isnan(strategy_vol) or strategy_vol <= 0:
        strategy_vol = 0

    # Sharpe (0% risk-free)
    spy_sharpe = (df['spy_returns'].mean() / df['spy_returns'].std()) * np.sqrt(252) if df['spy_returns'].std() > 0 else 0
    strategy_sharpe = (df['strategy_returns'].mean() / df['strategy_returns'].std()) * np.sqrt(252) if df['strategy_returns'].std() > 0 else 0

    # Max drawdown %
    spy_max_dd = df['spy_drawdown'].min()
    strategy_max_dd = df['strategy_drawdown'].min()

    # Calmar / MAR = CAGR / |Max DD|
    strategy_calmar = (strategy_annual / abs(strategy_max_dd)) if strategy_max_dd != 0 else None

    # Worst month / worst day (%)
    try:
        monthly_returns = df['strategy_returns'].resample('ME').apply(lambda x: (1 + x).prod() - 1)
    except Exception:
        monthly_returns = pd.Series(dtype=float)
    worst_month = (monthly_returns.min() * 100) if len(monthly_returns) > 0 else None
    worst_day = (df['strategy_returns'].min() * 100) if len(df) > 0 else None

    # Cost-to-run
    num_trades = (df['position'].diff() != 0).sum()
    trades_per_year = num_trades / years
    days_in_market = (df['position'] > 0).sum()
    days_in_market_pct = days_in_market / len(df) * 100 if len(df) > 0 else 0
    n_entries = ((df['position'] > 0) & (df['position'].shift(1).fillna(0) == 0)).sum()
    if df['position'].iloc[0] > 0:
        n_entries += 1
    avg_holding_days = (days_in_market / n_entries) if n_entries > 0 else 0
    # Annual turnover: sum of |position change| * 100% notional, annualized
    turn_notional = (df['position'].diff().abs() * df['strategy_portfolio']).sum()
    avg_aum = df['strategy_portfolio'].mean()
    annual_turnover_pct = (100 * turn_notional / avg_aum / years) if avg_aum > 0 and years > 0 else 0

    # Win rate (days in market when SPY was up)
    strategy_trades = df[df['position'] > 0]
    win_rate = (strategy_trades['spy_returns'] > 0).sum() / len(strategy_trades) * 100 if len(strategy_trades) > 0 else 0

    # Rolling 12-month Sharpe, drawdown, excess return
    roll_window = min(252, len(df) - 1)
    rolling_sharpe = []
    rolling_dd = []
    rolling_excess = []
    for i in range(roll_window, len(df)):
        window = df.iloc[i - roll_window:i]
        r = window['strategy_returns']
        sr = (r.mean() / r.std()) * np.sqrt(252) if r.std() > 0 else 0
        rolling_sharpe.append({'date': df.index[i].strftime('%Y-%m-%d'), 'sharpe': round(sr, 2)})
        dd = window['strategy_drawdown'].min()
        rolling_dd.append({'date': df.index[i].strftime('%Y-%m-%d'), 'drawdown': round(dd, 2)})
        strat_ret_12 = (window['strategy_portfolio'].iloc[-1] / window['strategy_portfolio'].iloc[0]) - 1
        spy_ret_12 = (window['spy_portfolio'].iloc[-1] / window['spy_portfolio'].iloc[0]) - 1
        rolling_excess.append({'date': df.index[i].strftime('%Y-%m-%d'), 'excess_pct': round((strat_ret_12 - spy_ret_12) * 100, 2)})

    return {
        'spy_total_return': round(spy_total_return, 2),
        'strategy_total_return': round(strategy_total_return, 2),
        'spy_annual_return': round(spy_annual, 2),
        'strategy_annual_return': round(strategy_annual, 2),
        'spy_volatility': round(spy_vol, 2),
        'strategy_volatility': round(strategy_vol, 2),
        'spy_sharpe': round(spy_sharpe, 2),
        'strategy_sharpe': round(strategy_sharpe, 2),
        'spy_max_drawdown': round(spy_max_dd, 2),
        'strategy_max_drawdown': round(strategy_max_dd, 2),
        'strategy_calmar': round(strategy_calmar, 2) if strategy_calmar is not None else None,
        'worst_month_pct': round(worst_month, 2) if worst_month is not None else None,
        'worst_day_pct': round(worst_day, 2) if worst_day is not None else None,
        'win_rate': round(win_rate, 2),
        'num_trades': int(num_trades),
        'trades_per_year': round(trades_per_year, 1),
        'avg_holding_period_days': round(avg_holding_days, 1),
        'annual_turnover_pct': round(annual_turnover_pct, 1),
        'days_in_market': int(days_in_market),
        'days_in_market_pct': round(days_in_market_pct, 2),
        'final_spy_value': round(df['spy_portfolio'].iloc[-1], 2),
        'final_strategy_value': round(df['strategy_portfolio'].iloc[-1], 2),
        'rolling_12m_sharpe': rolling_sharpe[-24:] if len(rolling_sharpe) > 24 else rolling_sharpe,  # last 24 months
        'rolling_12m_drawdown': rolling_dd[-24:] if len(rolling_dd) > 24 else rolling_dd,
        'rolling_12m_excess_vs_spy': rolling_excess[-24:] if len(rolling_excess) > 24 else rolling_excess,
    }

def prepare_chart_data(df):
    """Prepare data for charts"""
    
    # Portfolio value over time
    portfolio_data = []
    for idx, row in df.iterrows():
        point = {
            'date': idx.strftime('%Y-%m-%d'),
            'spy': round(row['spy_portfolio'], 2),
            'strategy': round(row['strategy_portfolio'], 2),
            'vix': round(row['vix_close'], 2),
            'in_market': 1 if row['position'] > 0 else 0
        }
        if 'spy_pct_from_ath' in df.columns and pd.notna(row.get('spy_pct_from_ath')):
            point['spy_pct_from_ath'] = round(row['spy_pct_from_ath'], 2)
        portfolio_data.append(point)
    
    # Drawdown data
    drawdown_data = []
    for idx, row in df.iterrows():
        drawdown_data.append({
            'date': idx.strftime('%Y-%m-%d'),
            'spy': round(row['spy_drawdown'], 2),
            'strategy': round(row['strategy_drawdown'], 2)
        })
    
    # Monthly returns
    df_monthly = df.resample('ME').apply({
        'spy_returns': lambda x: (1 + x).prod() - 1,
        'strategy_returns': lambda x: (1 + x).prod() - 1
    })
    
    monthly_data = []
    for idx, row in df_monthly.iterrows():
        monthly_data.append({
            'month': idx.strftime('%Y-%m'),
            'spy': round(row['spy_returns'] * 100, 2),
            'strategy': round(row['strategy_returns'] * 100, 2)
        })
    
    # VIX distribution
    vix_ranges = [0, 15, 20, 25, 30, 35, 40, 100]
    vix_labels = ['<15', '15-20', '20-25', '25-30', '30-35', '35-40', '>40']
    vix_dist = []
    
    for i in range(len(vix_ranges) - 1):
        count = ((df['vix_close'] >= vix_ranges[i]) & (df['vix_close'] < vix_ranges[i+1])).sum()
        vix_dist.append({
            'range': vix_labels[i],
            'days': int(count),
            'percentage': round(count / len(df) * 100, 2)
        })
    
    return {
        'portfolio': portfolio_data,
        'drawdown': drawdown_data,
        'monthly': monthly_data,
        'vix_distribution': vix_dist
    }

def run_backtest(years=5):
    """Run complete backtest: buy 100% at close, sell 100% at open (drawdown/recovery)."""

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years*365)

    print(f"Fetching data from {start_date.date()} to {end_date.date()}...", file=sys.stderr)
    df = fetch_data(start_date, end_date)

    print("Running backtest: $1000/day when VIX>30, start $100k...", file=sys.stderr)
    df = backtest_vix_strategy(df, initial_capital=100000, vix_buy_above=30, buy_dollars=1000)

    print("Calculating metrics...", file=sys.stderr)
    metrics = calculate_metrics(df)

    print("Preparing chart data...", file=sys.stderr)
    charts = prepare_chart_data(df)

    config = {
        'start_date': df.index[0].strftime('%Y-%m-%d'),
        'end_date': df.index[-1].strftime('%Y-%m-%d'),
        'ticker': 'SPY',
        'strategy': 'vix',
        'initial_capital': 100000,
        'vix_buy_above': 30,
        'buy_dollars': 1000
    }

    result = {
        'metrics': metrics,
        'charts': charts,
        'config': config
    }
    
    return result


def run_backtest_sma200(years=5):
    """Run SMA200 strategy backtest; same JSON shape as run_backtest for dashboard."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years*365)
    print(f"Fetching data from {start_date.date()} to {end_date.date()}...", file=sys.stderr)
    df = fetch_data(start_date, end_date)
    print("Running SMA200 backtest: long when close > 200d SMA, else cash...", file=sys.stderr)
    df = backtest_sma200_strategy(df, initial_capital=10000)
    metrics = calculate_metrics(df)
    charts = prepare_chart_data(df)
    config = {
        'start_date': df.index[0].strftime('%Y-%m-%d'),
        'end_date': df.index[-1].strftime('%Y-%m-%d'),
        'ticker': 'SPY',
        'strategy': 'sma200',
        'initial_capital': 10000,
    }
    return {'metrics': metrics, 'charts': charts, 'config': config}


def run_backtest_custom(start_date_str, end_date_str, strategy='sma200', initial_capital=10000,
                        sma_period=200, vix_threshold=30, buy_dollars=1000, tbill_annual_rate=0.04):
    """
    Run a backtest over a custom date range with chosen strategy and params.
    start_date_str, end_date_str: 'YYYY-MM-DD'
    strategy: 'sma200', 'sma50', 'vix', 'sma50_200_tbill'
    Returns same dict shape as run_backtest for dashboard.
    """
    start_date = pd.to_datetime(start_date_str).date()
    end_date = pd.to_datetime(end_date_str).date()
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")
    print(f"Fetching data from {start_date} to {end_date}...", file=sys.stderr)
    df = fetch_data(start_date, end_date)
    if len(df) < 2:
        raise ValueError("Not enough data in date range")
    initial_capital = int(initial_capital)
    if strategy == 'sma200':
        print(f"Running SMA{sma_period} backtest (long when close > {sma_period}d SMA)...", file=sys.stderr)
        df = backtest_sma_strategy(df, period=int(sma_period), initial_capital=initial_capital)
        config = {'strategy': 'sma200', 'sma_period': int(sma_period)}
    elif strategy == 'sma50':
        print(f"Running SMA{sma_period} backtest (sma50 strategy)...", file=sys.stderr)
        df = backtest_sma_strategy(df, period=int(sma_period), initial_capital=initial_capital)
        config = {'strategy': 'sma50', 'sma_period': int(sma_period)}
    elif strategy == 'vix':
        print(f"Running VIX strategy (buy ${buy_dollars}/day when VIX > {vix_threshold})...", file=sys.stderr)
        df = backtest_vix_strategy(df, initial_capital=initial_capital,
                                   vix_buy_above=int(vix_threshold), buy_dollars=int(buy_dollars))
        config = {'strategy': 'vix', 'vix_threshold': int(vix_threshold), 'buy_dollars': int(buy_dollars)}
    elif strategy == 'sma50_200_tbill':
        rate = float(tbill_annual_rate)
        print(f"Running SMA50/200 + T-bills (long when Close>SMA50 and SMA50>SMA200; else T-bills at {rate*100:.1f}%)...", file=sys.stderr)
        df = backtest_sma50_200_tbill(df, initial_capital=initial_capital, tbill_annual_rate=rate)
        config = {'strategy': 'sma50_200_tbill', 'tbill_annual_rate_pct': round(rate * 100, 2)}
    else:
        raise ValueError("strategy must be sma200, sma50, vix, or sma50_200_tbill")
    metrics = calculate_metrics(df)
    charts = prepare_chart_data(df)
    config['start_date'] = df.index[0].strftime('%Y-%m-%d')
    config['end_date'] = df.index[-1].strftime('%Y-%m-%d')
    config['ticker'] = 'SPY'
    config['initial_capital'] = initial_capital
    return {'metrics': metrics, 'charts': charts, 'config': config}


def run_compare(years=5):
    """Fetch data once, run multiple strategies, return comparison."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years*365)
    print(f"Fetching data from {start_date.date()} to {end_date.date()}...", file=sys.stderr)
    df = fetch_data(start_date, end_date)

    results = []
    # Buy & hold (market)
    df_bh = df.copy()
    df_bh['spy_returns'] = df_bh['spy_close'].pct_change().fillna(0)
    df_bh['spy_cumulative'] = (1 + df_bh['spy_returns']).cumprod()
    df_bh['spy_portfolio'] = 10000 * df_bh['spy_cumulative']
    df_bh['strategy_portfolio'] = df_bh['spy_portfolio']
    df_bh['position'] = 1
    df_bh['strategy_returns'] = df_bh['spy_returns']
    df_bh['spy_peak'] = df_bh['spy_portfolio'].cummax()
    df_bh['strategy_peak'] = df_bh['strategy_portfolio'].cummax()
    df_bh['spy_drawdown'] = (df_bh['spy_portfolio'] - df_bh['spy_peak']) / df_bh['spy_peak'] * 100
    df_bh['strategy_drawdown'] = df_bh['spy_drawdown']
    m = calculate_metrics(df_bh)
    results.append({"name": "Buy & Hold (SPY)", "strategy": "buy_hold", "metrics": m})

    df_run = backtest_vix_strategy(df.copy(), initial_capital=100000, vix_buy_above=30, buy_dollars=1000)
    m = calculate_metrics(df_run)
    results.append({"name": "VIX: $1000/day when >30, start $100k", "strategy": "vix", "metrics": m})

    # Print table to stderr
    print("\n" + "=" * 72, file=sys.stderr)
    print("STRATEGY COMPARISON ({} years, SPY)".format(years), file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    header = f"{'Strategy':<32} {'Return %':>10} {'MaxDD %':>10} {'Sharpe':>8} {'Days in':>10}"
    print(header, file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    for r in results:
        m = r["metrics"]
        row = f"{r['name']:<32} {m['strategy_total_return']:>10.1f} {m['strategy_max_drawdown']:>10.1f} {m['strategy_sharpe']:>8.2f} {m['days_in_market_pct']:>9.1f}%"
        print(row, file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    beat = [r for r in results[1:] if r["metrics"]["strategy_total_return"] > results[0]["metrics"]["strategy_total_return"]]
    if beat:
        print("Strategies that beat Buy & Hold: " + ", ".join(r["name"] for r in beat), file=sys.stderr)
    else:
        print("No strategy beat Buy & Hold on total return.", file=sys.stderr)
    print("", file=sys.stderr)

    return {"years": years, "strategies": results}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run backtest')
    parser.add_argument('years', nargs='?', type=int, default=5, help='Years of history (default 5)')
    parser.add_argument('mode', nargs='?', default='vix', help='vix | sma200 | compare')
    parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD (custom run)')
    parser.add_argument('--end', type=str, help='End date YYYY-MM-DD (custom run)')
    parser.add_argument('--strategy', type=str, default='sma200', choices=['sma200', 'sma50', 'vix', 'sma50_200_tbill'], help='Strategy for custom run')
    parser.add_argument('--capital', type=int, default=10000, help='Initial capital for custom run')
    parser.add_argument('--sma-period', type=int, default=200, help='SMA period for sma200 strategy')
    parser.add_argument('--vix-threshold', type=int, default=30, help='VIX threshold for vix strategy')
    parser.add_argument('--buy-dollars', type=int, default=1000, help='Dollars per day when VIX above threshold')
    parser.add_argument('--tbill-annual-rate', type=float, default=0.04, help='T-bill annual rate (decimal, e.g. 0.04) for sma50_200_tbill')
    args = parser.parse_args()

    if args.start and args.end:
        result = run_backtest_custom(
            args.start, args.end,
            strategy=args.strategy,
            initial_capital=args.capital,
            sma_period=args.sma_period,
            vix_threshold=args.vix_threshold,
            buy_dollars=args.buy_dollars,
            tbill_annual_rate=args.tbill_annual_rate,
        )
        print(json.dumps(result, indent=2))
    elif args.mode == 'compare':
        comparison = run_compare(years=args.years)
        print(json.dumps(comparison, indent=2))
    elif args.mode == 'sma200':
        result = run_backtest_sma200(years=args.years)
        print(json.dumps(result, indent=2))
    else:
        result = run_backtest(years=args.years)
        print(json.dumps(result, indent=2))

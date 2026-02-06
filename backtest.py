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
    Start with initial_capital (default 100k). Every day VIX is above 30, buy $buy_dollars of SPY.
    No selling; position is mark-to-market each day.
    """
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    cash = float(initial_capital)
    spy_value = 0.0
    strategy_values = []
    positions = []

    for i in range(len(df)):
        spy_ret = df['spy_returns'].iloc[i]
        vix = df['vix_close'].iloc[i]

        # Apply SPY return to current position
        if spy_value > 0:
            spy_value = spy_value * (1 + spy_ret)

        # Buy $buy_dollars when VIX > 30 (up to available cash)
        if vix > vix_buy_above:
            amount = min(float(buy_dollars), cash)
            cash -= amount
            spy_value += amount

        total = cash + spy_value
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


def backtest_sma_strategy(df, period=200, initial_capital=10000):
    """Long SPY when close > period-day SMA; otherwise cash."""
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    sma = df['spy_close'].rolling(period, min_periods=period).mean()
    position = (df['spy_close'] > sma).astype(int).fillna(0)
    df['position'] = position

    strategy_values = [float(initial_capital)]
    for i in range(1, len(df)):
        prev = strategy_values[-1]
        ret = df['spy_returns'].iloc[i]
        pos = df['position'].iloc[i]
        strategy_values.append(prev * (1 + ret * pos))
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
    Long SPY if Close > SMA(50) AND SMA(50) > SMA(200); otherwise T-bills.
    tbill_annual_rate: annualized T-bill return (e.g. 0.04 = 4%).
    """
    df = df.copy()
    df['spy_returns'] = df['spy_close'].pct_change().fillna(0)
    sma50 = df['spy_close'].rolling(50, min_periods=50).mean()
    sma200 = df['spy_close'].rolling(200, min_periods=200).mean()
    # In market when close > SMA50 and SMA50 > SMA200
    position = ((df['spy_close'] > sma50) & (sma50 > sma200)).astype(int).fillna(0)
    df['position'] = position

    daily_tbill = (1 + float(tbill_annual_rate)) ** (1 / 252) - 1
    strategy_values = [float(initial_capital)]
    for i in range(1, len(df)):
        prev = strategy_values[-1]
        ret = df['spy_returns'].iloc[i]
        pos = df['position'].iloc[i]
        # When in market: SPY return; when out: T-bill return
        strategy_ret = ret * pos + daily_tbill * (1 - pos)
        strategy_values.append(prev * (1 + strategy_ret))
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
    """Calculate performance metrics"""
    
    # Total returns
    spy_total_return = (df['spy_portfolio'].iloc[-1] / df['spy_portfolio'].iloc[0] - 1) * 100
    strategy_total_return = (df['strategy_portfolio'].iloc[-1] / df['strategy_portfolio'].iloc[0] - 1) * 100
    
    # Annualized returns
    years = (df.index[-1] - df.index[0]).days / 365.25
    spy_annual = ((df['spy_portfolio'].iloc[-1] / df['spy_portfolio'].iloc[0]) ** (1/years) - 1) * 100
    strategy_annual = ((df['strategy_portfolio'].iloc[-1] / df['strategy_portfolio'].iloc[0]) ** (1/years) - 1) * 100
    
    # Volatility (annualized)
    spy_vol = df['spy_returns'].std() * np.sqrt(252) * 100
    strategy_vol = df['strategy_returns'].std() * np.sqrt(252) * 100
    
    # Sharpe ratio (assuming 0% risk-free rate)
    spy_sharpe = (df['spy_returns'].mean() / df['spy_returns'].std()) * np.sqrt(252) if df['spy_returns'].std() > 0 else 0
    strategy_sharpe = (df['strategy_returns'].mean() / df['strategy_returns'].std()) * np.sqrt(252) if df['strategy_returns'].std() > 0 else 0
    
    # Max drawdown
    spy_max_dd = df['spy_drawdown'].min()
    strategy_max_dd = df['strategy_drawdown'].min()
    
    # Win rate
    strategy_trades = df[df['position'] == 1]
    win_rate = (strategy_trades['spy_returns'] > 0).sum() / len(strategy_trades) * 100 if len(strategy_trades) > 0 else 0
    
    # Number of trades (position changes)
    num_trades = (df['position'].diff() != 0).sum()
    
    # Days in market
    days_in_market = (df['position'] == 1).sum()
    days_in_market_pct = days_in_market / len(df) * 100
    
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
        'win_rate': round(win_rate, 2),
        'num_trades': int(num_trades),
        'days_in_market': int(days_in_market),
        'days_in_market_pct': round(days_in_market_pct, 2),
        'final_spy_value': round(df['spy_portfolio'].iloc[-1], 2),
        'final_strategy_value': round(df['strategy_portfolio'].iloc[-1], 2)
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
            'in_market': int(row['position'])
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

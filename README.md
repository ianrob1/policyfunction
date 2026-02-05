# Quant Trading Strategy Dashboard

A beautiful, interactive web dashboard for showcasing quantitative trading strategies with real-time backtesting visualizations.

## 🎯 Current Strategy: Buy at Close, Sell at Open

**Strategy Logic:**
- **Entry:** When SPY is down 5%+ from its all-time high, deploy 100% at **close**
- **Exit:** When SPY recovers 20% from that entry level, sell 100% at **open**
- No SMA or other indicators—only open/close execution timing

## 📊 Features

- **Interactive Charts:**
  - Portfolio value over time comparison
  - Drawdown analysis
  - Monthly returns heatmap
  - VIX distribution histogram

- **Performance Metrics:**
  - Total & annualized returns
  - Sharpe ratio
  - Maximum drawdown
  - Win rate & trade count
  - Time in market analysis

- **Responsive Design:**
  - Modern dark theme with cyan/blue gradients
  - Mobile-friendly responsive layout
  - Smooth animations and transitions
  - Time period filtering (6M, 1Y, 3Y, All)

## 🚀 Quick Start

### Option 1: Visualization site (animated historical replay)
Open **`index.html`** in a browser to see the strategy with **charts that replay over time** (play/pause + scrubber).

1. **One-time setup (Mac-friendly, uses a venv to avoid “externally-managed-environment”):**
```bash
cd quant-strategies
./run.sh
```
   This creates a `.venv`, installs dependencies, runs the backtest, and starts the server.

   Or do it manually:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
   python3 backtest.py 5 2>/dev/null > backtest_results.json
python3 -m http.server 8000
```

2. **Open in browser:**  
   Go to **http://localhost:8000** and click **Play** on the strategy to see the replay.

### Option 2: Full React dashboard
Open `vix-strategy-dashboard.html` in any modern web browser. All dependencies are loaded via CDN.

### Option 3: Run Backtest with Live Data

1. **Install Dependencies:**
```bash
pip install yfinance pandas numpy
```

2. **Run Backtest:**
```bash
python backtest.py [years]

# Examples:
python backtest.py 5           # 5 years
python backtest.py 10          # 10 years
```

3. **Save results for the visualization site:**
```bash
python backtest.py 5 2>/dev/null > backtest_results.json
```
Then open `index.html`.

## 📁 Project Structure

```
quant-strategies/
├── index.html                     # Strategy visualization site (replay charts)
├── backtest_results.json          # Backtest output (run backtest.py to generate)
├── vix-strategy-dashboard.html    # Full React dashboard (ready to use)
├── backtest.py                    # Python backtest engine (live data)
├── mock_backtest.py               # Mock data generator (for testing)
└── README.md                      # This file
```

## 🛠️ Tech Stack

**Frontend:**
- React 18 (via CDN)
- Recharts 2.5 (interactive charts)
- Tailwind CSS (styling)
- Babel Standalone (JSX compilation)

**Backend:**
- Python 3.x
- yfinance (market data)
- pandas (data analysis)
- numpy (calculations)

## 🧪 Compare vs Single Run

**Single run** (for the dashboard):

```bash
# Buy at close, sell at open (drawdown 5% / recovery 20%)
python3 backtest.py 5 2>/dev/null > backtest_results.json
```

Then open `index.html` to view the strategy.

**Compare** Buy & Hold vs the strategy (same data, same period):

```bash
python3 backtest.py 5 compare
```

This prints a comparison table to the terminal and outputs JSON. To save: `python3 backtest.py 5 compare 2>/dev/null > comparison.json`.

## 📈 Adding New Strategies

To add a new trading strategy to your dashboard:

1. **Create Backtest Script:**
```python
# my_strategy.py
def backtest_my_strategy(df, params):
    # Your strategy logic here
    df['signal'] = calculate_signal(df, params)
    df['position'] = df['signal'].shift(1)
    # Calculate returns...
    return df
```

2. **Generate Metrics:**
Follow the same format as `backtest.py`:
```json
{
  "metrics": {
    "total_return": 45.2,
    "sharpe_ratio": 1.23,
    ...
  },
  "charts": {
    "portfolio": [...],
    "drawdown": [...],
    ...
  }
}
```

3. **Update Dashboard:**
- Copy `vix-strategy-dashboard.html`
- Update the strategy description
- Inject your new backtest data
- Customize colors/branding as needed

## 🎨 Customization

### Change Color Scheme
Edit the color classes in the HTML:
```javascript
// Current: Cyan/Blue theme
className="bg-cyan-600"          // Primary actions
className="text-cyan-400"        // Headings
className="border-cyan-700"      // Borders

// Example: Purple theme
className="bg-purple-600"
className="text-purple-400"
className="border-purple-700"
```

### Modify Charts
Charts use Recharts library. Customize in the component:
```javascript
<AreaChart data={portfolioData}>
  <Area 
    type="monotone" 
    dataKey="strategy" 
    stroke="#06b6d4"        // Line color
    fill="url(#gradient)"    // Fill gradient
  />
</AreaChart>
```

## 📊 Sample Strategies to Implement

Here are ideas for additional strategies:

1. **Moving Average Crossover**
   - Buy when 50-day MA crosses above 200-day MA
   - Sell on opposite crossover

2. **RSI Mean Reversion**
   - Buy when RSI < 30 (oversold)
   - Sell when RSI > 70 (overbought)

3. **Momentum Strategy**
   - Buy top 10% performers from last month
   - Rebalance monthly

4. **Sector Rotation**
   - Rotate into strongest sectors
   - Monthly rebalancing

5. **Statistical Arbitrage**
   - Pairs trading with correlation
   - Mean reversion on spreads

## 🔧 Configuration

### Backtest Parameters
Edit in `backtest.py`:
```python
def run_backtest(years=5):     # Lookback period
# Drawdown/recovery thresholds and initial_capital are in backtest_drawdown_strategy()
```

### Chart Timeframes
Edit in the HTML:
```javascript
const timeframes = ['6m', '1y', '3y', 'all'];
```

## 📝 Performance Metrics Explained

- **Total Return:** Cumulative percentage gain/loss
- **Annual Return:** Annualized rate of return
- **Sharpe Ratio:** Risk-adjusted return (higher is better)
- **Max Drawdown:** Largest peak-to-trough decline
- **Win Rate:** Percentage of profitable trades
- **Days in Market:** Percentage of time holding positions

## ⚠️ Disclaimer

This dashboard is for educational and research purposes only. Past performance does not guarantee future results. Always conduct thorough research and consider your risk tolerance before implementing any trading strategy.

## 🚀 Deployment

### Host on GitHub Pages
1. Create a new repo
2. Upload `vix-strategy-dashboard.html` (rename to `index.html`)
3. Enable GitHub Pages in settings
4. Access at: `https://yourusername.github.io/repo-name`

### Host on Netlify/Vercel
1. Drag and drop the HTML file
2. Get instant live URL
3. Free tier available

### Host Locally
```bash
# Using Python
python -m http.server 8000

# Then visit: http://localhost:8000
```

## 📧 Contact & Support

- GitHub: github.com/yourhandle
- Twitter: @yourtwitter
- Email: your@email.com

## 📜 License

MIT License - Feel free to use this for your own trading research!

---

Built with ❤️ for quantitative traders

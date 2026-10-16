# Algorithmic Crypto Swing Trading Strategy: 3-Way Confirmation System

---

## 1. Executive Summary & Core Philosophy
This document specifies an algorithmic crypto swing trading system designed to trade market volatility safely on medium timeframes while filtering out noise and false signals [1, 3, 5]. The core framework uses a 3-way confirmation architecture (Macro Trend Filter + Signal Indicator + Momentum Filter) coupled with a volume-based trap detection model and strict mathematical risk controls [4, 6, 7, 16].

---

## 2. Technical System Parameters

| Indicator / Parameter | Configuration / Value | Function & Rationale |
| :--- | :--- | :--- |
| **Primary Timeframe** | `30-Minute (30m)` | Eliminates noise/whipsaws from 1m–15m charts while capturing multi-day swing moves [3, 4]. |
| **Macro Trend Filter** | `200 Exponential Moving Average (200 EMA)` | Establishes overall market direction. Only trade in direction of 200 EMA [6]. |
| **Signal Generator** | `Supertrend (Length = 13, Multiplier = 4)` *(Alt: 15, 5)* | Generates entry signals. Custom parameters reduce false flips relative to default 10,3 [4, 18]. |
| **Momentum Filter** | `MACD (12, 26, 9)` | Confirms momentum alignment relative to the zero line and histogram [7, 8]. |
| **Volume Filter** | `Standard Volume` | Identifies high-volume pivot candles to filter bear/bull traps [7, 9]. |

---

## 3. Algorithmic Entry Rules (3-Way Confirmation)

### 3.1 Long Entry (BUY Signal)
All four conditions must evaluate to `TRUE` simultaneously at the **close of a 30-minute candle** [7, 8, 18]:

1. **Macro Filter**: `Close Price > 200 EMA` [6].
2. **Signal Generator**: `Supertrend` flips from `RED` to `GREEN` [4, 7].
3. **Momentum Filter**:
   - `MACD Line > 0` AND `Signal Line > 0` (MACD above Zero Line) [7, 8].
   - `MACD Histogram > 0` (Green Histogram) [7, 8].
4. **Execution**: Open Long position on candle close [7].

```
[Candle Close 30m] ---> (Price > 200 EMA?) ---YES---> (Supertrend == GREEN?) ---YES---> (MACD > 0 & Hist > 0?) ---YES---> [EXECUTE LONG]
```

### 3.2 Short Entry (SELL Signal)
All four conditions must evaluate to `TRUE` simultaneously at the **close of a 30-minute candle** [6, 11, 18]:

1. **Macro Filter**: `Close Price < 200 EMA` [6].
2. **Signal Generator**: `Supertrend` flips from `GREEN` to `RED` [11].
3. **Momentum Filter**:
   - `MACD Line < 0` AND `Signal Line < 0` (MACD below Zero Line) [11].
   - `MACD Histogram < 0` (Red Histogram) [11].
4. **Execution**: Open Short position on candle close [11].

---

## 4. Trap Detection & False Signal Filtration Logic

When a counter-trend Supertrend signal occurs within an active macro trend (e.g., Supertrend turns RED while price remains above the 200 EMA), execute the following verification [8, 9]:

1. **Record Key Level**: Identify the 30m candle with the **highest volume** during the pullback/counter-move. Store its `Low Price` as `Pivot_Low` [9].
2. **Breakout Check**:
   - **False Signal (Bear Trap)**: If `Price` **does NOT close below** `Pivot_Low` and stays above `200 EMA`, the counter-signal is invalidated as a trap [9, 10, 11].
   - **Re-Entry / Scale-In Signal**: When Supertrend turns `GREEN` again, treat this as a high-probability continuation signal to add to the Long position [10, 20].
   - **True Reversal**: If `Price` closes below `Pivot_Low` AND breaks below `200 EMA` alongside negative MACD, close Long and confirm Short signal [9, 11].

---

## 5. Position Scaling & Pyramiding Rules

To maximize profitability on strong trending moves without increasing initial risk [10, 20]:

1. **Initial Entry**: Commit an initial position fraction (e.g., 10% of dedicated trading capital) upon initial 3-way confirmation [13, 20].
2. **Pyramiding Trigger**: Add capital (e.g., +10% increments) when:
   - Main trend parameters remain fully intact (`Price > 200 EMA`) [6].
   - Price pulls back toward the Supertrend line or prints a renewed Supertrend continuation signal [10, 20].

---

## 6. Exit & Trailing Stop Loss Management

1. **Continuous Dynamic Trailing Stop**: The `Supertrend line` functions as the dynamic trailing stop-loss level [17].
2. **Standard Exit Signal**: Close the trade when Supertrend changes color against the active position (e.g., Supertrend turns RED for a Long position) [17].
3. **Advanced Volume Exit Confirmation**: Verify if price breaks the high-volume pivot candle's boundary before executing full liquidation [9, 17].

---

## 7. Money Management & Position Sizing Mathematical Model

### 7.1 Capital Allocation & Leverage Limits
* **Leverage Cap**: `Leverage <= 10x` strictly enforced [14, 19].
* **Capital Segmentation**: Deploy a smaller fraction of available portfolio (e.g., ₹1 Lakh out of ₹5 Lakhs total capital, or ~20%) as practice capital to cushion against emotional stress and drawdown [13].

### 7.2 Dynamic Position Sizing Formula
Calculate exact unit quantity before every execution [15, 16]:

$$\text{Position Size (Units)} = \frac{\text{Maximum Allowed Risk (\$)}}{\text{Stop Loss Distance (\$)}} = \frac{\text{Risk Budget (\$)}}{\lvert \text{Entry Price} - \text{Supertrend SL Price} \rvert}$$

#### Mathematical Example:
* **Account Risk Allowance**: $\$300$ (e.g., Max loss limit per trade) [16].
* **Entry Price**: $\$2,800$
* **Supertrend SL Price**: $\$2,750$
* **SL Distance**: $\$2,800 - \$2,750 = \$50$ [16].
* **Calculated Position Size**:
  $$\text{Units} = \frac{300}{50} = 6 \text{ Units}$$

---

## 8. Algorithmic Implementation Flowchart (Pseudocode)

```python
# System State Variables
POSITION = 0  # -1 for Short, 0 for Flat, 1 for Long
PIVOT_LOW = None

def on_30m_candle_close(candle, df):
    ema200 = calculate_ema(df, 200)
    st_color, st_value = calculate_supertrend(df, period=13, multiplier=4)
    macd_line, signal_line, macd_hist = calculate_macd(df, 12, 26, 9)
    
    close = candle.close
    volume = candle.volume
    
    # 1. Check Long Entry
    if POSITION <= 0:
        if (close > ema200) and (st_color == "GREEN") and (macd_line > 0) and (macd_hist > 0):
            POSITION = 1
            set_stop_loss(st_value)
            execute_buy_order(size=calculate_position_size(risk=300, sl_dist=abs(close - st_value)))
            
    # 2. Check Short Entry
    if POSITION >= 0:
        if (close < ema200) and (st_color == "RED") and (macd_line < 0) and (macd_hist < 0):
            POSITION = -1
            set_stop_loss(st_value)
            execute_sell_order(size=calculate_position_size(risk=300, sl_dist=abs(close - st_value)))

    # 3. Trailing Stop & Trap Logic
    if POSITION == 1:
        update_trailing_stop(st_value)
        if st_color == "RED":
            # Volume trap check logic
            high_vol_candle = get_highest_volume_candle_in_pullback(df)
            if close < high_vol_candle.low and close < ema200:
                close_position()
                POSITION = 0
```

---

## 9. References & Grounding Index
- **Timeframe & Noise Reduction**: [3, 4]
- **Modified Supertrend Parameters (13, 4 / 15, 5)**: [4, 18]
- **200 EMA Macro Filtration**: [6]
- **MACD Zero Line & Histogram Confirmation**: [7, 8]
- **Volume Trap Verification**: [9, 10, 11]
- **Position Scaling / Pyramiding**: [10, 20]
- **Trailing Stop Loss & Exits**: [17]
- **Leverage Rules & Position Sizing Math**: [13, 14, 15, 16, 19]

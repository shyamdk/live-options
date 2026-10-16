# BTC Calm Strangle — Calm Strangle on Delta BTC daily options (paper)

Built 14 Oct 2026 after a 6-month backtest (8 Apr – 13 Oct 2026, 189 daily expiries, Delta 1-min
mark prices on a 1000-strike grid, IV interpolated; 4% slippage each way + Delta fees, 0.5 BTC/leg).

## Rules

| Topic | Rule |
|---|---|
| Session | The BTC daily expiry settling at 17:30 IST. |
| Entry window | **22:00–06:00 IST** only (overnight calm). |
| "Calm" | BTC's range over the last **15** one-minute closes ≤ **15%** of the ATM straddle (mark CE + PE). |
| Strikes | CE at the first listed strike ≥ spot + **1.5 × straddle**, PE ≤ spot − 1.5 × straddle; credit ≥ $20 per BTC. |
| Exits | BTC moves **1.5 × straddle** from entry; premium **+150%** (backstop); premium reaches its exit-time value early (then done for the session); **4 h before settlement** (13:30 IST). |
| Limits | Max 3 entries / 2 stops per session. |
| Size / mode | 500 contracts (0.5 BTC) per leg. Paper: sell at bid, buy at ask (mark fallback), Delta fee model. Live behind `BTC_CALM_LIVE_ORDER_ENABLED` + page mode. |

## Backtest

| | Apr–Jul | Jul–Oct | Full |
|---|---|---|---|
| Net | +$440 | +$1,523 | **+$1,964** (~$10/session) |

205 trades, 71% winners, max drawdown −$740, worst day −$290. 12 of 16 one-step parameter nudges
stayed positive; still positive at 6% (+$1,574) and 8% (+$1,194) slippage. Breaks: 30-min calm
window, midnight-only window start, holding to 2 h before settlement. NIFTY's own rules on BTC
lost −$3,377. Modelled prices, thin edge — paper first.

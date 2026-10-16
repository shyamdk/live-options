# Docs

| Folder | What's in it |
|---|---|
| `strategies/` | Specs for strategies the app runs. Source of truth is still the code; these record the rules and decisions. |
| `sources/` | The third-party documents those strategies were built from (PDF/DOCX), plus the Varaha source write-up and the Theta Book source notes and sample data. |
| `archived/` | Notes and specs for strategies that were retired or never built (XAUT cross over, pStrategy, crypto swing, PE-CE premium crossover, All-in-One Delta). Their code is in `/archive`. |
| `runbook/` | Running the app (`live-options.md`), the build log (`build_progress.md`), the original requirements (`notes.txt`) and PCR/OI tuning notes (`fine-tune.md`). |
| `guides/` | Plain-language PDF guides (Melting Straddles, Define Turtle). |

## Strategy specs

| App page | Spec | Built from |
|---|---|---|
| Melting Straddles | `strategies/melting-straddles.md` | `sources/mastering_intraday_options_straddles_algo_spec.docx` |
| Define Turtle | `strategies/define-turtle.md` | `sources/systematic-options-trading-strategy.pdf` |
| Calm Strangle | `strategies/calm-strangle.md` | own research |
| BTC Calm Strangle | `strategies/btc-calm-strangle.md` | own research |
| Mantra - Theta Gainers | `strategies/mantra.md` | `sources/mantra.docx` |
| Batman | (in code: `backend/app/services/batman.py`) | `sources/batman-option-strategy-guide.pdf` |
| BTC Strangle | (in code: `backend/app/services/btc_strangle.py`) | `sources/bitcoin-strangle.pdf` |
| Varaha | (in code: `backend/app/services/varaha*.py`) | `sources/varaha/` |
| Theta Book | (in code: `backend/app/services/theta_engine.py`) | `sources/theta-book/` |
| OI - Upgraded | `strategies/oi-upgraded.md` | own research |
| Simple Cross Over | `strategies/NIFTY-Entry-Exit-2026-09-25.md` (snapshot; code has changed since) | own research |
| ema5 / Animesh Scalping | `strategies/ema5.txt`, `strategies/animesh-scalping.txt` | strategy notes |
| Gamma Blast | `strategies/gamma-blast.md` | own research |

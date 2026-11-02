"""Build app/data/disha_base_rates.json: how each morning situation played out.

Uses the history store (NIFTY 1-min + daily bars) and the same classification
functions as the live Disha page (app/services/disha.py), so the page compares
today against history with identical definitions. Re-run to refresh:
  cd backend && PYTHONPATH=. ../.venv/bin/python scripts/disha_base_rates.py
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.services.disha import BASE_RATES_FILE, OR_END_MIN, find_breakout, first_move_class, gap_class, opening_range
from scripts.market_history import connect

IST = timezone(timedelta(hours=5, minutes=30))
LABELS = {
    "gap_up_big": "Gap up 0.5% or more", "gap_up": "Gap up 0.2-0.5%", "gap_flat": "Flat open (within 0.2%)",
    "gap_down": "Gap down 0.2-0.5%", "gap_down_big": "Gap down 0.5% or more",
    "open_strong_up": "First 15 min up 0.2% or more", "open_strong_down": "First 15 min down 0.2% or more", "open_quiet": "Quiet first 15 min",
    "breakout_up": "Breaks ABOVE the 09:15-09:30 range by 10:30", "breakout_down": "Breaks BELOW the 09:15-09:30 range by 10:30",
    "breakout_up_narrow": "Breaks above a narrow opening range", "breakout_down_narrow": "Breaks below a narrow opening range",
    "no_breakout": "No breakout of the opening range by 10:30",
}


def main() -> None:
    conn = connect()
    minutes = defaultdict(list)
    for ts, o, h, l, c in conn.execute("SELECT ts, open, high, low, close FROM index_bars WHERE underlying='NIFTY' AND interval=1 ORDER BY ts"):
        d = datetime.fromtimestamp(ts, IST); mod = d.hour * 60 + d.minute
        if 555 <= mod <= 929:
            minutes[d.date().isoformat()].append({"time": ts, "mod": mod, "open": o, "high": h, "low": l, "close": c})
    daily = {datetime.fromtimestamp(ts, IST).date().isoformat(): c
             for ts, c in conn.execute("SELECT ts, close FROM daily_bars WHERE segment='IDX_I' AND security_id='13' ORDER BY ts")}
    days = sorted(minutes)
    widths = []
    rows = []
    for i, d in enumerate(days):
        cs = minutes[d]; at = {c["mod"]: c for c in cs}
        prev = [x for x in daily if x < d]
        if not prev or (629 not in at and 630 not in at) or 660 not in at or 569 not in at: continue
        pc = daily[prev[-1]]; o = cs[0]["open"]
        rng = opening_range(cs)
        if not rng: continue
        widths.append((rng["high"] - rng["low"]) / o * 1e4)
        c930 = at[OR_END_MIN - 1]["close"]; c1030 = (at.get(630) or at[629])["close"]; c1100 = at[660]["close"]
        rows.append({"day": d, "year": d[:4], "gap": (o / pc - 1) * 1e4, "pc": pc, "o": o, "rng": rng, "c930": c930, "c1030": c1030,
                     "c1100": c1100, "bo": find_breakout(cs, rng), "move930": (c930 / o - 1) * 1e4,
                     "low_to_1100": min(c["low"] for c in cs if c["mod"] <= 660), "high_to_1100": max(c["high"] for c in cs if c["mod"] <= 660)})
    median_w = statistics.median(widths)

    def stat(text, items):
        """items: list of (year, hit: bool, pts: float)."""
        if not items: return None
        by = defaultdict(list)
        for y, hit, pts in items: by[y].append((hit, pts))
        pts = [p for _, _, p in items]
        return {"text": text, "n": len(items), "rate": round(sum(h for _, h, _ in items) / len(items), 3),
                "avgPts": round(statistics.mean(pts), 1), "medianPts": round(statistics.median(pts), 1),
                "byYear": {y: {"n": len(v), "rate": round(sum(h for h, _ in v) / len(v), 3)} for y, v in sorted(by.items())}}

    out: dict[str, dict] = {}
    def add(key, statements):
        statements = [s for s in statements if s]
        if statements: out[key] = {"label": LABELS[key], "n": statements[0]["n"], "statements": statements}

    for side in ("up", "down"):
        for narrow in (False, True):
            sel = [r for r in rows if r["bo"] and r["bo"]["side"] == side and (not narrow or (r["rng"]["high"] - r["rng"]["low"]) / r["o"] * 1e4 < median_w)]
            sgn = 1 if side == "up" else -1
            def beyond(r, c): return (c - r["bo"]["level"]) * sgn
            add(f"breakout_{side}{'_narrow' if narrow else ''}", [
                stat("Still beyond the breakout level at 10:30", [(r["year"], beyond(r, r["c1030"]) > 0, beyond(r, r["c1030"])) for r in sel]),
                stat("Still beyond the breakout level at 11:00", [(r["year"], beyond(r, r["c1100"]) > 0, beyond(r, r["c1100"])) for r in sel]),
            ])
    sel = [r for r in rows if not r["bo"]]
    add("no_breakout", [stat("NIFTY higher at 11:00 than at 09:30", [(r["year"], r["c1100"] > r["c930"], r["c1100"] - r["c930"]) for r in sel])])
    for key in ("gap_up_big", "gap_up", "gap_flat", "gap_down", "gap_down_big"):
        sel = [r for r in rows if gap_class(r["gap"]) == key]
        up = key.startswith("gap_up")
        fill = [(r["year"], (r["low_to_1100"] <= r["pc"]) if up else (r["high_to_1100"] >= r["pc"]), r["c1100"] - r["c930"]) for r in sel]
        add(key, [
            stat("NIFTY higher at 11:00 than at 09:30", [(r["year"], r["c1100"] > r["c930"], r["c1100"] - r["c930"]) for r in sel]),
            stat("Gap filled (touched the previous close) by 11:00", fill) if key != "gap_flat" else None,
        ])
    for key in ("open_strong_up", "open_strong_down", "open_quiet"):
        sel = [r for r in rows if first_move_class(r["move930"]) == key]
        sgn = -1 if key == "open_strong_down" else 1
        add(key, [
            stat("Moves further the same way 09:30 -> 10:30" if key != "open_quiet" else "NIFTY higher at 10:30 than at 09:30",
                 [(r["year"], (r["c1030"] - r["c930"]) * sgn > 0, (r["c1030"] - r["c930"]) * sgn) for r in sel]),
            stat("Moves further the same way 09:30 -> 11:00" if key != "open_quiet" else "NIFTY higher at 11:00 than at 09:30",
                 [(r["year"], (r["c1100"] - r["c930"]) * sgn > 0, (r["c1100"] - r["c930"]) * sgn) for r in sel]),
        ])
    payload = {"generatedAt": datetime.now(IST).isoformat(timespec="minutes"), "days": len(rows), "from": rows[0]["day"], "to": rows[-1]["day"],
               "orWidthMedianBps": round(median_w, 1), "situations": out,
               "note": "Historical frequencies, not predictions. In testing (Nov 2026) none of these beat the cost of a debit spread."}
    BASE_RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASE_RATES_FILE.write_text(json.dumps(payload, indent=1))
    print(f"{len(rows)} days {payload['from']}..{payload['to']}; median opening-range width {median_w:.1f} bps -> {BASE_RATES_FILE}")
    for k, v in out.items():
        print(f"  {v['label']:48} n={v['n']:3}  " + " | ".join(f"{s['text'][:38]}: {s['rate']*100:.0f}% (avg {s['avgPts']:+.0f} pts)" for s in v["statements"]))


if __name__ == "__main__":
    main()

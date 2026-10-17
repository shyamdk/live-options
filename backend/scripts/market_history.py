"""Local store of Dhan historical candles for backtests, downloaded once and
then only topped up with what's missing.

Data lives in backend/data/history/market_history.sqlite3 (git-ignored, not
deployed). Two kinds of series:

  option_bars  Dhan expired-options "rolling" 1-min data (/charts/rollingoption):
               one series per (underlying, expiry flag WEEK/MONTH, expiry code
               1 = nearest / 2 = next / 3 = far, strike offset vs ATM, CALL/PUT).
               Each bar carries the actual strike and the spot at that minute,
               so fixed-strike prices are rebuilt by filtering on `strike`.
               Dhan serves ATM+-10 for the nearest index expiry but only ATM+-3
               for the next one.
  index_bars   1-min index candles (/charts/intraday).

`fetched_days` remembers which (series, day) pairs were downloaded and with
which fields, so `sync` only requests the missing days (holidays included, so
they aren't asked for again). Today is never marked complete before 15:35 IST.

CLI (run from backend/):
  ../.venv/bin/python -m scripts.market_history status
  ../.venv/bin/python -m scripts.market_history sync --underlying NIFTY --expiry-code 1 \\
      --offsets -10:10 --from 2026-04-01 --to 2026-10-16
  ../.venv/bin/python -m scripts.market_history sync-index --underlying NIFTY --from 2026-04-01
  ../.venv/bin/python -m scripts.market_history import-json FILE --underlying SENSEX --expiry-code 1

In code:
  from scripts.market_history import load_option_bars, load_index_bars, weekly_expiries
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.core.config import get_settings
from app.services.dhan import DhanService

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "history" / "market_history.sqlite3"
IST = timezone(timedelta(hours=5, minutes=30))
UNDERLYINGS = {
    "NIFTY": {"securityId": 13, "segment": "NSE_FNO", "index": "13", "weeklyExpiry": 1},  # Tuesday
    "BANKNIFTY": {"securityId": 25, "segment": "NSE_FNO", "index": "25", "weeklyExpiry": None},
    "SENSEX": {"securityId": 51, "segment": "BSE_FNO", "index": "51", "weeklyExpiry": 3},  # Thursday
}
ALL_FIELDS = ("open", "high", "low", "close", "volume", "oi", "iv", "strike", "spot")
# A stored day counts as complete when it has these (older downloads have no
# oi/iv; every new request still asks for ALL_FIELDS).
CORE_FIELDS = ("open", "high", "low", "close", "volume", "strike", "spot")
WINDOW_DAYS = 14  # Dhan times out on longer 1-min windows
REQUEST_GAP_SECONDS = 1.1


# ---------------------------------------------------------------- storage


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS option_bars (
            underlying TEXT NOT NULL, expiry_flag TEXT NOT NULL, expiry_code INTEGER NOT NULL,
            strike_offset INTEGER NOT NULL, option_type TEXT NOT NULL, interval INTEGER NOT NULL,
            ts INTEGER NOT NULL, strike REAL, spot REAL, open REAL, high REAL, low REAL, close REAL,
            volume REAL, oi REAL, iv REAL,
            PRIMARY KEY (underlying, expiry_flag, expiry_code, strike_offset, option_type, interval, ts)
        );
        CREATE TABLE IF NOT EXISTS index_bars (
            underlying TEXT NOT NULL, interval INTEGER NOT NULL, ts INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (underlying, interval, ts)
        );
        CREATE TABLE IF NOT EXISTS daily_bars (
            symbol TEXT NOT NULL, security_id TEXT NOT NULL, segment TEXT NOT NULL, ts INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (segment, security_id, ts)
        );
        CREATE TABLE IF NOT EXISTS fetched_days (
            series TEXT NOT NULL, day TEXT NOT NULL, bars INTEGER NOT NULL, fields TEXT NOT NULL,
            fetched_at TEXT NOT NULL, PRIMARY KEY (series, day)
        );
        """
    )
    return conn


def option_series_key(underlying: str, expiry_flag: str, expiry_code: int, offset: int, option_type: str, interval: int) -> str:
    return f"opt|{underlying}|{expiry_flag}|{expiry_code}|{offset}|{option_type}|{interval}"


def index_series_key(underlying: str, interval: int) -> str:
    return f"idx|{underlying}|{interval}"


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _complete_cutoff() -> date:
    """Last day whose data is final: today only after 15:35 IST."""
    now = datetime.now(IST)
    return now.date() if now.hour * 60 + now.minute >= 15 * 60 + 35 else now.date() - timedelta(days=1)


def missing_days(conn: sqlite3.Connection, series: str, start: date, end: date, fields: Iterable[str]) -> list[date]:
    need = set(fields)
    have = {
        row["day"]: set(row["fields"].split(","))
        for row in conn.execute("SELECT day, fields FROM fetched_days WHERE series = ?", (series,))
    }
    return [d for d in _weekdays(start, end) if not need <= have.get(d.isoformat(), set())]


def _windows(days: list[date]) -> list[tuple[date, date]]:
    """Contiguous runs of missing days, cut into <= WINDOW_DAYS calendar-day windows."""
    out: list[tuple[date, date]] = []
    for d in days:
        if out and (d - out[-1][1]).days <= 3 and (d - out[-1][0]).days < WINDOW_DAYS:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _mark(conn: sqlite3.Connection, series: str, days: list[date], counts: dict[str, int], fields: Iterable[str]) -> None:
    cutoff = _complete_cutoff()
    now = datetime.now().isoformat(timespec="seconds")
    rows = [(series, d.isoformat(), counts.get(d.isoformat(), 0), ",".join(sorted(fields)), now) for d in days if d <= cutoff]
    conn.executemany(
        "INSERT INTO fetched_days (series, day, bars, fields, fetched_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(series, day) DO UPDATE SET bars = excluded.bars, fields = excluded.fields, fetched_at = excluded.fetched_at",
        rows,
    )


def _day_of(ts: int) -> str:
    return datetime.fromtimestamp(ts, IST).date().isoformat()


def store_option_payload(conn: sqlite3.Connection, key: tuple[str, str, int, int, str, int], payload: dict[str, Any]) -> dict[str, int]:
    """Upsert one Dhan rolling-option payload ({timestamp: [...], close: [...], ...})."""
    stamps = payload.get("timestamp") or []
    cols = {f: payload.get(f) or [] for f in ALL_FIELDS}
    rows, counts = [], {}
    for i, ts in enumerate(stamps):
        values = [cols[f][i] if i < len(cols[f]) else None for f in ALL_FIELDS]
        rows.append((*key, int(ts), *values))
        day = _day_of(int(ts))
        counts[day] = counts.get(day, 0) + 1
    conn.executemany(
        f"""INSERT INTO option_bars (underlying, expiry_flag, expiry_code, strike_offset, option_type, interval, ts,
            {", ".join(ALL_FIELDS)}) VALUES ({", ".join("?" * (7 + len(ALL_FIELDS)))})
            ON CONFLICT DO UPDATE SET {", ".join(f"{f} = COALESCE(excluded.{f}, {f})" for f in ALL_FIELDS)}""",
        rows,
    )
    return counts


# ---------------------------------------------------------------- downloading


async def _post(client: httpx.AsyncClient, dhan: DhanService, path: str, body: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(6):
        await asyncio.sleep(REQUEST_GAP_SECONDS)
        try:
            r = await client.post(f"{dhan.settings.dhan_base_url}{path}", headers=await dhan._headers(require_client_id=True), json=body)
            if r.status_code == 429 or "DH-904" in r.text or "Too many" in r.text:
                await asyncio.sleep(8 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            print(f"  retry {attempt + 1}: {type(exc).__name__} {str(exc)[:90]}", flush=True)
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{path} failed after 6 attempts")


async def sync_options(underlying: str, expiry_code: int, offsets: list[int], start: date, end: date, *,
                       expiry_flag: str = "WEEK", types: tuple[str, ...] = ("CALL", "PUT"), interval: int = 1) -> None:
    meta = UNDERLYINGS[underlying]
    dhan = DhanService(get_settings())
    conn = connect()
    jobs = []
    for offset in offsets:
        for typ in types:
            series = option_series_key(underlying, expiry_flag, expiry_code, offset, typ, interval)
            for window in _windows(missing_days(conn, series, start, end, CORE_FIELDS)):
                jobs.append((window, offset, typ, series))
    jobs.sort(key=lambda j: (j[0][0], abs(j[1]), j[1], j[2]))  # whole days fill in first, nearest strikes first
    print(f"{underlying} code {expiry_code}: {len(jobs)} requests to make", flush=True)
    async with httpx.AsyncClient(timeout=180) as client:
        for n, ((f, t), offset, typ, series) in enumerate(jobs, 1):
            strike = "ATM" if offset == 0 else f"ATM{offset:+d}"
            body = {"exchangeSegment": meta["segment"], "interval": str(interval), "securityId": meta["securityId"], "instrument": "OPTIDX",
                    "expiryFlag": expiry_flag, "expiryCode": expiry_code, "strike": strike, "drvOptionType": typ,
                    "requiredData": list(ALL_FIELDS), "fromDate": f.isoformat(), "toDate": t.isoformat()}
            t0 = time.monotonic()
            data = (await _post(client, dhan, "/charts/rollingoption", body)).get("data") or {}
            payload = data.get("ce" if typ == "CALL" else "pe") or {}
            counts = store_option_payload(conn, (underlying, expiry_flag, expiry_code, offset, typ, interval), payload)
            _mark(conn, series, _weekdays(f, t), counts, ALL_FIELDS)
            conn.commit()
            print(f"[{n}/{len(jobs)}] {strike} {typ} {f}..{t}: {sum(counts.values())} bars, {time.monotonic() - t0:.0f}s", flush=True)
    conn.close()


async def sync_index(underlying: str, start: date, end: date, interval: int = 1) -> None:
    meta = UNDERLYINGS[underlying]
    dhan = DhanService(get_settings())
    conn = connect()
    series = index_series_key(underlying, interval)
    fields = ("open", "high", "low", "close", "volume")
    for f, t in _windows(missing_days(conn, series, start, end, fields)):
        candles = await dhan.intraday_candles(meta["index"], "IDX_I", "INDEX", str(interval), f.isoformat(), (t + timedelta(days=1)).isoformat())
        counts: dict[str, int] = {}
        rows = []
        for c in candles:
            rows.append((underlying, interval, int(c["time"]), c["open"], c["high"], c["low"], c["close"], c.get("volume")))
            counts[_day_of(int(c["time"]))] = counts.get(_day_of(int(c["time"])), 0) + 1
        conn.executemany("INSERT OR REPLACE INTO index_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        _mark(conn, series, _weekdays(f, t), counts, fields)
        conn.commit()
        print(f"{underlying} index {f}..{t}: {len(rows)} bars", flush=True)
        await asyncio.sleep(REQUEST_GAP_SECONDS)
    conn.close()


async def sync_daily(symbol: str, security_id: str, segment: str = "NSE_EQ", instrument: str = "EQUITY",
                     start: date = date(2021, 1, 1), end: date | None = None, full: bool = False) -> int:
    """Daily candles for a stock/index; only the days after the last stored bar
    are fetched (full=True re-fetches everything, e.g. to backfill a field)."""
    end = end or date.today()
    conn = connect()
    row = conn.execute("SELECT MAX(ts) AS last FROM daily_bars WHERE segment = ? AND security_id = ?", (segment, str(security_id))).fetchone()
    if row["last"] and not full:
        start = max(start, datetime.fromtimestamp(row["last"], IST).date() + timedelta(days=1))
    if start > end:
        conn.close()
        return 0
    dhan = DhanService(get_settings())
    candles = await dhan.historical_daily_candles(str(security_id), segment, instrument, start.isoformat(), (end + timedelta(days=1)).isoformat())
    cutoff = _complete_cutoff()
    rows = [(symbol, str(security_id), segment, int(c["time"]), c["open"], c["high"], c["low"], c["close"], c.get("volume"))
            for c in candles if datetime.fromtimestamp(int(c["time"]), IST).date() <= cutoff]
    conn.executemany("INSERT OR REPLACE INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    await asyncio.sleep(REQUEST_GAP_SECONDS)
    return len(rows)


def load_daily_bars(security_id: str, segment: str = "NSE_EQ") -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute("SELECT * FROM daily_bars WHERE segment = ? AND security_id = ? ORDER BY ts", (segment, str(security_id))).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def import_json(path: str, underlying: str, expiry_code: int, expiry_flag: str = "WEEK", interval: int = 1) -> None:
    """Import an older scratch download: {"<anything>|<from>|ATM+n|CALL": payload, ...}."""
    conn = connect()
    raw = json.load(open(path))
    imported = 0
    for key, payload in raw.items():
        parts = key.split("|")
        strike, typ = parts[-2], parts[-1]
        if not payload or not payload.get("timestamp"):
            continue
        if len(parts) == 4 and parts[0].isdigit():  # "<code>|from|strike|type" files carry their own code
            code = int(parts[0])
        else:
            code = expiry_code
        offset = 0 if strike == "ATM" else int(strike[3:])
        fields = [f for f in ALL_FIELDS if payload.get(f)]
        counts = store_option_payload(conn, (underlying, expiry_flag, code, offset, typ, interval), payload)
        series = option_series_key(underlying, expiry_flag, code, offset, typ, interval)
        days = sorted(date.fromisoformat(d) for d in counts)
        if days:
            _mark(conn, series, _weekdays(days[0], days[-1]), counts, fields)
        imported += sum(counts.values())
    conn.commit()
    conn.close()
    print(f"imported {imported} bars from {path}")


# ---------------------------------------------------------------- reading


def load_option_bars(underlying: str, expiry_code: int, offset: int, option_type: str, start: str, end: str, *,
                     expiry_flag: str = "WEEK", interval: int = 1) -> list[dict[str, Any]]:
    """Bars of one rolling series between two ISO dates (inclusive), oldest first."""
    conn = connect()
    lo = int(datetime.fromisoformat(start + "T00:00:00+05:30").timestamp())
    hi = int(datetime.fromisoformat(end + "T23:59:59+05:30").timestamp())
    rows = conn.execute(
        "SELECT * FROM option_bars WHERE underlying = ? AND expiry_flag = ? AND expiry_code = ? AND strike_offset = ? "
        "AND option_type = ? AND interval = ? AND ts BETWEEN ? AND ? ORDER BY ts",
        (underlying, expiry_flag, expiry_code, offset, option_type, interval, lo, hi),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_strike_minutes(underlying: str, expiry_code: int, day: str, *, offsets: Iterable[int] = range(-10, 11),
                        expiry_flag: str = "WEEK", interval: int = 1) -> dict[tuple[float, str], list[dict[str, Any]]]:
    """One day rebuilt into fixed strikes: {(strike, "CE"|"PE"): [bar, ...]} from all rolling offsets."""
    out: dict[tuple[float, str], dict[int, dict[str, Any]]] = {}
    for offset in offsets:
        for typ in ("CALL", "PUT"):
            for bar in load_option_bars(underlying, expiry_code, offset, typ, day, day, expiry_flag=expiry_flag, interval=interval):
                if bar["strike"] is None:
                    continue
                out.setdefault((float(bar["strike"]), "CE" if typ == "CALL" else "PE"), {})[bar["ts"]] = bar
    return {k: [v[t] for t in sorted(v)] for k, v in out.items()}


def load_index_bars(underlying: str, start: str, end: str, interval: int = 1) -> list[dict[str, Any]]:
    conn = connect()
    lo = int(datetime.fromisoformat(start + "T00:00:00+05:30").timestamp())
    hi = int(datetime.fromisoformat(end + "T23:59:59+05:30").timestamp())
    rows = conn.execute(
        "SELECT * FROM index_bars WHERE underlying = ? AND interval = ? AND ts BETWEEN ? AND ? ORDER BY ts", (underlying, interval, lo, hi)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def trading_days(underlying: str, expiry_code: int = 1, expiry_flag: str = "WEEK") -> list[str]:
    """Days that have ATM option bars stored."""
    conn = connect()
    rows = conn.execute(
        "SELECT DISTINCT day FROM fetched_days WHERE series = ? AND bars > 0 ORDER BY day",
        (option_series_key(underlying, expiry_flag, expiry_code, 0, "CALL", 1),),
    ).fetchall()
    conn.close()
    return [r["day"] for r in rows]


def weekly_expiries(underlying: str, days: list[str]) -> list[str]:
    """Weekly expiry dates implied by the trading calendar: the expiry weekday,
    or the last trading day before it when that day is a holiday."""
    weekday = UNDERLYINGS[underlying]["weeklyExpiry"]
    if weekday is None or not days:
        return []
    have = set(days)
    out, d = [], date.fromisoformat(days[0])
    last = date.fromisoformat(days[-1]) + timedelta(days=7)
    while d <= last:
        if d.weekday() == weekday:
            e = d
            while e.isoformat() not in have and e > d - timedelta(days=4) and e >= date.fromisoformat(days[0]):
                e -= timedelta(days=1)
            out.append(e.isoformat() if e.isoformat() in have else d.isoformat())
        d += timedelta(days=1)
    return sorted(set(out))


def status() -> None:
    conn = connect()
    rows = conn.execute(
        "SELECT series, MIN(day) AS first, MAX(day) AS last, COUNT(*) AS days, SUM(bars) AS bars, MIN(fields) AS fields "
        "FROM fetched_days GROUP BY series ORDER BY series"
    ).fetchall()
    for r in rows:
        print(f"{r['series']:42} {r['first']} .. {r['last']}  {r['days']:4} days  {r['bars']:8} bars  [{r['fields']}]")
    size = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0
    print(f"{len(rows)} series, {size:.0f} MB at {DB_PATH}")
    conn.close()


def _offsets(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = (int(x) for x in spec.split(":"))
        return list(range(lo, hi + 1))
    return [int(x) for x in spec.split(",")]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("sync")
    s.add_argument("--underlying", required=True, choices=UNDERLYINGS)
    s.add_argument("--expiry-code", type=int, default=1)
    s.add_argument("--expiry-flag", default="WEEK", choices=("WEEK", "MONTH"))
    s.add_argument("--offsets", default="-10:10")
    s.add_argument("--types", default="CALL,PUT")
    s.add_argument("--from", dest="start", required=True)
    s.add_argument("--to", dest="end", default=date.today().isoformat())
    i = sub.add_parser("sync-index")
    i.add_argument("--underlying", required=True, choices=UNDERLYINGS)
    i.add_argument("--from", dest="start", required=True)
    i.add_argument("--to", dest="end", default=date.today().isoformat())
    j = sub.add_parser("import-json")
    j.add_argument("path")
    j.add_argument("--underlying", required=True, choices=UNDERLYINGS)
    j.add_argument("--expiry-code", type=int, default=1)
    args = parser.parse_args(argv)
    if args.cmd == "status":
        status()
    elif args.cmd == "sync":
        asyncio.run(sync_options(args.underlying, args.expiry_code, _offsets(args.offsets), date.fromisoformat(args.start),
                                 date.fromisoformat(args.end), expiry_flag=args.expiry_flag, types=tuple(args.types.split(","))))
    elif args.cmd == "sync-index":
        asyncio.run(sync_index(args.underlying, date.fromisoformat(args.start), date.fromisoformat(args.end)))
    elif args.cmd == "import-json":
        import_json(args.path, args.underlying, args.expiry_code)


if __name__ == "__main__":
    main(sys.argv[1:])

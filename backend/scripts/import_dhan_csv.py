"""One-time importer for user-provided Dhan "Global Transaction Report" CSVs.

Dhan's live trade-history API only reaches back ~2.5-3 months and has no
per-leg options granularity, so historical reconciliation has to come from
these manually-exported CSVs instead. This script:

- Parses every "*.csv" file in a given folder (Dhan's "Global Transaction
  Report" format: a 5-line header preamble, a blank line, a data table, a
  blank line, a "Net P&L,..." summary line, a blank line, a "NOTE:..." line).
- Splits each row into an OPTIONS leg-day (scrip name starts with "OPT ") or
  an EQUITY/ETF leg (everything else), producing a synthetic BUY and/or SELL
  transaction per equity row (mirroring the shape DhanEquityService._transaction
  already produces from the live API).
- Skips any equity leg that content-matches (security id + date + side + qty
  + price) a transaction already in equity_transactions_cache, so re-running
  this after the live API has already covered a period is a no-op for that
  period -- avoids double-counting where the CSV's date range overlaps what
  the live API already fetched.
- Upserts equity legs into equity_transactions_cache (same table/shape the
  live API path uses) and options legs into equity_options_transactions.

Usage:
    cd backend && python -m scripts.import_dhan_csv <csv-folder> [--dry-run]

The DB path is whatever `app.core.config.get_settings().database_file`
resolves to (same as the running backend), so run this with the same
working directory / .env the backend itself uses.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.sqlite import (  # noqa: E402
    init_db,
    list_equity_transactions_cache,
    upsert_equity_options_transactions,
    upsert_equity_transactions,
)

# CSV "Scrip Name" -> (symbol, securityId, isin), built from the account's
# current Dhan holdings (backend/data/live_options.sqlite3, category=holdings)
# on 2026-09-26. TCS has no current holding (fully sold) so it maps to a bare
# symbol only -- harmless, since the app's portfolio filter only ever surfaces
# transactions for securities still held today.
SCRIP_MAP: dict[str, tuple[str, str | None, str | None]] = {
    "Abbott": ("ABBOTINDIA", "17903", "INE358A01014"),
    "Affle 3i": ("AFFLE", "11343", "INE00WC01027"),
    "Apollo Hospitals": ("APOLLOHOSP", "157", "INE437A01024"),
    "BSE": ("BSE", "19585", "INE118H01025"),
    "Bajaj Finance": ("BAJFINANCE", "317", "INE296A01032"),
    "CAMS": ("CAMS", "342", "INE596I01020"),
    "CDSL": ("CDSL", "21174", "INE736A01011"),
    "Coal India": ("COALINDIA", "20374", "INE522F01014"),
    "Gillette": ("GILLETTE", "1576", "INE322A01010"),
    "HDFC Bank": ("HDFCBANK", "1333", "INE040A01034"),
    "ICICI Bank": ("ICICIBANK", "4963", "INE090A01021"),
    "ICICI Lombard General Insurance": ("ICICIGI", "21770", "INE765G01017"),
    "ITC": ("ITC", "1660", "INE154A01025"),
    "Jio Financial Services": ("JIOFIN", "18143", "INE758E01017"),
    "Larsen & Toubro": ("LT", "11483", "INE018A01030"),
    "MCX": ("MCX", "31181", "INE745G01043"),
    "National Stock Exchange of India": ("NSE", "544937", "INE721I01024"),
    "Nippon Gold ETF (GOLDBEES)": ("GOLDBEES", "14428", "INF204KB17I5"),
    "Nippon Life India AMC": ("NAM-INDIA", "357", "INE298J01013"),
    "Nippon Nifty 50 ETF (NIFTYBEES)": ("NIFTYBEES", "10576", "INF204KB14I2"),
    "Nippon Nifty Bank ETF (BANKBEES)": ("BANKBEES", "11439", "INF204KB15I9"),
    "Nippon Nifty IT ETF (ITBEES)": ("ITBEES", "19084", "INF204KB15V2"),
    "Nippon Pharma ETF (PHARMABEES)": ("PHARMABEES", "4973", "INF204KC1089"),
    "Nippon Silver ETF (SILVERBEES)": ("SILVERBEES", "8080", "INF204KC1402"),
    "Reliance Industries": ("RELIANCE", "2885", "INE002A01018"),
    "Sun Pharmaceutical": ("SUNPHARMA", "3351", "INE044A01036"),
    "Tata Consultancy Services": ("TCS", None, None),
    "UltraTech Cement": ("ULTRACEMCO", "11532", "INE481G01011"),
}

OPT_PATTERN = re.compile(r"^OPT (\S+) (\d{2} \w{3} \d{4}) (\d+) (CE|PE)$")


def _num(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def read_data_rows(path: Path) -> list[dict[str, str]]:
    lines = path.read_text().splitlines(keepends=True)
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("Date,Scrip Name"))
    data_lines = []
    for line in lines[header_idx + 1 :]:
        if line.strip() == "" or line.startswith("Net P&L") or line.startswith("NOTE"):
            break
        data_lines.append(line)
    reader = csv.DictReader([lines[header_idx]] + data_lines)
    return list(reader)


def parse_trade_date(raw: str) -> datetime:
    return datetime.strptime(raw.split(" ")[0] + " " + raw.split(" ")[1] + " " + raw.split(" ")[2], "%d %b %Y")


def build_equity_legs(row: dict[str, str], source: str) -> list[dict]:
    scrip = row["Scrip Name"].strip()
    mapping = SCRIP_MAP.get(scrip)
    if mapping is None:
        print(f"WARNING: no symbol mapping for equity scrip {scrip!r}, skipping row (bill {row.get('Bill No.')})")
        return []
    symbol, security_id, isin = mapping
    exchange = str(row.get("Exchange") or "NSE").upper()
    exchange_segment = "BSE_EQ" if "BSE" in exchange else "NSE_EQ"
    trade_dt = parse_trade_date(row["Date"])
    exchange_time = trade_dt.strftime("%Y-%m-%dT%H:%M:%S")
    bill_no = row.get("Bill No.") or ""
    buy_qty = _num(row.get("Buy Qty."))
    buy_value = _num(row.get("Buy Value"))
    sell_qty = _num(row.get("Sell Qty."))
    sell_value = _num(row.get("Sell Value"))
    total_charges = round(
        sum(
            _num(row.get(key))
            for key in ("Brokerage", "GST", "STT", "SEBI Fees", "Stamp Duty", "Txn. Charges", "Oth. Charges")
        ),
        4,
    )
    legs = []
    if buy_qty > 0:
        legs.append(
            {
                "id": f"CSV:{bill_no}:BUY:{security_id or symbol}:{exchange_time}",
                "orderId": bill_no,
                "exchangeOrderId": None,
                "exchangeTradeId": "CSV",
                "transactionType": "BUY",
                "exchangeSegment": exchange_segment,
                "productType": "CNC",
                "orderType": None,
                "tradingSymbol": None,
                "customSymbol": scrip,
                "symbol": symbol,
                "securityId": security_id or "",
                "isin": isin,
                "instrument": "EQUITY",
                "quantity": int(buy_qty),
                "price": round(buy_value / buy_qty, 4),
                "value": round(buy_value, 2),
                # Full bill charges attributed to the sell leg when both legs
                # exist on the same bill (STT etc. are levied on the sell side
                # for delivery trades); a buy-only bill keeps its own charges.
                "charges": 0.0 if sell_qty > 0 else total_charges,
                "createTime": None,
                "updateTime": None,
                "exchangeTime": exchange_time,
                "raw": row,
                "source": source,
            }
        )
    if sell_qty > 0:
        legs.append(
            {
                "id": f"CSV:{bill_no}:SELL:{security_id or symbol}:{exchange_time}",
                "orderId": bill_no,
                "exchangeOrderId": None,
                "exchangeTradeId": "CSV",
                "transactionType": "SELL",
                "exchangeSegment": exchange_segment,
                "productType": "CNC",
                "orderType": None,
                "tradingSymbol": None,
                "customSymbol": scrip,
                "symbol": symbol,
                "securityId": security_id or "",
                "isin": isin,
                "instrument": "EQUITY",
                "quantity": int(sell_qty),
                "price": round(sell_value / sell_qty, 4),
                "value": round(sell_value, 2),
                "charges": total_charges,
                "createTime": None,
                "updateTime": None,
                "exchangeTime": exchange_time,
                "raw": row,
                "source": source,
            }
        )
    return legs


def build_option_leg(row: dict[str, str], source: str) -> dict | None:
    scrip = row["Scrip Name"]
    match = OPT_PATTERN.match(scrip)
    if not match:
        print(f"WARNING: unparsed option scrip {scrip!r}, skipping row (bill {row.get('Bill No.')})")
        return None
    underlying, expiry_raw, strike, option_type = match.groups()
    expiry_date = datetime.strptime(expiry_raw, "%d %b %Y").strftime("%Y-%m-%d")
    trade_dt = parse_trade_date(row["Date"])
    trade_date = trade_dt.strftime("%Y-%m-%d")
    bill_no = row.get("Bill No.") or ""
    return {
        "id": f"CSV:{bill_no}:{underlying}:{expiry_date}:{strike}:{option_type}",
        "tradeDate": trade_date,
        "underlying": underlying,
        "expiryDate": expiry_date,
        "strike": float(strike),
        "optionType": option_type,
        "exchange": str(row.get("Exchange") or "NSE").upper(),
        "billNo": bill_no,
        "buyQty": _num(row.get("Buy Qty.")),
        "buyValue": _num(row.get("Buy Value")),
        "sellQty": _num(row.get("Sell Qty.")),
        "sellValue": _num(row.get("Sell Value")),
        "brokerage": _num(row.get("Brokerage")),
        "gst": _num(row.get("GST")),
        "stt": _num(row.get("STT")),
        "sebiFees": _num(row.get("SEBI Fees")),
        "stampDuty": _num(row.get("Stamp Duty")),
        "txnCharges": _num(row.get("Txn. Charges")),
        "othCharges": _num(row.get("Oth. Charges")),
        "grossAmount": _num(row.get("Gross Amount")),
        "source": source,
    }


def _existing_equity_fingerprints() -> set[tuple[str, str, str, int, float]]:
    existing = list_equity_transactions_cache(limit=20000)
    fingerprints = set()
    for row in existing:
        security_id = str(row.get("securityId") or "")
        exchange_time = str(row.get("exchangeTime") or "")
        date_part = exchange_time.split("T")[0] if exchange_time else ""
        txn_type = str(row.get("transactionType") or "")
        quantity = int(row.get("quantity") or 0)
        price = round(float(row.get("price") or 0), 2)
        if security_id and date_part:
            fingerprints.add((security_id, date_part, txn_type, quantity, price))
    return fingerprints


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Folder containing Dhan Global Transaction Report CSVs")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report counts without writing to the DB")
    args = parser.parse_args()

    init_db()
    existing_fingerprints = _existing_equity_fingerprints()
    print(f"Found {len(existing_fingerprints)} existing equity transaction fingerprints in the DB.")

    equity_legs: list[dict] = []
    option_legs: list[dict] = []
    skipped_dupes = 0

    for csv_path in sorted(p for p in args.folder.glob("*.csv") if not p.name.startswith("._")):
        source = csv_path.name
        rows = read_data_rows(csv_path)
        print(f"{csv_path.name}: {len(rows)} data rows")
        for row in rows:
            scrip = row["Scrip Name"]
            if scrip.startswith("OPT "):
                leg = build_option_leg(row, source)
                if leg:
                    option_legs.append(leg)
            else:
                for leg in build_equity_legs(row, source):
                    date_part = leg["exchangeTime"].split("T")[0]
                    fingerprint = (
                        str(leg["securityId"] or ""),
                        date_part,
                        leg["transactionType"],
                        leg["quantity"],
                        round(leg["price"], 2),
                    )
                    if leg["securityId"] and fingerprint in existing_fingerprints:
                        skipped_dupes += 1
                        continue
                    equity_legs.append(leg)

    print(f"Parsed {len(equity_legs)} new equity legs (skipped {skipped_dupes} already-covered by live API data).")
    print(f"Parsed {len(option_legs)} option leg-days.")

    if args.dry_run:
        print("--dry-run: not writing to the database.")
        return

    upsert_equity_transactions(equity_legs)
    upsert_equity_options_transactions(option_legs)
    print("Import complete.")


if __name__ == "__main__":
    main()

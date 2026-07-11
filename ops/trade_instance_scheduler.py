#!/usr/bin/python3
"""Starts/stops the live-options trading instance (140.245.25.236) based on an
IST trading-day/trading-hours schedule. Deployed and run every 5 minutes via
cron on 161.118.162.75 (always-on), using instance-principal auth scoped to
just the trade instance via an OCI Dynamic Group + Policy:

  Dynamic Group "trade-instance-scheduler" matches 161.118.162.75 by instance OCID.
  Policy: Allow dynamic-group trade-instance-scheduler to manage instance-family
          in compartment id <compartment OCID>
  (a `where target.resource.id = '<trade instance OCID>'` condition was tried
  first to scope this to only the trade instance, but OCI rejected it as a
  no-op for this resource type — fell back to compartment-scoped, acceptable
  since the compartment only has these two instances.)

This copy lives in the live-options repo for documentation/version history;
the deployed copy is at ~/trade-instance-scheduler/scheduler.py on
161.118.162.75 and is what cron actually runs.

Idempotent/self-healing by design: each run reads the instance's actual
lifecycle state and only acts if it disagrees with what the schedule says it
should be, so a missed tick, a slow OCI API, or a mid-transition state never
causes a duplicate or wrong action.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

TRADE_INSTANCE_ID = "ocid1.instance.oc1.ap-mumbai-1.anrg6ljrtbq7fjycklo2cyebu7xa6hkznnqhxko2glzfczq6pod4zgangyuq"
IST = ZoneInfo("Asia/Kolkata")
START_TIME = time(8, 30)
STOP_TIME = time(17, 0)

# NSE/BSE trading holidays for 2026 (source: zerodha.com/marketintel/holiday-calendar).
# Update this set once a year when the exchanges publish the next year's calendar.
HOLIDAYS: set[str] = {
    "2026-01-15",  # Municipal Corporation Elections (Maharashtra)
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-26",  # Shri Ram Navami
    "2026-03-31",  # Shri Mahavir Jayanti
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Eid
    "2026-06-26",  # Moharram
    "2026-09-14",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali-Balipratipada
    "2026-11-24",  # Prakash Gurpurb Sri Guru Nanak Dev
    "2026-12-25",  # Christmas
}

LOG_PATH = Path.home() / "trade-instance-scheduler" / "scheduler.log"


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def should_be_running(now: datetime, holidays: set[str] = HOLIDAYS) -> bool:
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    if now.date().isoformat() in holidays:
        return False
    return START_TIME <= now.time() <= STOP_TIME


def main() -> None:
    import oci

    setup_logging()
    now = datetime.now(IST)
    target_running = should_be_running(now)

    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        client = oci.core.ComputeClient(config={}, signer=signer)
        instance = client.get_instance(TRADE_INSTANCE_ID).data
        state = instance.lifecycle_state
    except Exception as exc:
        logging.error("Failed to read instance state: %s", exc)
        return

    logging.info("now=%s target_running=%s current_state=%s", now.isoformat(timespec="seconds"), target_running, state)

    try:
        if target_running and state == "STOPPED":
            logging.info("Starting trade instance")
            client.instance_action(TRADE_INSTANCE_ID, "START")
        elif not target_running and state == "RUNNING":
            logging.info("Soft-stopping trade instance")
            client.instance_action(TRADE_INSTANCE_ID, "SOFTSTOP")
        else:
            logging.info("No action needed")
    except Exception as exc:
        logging.error("Failed to act on instance: %s", exc)


if __name__ == "__main__":
    main()

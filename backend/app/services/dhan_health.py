"""Dhan connection health: readable error reasons and Telegram alerts.

On 26-28 Oct 2026 every strategy ran blind for two days: first the access
token could not be renewed ("Invalid TOTP" -- the authenticator had been
re-registered), then the Data API plan had lapsed ("Data APIs not
Subscribed"). Both showed up only as a generic "401 Unauthorized" banner.
This module
  * turns Dhan's error payloads into the real reason plus what to do,
  * sends a Telegram alert when the login or the data plan fails (at most
    once every ALERT_EVERY_SECONDS per kind, shared across workers via the DB),
  * checks the profile once a day and warns PLAN_WARN_DAYS before the Data
    API plan expires.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
ALERT_EVERY_SECONDS = 2 * 3600
PLAN_WARN_DAYS = 5
CHECK_EVERY_SECONDS = 6 * 3600

HINTS = {
    "data_plan": "Dhan's Data API plan is not active -- renew it on web.dhan.co (Profile -> DhanHQ Trading APIs -> Data APIs). "
    "Strategies get no market data until then.",
    "totp": "TOTP_SECRET in .env no longer matches your Dhan authenticator (it was reset or re-registered). "
    "Set up TOTP again in Dhan and put the new key in TOTP_SECRET on the Mac and the server, then restart.",
    "token": "Dhan rejected the access token; the app renews it automatically -- if this persists, check the login alerts.",
}


def payload_reason(payload: Any) -> str | None:
    """Dhan's own message from an error payload: {"errorMessage": ...},
    {"message": ...} or {"data": {"806": "Data APIs not Subscribed"}, "status": "failed"}."""
    if not isinstance(payload, dict):
        return None
    for key in ("errorMessage", "message", "remarks", "error"):
        if payload.get(key):
            code = payload.get("errorCode")
            return f"{payload[key]}{f' ({code})' if code else ''}"
    data = payload.get("data")
    if isinstance(data, dict) and data:
        return "; ".join(f"{v} ({k})" for k, v in data.items())
    if isinstance(data, str) and data:
        return data
    return None


def classify(reason: str | None) -> str | None:
    text = (reason or "").lower()
    if "not subscribed" in text or "data api" in text:
        return "data_plan"
    if "totp" in text:
        return "totp"
    if "token" in text or "dh-906" in text:
        return "token"
    return None


def describe_401(payload: Any) -> str:
    """Error text for a 401 from Dhan: the real reason and what to do."""
    reason = payload_reason(payload)
    kind = classify(reason)
    if kind == "data_plan":
        report("data_plan", f"Dhan market data refused: {reason}")
    if not reason:
        return "401 Unauthorized from Dhan. Check DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID."
    return f"401 from Dhan: {reason}." + (f" {HINTS[kind]}" if kind else "")


def describe_auth_failure(message: str) -> str:
    """Error text for a failed token generation, plus an alert."""
    kind = classify(message) or "login"
    report("login", f"Dhan login (token renewal) failed: {message}")
    return f"{message}. {HINTS[kind]}" if kind in HINTS else message


def report(kind: str, text: str) -> None:
    """Send a Telegram alert for `kind`, at most once per ALERT_EVERY_SECONDS."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if not _claim(f"dhanHealth.lastAlert.{kind}", ALERT_EVERY_SECONDS):
        return
    hint = HINTS.get(classify(text) or kind, "")
    loop.create_task(_send(f"⚠️ {text}\n{hint}".strip()))


def _claim(key: str, every: int) -> bool:
    """True if no alert of this key was sent in the last `every` seconds (and records this one)."""
    try:
        from app.db.sqlite import get_manage_setting, set_manage_setting

        last = float(get_manage_setting(key) or 0)
        now = time.time()
        if now - last < every:
            return False
        set_manage_setting(key, str(now))
        return True
    except Exception:
        logger.exception("dhan_health: could not read/record the alert time")
        return False


async def _send(text: str) -> None:
    from app.services.telegram import TelegramNotifier

    logger.warning("dhan_health: %s", text.replace("\n", " "))
    await TelegramNotifier().send(text)


# ---------------------------------------------------------------- daily plan check


def plan_status(profile: dict[str, Any], today: datetime | None = None) -> dict[str, Any]:
    """{"active", "validUntil", "daysLeft"} from Dhan's profile (dataPlan / dataValidity)."""
    today = today or datetime.now(IST)
    active = str(profile.get("dataPlan") or "").lower() == "active"
    valid = str(profile.get("dataValidity") or "")
    until = None
    try:
        until = datetime.strptime(valid[:10], "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        pass
    days_left = (until.date() - today.date()).days if until else None
    return {"active": active, "validUntil": until.date().isoformat() if until else None, "daysLeft": days_left}


async def check_plan_once() -> dict[str, Any]:
    from app.services.dhan import DhanService

    status = plan_status(await DhanService().profile())
    if not status["active"]:
        report("data_plan", "Dhan Data API plan is not active.")
    elif status["daysLeft"] is not None and status["daysLeft"] <= PLAN_WARN_DAYS:
        if _claim(f"dhanHealth.planWarned.{status['validUntil']}.{status['daysLeft']}", 86400):
            await _send(f"⏰ Dhan Data API plan expires on {status['validUntil']} ({status['daysLeft']} day(s) left). "
                        "Renew it on web.dhan.co (Profile -> DhanHQ Trading APIs -> Data APIs) to keep market data flowing.")
    return status


async def _loop() -> None:
    while True:
        try:
            await check_plan_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dhan_health: plan check failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


def start_dhan_health_task() -> asyncio.Task | None:
    from app.core.config import get_settings

    if not get_settings().dhan_health_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_dhan_health_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return

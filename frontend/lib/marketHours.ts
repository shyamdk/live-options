/** Rough IST market-hours check for gating client-side polling. Doesn't
 * account for NSE holidays -- the backend's own session schedulers already
 * handle that for the things that actually matter (starting/stopping the
 * trade instance, background monitors). This just needs to stop pages from
 * re-polling every few seconds on evenings/weekends when nothing is
 * changing, not be exact.
 */
export function isMarketHoursNow(): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());

  const weekday = parts.find((p) => p.type === "weekday")?.value ?? "";
  if (weekday === "Sat" || weekday === "Sun") return false;

  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0") % 24;
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  const minutesSinceMidnight = hour * 60 + minute;
  return minutesSinceMidnight >= 9 * 60 + 15 && minutesSinceMidnight <= 15 * 60 + 30;
}

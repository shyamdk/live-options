"use client";

import { useEffect, useState } from "react";

import AlarmOverlay, { type PageAlarm } from "@/components/AlarmOverlay";
import { alertAction, getAlerts } from "@/lib/api";
import type { PortalAlert } from "@/types/alerts";

const POLL_MS = 30_000;

export function alertTitle(a: PortalAlert): string {
  if (a.kind === "price") {
    return `${a.symbol} ${a.direction === "below" ? "≤" : "≥"} ${a.price?.toLocaleString("en-IN")}${a.triggerPrice ? ` (at ${a.triggerPrice.toLocaleString("en-IN")})` : ""}`;
  }
  return `Reminder${a.symbol ? ` -- ${a.symbol}` : ""}`;
}

/** Portal-wide alarm for triggered price alerts and reminders, on every page. */
export default function GlobalAlerts() {
  const [pending, setPending] = useState<PortalAlert[]>([]);

  async function load() {
    try {
      setPending((await getAlerts()).pending);
    } catch {
      // keep the last state; the next poll retries
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const alarms: PageAlarm[] = pending.map((a) => ({
    id: a.id,
    createdAt: a.triggeredAt ?? a.createdAt,
    title: alertTitle(a),
    message: a.note || (a.kind === "price" ? "Price alert reached." : "Reminder due."),
  }));
  return (
    <AlarmOverlay
      title="Price alert / reminder"
      alarms={alarms}
      acknowledge={(id) => alertAction(id, "acknowledge")}
      onAcknowledged={load}
      showArmBanner={false}
    />
  );
}

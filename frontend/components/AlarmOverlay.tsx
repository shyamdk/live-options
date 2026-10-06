"use client";

import { BellRing } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export type PageAlarm = {
  id: number;
  createdAt: number;
  title: string;
  message: string;
};

function ist(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// Full-screen alarm for unacknowledged alarms: repeating beep (Web Audio --
// browsers only allow sound after the first click on the page, hence the
// "enable sound" banner), a system notification and a flashing tab title,
// until every alarm is acknowledged.
export default function AlarmOverlay({
  title,
  alarms,
  acknowledge,
  onAcknowledged,
}: {
  title: string;
  alarms: PageAlarm[];
  acknowledge: (id: number) => Promise<unknown>;
  onAcknowledged: () => void;
}) {
  const [soundReady, setSoundReady] = useState(false);
  const audioRef = useRef<AudioContext | null>(null);
  const notifiedRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    function unlock() {
      try {
        if (!audioRef.current) audioRef.current = new AudioContext();
        void audioRef.current.resume().then(() => setSoundReady(audioRef.current?.state === "running"));
      } catch {
        // no audio support
      }
    }
    window.addEventListener("pointerdown", unlock);
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);

  useEffect(() => {
    if (!alarms.length) return;
    const original = document.title;
    let flip = false;
    const titleTimer = window.setInterval(() => {
      flip = !flip;
      document.title = flip ? `⏰ ALARM -- ${title}` : original;
    }, 1000);
    const beepTimer = window.setInterval(() => {
      const ctx = audioRef.current;
      if (!ctx || ctx.state !== "running") return;
      for (const offset of [0, 0.25, 0.5]) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "square";
        osc.frequency.value = 880;
        gain.gain.value = 0.15;
        osc.connect(gain).connect(ctx.destination);
        osc.start(ctx.currentTime + offset);
        osc.stop(ctx.currentTime + offset + 0.15);
      }
    }, 1500);
    for (const alarm of alarms) {
      if (notifiedRef.current.has(alarm.id)) continue;
      notifiedRef.current.add(alarm.id);
      try {
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification(`⏰ ${alarm.title}`, { body: alarm.message, requireInteraction: true });
        }
      } catch {
        // notifications unavailable
      }
    }
    return () => {
      window.clearInterval(titleTimer);
      window.clearInterval(beepTimer);
      document.title = original;
    };
  }, [alarms]);

  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") void Notification.requestPermission();
  }, []);

  if (!alarms.length) {
    return soundReady ? null : (
      <div className="alert warning" style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <BellRing size={16} /> Click anywhere on this page once to arm the alarm sound (browsers block audio until you interact).
      </div>
    );
  }

  async function acknowledgeAll() {
    for (const alarm of alarms) {
      try {
        await acknowledge(alarm.id);
      } catch {
        // already acknowledged elsewhere
      }
    }
    onAcknowledged();
  }

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(201, 53, 53, 0.92)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div style={{ background: "#fff", borderRadius: 10, padding: 24, maxWidth: 560, width: "100%", boxShadow: "0 10px 40px rgba(0,0,0,0.3)" }}>
        <h2 style={{ margin: "0 0 8px", color: "var(--red)", display: "flex", gap: 8, alignItems: "center" }}>
          <BellRing size={22} /> {title}
        </h2>
        {alarms.map((alarm) => (
          <div key={alarm.id} style={{ marginBottom: 12 }}>
            <strong>{alarm.title}</strong>
            <div className="pcr-oi-caption">{ist(alarm.createdAt)}</div>
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "6px 0 0", fontSize: 13 }}>{alarm.message}</pre>
          </div>
        ))}
        {!soundReady ? <p className="pcr-oi-caption">Click anywhere to hear the alarm sound.</p> : null}
        <button type="button" className="button" onClick={acknowledgeAll} style={{ marginTop: 8 }}>
          Acknowledge {alarms.length > 1 ? `all ${alarms.length}` : ""}
        </button>
      </div>
    </div>
  );
}

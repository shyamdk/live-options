"use client";

import type { IPriceLine } from "lightweight-charts";
import { LineStyle } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { ChartHandle } from "@/components/PcrOiPanel";

const STORAGE_KEY = "oi-analysis-chart-lines-v1";
const HIT_TOLERANCE_PX = 6;
const CLICK_MOVE_TOLERANCE_PX = 4;
const LINE_COLOR = "#4a5568";

export type StoredLine = { id: string; price: number };

function loadAll(): Record<string, StoredLine[]> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, StoredLine[]>) : {};
  } catch {
    return {};
  }
}

function saveAll(all: Record<string, StoredLine[]>) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    // Ignore quota/serialization errors -- lines just won't persist this time.
  }
}

function newId(): string {
  if (typeof window !== "undefined" && window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `line-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Click-to-add / drag-to-move / remove horizontal reference lines on a
 * lightweight-charts series, persisted in localStorage per storageKey (e.g.
 * one key per chart+underlying) so they survive reloads. lightweight-charts
 * has no built-in draggable price line, so dragging is hand-rolled: hit-test
 * mousedown against each line's current pixel Y (via priceToCoordinate),
 * and while dragging, suspend the chart's own pan/zoom so our drag doesn't
 * fight it. A plain click (mousedown+mouseup within a few px, not on an
 * existing line) adds a new line at that price; anything that moved further
 * is either a pan or a line-drag, never an add -- otherwise every pan
 * gesture would spam a new line.
 */
export function useChartLines(handle: ChartHandle | null, storageKey: string) {
  const [lines, setLines] = useState<StoredLine[]>([]);
  const linesRef = useRef<StoredLine[]>([]);
  const priceLineRefs = useRef<Map<string, IPriceLine>>(new Map());
  const storageKeyRef = useRef(storageKey);
  storageKeyRef.current = storageKey;

  function persist(next: StoredLine[]) {
    const all = loadAll();
    all[storageKeyRef.current] = next;
    saveAll(all);
    linesRef.current = next;
    setLines(next);
  }

  // (Re)load and render this key's lines whenever the chart or key changes.
  useEffect(() => {
    if (!handle) return;
    const { series } = handle;
    const initial = loadAll()[storageKey] ?? [];
    const created = new Map<string, IPriceLine>();
    initial.forEach((line) => {
      const priceLine = series.createPriceLine({
        id: line.id,
        price: line.price,
        color: LINE_COLOR,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        title: "",
      });
      created.set(line.id, priceLine);
    });
    priceLineRefs.current = created;
    linesRef.current = initial;
    setLines(initial);

    return () => {
      created.forEach((priceLine) => {
        try {
          series.removePriceLine(priceLine);
        } catch {
          // Chart may already be torn down (unmount race) -- nothing to clean up then.
        }
      });
    };
  }, [handle, storageKey]);

  // Mouse handling: add / drag / pan-passthrough.
  useEffect(() => {
    if (!handle) return;
    const { chart, series } = handle;
    const container = chart.chartElement();

    let downAt: { x: number; y: number } | null = null;
    let draggingId: string | null = null;

    function localY(clientY: number): number {
      return clientY - container.getBoundingClientRect().top;
    }

    function findNear(clientY: number): string | null {
      const y = localY(clientY);
      for (const line of linesRef.current) {
        const coord = series.priceToCoordinate(line.price);
        if (coord !== null && Math.abs(coord - y) <= HIT_TOLERANCE_PX) return line.id;
      }
      return null;
    }

    function addLineAt(clientY: number) {
      const price = series.coordinateToPrice(localY(clientY));
      if (price === null) return;
      const id = newId();
      const priceLine = series.createPriceLine({
        id,
        price,
        color: LINE_COLOR,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        title: "",
      });
      priceLineRefs.current.set(id, priceLine);
      persist([...linesRef.current, { id, price }]);
    }

    function onMouseDown(event: MouseEvent) {
      downAt = { x: event.clientX, y: event.clientY };
      const hitId = findNear(event.clientY);
      if (!hitId) return;
      draggingId = hitId;
      chart.applyOptions({ handleScroll: false, handleScale: false });
      container.style.cursor = "ns-resize";
      event.preventDefault();
      event.stopPropagation();
    }

    function onMouseMove(event: MouseEvent) {
      if (!draggingId) return;
      const price = series.coordinateToPrice(localY(event.clientY));
      if (price === null) return;
      priceLineRefs.current.get(draggingId)?.applyOptions({ price });
      linesRef.current = linesRef.current.map((l) => (l.id === draggingId ? { ...l, price } : l));
      setLines(linesRef.current);
    }

    function onMouseUp(event: MouseEvent) {
      if (draggingId) {
        chart.applyOptions({ handleScroll: true, handleScale: true });
        container.style.cursor = "";
        draggingId = null;
        downAt = null;
        persist(linesRef.current);
        return;
      }
      if (downAt) {
        const dx = event.clientX - downAt.x;
        const dy = event.clientY - downAt.y;
        if (Math.sqrt(dx * dx + dy * dy) <= CLICK_MOVE_TOLERANCE_PX && !findNear(event.clientY)) {
          addLineAt(event.clientY);
        }
        downAt = null;
      }
    }

    container.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      container.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  function removeLine(id: string) {
    const priceLine = priceLineRefs.current.get(id);
    if (priceLine && handle) {
      try {
        handle.series.removePriceLine(priceLine);
      } catch {
        // Already gone -- fine.
      }
    }
    priceLineRefs.current.delete(id);
    persist(linesRef.current.filter((l) => l.id !== id));
  }

  return { lines, removeLine };
}

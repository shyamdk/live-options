/**
 * Running total of net P&L over closed trades, in time order (oldest first):
 * row id -> cumulative net. Accessors keep it independent of each page's
 * trade shape. Open trades are skipped (their P&L is not final).
 */
export function cumulativeNet<T>(
  rows: T[],
  id: (t: T) => string | number,
  time: (t: T) => number | null | undefined,
  net: (t: T) => number | null | undefined,
  closed: (t: T) => boolean,
): Map<string | number, number> {
  const out = new Map<string | number, number>();
  let total = 0;
  const done = rows.filter(closed).sort((a, b) => (time(a) ?? 0) - (time(b) ?? 0) || (Number(id(a)) || 0) - (Number(id(b)) || 0));
  for (const t of done) {
    total += net(t) ?? 0;
    out.set(id(t), total);
  }
  return out;
}

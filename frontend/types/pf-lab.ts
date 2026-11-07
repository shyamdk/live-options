export type PfMarket = "NIFTY" | "BTC" | "GOLD";
export type PfHorizon = "short" | "medium" | "long";

export interface PfColumn {
  index: number;
  type: "X" | "O";
  top: number;
  bottom: number;
  topPrice: number;
  bottomPrice: number;
  start: number;
  end: number;
}

export interface PfUnderlyingStats {
  trades: number;
  years: number;
  perYear?: number;
  win?: number;
  avg?: number;
  total?: number;
  annual?: number;
  logAnnual?: number;
  pf?: number | null;
  maxDD?: number;
  posYears?: number;
  nYears?: number;
  inMarket?: number;
  avgDays?: number;
  longTotal?: number;
  shortTotal?: number;
}

export interface PfSpreadStats {
  trades: number;
  win?: number;
  total?: number;
  annual?: number;
  maxDD?: number;
  last3y?: number;
}

export interface PfCell {
  underlying: PfUnderlyingStats;
  spread?: PfSpreadStats;
}

export interface PfTrade {
  id: number;
  positionId: number | null;
  system: string;
  side: 1 | -1;
  status: "OPEN" | "CLOSED";
  trigger: string;
  openedAt: number;
  closedAt: number | null;
  exitReason: string | null;
  underlyingEntry: number;
  underlyingExit: number | null;
  instrument: string;
  qty: number;
  entryPrice: number | null;
  exitPrice: number | null;
  expiry: string | null;
  lastValue: number | null;
  pnl: number | null;
  charges: number | null;
  lastUpdate: number | null;
}

export interface PfState {
  market: PfMarket;
  horizon: PfHorizon;
  meta: { label: string; venue: string; instrument: string };
  horizonLabel: string;
  currency: string;
  config: { enabled: boolean; lots: number; notionalUsd: number; systems: string[]; boxPercent: number };
  systems: { key: string; label: string }[];
  lastRun: number | null;
  chart?: { columns: PfColumn[]; ma: number | null; lastClose: number; lastTime: number; boxPercent: number };
  signals?: Record<string, { side: number; since: number | null; at: number | null; lastTrades: { side: number; entryTime: number; entryPrice: number; exitTime: number; exitPrice: number }[] }>;
  trades: PfTrade[];
  totals: Record<string, { realized: number; open: number; closedCount: number }>;
  backtest: Record<string, PfCell | null>;
  backtestData?: { from: string; to: string; bars: number; buyHoldCagr: number; buyHoldLog?: number };
  events: { id: number; time: number; system: string | null; kind: string; text: string }[];
}

export interface PfOverview {
  backtest: { generatedAt?: string; cells: Record<string, PfCell>; data: Record<string, { from: string; to: string; bars: number; buyHoldCagr: number; buyHoldLog?: number }> };
  books: Record<string, { open: number; realized: number; openPnl: number; currency: string }>;
  markets: Record<string, { label: string; venue: string; instrument: string }>;
  horizons: Record<string, string>;
  systems: { key: string; label: string }[];
}

export type SwingConfig = {
  enabled: boolean;
  mode: "paper" | "live";
  capital: number;
  positions: number;
  fillDepth: number;
  exitRank: number;
  maxHoldWeeks: number;
  cooldownWeeks: number;
  lookbacks: string;
  requireSma200: boolean;
  regimeFilter: boolean;
  qualityFilter: boolean;
  newsFilter: boolean;
  slippagePercent: number;
  rebalanceAfter: string;
  executeAt: string;
  liveOrdersAllowed: boolean;
  angelConfigured: boolean;
};

export type SwingTrade = {
  id: number;
  symbol: string;
  securityId: string;
  industry?: string | null;
  mode: string;
  status: "PLANNED" | "OPEN" | "PENDING_EXIT" | "CLOSED" | "CANCELLED";
  qty: number;
  plannedAt?: number | null;
  entryTime?: number | null;
  entryPrice?: number | null;
  entryCharges?: number | null;
  entryReason?: string | null;
  entryRank?: number | null;
  entryScore?: number | null;
  exitTime?: number | null;
  exitPrice?: number | null;
  exitCharges?: number | null;
  exitReason?: string | null;
  pnl?: number | null;
  pnlPercent?: number | null;
  lastPrice?: number | null;
  lastRank?: number | null;
  heldWeeks?: number | null;
  note?: string | null;
};

export type SwingRankRow = {
  symbol: string;
  rank: number | null;
  score: number;
  returns: Record<string, number>;
  vol: number;
  close: number;
  sma200: number | null;
  aboveSma200: boolean;
  eligible: boolean;
};

export type SwingPlan = {
  sells: Array<{ symbol: string; reason: string; kind: string }>;
  buys: Array<{ symbol: string; rank: number; score: number; reason: string }>;
  skipped: Array<{ symbol: string; rank: number; reason: string }>;
  free: number;
  note: string | null;
};

export type SwingState = {
  config: SwingConfig;
  summary: {
    capital: number;
    cash: number;
    holdingsValue: number;
    equity: number;
    pnl: number;
    pnlPercent: number;
    realized: number;
    closedTrades: number;
    winRate: number | null;
    nextRebalance: string;
    barsSyncedFor: string | null;
  };
  regime: { ok: boolean; nifty: number | null; sma200: number | null };
  open: SwingTrade[];
  planned: SwingTrade[];
  closed: SwingTrade[];
  latest: null | {
    week: string;
    trigger: string;
    regimeOk: boolean;
    plan: SwingPlan;
    gates: Record<string, { quality?: string | string[]; news?: Record<string, unknown> }>;
    ranking: SwingRankRow[];
    eligible: number;
    universe: number;
  };
  equityCurve: Array<{ day: string; cash: number; holdings: number; equity: number; nifty: number | null; positions: number }>;
  events: Array<{ id: number; time: number; kind: string; symbol?: string | null; text: string }>;
  universe: number;
};

export type SwingBacktest = { cagr: number; totalReturn: number; maxDrawdown: number; niftyCagr: number; trades: number; winRate: number | null; costs: number; years: number };

export type SwingRetro = {
  id: number;
  createdAt: number;
  trigger: string;
  settings: Record<string, unknown>;
  review: {
    openPositions: number;
    closedTrades: number;
    realized: number;
    winRate: number | null;
    avgWin: number | null;
    avgLoss: number | null;
    medianHoldWeeks: number | null;
    byExit: Record<string, { trades: number; pnl: number; winRate: number }>;
    bySector: Record<string, { trades: number; pnl: number; winRate: number }>;
    byEntryRank: Record<string, { trades: number; pnl: number; winRate: number }>;
    sinceStart: { from: string; to: string; strategy: number; nifty: number } | null;
  };
  retest: {
    error?: string;
    recentNote?: string | null;
    window?: { from: string; to: string; recentFrom: string };
    current?: { full: SwingBacktest; recent: SwingBacktest };
    random?: { median: number; min: number; max: number };
    variants?: Array<{ label: string; change: Record<string, unknown>; full: SwingBacktest; recent: SwingBacktest; gainFull: number; gainRecent: number; suggest: boolean }>;
  };
  decisions: Array<{ at: number; applied: string }>;
};

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

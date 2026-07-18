export type AnimeshCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type AnimeshSide = "PE" | "CE";

export type AnimeshSignal = {
  id: number;
  sessionId: string;
  side: AnimeshSide;
  kind: "ENTRY" | "EXIT";
  status: "PENDING" | "APPROVED" | "REJECTED" | "FAILED" | string;
  strike: number | null;
  indexLevel: number | null;
  tradeId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type AnimeshTradeLeg = {
  id: number;
  tradeId: string;
  lotNumber: number;
  qty: number;
  status: "OPEN" | "CLOSED";
  exitIndexLevel: number | null;
  exitPremium: number | null;
  exitAt: string | null;
  exitReason: string | null;
  realizedPnl: number | null;
  createdAt: string;
  updatedAt: string;
};

export type AnimeshTrade = {
  id: string;
  sessionId: string;
  side: AnimeshSide;
  strike: number | null;
  securityId: string | null;
  exchangeSegment: string | null;
  mode: "PAPER" | "LIVE";
  status: "OPEN" | "CLOSED";
  entrySignalId: number | null;
  entryIndexLevel: number;
  entryPremium: number | null;
  entryQty: number | null;
  entryAt: string | null;
  initialSl: number;
  target1: number;
  target2: number;
  phase: "OPEN_ALL" | "LOT1_BOOKED" | "LOT2_BOOKED";
  lot3TrailSl: number | null;
  realizedPnl: number | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
  legs?: AnimeshTradeLeg[];
  currentPremium?: number | null;
  unrealizedPnl?: number | null;
};

export type AnimeshEvent = {
  id: number;
  sessionId: string;
  eventType: string;
  message: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type AnimeshSideState = {
  candles: AnimeshCandle[];
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
  bandHigh: (number | null)[];
  bandLow: (number | null)[];
  bandMedian: (number | null)[];
  crossoverCandle: AnimeshCandle | null;
  isBiasActive: boolean;
  openTrade: AnimeshTrade | null;
  legs: AnimeshTradeLeg[];
  trades: AnimeshTrade[];
  tradesCount: number;
  consecutiveSl: number;
  halted: boolean;
};

export type AnimeshState =
  | { mode: "PAPER" | "LIVE"; status: "NOT_STARTED" }
  | {
      mode: "PAPER" | "LIVE";
      status: "RUNNING";
      sessionId: string;
      dailyBias: AnimeshSide | null;
      wsConnected: boolean;
      spot: number | null;
      sides: Record<AnimeshSide, AnimeshSideState>;
      pendingSignals: AnimeshSignal[];
      events: AnimeshEvent[];
    };

export type AnimeshSession = {
  id: string;
  sessionDate: string;
  mode: string;
  status: string;
  dailyBias: AnimeshSide | null;
  peTradesCount: number;
  peConsecutiveSl: number;
  peHalted: boolean;
  ceTradesCount: number;
  ceConsecutiveSl: number;
  ceHalted: boolean;
  createdAt: string;
  updatedAt: string;
};

export type AnimeshSessionDetail = {
  session: AnimeshSession;
  signals: AnimeshSignal[];
  trades: AnimeshTrade[];
  events: AnimeshEvent[];
};

export type AnimeshCandlesResponse = {
  side: AnimeshSide;
  intervalMinutes: number;
  candles: AnimeshCandle[];
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
  bandHigh: (number | null)[];
  bandLow: (number | null)[];
  bandMedian: (number | null)[];
};

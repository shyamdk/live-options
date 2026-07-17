export type Ema5Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type Ema5Side = "PE" | "CE";

export type Ema5Signal = {
  id: number;
  sessionId: string;
  side: Ema5Side;
  kind: "ENTRY" | "EXIT";
  status: "PENDING" | "APPROVED" | "REJECTED" | "FAILED" | string;
  strike: number | null;
  indexLevel: number | null;
  tradeId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type Ema5TradeLeg = {
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

export type Ema5Trade = {
  id: string;
  sessionId: string;
  side: Ema5Side;
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
  target3: number;
  phase: "OPEN_ALL" | "LOT1_BOOKED" | "LOT2_BOOKED";
  lot3TrailSl: number | null;
  realizedPnl: number | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
  legs?: Ema5TradeLeg[];
  currentPremium?: number | null;
  unrealizedPnl?: number | null;
};

export type Ema5Event = {
  id: number;
  sessionId: string;
  eventType: string;
  message: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type Ema5SideState = {
  alertCandle: Ema5Candle | null;
  candles: Ema5Candle[];
  ema: (number | null)[];
  openTrade: Ema5Trade | null;
  legs: Ema5TradeLeg[];
  trades: Ema5Trade[];
  tradesCount: number;
  consecutiveSl: number;
  halted: boolean;
};

export type Ema5State =
  | { mode: "PAPER" | "LIVE"; status: "NOT_STARTED" }
  | {
      mode: "PAPER" | "LIVE";
      status: "RUNNING";
      sessionId: string;
      wsConnected: boolean;
      spot: number | null;
      sides: Record<Ema5Side, Ema5SideState>;
      pendingSignals: Ema5Signal[];
      events: Ema5Event[];
    };

export type Ema5Session = {
  id: string;
  sessionDate: string;
  mode: string;
  status: string;
  peTradesCount: number;
  peConsecutiveSl: number;
  peHalted: boolean;
  ceTradesCount: number;
  ceConsecutiveSl: number;
  ceHalted: boolean;
  createdAt: string;
  updatedAt: string;
};

export type Ema5SessionDetail = {
  session: Ema5Session;
  signals: Ema5Signal[];
  trades: Ema5Trade[];
  events: Ema5Event[];
};

export type Ema5CandlesResponse = {
  side: Ema5Side;
  intervalMinutes: number;
  candles: Ema5Candle[];
  ema: (number | null)[];
};

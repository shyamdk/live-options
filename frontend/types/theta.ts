export type ThetaUnderlying = "NIFTY" | "SENSEX";
export type ThetaSide = "CE" | "PE";
export type ThetaDayType = "expiry" | "t1" | "t2" | "too_far";

export type ThetaSignal = {
  id: number;
  sessionId: string;
  kind: "ENTRY" | "ADD" | "EXIT";
  status: "PENDING" | "APPROVED" | "REJECTED" | "FAILED" | string;
  underlying: ThetaUnderlying;
  side: ThetaSide;
  strike: number | null;
  expiry: string | null;
  positionId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type ThetaTranche = {
  id: number;
  positionId: string;
  qty: number;
  premium: number;
  spotAtEntry: number | null;
  distancePctAtEntry: number | null;
  dayType: string | null;
  createdAt: string;
};

export type ThetaPosition = {
  id: string;
  sessionId: string;
  underlying: ThetaUnderlying;
  side: ThetaSide;
  strike: number;
  expiry: string;
  securityId: string | null;
  exchangeSegment: string | null;
  mode: "PAPER" | "LIVE";
  status: "OPEN" | "CLOSED";
  dayType: ThetaDayType | null;
  trancheCount: number;
  totalQty: number;
  avgEntryPremium: number | null;
  entrySpot: number | null;
  estimatedMargin: number | null;
  realizedPnl: number | null;
  closeReason: string | null;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
  tranches?: ThetaTranche[];
  currentPremium?: number | null;
  spot?: number | null;
  distancePct?: number | null;
  unrealizedPnl?: number | null;
};

export type ThetaEvent = {
  id: number;
  sessionId: string;
  eventType: string;
  message: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type ThetaUnderlyingState = {
  dayType: ThetaDayType | null;
  expiry: string | null;
  spot: number | null;
  openingRangeHigh: number | null;
  openingRangeLow: number | null;
  confirmedFlat: boolean;
};

export type ThetaState =
  | { mode: "PAPER" | "LIVE"; status: "NOT_STARTED" }
  | {
      mode: "PAPER" | "LIVE";
      status: "RUNNING";
      sessionId: string;
      halted: boolean;
      realizedPnl: number;
      marginUsed: number;
      marginCap: number;
      underlyings: Record<ThetaUnderlying, ThetaUnderlyingState>;
      wsConnected: boolean;
      openPositions: ThetaPosition[];
      closedPositions: ThetaPosition[];
      pendingSignals: ThetaSignal[];
      events: ThetaEvent[];
    };

export type ThetaSession = {
  id: string;
  sessionDate: string;
  mode: string;
  status: string;
  niftyDayType: string | null;
  sensexDayType: string | null;
  realizedPnl: number;
  halted: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ThetaSessionDetail = {
  session: ThetaSession;
  signals: ThetaSignal[];
  positions: ThetaPosition[];
  events: ThetaEvent[];
};

export type ThetaRuntimeConfig = {
  maxConcurrentMargin: number;
  maxDailyLoss: number;
};

export type GammaBlastWallStrike = {
  strike: number;
  optionSide: "CE" | "PE";
  securityId: string;
  ltp: number | null;
  oi: number | null;
};

export type GammaBlastWalls = {
  callWall: GammaBlastWallStrike | null;
  putWall: GammaBlastWallStrike | null;
};

export type GammaBlastQuietDay = {
  isQuiet: boolean;
  movePercent: number | null;
};

export type GammaBlastSignal = {
  id: number;
  sessionId: string;
  indexSymbol: string;
  kind: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "FAILED" | string;
  strike: number | null;
  optionSide: "CE" | "PE" | null;
  triggerPrice: number | null;
  level: number | null;
  tradeId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type GammaBlastTrade = {
  id: string;
  sessionId: string;
  indexSymbol: string;
  strike: number | null;
  optionSide: "CE" | "PE" | null;
  securityId: string | null;
  exchangeSegment: string | null;
  mode: "PAPER" | "LIVE";
  status: "OPEN" | "CLOSED";
  entrySignalId: number | null;
  entryPrice: number | null;
  entryQty: number | null;
  entryAt: string | null;
  exitPrice: number | null;
  exitQty: number | null;
  exitAt: string | null;
  exitReason: string | null;
  realizedPnl: number | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type GammaBlastEvent = {
  id: number;
  sessionId: string;
  eventType: string;
  message: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type GammaBlastIndexState =
  | { status: "NOT_STARTED" }
  | {
      status: "RUNNING";
      sessionId: string;
      expiry: string;
      sessionOpen: number;
      wsConnected: boolean;
      spot: number | null;
      walls: GammaBlastWalls | null;
      quietDay: GammaBlastQuietDay | null;
      pendingSignals: GammaBlastSignal[];
      openTrades: GammaBlastTrade[];
      events: GammaBlastEvent[];
    };

export type GammaBlastState = {
  mode: "PAPER" | "LIVE";
  indices: Record<string, GammaBlastIndexState>;
};

export type GammaBlastSession = {
  id: string;
  sessionDate: string;
  indexSymbol: string;
  mode: string;
  status: string;
  spotOpen: number | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type GammaBlastRetrospective = {
  sessionId: string;
  sessionDate: string;
  summary: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type GammaBlastSessionDetail = {
  session: GammaBlastSession;
  signals: GammaBlastSignal[];
  trades: GammaBlastTrade[];
  events: GammaBlastEvent[];
  retrospective: GammaBlastRetrospective | null;
};

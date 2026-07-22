export type CreditSpreadLeg = {
  strike: number;
  side: string;
  securityId: string;
  price: number;
};

export type CreditSpreadSelection = {
  spot: number;
  syntheticFuture: number;
  atmStrike: number;
  sell: CreditSpreadLeg;
  hedge: CreditSpreadLeg | null;
  netCredit: number;
  width: number | null;
  creditPercentOfWidth: number | null;
};

export type CreditSpreadEvaluation = {
  at: string;
  expiry: string;
  selection: CreditSpreadSelection;
  vix: number | null;
  blockers: string[];
};

export type CreditSpreadMtm = {
  at: string;
  spot: number | null;
  sellLtp: number | null;
  hedgeLtp: number | null;
  unrealizedPnl: number;
  capturePercent: number | null;
  remainingTradingDays: number | null;
};

export type CreditSpreadPosition = {
  id: string;
  expiry: string;
  mode: "PAPER" | "LIVE";
  status: "OPEN" | "CLOSED";
  qty: number;
  sellStrike: number;
  sellSecurityId: string;
  sellEntryPrice: number;
  hedgeStrike: number | null;
  hedgeSecurityId: string | null;
  hedgeEntryPrice: number | null;
  netCredit: number;
  entrySpot: number | null;
  entrySyntheticFuture: number | null;
  entryVix: number | null;
  plannedExitDate: string | null;
  entrySignalId: number | null;
  entryAt: string;
  sellExitPrice: number | null;
  hedgeExitPrice: number | null;
  exitReason: string | null;
  realizedPnl: number | null;
  exitAt: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type CreditSpreadSignal = {
  id: number;
  kind: "ENTRY" | "EXIT" | string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "FAILED" | "EXPIRED" | string;
  positionId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
};

export type CreditSpreadEvent = {
  id: number;
  eventType: string;
  message: string;
  positionId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
};

export type CreditSpreadConfig = {
  lotSize: number;
  lots: number;
  capitalBase: number;
  entryTime: string;
  entryWindowEnd: string;
  exitTime: string;
  exitTradingDaysBeforeExpiry: number;
  hedgePremiumTarget: number;
  minNetCredit: number;
  minCreditWidthPercent: number;
  maxEntryVix: number;
  profitTargetPercent: number;
  hardStopCreditMultiple: number;
  allowLateEntry: boolean;
  minEntryTradingDaysLeft: number;
  skipDates: string[];
  paperAutoApprove: boolean;
  liveOrderEnabled: boolean;
};

export type CreditSpreadState = {
  strategy: string;
  mode: "PAPER" | "LIVE";
  monitorEnabled: boolean;
  now: string;
  isTradingDay: boolean;
  frontExpiry: string | null;
  seriesStartDate: string | null;
  remainingTradingDays: number | null;
  plannedExitDate: string | null;
  openPosition: CreditSpreadPosition | null;
  mtm: CreditSpreadMtm | null;
  lastEvaluation: CreditSpreadEvaluation | null;
  lastError: string | null;
  pendingSignals: CreditSpreadSignal[];
  positions: CreditSpreadPosition[];
  events: CreditSpreadEvent[];
  config: CreditSpreadConfig;
};

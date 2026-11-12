export interface TurtleConfig {
  enabled: boolean;
  mode?: "paper" | "live"; // Define Turtle A1 only
  liveOrdersAllowed?: boolean;
  broker?: "dhan" | "angel";
  capital: number;
  capitalPerLot: number;
  boxPercent: number;
  reversal: number;
  turtleLookback: number;
  rsiPeriod: number;
  rsiThreshold: number;
  spreadWidth: number;
  strikeRounding: number;
  profitDecayPercent: number;
  calendarExitDays: number;
  lots: number;
  lotSize: number;
  entryRsi?: number; // Define Turtle - Filtered
  trendSmaDays?: number;
  shortOtmPoints?: number;
  bearish?: boolean;
}

export interface PnfColumn {
  index: number;
  type: "X" | "O";
  top: number;
  bottom: number;
  topPrice: number;
  bottomPrice: number;
  start: number;
  end: number;
  turtle: boolean;
  followThrough: boolean;
  rsi: number | null;
}

export interface PnfSignal {
  kind: "turtle_breakout" | "turtle_follow_through" | "strike_back" | "turtle_breakdown" | "turtle_follow_through_bearish";
  time: number;
  column: number;
  price: number;
  rsi: number | null;
}

export interface TurtleTrade {
  id: number;
  side?: "bull" | "bear";
  status: "OPEN" | "CLOSED";
  trigger: string;
  signalTime: number | null;
  signalRsi: number | null;
  entryTime: number;
  expiry: string;
  spot: number;
  lots: number;
  lotSize: number;
  shortStrike: number;
  longStrike: number;
  shortEntry: number;
  longEntry: number;
  creditPoints: number;
  shortExit: number | null;
  longExit: number | null;
  exitTime: number | null;
  exitReason: string | null;
  lastCost: number | null;
  lastDecay: number | null;
  lastRsi: number | null;
  lastUpdate: number | null;
  credit: number;
  maxLoss: number;
  daysToExpiry: number;
  grossPnl: number;
  charges: number;
  netPnl: number;
  mode?: "paper" | "live";
  shortSecurityId?: string | null;
  longSecurityId?: string | null;
  shortOrderId?: string | null;
  longOrderId?: string | null;
  needsAttention?: string | null;
  broker?: "dhan" | "angel" | null;
}

export interface TurtleAlarm {
  id: number;
  createdAt: number;
  kind: string;
  title: string;
  message: string;
  tradeId: number | null;
  acknowledgedAt: number | null;
}

export interface TurtleState {
  error?: string;
  config: TurtleConfig;
  chart?: { columns: PnfColumn[]; signals: PnfSignal[]; rsi: number | null; boxPoints: number | null };
  lastCandle?: { time: number; close: number } | null;
  trend?: "BULLISH" | "NOT_BULLISH" | null;
  lastFollowThrough?: PnfSignal | null;
  nextWeekExpiry?: string | null;
  trendFilter?: { sma: number | null; close: number | null; bull: boolean; bear: boolean; days?: number };
  openTrades: TurtleTrade[];
  alarms: TurtleAlarm[];
  marketOpen: boolean;
}

export interface AngelPosition {
  symbol: string;
  token: string;
  exchange: string;
  product: string;
  netQty: number;
  buyQty: number;
  sellQty: number;
  buyAvg: number | null;
  sellAvg: number | null;
  ltp: number | null;
  pnl: number | null;
}

/** Define Turtle A1's Angel One book, shown on Manage Trades. */
export interface TurtleA1Book {
  configured: boolean;
  mode?: "paper" | "live";
  liveOrdersAllowed?: boolean;
  positions?: AngelPosition[];
  trades?: TurtleTrade[];
  openNet?: number;
  dayPnl?: number;
  error?: string;
}

export interface TurtleConfig {
  enabled: boolean;
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
  kind: "turtle_breakout" | "turtle_follow_through" | "strike_back";
  time: number;
  column: number;
  price: number;
  rsi: number | null;
}

export interface TurtleTrade {
  id: number;
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
  openTrades: TurtleTrade[];
  alarms: TurtleAlarm[];
  marketOpen: boolean;
}

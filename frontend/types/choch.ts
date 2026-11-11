export interface ChochTrade {
  id: number;
  day: string;
  side: 1 | -1;
  status: "OPEN" | "CLOSED";
  entryTime: number;
  entry: number;
  stop: number;
  target: number;
  exitTime: number | null;
  exit: number | null;
  exitReason: string | null;
  points: number;
  lots: number;
  lotSize: number;
  lastPrice: number | null;
  grossPnl: number;
  charges: number;
  netPnl: number;
  params: Record<string, number>;
}

export interface ChochConfig {
  enabled: boolean;
  swing: number;
  stop: number;
  target: number;
  maxTrades: number;
  start: string;
  lastEntry: string;
  flat: string;
  lots: number;
  costPoints: number;
  lotSize: number;
}

export interface ChochState {
  config: ChochConfig;
  marketOpen: boolean;
  error?: string;
  structure?: { trend: number; choch: number | null; swingHigh: number | null; swingLow: number | null; zigzag: string | null; extreme: number | null };
  lastBar?: { time: number; open: number; high: number; low: number; close: number };
  dayParams?: Record<string, number> | null;
  today: ChochTrade[];
  open: ChochTrade[];
  backtest: { period: string; rows: { label: string; result: string; win: string }[]; notes: string };
}

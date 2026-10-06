export type MantraMode = "monthly" | "weekly";

export type MantraConfig = Record<string, number | string | boolean | number[]> & {
  mode: MantraMode;
  enabled: boolean;
  capital: number;
  capitalPerLot: number;
  targetPremium: number;
  minDte: number;
  maxDte: number;
  targetPercent: number;
  stopPercent: number;
  rollLadder: string;
  unstableDte: number;
  lots: number;
  lotSize: number;
  ladder: number[];
};

export interface MantraPlanLeg {
  strike: number;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  delta: number | null;
  iv: number | null;
  oiLots: number;
  fill: number | null;
  liquidityOk: boolean;
  liquidity: string;
  distancePercent: number;
}

export interface MantraPlan {
  error?: string;
  config: MantraConfig;
  monday?: string;
  series?: string;
  dte?: number;
  spot?: number;
  legs?: { CE: MantraPlanLeg; PE: MantraPlanLeg };
  creditPoints?: number;
  credit?: number;
  target?: number;
  stop?: number;
  rollLevels?: number[];
  exitBy?: string;
  liquidityOk?: boolean;
}

export interface MantraLeg {
  id: number;
  optionType: "CE" | "PE";
  strike: number;
  entry: number;
  exit: number | null;
  status: "OPEN" | "CLOSED";
  openedAt: number;
  closedAt: number | null;
  rollNo: number;
  lastLtp: number | null;
  lastBid: number | null;
  lastAsk: number | null;
}

export interface MantraTrade {
  id: number;
  mode: MantraMode;
  trigger: string;
  status: "OPEN" | "CLOSED";
  state: "STRANGLE" | "STRADDLE";
  expiry: string;
  entryTime: number;
  spot: number;
  lots: number;
  lotSize: number;
  creditPoints: number;
  booked: number;
  gross: number | null;
  charges: number;
  rolls: number;
  exitTime: number | null;
  exitReason: string | null;
  lastMtm: number | null;
  lastSpot: number | null;
  lastUpdate: number | null;
  legs: MantraLeg[];
  events: { time: number; kind: string; text: string }[];
  credit: number;
  target: number;
  stop: number;
  nextRollAt: number | null;
  grossPnl: number;
  netPnl: number;
  daysToExpiry: number;
  exitBy: string;
  mtmHistory?: { time: number; mtm: number; spot: number | null }[];
}

export interface MantraAlarm {
  id: number;
  createdAt: number;
  kind: string;
  title: string;
  message: string;
  tradeId: number | null;
  acknowledgedAt: number | null;
}

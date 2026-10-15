import type { VarahaPayoffPoint } from "@/types/varaha";

export interface VarahaPaperConfig {
  enabled: boolean;
  mode: "paper" | "live";
  lots: number;
  butterflyTargetPercent: number;
  butterflyStopPercent: number;
  condorTargetPercent: number;
  condorStopMultiple: number;
  exitTime: string;
  flipExit: boolean;
  maxLossInr: number;
  lotSize: number;
  decisionTime: string;
  liveOrdersAllowed: boolean;
}

export interface VarahaPaperDecision {
  recId: number | null;
  trigger: string | null;
  status: string | null;
  moveClass: string | null;
  moveScore: number | null;
  maxMoveScore: number | null;
  expectedMove: number | null;
  direction: string | null;
  effective: string | null;
  override: string | null;
  bullish: number | null;
  bearish: number | null;
  neutral: number | null;
  bullishConfidence: number | null;
  bearishConfidence: number | null;
  threshold: number | null;
  engineStructure: string | null;
  why?: string;
}

export interface VarahaPaperCandidateLeg {
  action: "BUY" | "SELL";
  qty: number;
  optionType: "CE" | "PE";
  strike: number;
  price: number;
  bid: number | null;
  ask: number | null;
  delta: number | null;
}

export interface VarahaPaperLeg {
  id: number;
  action: "BUY" | "SELL";
  optionType: "CE" | "PE";
  strike: number;
  ratio: number;
  quantity: number;
  securityId: string;
  entryPrice: number | null;
  entryBid: number | null;
  entryAsk: number | null;
  entryLtp: number | null;
  entryOrderId: string | null;
  exitPrice: number | null;
  exitBid: number | null;
  exitAsk: number | null;
  exitLtp: number | null;
  exitOrderId: string | null;
  lastLtp: number | null;
  lastBid: number | null;
  lastAsk: number | null;
  iv: number | null;
  delta: number | null;
  pnl: number | null;
}

export interface VarahaPaperTrade {
  id: number;
  recId: number | null;
  sessionDate: string;
  mode: "paper" | "live";
  trigger: string;
  structure: string;
  structureLabel: string;
  variantLabel: string | null;
  direction: string;
  moveClass: string | null;
  decision: VarahaPaperDecision;
  expiry: string;
  exitBy: number;
  entryTime: number;
  entrySpot: number;
  lots: number;
  lotSize: number;
  entryValue: number;
  premiumType: "DEBIT" | "CREDIT";
  maxProfitPoints: number | null;
  maxLossPoints: number | null;
  breakevens: number[];
  targetPoints: number;
  stopPoints: number;
  status: "OPEN" | "CLOSED";
  exitTime: number | null;
  exitReason: string | null;
  exitValue: number | null;
  exitSpot: number | null;
  lastValue: number | null;
  lastSpot: number | null;
  lastUpdate: number | null;
  bestPoints: number | null;
  worstPoints: number | null;
  needsAttention: string | null;
  pnlPoints: number;
  grossPnl: number;
  charges: number;
  netPnl: number;
  maxProfit: number;
  maxLoss: number;
  target: number;
  stop: number;
  legs: VarahaPaperLeg[];
  marks?: { time: number; pnl_points: number; spot: number | null }[];
  events?: { time: number; kind: string; text: string }[];
  payoff?: VarahaPayoffPoint[];
}

export interface VarahaPaperState {
  config: VarahaPaperConfig;
  now: number;
  marketOpen: boolean;
  mode: "paper" | "live";
  preview: {
    decision: VarahaPaperDecision;
    sessionDate: string;
    structure: string | null;
    structureLabel: string | null;
    why: string;
    candidate: {
      id: string;
      variantLabel: string;
      expiry: string;
      legs: VarahaPaperCandidateLeg[];
      netPremiumPoints: number;
      premiumType: "DEBIT" | "CREDIT";
      maxProfit: number;
      maxLoss: number;
      breakevens: number[];
      lots: number;
      lotSize: number;
      rewardRisk: number | null;
    } | null;
  } | null;
  openTrade: VarahaPaperTrade | null;
  events: { time: number; kind: string; text: string; tradeId: number | null }[];
}

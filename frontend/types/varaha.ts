export type VarahaOverride = "AUTO" | "UP" | "DOWN" | "NO_DIRECTION";
export type VarahaMoveClass = "BIG_MOVE" | "WATCH" | "LOW";
export type VarahaDirection = "UP" | "DOWN" | "NO_CLEAR_DIRECTION";
export type VarahaStatus = "VALID" | "WATCH" | "NO_TRADE";
export type VarahaCheckStatus = "PASS" | "WATCH" | "FAIL";

export interface VarahaMoveComponent {
  key: string;
  label: string;
  score: number;
  max: number;
  value: string;
  detail: string;
}

export interface VarahaMove {
  components: VarahaMoveComponent[];
  moveScore: number;
  maxScore: number;
  classification: VarahaMoveClass;
  bigMoveScore: number;
  watchScore: number;
  expectedMove: number | null;
  atmIv: number | null;
  atr14: number | null;
  emAtrRatio: number | null;
  vix: number | null;
  vixPercentile: number | null;
}

export interface VarahaSignal {
  key: string;
  label: string;
  vote: number | null;
  detail: string;
}

export interface VarahaDirectionAssessment {
  signals: VarahaSignal[];
  bullish: number;
  bearish: number;
  neutral: number;
  bullishConfidence: number;
  bearishConfidence: number;
  threshold: number;
  classification: VarahaDirection;
  manualOverride: VarahaOverride | null;
  effective: VarahaDirection;
}

export interface VarahaLeg {
  action: "BUY" | "SELL";
  qty: number;
  optionType: "CE" | "PE";
  strike: number;
  price: number;
  ltp: number;
  bid: number | null;
  ask: number | null;
  iv: number | null;
  delta: number | null;
  oi: number | null;
  distance: number;
  distancePercent: number;
  emMultiple: number | null;
}

export interface VarahaCheck {
  key: string;
  label: string;
  status: VarahaCheckStatus;
  hard: boolean;
  detail: string;
}

export interface VarahaZone {
  type: "profit" | "loss";
  from: number | null;
  to: number | null;
}

export interface VarahaPayoffPoint {
  price: number;
  expiry: number;
  today: number;
}

export interface VarahaCandidate {
  id: string;
  structure: string;
  structureLabel: string;
  variant: string;
  variantLabel: string;
  expiry: string;
  dte: number;
  tradingDte: number;
  lots: number;
  lotSize: number;
  legs: VarahaLeg[];
  netPremium: number;
  premiumType: "DEBIT" | "CREDIT";
  maxProfit: number;
  maxLoss: number;
  rewardRisk: number | null;
  breakevens: number[];
  zones: VarahaZone[];
  charges: number;
  netDelta: number;
  centralLossWidth: number | null;
  lossWidthEmRatio: number | null;
  checks: VarahaCheck[];
  watchItems: string[];
  fallbackRank: number;
  aiRank?: number;
  aiReason?: string;
  payoff?: VarahaPayoffPoint[];
}

export interface VarahaAiSections {
  marketView: string;
  whyThisStrategy: string;
  keyStrikes: string;
  risk: string;
  expectedMove: string;
  whatCouldGoWrong: string;
  invalidation: string;
  alternative: string;
  overrideComment: string;
}

export interface VarahaResult {
  status: VarahaStatus;
  statusReason: string;
  move: VarahaMove | null;
  direction: VarahaDirectionAssessment | null;
  selectedStructure: string | null;
  selectedStructureLabel: string | null;
  candidates: VarahaCandidate[];
  rejected: { id: string; structureLabel: string; variantLabel: string; expiry: string; reasons: string[] }[];
  rankingSource?: "AI" | "FALLBACK";
  ai?: { source: "AI" | "FALLBACK"; error: string | null; model?: string | null; sections: VarahaAiSections | null };
  topIds?: string[];
  spot: number | null;
  takenAt: number | null;
  marketOpen: boolean;
  warnings: string[];
  expiries: { expiry: string; dte: number; tradingDte: number }[];
  pcr: number | null;
  events: { headline: string; impact: string }[];
  requestedOverride: VarahaOverride;
}

export interface VarahaRecommendation {
  id: number;
  sessionDate: string;
  trigger: "scheduled" | "manual" | "override";
  manualOverride: VarahaOverride | null;
  createdAt: string;
  result: VarahaResult;
}

export interface VarahaConfig {
  lots: number;
  maxLossInr: number;
  lotSize: number;
  decisionTime: string;
  minDte: number;
  maxDte: number;
  bigMoveScore: number;
  watchScore: number;
  directionConfidencePercent: number;
  minRewardRisk: number;
  lossWidthEmTarget: number;
  aiEnabled: boolean;
}

export interface VarahaLatestPayload {
  recommendation: VarahaRecommendation | null;
  override: VarahaOverride;
  config?: VarahaConfig;
}

export interface VarahaHistoryItem {
  id: number;
  sessionDate: string;
  trigger: string;
  createdAt: string;
  status: VarahaStatus | null;
  spot: number | null;
  moveClass: VarahaMoveClass | null;
  moveScore: number | null;
  engineDirection: VarahaDirection | null;
  manualOverride: VarahaOverride | null;
  topCandidate: { structureLabel: string; variantLabel: string; expiry: string; maxProfit: number; maxLoss: number } | null;
  rankingSource: "AI" | "FALLBACK" | null;
}

export interface FullButterflyResult {
  id: string;
  legs: VarahaLeg[];
  netDebit: number;
  netDebitPoints: number;
  maxProfit: number;
  maxLoss: number;
  rewardRisk: number;
  lossWidth: number;
  lossWidthEm: number | null;
  lossZone: [number, number];
  shortDistances: [number, number];
  breakevens: number[];
  zones: VarahaZone[];
  pop: number;
  frontier: boolean;
  wingRatios: [number, number];
  innerWings: [number, number];
  longGap: number;
  charges: number;
  lots: number;
  lotSize: number;
  payoff: VarahaPayoffPoint[];
}

export interface FullButterflyScan {
  error?: string;
  spot: number;
  forward: number;
  expectedMove: number | null;
  atmIv: number | null;
  expiry: { expiry: string; dte: number; tradingDte: number };
  expiries: { expiry: string; dte: number; tradingDte: number }[];
  shortRangePoints: [number, number | null];
  quotesAt: number;
  marketOpen: boolean;
  lots: number;
  lotSize: number;
  maxLossLimitInr: number;
  scanned: number;
  matched: number;
  frontierCount: number;
  results: FullButterflyResult[];
  scatter: { width: number; rr: number; frontier: boolean }[];
  warnings: string[];
}

export interface FullButterflyFilters {
  expiry?: string;
  symmetric: boolean;
  longPlacement: "any" | "adjacent" | "atm";
  centered: boolean;
  minShortEm?: number;
  maxShortEm?: number;
  maxWidth?: number;
  maxWidthEm?: number;
  maxLossInr?: number;
  minRr?: number;
  minMaxProfitInr?: number;
  minPop?: number;
  wingRatioMin: number;
  wingRatioMax: number;
  requireLiquid: boolean;
  frontierOnly: boolean;
  sort: "width" | "rr" | "pop" | "maxLoss" | "maxProfit";
}

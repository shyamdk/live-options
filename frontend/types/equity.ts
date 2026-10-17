export type EquityFundamentals = {
  symbol: string;
  source: string;
  url?: string | null;
  warning?: string | null;
  pe?: number | null;
  medianPe?: number | null;
  industryPe?: number | null;
  roce?: number | null;
  roe?: number | null;
  debtToEquity?: number | null;
  salesGrowth3y?: number | null;
  profitGrowth3y?: number | null;
  promoterHolding?: number | null;
  pledge?: number | null;
  marketCap?: number | null;
  dividendYield?: number | null;
  cachedAt?: string;
};

export type EquityTechnicals = {
  source: string;
  close?: number | null;
  sma20?: number | null;
  sma50?: number | null;
  sma200?: number | null;
  sma200Rising?: boolean | null;
  rsi14?: number | null;
  fiftyTwoWeekHigh?: number | null;
  fiftyTwoWeekLow?: number | null;
  candleCount?: number;
  warning?: string | null;
  cachedAt?: string;
};

export type EquityNewsHeadline = {
  title: string;
  source?: string;
  url?: string;
  date?: string;
  impact?: string;
};

export type EquityNewsItem = {
  symbol: string;
  source: string;
  sentiment: "positive" | "neutral" | "negative" | "mixed" | string;
  summary: string;
  headlines: EquityNewsHeadline[];
  risks: string[];
  sources: Array<{ url: string; title: string }>;
  updatedAt?: string;
  cachedAt?: string;
  warning?: string | null;
};

export type EquityRecommendation = {
  symbol: string;
  score: number;
  grade: string;
  action: string;
  reasons: string[];
  risks: string[];
  longTermGates?: Array<{ key: string; label: string; passed: boolean; detail: string }>;
  guruSignals: Array<{ name: string; status: "pass" | "watch" | string; detail: string }>;
};

export type EquityEntrySignal = {
  state: "BUY_ZONE" | "ADD_ZONE" | "BLOCKED" | "NEUTRAL" | "NOT_QUALITY" | "NO_DATA" | string;
  label: string;
  reasons: string[];
  blocks: string[];
  rsi?: number | null;
  sma200?: number | null;
  buyBelow?: number | null;
  distanceToSma200Percent?: number | null;
  lastBuy?: { date: string; price?: number | null } | null;
  nextAddBelow?: number | null;
  deep?: boolean;
};

export type EquityHolding = {
  id: string;
  exchange?: string | null;
  exchangeSegment?: string | null;
  tradingSymbol?: string | null;
  symbol: string;
  securityId: string;
  isin?: string | null;
  totalQty: number;
  dpQty: number;
  t1Qty: number;
  availableQty: number;
  collateralQty: number;
  avgCostPrice?: number | null;
  investedValue?: number | null;
  ltp?: number | null;
  quoteSource?: "dhan_quote" | "technical_close" | string;
  marketValue?: number | null;
  pnl?: number | null;
  pnlPercent?: number | null;
  exposurePercent?: number | null;
  fundamentals: EquityFundamentals;
  technicals: EquityTechnicals;
  news: EquityNewsItem;
  recommendation: EquityRecommendation;
  entrySignal?: EquityEntrySignal;
};

export type EquityPortfolioPayload = {
  source: string;
  updatedAt: string;
  warning?: string | null;
  count: number;
  summary: {
    totalInvested: number;
    marketValue: number;
    pnl: number;
    pnlPercent?: number | null;
    potentialBuyCount: number;
    reviewCount: number;
    entrySignals?: Record<string, number>;
  };
  data: EquityHolding[];
};

export type EquityTransaction = {
  id: string;
  orderId?: string | null;
  exchangeOrderId?: string | null;
  exchangeTradeId?: string | null;
  transactionType: "BUY" | "SELL" | string;
  exchangeSegment?: string | null;
  productType?: string | null;
  orderType?: string | null;
  tradingSymbol?: string | null;
  customSymbol?: string | null;
  symbol: string;
  securityId: string;
  isin?: string | null;
  instrument?: string | null;
  quantity: number;
  price?: number | null;
  value?: number | null;
  charges?: number | null;
  createTime?: string | null;
  updateTime?: string | null;
  exchangeTime?: string | null;
};

export type EquityTransactionsPayload = {
  source: string;
  warning?: string | null;
  fromDate: string;
  toDate: string;
  updatedAt: string;
  count: number;
  summary: {
    buyValue: number;
    sellValue: number;
    netCashFlow: number;
    charges: number;
    buyCount: number;
    sellCount: number;
  };
  data: EquityTransaction[];
};

export type EquityNewsPayload = {
  source: string;
  updatedAt: string;
  count: number;
  data: EquityNewsItem[];
};

export type EquityOptionsPeriodBucket = {
  trades: number;
  buyValue: number;
  sellValue: number;
  charges: number;
  grossPnl: number;
};

export type EquityOptionsPeriod = EquityOptionsPeriodBucket & {
  period: string;
  byUnderlying: Record<string, EquityOptionsPeriodBucket>;
};

export type EquityOptionsReportPayload = {
  monthly: EquityOptionsPeriod[];
  yearly: EquityOptionsPeriod[];
  totals: EquityOptionsPeriodBucket;
  count: number;
};

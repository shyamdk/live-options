export interface DishaStatement {
  text: string;
  n: number;
  rate: number;
  avgPts: number;
  medianPts: number;
  byYear: Record<string, { n: number; rate: number }>;
}

export interface DishaSituation {
  label: string;
  n: number;
  statements: DishaStatement[];
}

export interface DishaBaseRates {
  generatedAt: string;
  days: number;
  from: string;
  to: string;
  orWidthMedianBps: number;
  note: string;
  situations: Record<string, DishaSituation>;
}

export interface DishaState {
  asOf: number;
  day: string;
  errors: string[];
  marketOpen: boolean;
  spot: { time: number; close: number }[];
  last: number | null;
  open: number | null;
  prevClose: number | null;
  gapPts: number | null;
  gapBps: number | null;
  fromOpenPts: number | null;
  move930Bps: number | null;
  openingRange: { high: number; low: number; widthPts: number; widthBps: number | null; narrow: boolean | null; complete: boolean } | null;
  breakout: { side: "up" | "down"; time: number; level: number; distancePts: number } | null;
  vix: { now: number | null; prev: number | null; change: number | null };
  oi: { ceAdded: number; peAdded: number; pcrOpen: number | null; pcrNow: number | null; since: number; asOf: number } | null;
  matches: string[];
  baseRates: DishaBaseRates | null;
}

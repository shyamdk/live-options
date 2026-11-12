export interface OrderFlowMinute {
  minute_ts: number;
  label: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  buy_vol: number;
  sell_vol: number;
  book_buy: number;
  book_sell: number;
  bid_qty: number;
  ask_qty: number;
  spread: number | null;
  oi: number;
}

export interface OrderFlowState {
  recording: { connected: boolean; packets: number; centre: number | null; day: string | null; error: string | null };
  secondsSincePacket: number | null;
  instruments: { securityId: string; label: string; kind: string }[];
  days: { day: string; minutes: number; instruments: number; volume: number }[];
  today: {
    minutes: number;
    futures: { time: number; close: number; delta: number; cumDelta: number; bookImbalance: number | null }[];
    byKind: Record<string, { buy: number; sell: number; volume: number }>;
    lastFutures: OrderFlowMinute[];
  };
}

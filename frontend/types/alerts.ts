export type PortalAlert = {
  id: number;
  kind: "price" | "reminder";
  symbol?: string | null;
  securityId?: string | null;
  segment?: string | null;
  direction?: "below" | "above" | null;
  price?: number | null;
  remindAt?: number | null;
  note?: string | null;
  source: string;
  status: "active" | "triggered" | "acknowledged" | "dismissed";
  createdAt: number;
  triggeredAt?: number | null;
  triggerPrice?: number | null;
  telegramSent?: boolean | null;
  acknowledgedAt?: number | null;
};

export type TelegramStatus = {
  tokenSet: boolean;
  botUsername?: string | null;
  chatIdSource?: "env" | "remembered" | null;
  lastOk?: boolean | null;
  lastAt?: number | null;
  lastError?: string | null;
};

export type AlertsPayload = {
  active: PortalAlert[];
  pending: PortalAlert[];
  history: PortalAlert[];
  telegram: TelegramStatus;
};

export type NewAlert = {
  kind: "price" | "reminder";
  symbol?: string;
  securityId?: string;
  segment?: string;
  direction?: "below" | "above";
  price?: number;
  remindAt?: number;
  note?: string;
  source?: string;
};

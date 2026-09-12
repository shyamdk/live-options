export interface DeltaWalletBalance {
  asset_symbol?: string;
  asset?: { symbol?: string };
  balance?: string | number;
  available_balance?: string | number;
}

export interface CryptoSwingWallet {
  connected: boolean;
  error: string | null;
  balances: DeltaWalletBalance[];
}

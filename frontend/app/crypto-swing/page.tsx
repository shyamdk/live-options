"use client";

import { Bitcoin, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { getCryptoSwingWallet } from "@/lib/api";
import type { CryptoSwingWallet } from "@/types/crypto-swing";

function assetLabel(row: CryptoSwingWallet["balances"][number]): string {
  return row.asset_symbol ?? row.asset?.symbol ?? "?";
}

function fmtAmount(value: string | number | undefined): string {
  if (value === undefined || value === null) return "—";
  const num = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(num) ? num.toLocaleString("en-IN", { maximumFractionDigits: 8 }) : String(value);
}

export default function CryptoSwingPage() {
  const [wallet, setWallet] = useState<CryptoSwingWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setWallet(await getCryptoSwingWallet());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Delta Exchange wallet.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const nonZero = wallet?.balances.filter((row) => Number(row.balance ?? 0) !== 0) ?? [];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Bitcoin size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Crypto-Swing
          </h1>
          <p>Delta Exchange India connectivity and account funds. Strategy execution isn&apos;t wired up yet -- this confirms the connection and shows what capital is available to trade.</p>
        </div>
        <div className="toolbar">
          <button type="button" className="button secondary" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Checking…" : "Refresh"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      {wallet && !wallet.connected ? (
        <div className="alert error">
          Not connected to Delta Exchange: {wallet.error}
          {wallet.error?.includes("ip_not_whitelisted") ? " -- whitelist this server's IP under the Delta Exchange API key settings." : ""}
        </div>
      ) : null}

      {wallet?.connected ? (
        <div className="pcr-oi-section">
          <h3>Wallet balances</h3>
          {nonZero.length === 0 ? (
            <p className="pcr-oi-caption">Connected, but every asset balance is currently zero.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Balance</th>
                    <th>Available</th>
                  </tr>
                </thead>
                <tbody>
                  {nonZero.map((row) => (
                    <tr key={assetLabel(row)}>
                      <td>{assetLabel(row)}</td>
                      <td>{fmtAmount(row.balance)}</td>
                      <td>{fmtAmount(row.available_balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

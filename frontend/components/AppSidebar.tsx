"use client";

import {
  Compass,
  BookOpenText,
  Moon,
  Infinity as InfinityIcon,
  BellRing,
  Droplets,
  TrendingUp,
  Spline,
  Waves,
  Turtle,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Lightbulb,
  RadioTower,
  Shapes,
  WalletCards,
  NotebookPen,
  Grid3x3,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

// Two different kinds of "archived" have accumulated here:
// 1. Gamma Blast, ema5, animesh-scalping, BN Credit Spread, Theta Book, and
//    OI Analysis: nav-hidden only -- pages/routes/background monitors still
//    exist and run (see .env's *_MONITOR_ENABLED flags; OI Analysis has none
//    of its own, since its pcr_oi feed is shared with OI Upgraded/OI
//    Improvements, which stay active). Re-add the entry + flip the flag to
//    unarchive. Also Simple Cross Over, BTC Strangle and BTC Calm Strangle
//    (Nov 2026: no edge in backtests or paper) -- their monitors are off
//    (SIMPLE_CROSSOVER_MONITOR_ENABLED / btc_strangle_monitor_enabled default;
//    BTC Calm's auto entry is off, so its monitor idles); pages keep the history.
// 2. Crypto-Swing, pStrategy, Nifty-Swing, pStrategy-Nifty, PE-CE Crossover:
//    physically moved to /archive at the repo root -- no page, no route, no
//    background monitor exists in the running app at all. Unarchiving means
//    moving the files back (see archive/README.md), not just adding a nav
//    entry.
const navItems = [
  { href: "/manage-trades", label: "Manage Trades", short: "MT", icon: BriefcaseBusiness },
  { href: "/alerts", label: "Alerts & Reminders", short: "AL", icon: BellRing },
  { href: "/notes", label: "Notes", short: "NO", icon: NotebookPen },
  { href: "/equity", label: "Equity", short: "EQ", icon: WalletCards },
  { href: "/equity-swing", label: "Equity-Swing", short: "ES", icon: TrendingUp },
  { href: "/trade-journals", label: "Trade Journals", short: "TJ", icon: BookOpenText },
  { href: "/disha", label: "Disha - NM", short: "DI", icon: Compass },
  { href: "/oi-upgraded", label: "OI - Upgraded", short: "OU", icon: RadioTower },
  { href: "/oi-improvements", label: "OI Improvements", short: "IM", icon: Lightbulb },
  { href: "/varaha", label: "Varaha", short: "VA", icon: Shapes },
  { href: "/nifty-strangle", label: "NIFTY Strangle", short: "NS", icon: Spline },
  { href: "/calm-strangle", label: "Calm Strangle", short: "CS", icon: Waves },
  { href: "/calm-strangle-or", label: "Calm Strangle - OR", short: "CO", icon: Waves },
  { href: "/batman", label: "Batman", short: "BM", icon: Moon },
  { href: "/define-turtle", label: "Define Turtle", short: "DT", icon: Turtle },
  { href: "/define-turtle-a1", label: "Define Turtle A1", short: "A1", icon: Turtle },
  { href: "/pf-lab", label: "P&F Lab", short: "PF", icon: Grid3x3 },
  { href: "/pf-lab/nifty/short", label: "PF NIFTY · Short", short: "NS", icon: Grid3x3 },
  { href: "/pf-lab/nifty/medium", label: "PF NIFTY · Medium", short: "NM", icon: Grid3x3 },
  { href: "/pf-lab/nifty/long", label: "PF NIFTY · Long", short: "NL", icon: Grid3x3 },
  { href: "/pf-lab/btc/short", label: "PF BTC · Short", short: "BS", icon: Grid3x3 },
  { href: "/pf-lab/btc/medium", label: "PF BTC · Medium", short: "BM", icon: Grid3x3 },
  { href: "/pf-lab/btc/long", label: "PF BTC · Long", short: "BL", icon: Grid3x3 },
  { href: "/pf-lab/gold/short", label: "PF Gold · Short", short: "GS", icon: Grid3x3 },
  { href: "/pf-lab/gold/medium", label: "PF Gold · Medium", short: "GM", icon: Grid3x3 },
  { href: "/pf-lab/gold/long", label: "PF Gold · Long", short: "GL", icon: Grid3x3 },
  { href: "/mantra-theta-gainers", label: "Mantra - Theta Gainers", short: "MT", icon: InfinityIcon },
  { href: "/melting-straddles", label: "Melting Straddles", short: "MS", icon: Droplets },
  { href: "/melting-straddles-gap", label: "Melting Straddles - Gap", short: "MG", icon: Droplets },
];

const STORAGE_KEY = "live-options-sidebar-collapsed";

export default function AppSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark">L</span>
        <span className="brand-name">Live Options</span>
        <button className="icon-button sidebar-toggle" type="button" title={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleCollapsed}>
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
      </div>
      <nav className="nav-tabs" aria-label="Primary navigation">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link key={item.href} href={item.href} title={item.label} className={active ? "active" : ""}>
              <span className="nav-icon">
                <Icon size={17} />
              </span>
              <span className="nav-short">{item.short}</span>
              <span className="nav-label">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}


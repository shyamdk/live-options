"use client";

import {
  Bitcoin,
  BookOpenText,
  Moon,
  Infinity as InfinityIcon,
  Droplets,
  Turtle,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Lightbulb,
  RadioTower,
  Shapes,
  WalletCards,
  Waypoints,
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
//    unarchive.
// 2. Crypto-Swing, pStrategy, Nifty-Swing, pStrategy-Nifty, PE-CE Crossover:
//    physically moved to /archive at the repo root -- no page, no route, no
//    background monitor exists in the running app at all. Unarchiving means
//    moving the files back (see archive/README.md), not just adding a nav
//    entry.
const navItems = [
  { href: "/manage-trades", label: "Manage Trades", short: "MT", icon: BriefcaseBusiness },
  { href: "/equity", label: "Equity", short: "EQ", icon: WalletCards },
  { href: "/trade-journals", label: "Trade Journals", short: "TJ", icon: BookOpenText },
  { href: "/oi-upgraded", label: "OI - Upgraded", short: "OU", icon: RadioTower },
  { href: "/oi-improvements", label: "OI Improvements", short: "IM", icon: Lightbulb },
  { href: "/simple-crossover", label: "Simple Cross Over", short: "SC", icon: Waypoints },
  { href: "/varaha", label: "Varaha", short: "VA", icon: Shapes },
  { href: "/btc-strangle", label: "BTC Strangle", short: "BS", icon: Bitcoin },
  { href: "/batman", label: "Batman", short: "BM", icon: Moon },
  { href: "/define-turtle", label: "Define Turtle", short: "DT", icon: Turtle },
  { href: "/mantra-theta-gainers", label: "Mantra - Theta Gainers", short: "MT", icon: InfinityIcon },
  { href: "/melting-straddles", label: "Melting Straddles", short: "MS", icon: Droplets },
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


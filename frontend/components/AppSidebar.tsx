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
  ChevronDown,
  Menu,
  X,
  Crosshair,
  Activity,
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
  { href: "/nifty-strangle-hedged", label: "NIFTY Strangle - Hedged", short: "NH", icon: Spline },
  { href: "/calm-strangle", label: "Calm Strangle", short: "CS", icon: Waves },
  { href: "/calm-strangle-or", label: "Calm Strangle - OR", short: "CO", icon: Waves },
  { href: "/batman", label: "Batman", short: "BM", icon: Moon },
  { href: "/define-turtle", label: "Define Turtle", short: "DT", icon: Turtle },
  { href: "/define-turtle-a1", label: "Define Turtle A1", short: "A1", icon: Turtle },
  { href: "/choch-1min", label: "1-Min CHoCH", short: "CH", icon: Crosshair },
  { href: "/order-flow", label: "Order Flow (recording)", short: "OF", icon: Activity },
  { href: "/pf-lab", label: "Overview", short: "PF", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/nifty/short", label: "NIFTY · Short", short: "NS", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/nifty/medium", label: "NIFTY · Medium", short: "NM", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/nifty/long", label: "NIFTY · Long", short: "NL", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/btc/short", label: "BTC · Short", short: "BS", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/btc/medium", label: "BTC · Medium", short: "BM", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/btc/long", label: "BTC · Long", short: "BL", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/gold/short", label: "Gold · Short", short: "GS", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/gold/medium", label: "Gold · Medium", short: "GM", icon: Grid3x3, group: "pf" },
  { href: "/pf-lab/gold/long", label: "Gold · Long", short: "GL", icon: Grid3x3, group: "pf" },
  { href: "/mantra-theta-gainers", label: "Mantra - Theta Gainers", short: "MT", icon: InfinityIcon },
  { href: "/melting-straddles", label: "Melting Straddles", short: "MS", icon: Droplets },
  { href: "/melting-straddles-gap", label: "Melting Straddles - Gap", short: "MG", icon: Droplets },
];

// Folders in the nav: items with a matching `group` render inside a collapsible
// entry, closed by default (opened automatically while one of its pages is shown).
const NAV_GROUPS: Record<string, { label: string; short: string; icon: typeof Grid3x3 }> = {
  pf: { label: "P&F Lab", short: "PF", icon: Grid3x3 },
};

const STORAGE_KEY = "live-options-sidebar-collapsed";
const GROUP_KEY = "live-options-sidebar-groups";

function isActive(pathname: string, href: string, exact: boolean): boolean {
  return pathname === href || (!exact && pathname.startsWith(`${href}/`));
}

export default function AppSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  // phones: the menu is a drawer behind a Menu button (closed after each navigation)
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => setMobileOpen(false), [pathname]);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  useEffect(() => {
    try {
      setOpenGroups(JSON.parse(window.localStorage.getItem(GROUP_KEY) || "{}"));
    } catch {
      // storage blocked: groups just start closed
    }
  }, []);

  function toggleGroup(group: string, open: boolean) {
    setOpenGroups((current) => {
      const next = { ...current, [group]: open };
      try {
        window.localStorage.setItem(GROUP_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  }

  function renderLink(item: (typeof navItems)[number], nested: boolean) {
    const Icon = item.icon;
    return (
      <Link key={item.href} href={item.href} title={item.label} className={`${isActive(pathname, item.href, nested) ? "active" : ""} ${nested ? "nav-nested" : ""}`}>
        <span className="nav-icon">
          <Icon size={nested ? 15 : 17} />
        </span>
        <span className="nav-short">{item.short}</span>
        <span className="nav-label">{item.label}</span>
      </Link>
    );
  }

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""} ${mobileOpen ? "mobile-open" : ""}`}>
      <div className="brand">
        <span className="brand-mark">L</span>
        <span className="brand-name">Live Options</span>
        <button className="icon-button sidebar-toggle" type="button" title={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleCollapsed}>
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
        <button className="button secondary mobile-menu-button" type="button" aria-expanded={mobileOpen} onClick={() => setMobileOpen((o) => !o)}>
          {mobileOpen ? <X size={16} /> : <Menu size={16} />} {mobileOpen ? "Close" : "Menu"}
        </button>
      </div>
      <nav className="nav-tabs" aria-label="Primary navigation">
        {navItems.map((item, index) => {
          const group = "group" in item ? (item.group as string) : null;
          if (group && index > 0 && "group" in navItems[index - 1] && navItems[index - 1].group === group) return null;
          if (group) {
            const children = navItems.filter((x) => "group" in x && x.group === group);
            const meta = NAV_GROUPS[group];
            const inside = children.some((x) => isActive(pathname, x.href, true));
            const open = openGroups[group] ?? inside;
            const GroupIcon = meta.icon;
            return (
              <div key={`group-${group}`} className="nav-group">
                <button type="button" className={`nav-group-toggle ${inside && !open ? "active" : ""}`} onClick={() => toggleGroup(group, !open)}
                  title={meta.label} aria-expanded={open}>
                  <span className="nav-icon">
                    <GroupIcon size={17} />
                  </span>
                  <span className="nav-short">{meta.short}</span>
                  <span className="nav-label">{meta.label}</span>
                  <span className="nav-chevron">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                </button>
                {open ? (
                  <div className="nav-group-items">
                    {children.map((child) => renderLink(child, true))}
                  </div>
                ) : null}
              </div>
            );
          }
          return renderLink(item, false);
        })}
      </nav>
    </aside>
  );
}


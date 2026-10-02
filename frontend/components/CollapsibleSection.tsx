"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

// A pcr-oi-section card whose body collapses; the open/closed choice is
// remembered per section id in this browser (localStorage may be blocked --
// then it just isn't remembered).
export default function CollapsibleSection({
  id,
  title,
  aside,
  defaultOpen = true,
  children,
}: {
  id: string;
  title: React.ReactNode;
  aside?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const storageKey = `section-expanded:${id}`;
  const [expanded, setExpanded] = useState(defaultOpen);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw !== null) setExpanded(raw === "1");
    } catch {
      // ignore
    }
  }, [storageKey]);
  function toggle() {
    setExpanded((current) => {
      try {
        window.localStorage.setItem(storageKey, current ? "0" : "1");
      } catch {
        // ignore
      }
      return !current;
    });
  }
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flexWrap: "wrap" }} onClick={toggle}>
        <button className="icon-button" type="button" aria-expanded={expanded} title={expanded ? "Collapse" : "Expand"}>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        <h3 style={{ margin: 0 }}>{title}</h3>
        {aside ? (
          <div style={{ marginLeft: "auto" }} onClick={(event) => event.stopPropagation()}>
            {aside}
          </div>
        ) : null}
      </div>
      {expanded ? <div style={{ marginTop: 10 }}>{children}</div> : null}
    </div>
  );
}

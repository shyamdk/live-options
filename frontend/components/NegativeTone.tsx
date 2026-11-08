"use client";

import { useEffect } from "react";

/**
 * Platform rule: a negative figure is always shown in red.
 *
 * Prices and premiums are never negative, so any element whose whole text is a
 * negative number (−₹1,234 · -$3.54 · ₹-120 · −2.4% · -0.35) is a loss, a P&L
 * or a drop. This watches the page and gives such elements the `auto-negative`
 * class (and removes it when the value turns positive), so every page -- old
 * and new -- follows the rule without each one remembering to colour its
 * numbers. Figures inside a longer sentence are not matched; pages render those
 * as separate pieces.
 */
const NEGATIVE = /^\(?\s*(?:[−-]\s?(?:₹|\$|Rs\.?\s?)?|(?:₹|\$|Rs\.?\s?)[−-]\s?)\d[\d,]*(?:\.\d+)?\s*(?:%|pts?|L|Cr|k|K)?\s*\)?$/;
const SKIP = new Set(["INPUT", "TEXTAREA", "SELECT", "OPTION", "SCRIPT", "STYLE", "CODE", "PRE"]);

function evaluate(el: Element) {
  if (SKIP.has(el.tagName) || el.closest("[data-no-auto-negative]")) return;
  // leaf-like elements only: every child is text (a figure split by React into several text nodes still counts)
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType !== Node.TEXT_NODE) {
      el.classList.remove("auto-negative");
      return;
    }
  }
  const text = (el.textContent || "").trim();
  if (text && text.length < 32 && NEGATIVE.test(text) && /[1-9]/.test(text)) el.classList.add("auto-negative");
  else el.classList.remove("auto-negative");
}

function scan(root: Node, deep = true) {
  if (root.nodeType === Node.TEXT_NODE) {
    if (root.parentElement) evaluate(root.parentElement);
    return;
  }
  if (!(root instanceof Element)) return;
  evaluate(root);
  if (deep) root.querySelectorAll("*").forEach((el) => evaluate(el));
}

export default function NegativeTone() {
  useEffect(() => {
    let pending = new Set<Node>();
    let classOnly = new Set<Node>(); // class changed: re-check that element only
    let frame = 0;
    const flush = () => {
      frame = 0;
      const nodes = pending;
      pending = new Set();
      nodes.forEach((n) => scan(n, !classOnly.has(n)));
      classOnly = new Set();
    };
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === "attributes") {
          pending.add(m.target);
          classOnly.add(m.target);
        } else if (m.type === "characterData") pending.add(m.target);
        else {
          m.addedNodes.forEach((n) => pending.add(n));
          pending.add(m.target);
        }
      }
      if (!frame) frame = window.setTimeout(flush, 30); // a timer, not rAF: keeps working in background tabs
    });
    scan(document.body);
    // class changes too: React rewriting className would otherwise drop the marker
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class"] });
    return () => {
      observer.disconnect();
      if (frame) window.clearTimeout(frame);
    };
  }, []);
  return null;
}

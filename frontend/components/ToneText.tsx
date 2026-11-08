import { Fragment } from "react";

// Negative amounts inside running text ("booked ₹1,200 · net −₹340") -- the
// platform rule (components/NegativeTone.tsx) only reaches figures that stand
// alone, so captions that mix several figures render through this.
const TOKEN = /([−-]\s?(?:₹|\$)\s?\d[\d,]*(?:\.\d+)?|(?:₹|\$)\s?[−-]\s?\d[\d,]*(?:\.\d+)?|[−-]\d[\d,]*(?:\.\d+)?%)/g;

export default function ToneText({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const parts = text.split(TOKEN);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 && /[1-9]/.test(part) ? (
          <span key={i} style={{ color: "var(--red)" }}>
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

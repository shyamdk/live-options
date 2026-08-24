"use client";

import { Bot, RotateCcw, Send, X } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { askAssistant } from "@/lib/api";
import type { ChatMessage } from "@/types/live";

const GREETING: ChatMessage = {
  role: "assistant",
  content:
    "Hi — ask me about your current P&L/positions, or NIFTY/SENSEX PCR, OI, VIX, IV, and whether the upgraded signal engine is currently calling a CE or PE. I'm read-only: I can't place, modify, or close any order myself.",
};

export default function AssistantChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;
    const history = messages.filter((m) => m !== GREETING);
    const nextMessages = [...messages, { role: "user", content: question } as ChatMessage];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const { answer } = await askAssistant(question, history);
      setMessages((current) => [...current, { role: "assistant", content: answer }]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to reach the assistant.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setMessages([GREETING]);
    setError(null);
  }

  return (
    <div className="assistant-widget">
      {open ? (
        <div className="assistant-panel">
          <div className="assistant-panel-head">
            <span>
              <Bot size={16} /> Live Options Assistant
            </span>
            <div className="row-actions">
              <button className="icon-button" type="button" title="New chat" onClick={handleReset}>
                <RotateCcw size={14} />
              </button>
              <button className="icon-button" type="button" title="Close" onClick={() => setOpen(false)}>
                <X size={14} />
              </button>
            </div>
          </div>
          <div className="assistant-messages" ref={listRef}>
            {messages.map((message, index) => (
              <div key={index} className={`assistant-message ${message.role}`}>
                {message.content}
              </div>
            ))}
            {loading ? <div className="assistant-message assistant pending">Thinking…</div> : null}
          </div>
          {error ? <div className="alert error assistant-error">{error}</div> : null}
          <form className="assistant-input-row" onSubmit={handleSubmit}>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="e.g. should I buy CE or PE right now?"
              disabled={loading}
            />
            <button className="icon-button approve" type="submit" title="Send" disabled={loading || !input.trim()}>
              <Send size={15} />
            </button>
          </form>
          <p className="pcr-oi-caption assistant-caption">
            Advisory only, reads live app data -- never places or changes an order.
          </p>
        </div>
      ) : null}
      <button className="assistant-fab" type="button" title="Ask the assistant" onClick={() => setOpen((v) => !v)}>
        <Bot size={20} />
      </button>
    </div>
  );
}

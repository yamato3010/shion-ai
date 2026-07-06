import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  streaming: string;
  busy: boolean;
  error: string | null;
  runningTool: string | null;
  onSend: (text: string) => void;
}

export default function ChatWindow({
  messages,
  streaming,
  busy,
  error,
  runningTool,
  onSend,
}: Props) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    onSend(text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <main className="chat-window">
      <div className="message-scroll" ref={scrollRef}>
        {messages.length === 0 && !streaming && (
          <div className="chat-empty">
            <p>紫桜に話しかけてみよう🌸</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={m.id ?? `local-${i}`} className={`bubble-row ${m.role}`}>
            <div className="bubble">{m.content}</div>
          </div>
        ))}
        {streaming && (
          <div className="bubble-row assistant">
            <div className="bubble is-streaming">{streaming}</div>
          </div>
        )}
        {runningTool && (
          <div className="tool-status-line">🔧 {runningTool} を実行中…</div>
        )}
        {busy && !streaming && !runningTool && (
          <div className="bubble-row assistant">
            <div className="bubble typing-indicator">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        {error && <div className="chat-error">エラー: {error}</div>}
      </div>
      <form className="input-bar" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="メッセージを入力…(Enterで送信 / Shift+Enterで改行)"
          rows={2}
        />
        <button type="submit" disabled={busy || input.trim().length === 0}>
          送信
        </button>
      </form>
    </main>
  );
}

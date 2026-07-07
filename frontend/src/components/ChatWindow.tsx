import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  streaming: string;
  busy: boolean;
  error: string | null;
  runningTool: string | null;
  onSend: (text: string) => void;
  voiceUsable: boolean;
  voiceOn: boolean;
  onToggleVoice: () => void;
}

// Web Speech API(Chrome / Edge / Safari の webkit 実装)
const SpeechRecognitionImpl =
  (window as unknown as Record<string, unknown>).SpeechRecognition ??
  (window as unknown as Record<string, unknown>).webkitSpeechRecognition;

export default function ChatWindow({
  messages,
  streaming,
  busy,
  error,
  runningTool,
  onSend,
  voiceUsable,
  voiceOn,
  onToggleVoice,
}: Props) {
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const inputBeforeMicRef = useRef("");

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  useEffect(() => () => recognitionRef.current?.abort?.(), []);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    recognitionRef.current?.abort?.();
    setInput("");
    onSend(text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const toggleMic = () => {
    if (listening) {
      recognitionRef.current?.stop?.();
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const recognition = new (SpeechRecognitionImpl as any)();
    recognition.lang = "ja-JP";
    recognition.interimResults = true;
    recognition.continuous = false;
    inputBeforeMicRef.current = input;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (e: any) => {
      let transcript = "";
      for (const result of e.results) transcript += result[0].transcript;
      const base = inputBeforeMicRef.current;
      setInput(base ? `${base} ${transcript}` : transcript);
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
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
        {voiceUsable && (
          <button
            type="button"
            className={`icon-button ${voiceOn ? "is-on" : ""}`}
            title={voiceOn ? "読み上げON(VOICEVOX)" : "読み上げOFF"}
            onClick={onToggleVoice}
          >
            {voiceOn ? "🔊" : "🔇"}
          </button>
        )}
        {Boolean(SpeechRecognitionImpl) && (
          <button
            type="button"
            className={`icon-button ${listening ? "is-listening" : ""}`}
            title={listening ? "録音停止" : "音声入力"}
            onClick={toggleMic}
          >
            🎤
          </button>
        )}
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            listening ? "聞き取り中…🎤" : "メッセージを入力…(Enterで送信 / Shift+Enterで改行)"
          }
          rows={2}
        />
        <button type="submit" disabled={busy || input.trim().length === 0}>
          送信
        </button>
      </form>
    </main>
  );
}

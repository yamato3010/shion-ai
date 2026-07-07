import { MutableRefObject, useCallback, useEffect, useRef, useState } from "react";
import {
  deleteConversation,
  getMessages,
  getVoiceStatus,
  listConversations,
  synthesizeSpeech,
} from "../api/client";
import { ChatSocket } from "../api/ws";
import type { ChatMessage, Conversation, Emotion, ServerEvent } from "../types";
import CharacterView from "./CharacterView";
import ChatWindow from "./ChatWindow";
import Sidebar from "./Sidebar";

interface Props {
  socketRef: MutableRefObject<ChatSocket | null>;
  chatHandlerRef: MutableRefObject<((ev: ServerEvent) => void) | null>;
}

export default function ChatPage({ socketRef, chatHandlerRef }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [emotion, setEmotion] = useState<Emotion>("normal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningTool, setRunningTool] = useState<string | null>(null);
  const streamingRef = useRef("");

  // 音声(VOICEVOX)。バックエンドで無効なら null のままボタンごと非表示
  const [voiceUsable, setVoiceUsable] = useState(false);
  const [voiceOn, setVoiceOn] = useState(() => localStorage.getItem("shion-voice") === "on");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    getVoiceStatus()
      .then((s) => setVoiceUsable(s.enabled))
      .catch(() => setVoiceUsable(false));
  }, []);

  const toggleVoice = () => {
    setVoiceOn((prev) => {
      const next = !prev;
      localStorage.setItem("shion-voice", next ? "on" : "off");
      if (!next) audioRef.current?.pause();
      return next;
    });
  };

  const speak = useCallback(async (text: string) => {
    try {
      const blob = await synthesizeSpeech(text);
      if (!blob) return; // エンジン未起動などは黙ってスキップ(音声はおまけ)
      audioRef.current?.pause();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch {
      /* 自動再生ブロック等も無視 */
    }
  }, []);

  const refreshConversations = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    chatHandlerRef.current = (event: ServerEvent) => {
      switch (event.type) {
        case "session":
          setCurrentId(event.conversation_id);
          refreshConversations();
          break;
        case "emotion":
          setEmotion(event.value);
          break;
        case "chunk":
          streamingRef.current += event.text;
          setStreaming(streamingRef.current);
          break;
        case "tool_status":
          setRunningTool(event.state === "running" ? event.name : null);
          break;
        case "done": {
          const content = streamingRef.current;
          streamingRef.current = "";
          setStreaming("");
          setRunningTool(null);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content, emotion: event.emotion },
          ]);
          setBusy(false);
          if (voiceOn && voiceUsable && content) speak(content);
          break;
        }
        case "proactive":
          // 紫桜からの自発的発話。表示中の会話宛てなら吹き出しとして追加
          refreshConversations();
          if (event.conversation_id === currentId) {
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: event.text, emotion: event.emotion },
            ]);
            setEmotion(event.emotion);
          }
          if (voiceOn && voiceUsable) speak(event.text);
          break;
        case "error":
          streamingRef.current = "";
          setStreaming("");
          setRunningTool(null);
          setBusy(false);
          setEmotion("troubled");
          setError(event.message);
          break;
      }
    };
    return () => {
      chatHandlerRef.current = null;
    };
  }, [chatHandlerRef, refreshConversations, currentId, voiceOn, voiceUsable, speak]);

  const selectConversation = async (id: number) => {
    setCurrentId(id);
    setError(null);
    const msgs = await getMessages(id);
    setMessages(msgs);
    const lastAssistant = [...msgs].reverse().find((m) => m.role === "assistant");
    setEmotion((lastAssistant?.emotion as Emotion) ?? "normal");
  };

  const newConversation = () => {
    setCurrentId(null);
    setMessages([]);
    setEmotion("normal");
    setError(null);
  };

  const removeConversation = async (id: number) => {
    await deleteConversation(id);
    refreshConversations();
    if (id === currentId) newConversation();
  };

  const send = (text: string) => {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setBusy(true);
    setError(null);
    setEmotion("thinking");
    socketRef.current?.sendChat(text, currentId);
  };

  return (
    <div className="chat-layout">
      <Sidebar
        conversations={conversations}
        currentId={currentId}
        onSelect={selectConversation}
        onNew={newConversation}
        onDelete={removeConversation}
      />
      <CharacterView emotion={emotion} busy={busy} />
      <ChatWindow
        messages={messages}
        streaming={streaming}
        busy={busy}
        error={error}
        runningTool={runningTool}
        onSend={send}
        voiceUsable={voiceUsable}
        voiceOn={voiceOn}
        onToggleVoice={toggleVoice}
      />
    </div>
  );
}

import { MutableRefObject, useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, getMessages, listConversations } from "../api/client";
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
          break;
        }
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
  }, [chatHandlerRef, refreshConversations]);

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
      />
    </div>
  );
}

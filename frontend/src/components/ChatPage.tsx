import { useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, getMessages, listConversations, logout } from "../api/client";
import { ChatSocket, openChatSocket } from "../api/ws";
import type { ChatMessage, Conversation, Emotion } from "../types";
import CharacterView from "./CharacterView";
import ChatWindow from "./ChatWindow";
import Sidebar from "./Sidebar";

export default function ChatPage({ onLogout }: { onLogout: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [emotion, setEmotion] = useState<Emotion>("normal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<ChatSocket | null>(null);
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
    const socket = openChatSocket((event) => {
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
        case "done": {
          const content = streamingRef.current;
          streamingRef.current = "";
          setStreaming("");
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
          setBusy(false);
          setEmotion("troubled");
          setError(event.message);
          break;
      }
    });
    socketRef.current = socket;
    return () => socket.close();
  }, [refreshConversations]);

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

  const handleLogout = async () => {
    await logout();
    onLogout();
  };

  return (
    <div className="chat-layout">
      <Sidebar
        conversations={conversations}
        currentId={currentId}
        onSelect={selectConversation}
        onNew={newConversation}
        onDelete={removeConversation}
        onLogout={handleLogout}
      />
      <CharacterView emotion={emotion} busy={busy} />
      <ChatWindow
        messages={messages}
        streaming={streaming}
        busy={busy}
        error={error}
        onSend={send}
      />
    </div>
  );
}

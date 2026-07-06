import { useEffect, useRef, useState } from "react";
import { logout, me } from "./api/client";
import { ChatSocket, openChatSocket } from "./api/ws";
import ChatPage from "./components/ChatPage";
import Login from "./components/Login";
import MemoriesPage from "./components/MemoriesPage";
import PluginsPage from "./components/PluginsPage";
import type { ServerEvent } from "./types";

type AuthState = "loading" | "anonymous" | "authenticated";
type Page = "chat" | "memories" | "plugins";

interface Toast {
  id: number;
  title: string;
  body: string;
}

let toastSeq = 0;

export default function App() {
  const [auth, setAuth] = useState<AuthState>("loading");

  useEffect(() => {
    me()
      .then((res) => setAuth(res.authenticated ? "authenticated" : "anonymous"))
      .catch(() => setAuth("anonymous"));
  }, []);

  if (auth === "loading") {
    return <div className="fullscreen-center">読み込み中…</div>;
  }
  if (auth === "anonymous") {
    return <Login onSuccess={() => setAuth("authenticated")} />;
  }
  return <MainShell onLogout={() => setAuth("anonymous")} />;
}

function MainShell({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<Page>("chat");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const socketRef = useRef<ChatSocket | null>(null);
  // チャットイベントの処理はChatPageが登録する(通知はここで捌く)
  const chatHandlerRef = useRef<((ev: ServerEvent) => void) | null>(null);

  useEffect(() => {
    const socket = openChatSocket((ev) => {
      if (ev.type === "notification") {
        const id = ++toastSeq;
        setToasts((prev) => [...prev, { id, title: ev.title, body: ev.body }]);
        setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 8000);
      } else {
        chatHandlerRef.current?.(ev);
      }
    });
    socketRef.current = socket;
    return () => socket.close();
  }, []);

  const handleLogout = async () => {
    await logout();
    onLogout();
  };

  return (
    <div className="app-shell">
      <nav className="nav-rail">
        <button
          className={`nav-item ${page === "chat" ? "is-active" : ""}`}
          title="チャット"
          onClick={() => setPage("chat")}
        >
          💬
        </button>
        <button
          className={`nav-item ${page === "memories" ? "is-active" : ""}`}
          title="長期記憶"
          onClick={() => setPage("memories")}
        >
          🧠
        </button>
        <button
          className={`nav-item ${page === "plugins" ? "is-active" : ""}`}
          title="プラグイン"
          onClick={() => setPage("plugins")}
        >
          🔌
        </button>
        <div className="nav-spacer" />
        <button className="nav-item" title="ログアウト" onClick={handleLogout}>
          🚪
        </button>
      </nav>
      <div className="app-content">
        {/* チャットはWS状態を保持するため、ページ切替でも unmount しない */}
        <div style={{ display: page === "chat" ? "contents" : "none" }}>
          <ChatPage socketRef={socketRef} chatHandlerRef={chatHandlerRef} />
        </div>
        {page === "memories" && <MemoriesPage />}
        {page === "plugins" && <PluginsPage />}
      </div>
      <div className="toast-host">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <div className="toast-title">🌸 {t.title}</div>
            <div className="toast-body">{t.body}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

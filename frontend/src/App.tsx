import { useEffect, useState } from "react";
import { me } from "./api/client";
import ChatPage from "./components/ChatPage";
import Login from "./components/Login";

type AuthState = "loading" | "anonymous" | "authenticated";

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
  return <ChatPage onLogout={() => setAuth("anonymous")} />;
}

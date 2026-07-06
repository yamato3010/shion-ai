import { FormEvent, useState } from "react";
import { login } from "../api/client";

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ログインに失敗しました");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fullscreen-center">
      <form className="login-card" onSubmit={submit}>
        <img src="/character/normal.svg" alt="紫桜" className="login-portrait" />
        <h1>
          紫桜 <span className="login-subtitle">shion-ai</span>
        </h1>
        <p>おかえりなさい。パスワードを入れてね</p>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="パスワード"
          autoFocus
        />
        {error && <div className="login-error">{error}</div>}
        <button type="submit" disabled={busy || password.length === 0}>
          {busy ? "確認中…" : "ログイン"}
        </button>
      </form>
    </div>
  );
}

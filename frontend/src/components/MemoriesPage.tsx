import { useEffect, useState } from "react";
import { addMemory, deleteMemory, listMemories } from "../api/client";
import type { Memory } from "../types";

const CATEGORY_LABEL: Record<string, string> = {
  profile: "プロフィール",
  preference: "好み",
  relationship: "人間関係",
  event: "予定・出来事",
  task: "依頼・タスク",
  other: "その他",
};

export default function MemoriesPage() {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("other");
  const [message, setMessage] = useState<string | null>(null);

  const refresh = () => {
    listMemories()
      .then(setMemories)
      .catch(() => setMemories([]));
  };

  useEffect(refresh, []);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 4000);
  };

  const handleAdd = async () => {
    if (!content.trim()) return;
    try {
      await addMemory(content.trim(), category);
      setContent("");
      refresh();
    } catch (e) {
      flash(`⚠ ${e instanceof Error ? e.message : "追加に失敗しました"}`);
    }
  };

  const handleDelete = async (id: number) => {
    await deleteMemory(id);
    setMemories((prev) => prev?.filter((m) => m.id !== id) ?? null);
  };

  if (memories === null) {
    return <div className="fullscreen-center">読み込み中…</div>;
  }

  return (
    <main className="memories-page">
      <h1>🧠 長期記憶</h1>
      <p className="page-note">
        会話から自動抽出された「紫桜が覚えていること」です。応答時に関連する記憶が参照されます。
      </p>

      <div className="memory-add">
        <input
          value={content}
          placeholder="覚えさせたいことを一文で(例: ユーザーは犬を飼っている)"
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing || e.keyCode === 229) return;
            if (e.key === "Enter") handleAdd();
          }}
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {Object.entries(CATEGORY_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button onClick={handleAdd} disabled={!content.trim()}>
          追加
        </button>
      </div>
      {message && <p className="page-note">{message}</p>}

      {memories.length === 0 && <p>まだ記憶はありません。会話すると自動で増えていきます。</p>}
      <ul className="memory-list">
        {memories.map((m) => (
          <li key={m.id} className="memory-item">
            <div className="memory-main">
              <span className={`memory-category cat-${m.category}`}>
                {CATEGORY_LABEL[m.category] ?? m.category}
              </span>
              <span className="memory-content">{m.content}</span>
            </div>
            <div className="memory-meta">
              <span>{new Date(m.created_at).toLocaleDateString()}</span>
              {m.source === "manual" && <span>手動</span>}
              <button
                className="memory-delete"
                title="この記憶を消す"
                onClick={() => handleDelete(m.id)}
              >
                🗑
              </button>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}

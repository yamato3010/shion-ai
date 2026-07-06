import type { Conversation } from "../types";

interface Props {
  conversations: Conversation[];
  currentId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
  onDelete: (id: number) => void;
  onLogout: () => void;
}

export default function Sidebar({
  conversations,
  currentId,
  onSelect,
  onNew,
  onDelete,
  onLogout,
}: Props) {
  return (
    <nav className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-logo">🌸 shion-ai</span>
      </div>
      <button className="new-chat-button" onClick={onNew}>
        + 新しい会話
      </button>
      <ul className="conversation-list">
        {conversations.map((c) => (
          <li
            key={c.id}
            className={`conversation-item ${c.id === currentId ? "is-active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-title">{c.title}</span>
            <button
              className="conversation-delete"
              title="削除"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm(`「${c.title}」を削除する?`)) onDelete(c.id);
              }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <button className="logout-button" onClick={onLogout}>
        ログアウト
      </button>
    </nav>
  );
}

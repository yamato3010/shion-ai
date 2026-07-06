import type { ServerEvent } from "../types";

export interface ChatSocket {
  sendChat: (text: string, conversationId: number | null) => void;
  close: () => void;
}

/** チャット用WebSocket。切断時は自動再接続する(docs/05 §1.4) */
export function openChatSocket(onEvent: (event: ServerEvent) => void): ChatSocket {
  let ws: WebSocket | null = null;
  let closed = false;
  const pending: string[] = [];

  const connect = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = () => {
      while (pending.length > 0) {
        ws?.send(pending.shift()!);
      }
    };
    ws.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data) as ServerEvent);
      } catch {
        /* 不正なメッセージは無視 */
      }
    };
    ws.onclose = () => {
      if (!closed) setTimeout(connect, 1500);
    };
  };
  connect();

  return {
    sendChat: (text, conversationId) => {
      const payload = JSON.stringify({ type: "chat", text, conversation_id: conversationId });
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(payload);
      } else {
        pending.push(payload);
      }
    },
    close: () => {
      closed = true;
      ws?.close();
    },
  };
}

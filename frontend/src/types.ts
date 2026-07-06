export type Emotion =
  | "normal"
  | "joy"
  | "sad"
  | "surprised"
  | "troubled"
  | "shy"
  | "thinking";

export const EMOTIONS: Emotion[] = [
  "normal",
  "joy",
  "sad",
  "surprised",
  "troubled",
  "shy",
  "thinking",
];

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
}

export interface ChatMessage {
  id?: number;
  role: "user" | "assistant";
  content: string;
  emotion?: string | null;
}

export type ServerEvent =
  | { type: "session"; conversation_id: number; title: string }
  | { type: "emotion"; value: Emotion }
  | { type: "chunk"; text: string }
  | { type: "done"; conversation_id: number; message_id: number; emotion: Emotion }
  | { type: "error"; message: string };

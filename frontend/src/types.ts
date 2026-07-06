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
  | { type: "tool_status"; name: string; state: "running" | "done" | "error" }
  | { type: "done"; conversation_id: number; message_id: number; emotion: Emotion }
  | { type: "error"; message: string }
  | { type: "notification"; title: string; body: string; channel: string; url?: string | null };

export interface SchemaField {
  type: string;
  default?: unknown;
  description?: string;
}

export interface JobInfo {
  name: string;
  cron: string;
}

export interface PluginInfo {
  name: string;
  display_name: string;
  version: string;
  description: string;
  author: string;
  enabled: boolean;
  status: "disabled" | "loaded" | "error";
  error: string | null;
  config_schema: Record<string, SchemaField>;
  config: Record<string, unknown>;
  tools: string[];
  jobs: JobInfo[];
}

export interface Memory {
  id: number;
  content: string;
  category: string;
  source: string;
  created_at: string;
  last_accessed_at: string | null;
}

export interface JobLogEntry {
  id: number;
  job_name: string;
  status: string;
  detail: string | null;
  started_at: string;
  finished_at: string | null;
}

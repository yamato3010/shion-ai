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

export interface DashboardCardItem {
  text: string;
  url?: string | null;
}

export interface DashboardCard {
  plugin: string;
  title: string;
  items: DashboardCardItem[];
  footer?: string | null;
}

export interface UsageEntry {
  date: string;
  provider: string;
  model: string;
  purpose: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  calls: number;
  has_estimate: boolean;
}

export interface UsageSummary {
  days: number;
  total_cost: number;
  today_cost: number;
  total_calls: number;
  entries: UsageEntry[];
}

export interface DashboardData {
  cards: DashboardCard[];
  usage: UsageSummary;
}

export interface GoogleStatus {
  configured: boolean;
  connected: boolean;
}

export interface JobLogEntry {
  id: number;
  job_name: string;
  status: string;
  detail: string | null;
  started_at: string;
  finished_at: string | null;
}

import type {
  ChatMessage,
  Conversation,
  DashboardData,
  GoogleStatus,
  JobLogEntry,
  Memory,
  PluginInfo,
  VoiceStatus,
} from "../types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* JSONでないエラーレスポンスはstatusTextのまま */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export interface MeResponse {
  authenticated: boolean;
  assistant_name: string;
}

export const login = (password: string) =>
  api<{ ok: boolean }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });

export const logout = () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" });

export const me = () => api<MeResponse>("/api/auth/me");

export const listConversations = () => api<Conversation[]>("/api/conversations");

export const getMessages = (conversationId: number) =>
  api<ChatMessage[]>(`/api/conversations/${conversationId}/messages`);

export const deleteConversation = (conversationId: number) =>
  api<{ ok: boolean }>(`/api/conversations/${conversationId}`, { method: "DELETE" });

// --- プラグイン管理 ---

export const listPlugins = () => api<PluginInfo[]>("/api/plugins");

export const setPluginEnabled = (name: string, enabled: boolean) =>
  api<PluginInfo>(`/api/plugins/${name}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

export const updatePluginConfig = (name: string, config: Record<string, unknown>) =>
  api<PluginInfo>(`/api/plugins/${name}/config`, {
    method: "PUT",
    body: JSON.stringify({ config }),
  });

export const reloadPlugin = (name: string) =>
  api<PluginInfo>(`/api/plugins/${name}/reload`, { method: "POST" });

export const runPluginJob = (name: string, jobName: string) =>
  api<{ ok: boolean }>(`/api/plugins/${name}/jobs/${jobName}/run`, { method: "POST" });

export const getPluginLogs = (name: string) =>
  api<JobLogEntry[]>(`/api/plugins/${name}/logs`);

// --- 長期記憶 ---

export const listMemories = () => api<Memory[]>("/api/memories");

export const addMemory = (content: string, category: string) =>
  api<Memory>("/api/memories", {
    method: "POST",
    body: JSON.stringify({ content, category }),
  });

export const deleteMemory = (id: number) =>
  api<{ ok: boolean }>(`/api/memories/${id}`, { method: "DELETE" });

// --- ダッシュボード / Google連携 ---

export const getDashboard = () => api<DashboardData>("/api/dashboard");

export const getGoogleStatus = () => api<GoogleStatus>("/api/google/status");

export const disconnectGoogle = () =>
  api<{ ok: boolean }>("/api/google/disconnect", { method: "POST" });

export const runPluginTool = (plugin: string, tool: string, args: Record<string, unknown>) =>
  api<{ result: unknown }>(`/api/plugins/${plugin}/tools/${tool}/run`, {
    method: "POST",
    body: JSON.stringify({ args }),
  });

// --- 音声合成 ---

export const getVoiceStatus = () => api<VoiceStatus>("/api/voice/status");

/** 応答テキストをWAVにする。合成できない環境では null(音声はおまけ機能) */
export const synthesizeSpeech = async (text: string): Promise<Blob | null> => {
  const res = await fetch("/api/voice", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) return null;
  return res.blob();
};

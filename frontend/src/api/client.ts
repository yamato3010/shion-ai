import type { ChatMessage, Conversation, JobLogEntry, PluginInfo } from "../types";

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

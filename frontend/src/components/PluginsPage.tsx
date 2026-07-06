import { useEffect, useState } from "react";
import {
  getPluginLogs,
  listPlugins,
  reloadPlugin,
  runPluginJob,
  setPluginEnabled,
  updatePluginConfig,
} from "../api/client";
import type { JobLogEntry, PluginInfo, SchemaField } from "../types";

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[] | null>(null);

  const refresh = () => {
    listPlugins()
      .then(setPlugins)
      .catch(() => setPlugins([]));
  };

  useEffect(refresh, []);

  if (plugins === null) {
    return <div className="fullscreen-center">読み込み中…</div>;
  }

  return (
    <main className="plugins-page">
      <h1>🔌 プラグイン管理</h1>
      <p className="page-note">
        <code>plugins/</code> にディレクトリを置くと自動で発見されます(初回は無効状態)。
      </p>
      {plugins.length === 0 && <p>プラグインが見つかりません。</p>}
      {plugins.map((p) => (
        <PluginCard
          key={p.name}
          plugin={p}
          onChanged={(updated) =>
            setPlugins((prev) => prev!.map((x) => (x.name === updated.name ? updated : x)))
          }
        />
      ))}
    </main>
  );
}

function PluginCard({
  plugin,
  onChanged,
}: {
  plugin: PluginInfo;
  onChanged: (p: PluginInfo) => void;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>(plugin.config);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<JobLogEntry[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(null), 4000);
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      flash(e instanceof Error ? e.message : "操作に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const toggle = () =>
    run(async () => {
      const updated = await setPluginEnabled(plugin.name, !plugin.enabled);
      onChanged(updated);
      setConfig(updated.config);
    });

  const saveConfig = () =>
    run(async () => {
      const updated = await updatePluginConfig(plugin.name, config);
      onChanged(updated);
      setConfig(updated.config);
      flash("設定を保存してリロードしました");
    });

  const reload = () =>
    run(async () => {
      const updated = await reloadPlugin(plugin.name);
      onChanged(updated);
      flash("リロードしました");
    });

  const runJob = (jobName: string) =>
    run(async () => {
      await runPluginJob(plugin.name, jobName);
      flash(`${jobName} を実行しました`);
    });

  const toggleLogs = () =>
    run(async () => {
      setLogs(logs === null ? await getPluginLogs(plugin.name) : null);
    });

  const schemaEntries = Object.entries(plugin.config_schema);

  return (
    <section className={`plugin-card status-${plugin.status}`}>
      <header className="plugin-header">
        <div>
          <span className="plugin-name">{plugin.display_name}</span>
          <span className="plugin-version">v{plugin.version}</span>
          <StatusBadge status={plugin.status} />
        </div>
        <label className="switch">
          <input type="checkbox" checked={plugin.enabled} onChange={toggle} disabled={busy} />
          <span className="switch-slider" />
        </label>
      </header>
      <p className="plugin-description">{plugin.description}</p>
      {plugin.error && <div className="plugin-error">⚠ {plugin.error}</div>}
      {message && <div className="plugin-flash">{message}</div>}

      {plugin.tools.length > 0 && (
        <div className="plugin-row">
          <span className="row-label">ツール</span>
          {plugin.tools.map((t) => (
            <code key={t} className="chip">
              {t}
            </code>
          ))}
        </div>
      )}

      {plugin.jobs.length > 0 && (
        <div className="plugin-row">
          <span className="row-label">ジョブ</span>
          {plugin.jobs.map((j) => (
            <span key={j.name} className="job-item">
              <code className="chip">{j.name}</code>
              <span className="job-cron">{j.cron}</span>
              <button className="mini-button" disabled={busy} onClick={() => runJob(j.name)}>
                ▶ 今すぐ実行
              </button>
            </span>
          ))}
        </div>
      )}

      {schemaEntries.length > 0 && (
        <div className="plugin-config">
          {schemaEntries.map(([key, field]) => (
            <ConfigField
              key={key}
              name={key}
              field={field}
              value={config[key]}
              onChange={(v) => setConfig((prev) => ({ ...prev, [key]: v }))}
            />
          ))}
          <div className="plugin-actions">
            <button className="mini-button primary" disabled={busy} onClick={saveConfig}>
              設定を保存
            </button>
            <button className="mini-button" disabled={busy} onClick={reload}>
              リロード
            </button>
            <button className="mini-button" disabled={busy} onClick={toggleLogs}>
              {logs === null ? "実行ログ" : "ログを閉じる"}
            </button>
          </div>
        </div>
      )}

      {logs !== null && (
        <div className="job-logs">
          {logs.length === 0 && <p className="page-note">まだ実行ログはありません。</p>}
          {logs.map((log) => (
            <div key={log.id} className={`job-log log-${log.status}`}>
              <code>{log.job_name}</code>
              <span>{log.status}</span>
              <span>{new Date(log.started_at).toLocaleString("ja-JP")}</span>
              {log.detail && <span className="log-detail">{log.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusBadge({ status }: { status: PluginInfo["status"] }) {
  const label = { loaded: "稼働中", disabled: "無効", error: "エラー" }[status];
  return <span className={`status-badge status-${status}`}>{label}</span>;
}

function ConfigField({
  name,
  field,
  value,
  onChange,
}: {
  name: string;
  field: SchemaField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `cfg-${name}`;
  return (
    <div className="config-field">
      <label htmlFor={id}>
        <code>{name}</code>
        {field.description && <span className="field-description"> — {field.description}</span>}
      </label>
      {field.type === "boolean" ? (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : field.type === "integer" || field.type === "number" ? (
        <input
          id={id}
          type="number"
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) =>
            onChange(field.type === "integer" ? parseInt(e.target.value || "0", 10) : Number(e.target.value || 0))
          }
        />
      ) : field.type === "list" ? (
        <textarea
          id={id}
          rows={3}
          placeholder="1行に1項目"
          value={Array.isArray(value) ? value.join("\n") : ""}
          onChange={(e) => onChange(e.target.value.split("\n").filter((s) => s.trim() !== ""))}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { disconnectGoogle, getDashboard, getGoogleStatus } from "../api/client";
import type { DashboardData, GoogleStatus, UsageEntry } from "../types";

function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface ModelRow {
  key: string;
  purpose: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  calls: number;
  has_estimate: boolean;
}

function aggregateByModel(entries: UsageEntry[]): ModelRow[] {
  const map = new Map<string, ModelRow>();
  for (const e of entries) {
    const key = `${e.provider}/${e.model}`;
    const row = map.get(key) ?? {
      key,
      purpose: e.purpose,
      tokens_in: 0,
      tokens_out: 0,
      cost: 0,
      calls: 0,
      has_estimate: false,
    };
    row.tokens_in += e.tokens_in;
    row.tokens_out += e.tokens_out;
    row.cost += e.cost;
    row.calls += e.calls;
    row.has_estimate ||= e.has_estimate;
    if (!row.purpose.includes(e.purpose)) row.purpose += `, ${e.purpose}`;
    map.set(key, row);
  }
  return [...map.values()].sort((a, b) => b.cost - a.cost || b.calls - a.calls);
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [google, setGoogle] = useState<GoogleStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    getDashboard().then(setData).catch((e) => setError(String(e)));
    getGoogleStatus().then(setGoogle).catch(() => setGoogle(null));
  };

  useEffect(refresh, []);

  if (error) {
    return <main className="dashboard-page"><p className="page-note">⚠ {error}</p></main>;
  }
  if (data === null) {
    return <div className="fullscreen-center">読み込み中…</div>;
  }

  const models = aggregateByModel(data.usage.entries);

  return (
    <main className="dashboard-page">
      <h1>📊 ダッシュボード</h1>

      <div className="stat-tiles">
        <div className="stat-tile">
          <div className="stat-value">{formatCost(data.usage.today_cost)}</div>
          <div className="stat-label">今日のLLMコスト</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{formatCost(data.usage.total_cost)}</div>
          <div className="stat-label">直近{data.usage.days}日の合計</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{data.usage.total_calls}</div>
          <div className="stat-label">LLM呼び出し回数</div>
        </div>
      </div>

      <div className="dashboard-cards">
        {data.cards.map((card) => (
          <section key={card.plugin} className="dashboard-card">
            <h2>{card.title}</h2>
            {card.items.length === 0 && <p className="card-empty">表示できる項目がありません</p>}
            <ul>
              {card.items.map((item, i) => (
                <li key={i}>
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noreferrer">
                      {item.text}
                    </a>
                  ) : (
                    item.text
                  )}
                </li>
              ))}
            </ul>
            {card.footer && <div className="card-footer">{card.footer}</div>}
          </section>
        ))}

        <section className="dashboard-card">
          <h2>🔗 Google連携</h2>
          {google === null ? (
            <p className="card-empty">状態を取得できませんでした</p>
          ) : !google.configured ? (
            <p className="card-empty">
              .env に GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET を設定すると使えます
            </p>
          ) : google.connected ? (
            <>
              <p>✅ 連携済み(Gmail・カレンダー)</p>
              <button
                className="mini-button"
                onClick={async () => {
                  await disconnectGoogle();
                  refresh();
                }}
              >
                連携を解除
              </button>
            </>
          ) : (
            <a className="connect-button" href="/api/google/oauth/start">
              Googleと連携する
            </a>
          )}
        </section>
      </div>

      <section className="usage-section">
        <h2>モデル別使用量(直近{data.usage.days}日)</h2>
        {models.length === 0 ? (
          <p className="page-note">まだ記録がありません。会話すると記録されます。</p>
        ) : (
          <table className="usage-table">
            <thead>
              <tr>
                <th>モデル</th>
                <th>用途</th>
                <th>入力</th>
                <th>出力</th>
                <th>回数</th>
                <th>コスト</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.key}>
                  <td>{m.key}</td>
                  <td>{m.purpose}</td>
                  <td>{formatTokens(m.tokens_in)}</td>
                  <td>{formatTokens(m.tokens_out)}</td>
                  <td>{m.calls}</td>
                  <td>
                    {formatCost(m.cost)}
                    {m.has_estimate && <span title="トークン数は概算を含む">*</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="page-note">
          * はプロバイダがトークン数を報告しなかったため文字数からの概算を含みます。
        </p>
      </section>
    </main>
  );
}

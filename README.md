# 🌸 shion-ai

自分専用AIアシスタント「紫桜(しおん)」。
Web UI と Discord から、同じ人格・同じ記憶で対話できるパーソナルアシスタント。

設計書は [docs/](./docs/README.md) を参照。

## 現在の実装状況

フェーズ4(体験強化)の大部分まで実装済み:

- Web UI(React)でのチャット。立ち絵 + 表情差分(7種)が応答の感情に連動
- FastAPI + WebSocket によるストリーミング応答
- LLM抽象化層: OpenAI / Gemini / Ollama(OpenAI互換)+ Anthropic(ネイティブ)+ 用途別モデル割当・フォールバック
- SQLite への会話履歴保存、パスワード認証
- **プラグインシステム**: `plugins/` に置くだけで Tool(function calling)/ Job(cron)/ Command / 通知 / ダッシュボードカードを追加可能
- **管理画面**(🔌タブ): プラグインの有効化・設定編集・ジョブ手動実行・実行ログ
- **長期記憶**(🧠タブ): 会話から自動抽出した事実を保存し、応答時に関連記憶を注入。手動追加・削除も可能
- **ダッシュボード**(📊タブ): 今日の予定・ニュース・天気などのカード集約 + LLM使用量・コスト概算 + Google連携ボタン
- **Discord Bot**: DMで対話(ストリーミング編集)、スラッシュコマンド(/new /status + プラグインコマンド)、通知のDM配送。会話はWebと共有
- **通知**: プラグイン発の通知が Web UI のトースト + Discord DM に届く
- **音声**: VOICEVOX による読み上げ(🔊トグル)と、Web Speech API の音声入力(🎤)
- **VRM立ち絵**: `model.vrm` を置くとアニメーションする3D立ち絵(まばたき・表情・口パク)に自動切替
- **プロアクティブ会話**: 就寝前の声かけ・しばらく会話がないときの雑談など、紫桜からの自発的発話
- **ニュース興味学習**: 📊の記事に👍/👎を付ける(または会話で感想を言う)と興味プロファイルが自動調整
- 同梱プラグイン: `weather`(天気予報)/ `reminder`(リマインダー)/ `news`(RSS収集・朝夕ダイジェスト)/ `google_workspace`(Gmail・カレンダー・Tasks・Drive)/ `proactive`(自発的発話)
- Docker Compose 対応、GitHub Actions CI(lint / test / build)

進捗の詳細は [docs/09_roadmap.md](./docs/09_roadmap.md)。

## セットアップ

### 1. 環境変数

```bash
cp .env.example .env
# SHION_PASSWORD(ログインパスワード)と SHION_SECRET_KEY を必ず変更する。
# 使うLLMのAPIキー(OPENAI_API_KEY など)を設定する。
# キー未設定でもモック応答で動作確認は可能。
```

利用するモデルは `config/config.yaml` の `llm.models.chat` で選ぶ
(例: `openai/gpt-4o-mini`, `gemini/gemini-2.0-flash`, `ollama/qwen3:8b`)。

### 2. バックエンド

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn shion.main:app --reload --port 8000
```

### 3. フロントエンド(開発時)

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (APIは8000へプロキシされる)
```

### 本番相当で動かす場合

```bash
cd frontend && npm run build   # 生成された dist/ をバックエンドが配信する
cd ../backend && uvicorn shion.main:app --port 8000
# → http://localhost:8000 を開く
```

## 音声(VOICEVOX)を使う場合

1. [VOICEVOX](https://voicevox.hiroshiba.jp/) をダウンロードしてインストール(Mac対応・無料)
2. VOICEVOXアプリを起動しておく(アプリ起動中は `localhost:50021` でエンジンが動く)
3. Web UIのチャット入力欄の 🔇 を押して 🔊 にすると、紫桜の応答が読み上げられる

- 声は `config/config.yaml` の `voice.speaker` で変更できる
  (エンジン起動中に http://localhost:50021/speakers で話者ID一覧を確認。既定は 46=小夜/SAYO)
- エンジンが起動していないときは自動で無効化される(エラーにはならない)
- 🎤(音声入力)はブラウザのWeb Speech APIを使うため、VOICEVOX不要(Chrome/Edge推奨)

## Google連携(Gmail・カレンダー)を使う場合

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成し、
   「APIとサービス」で **Gmail API** と **Google Calendar API** を有効化
2. 「OAuth同意画面」を設定(External / テストユーザーに自分のGoogleアカウントを追加)
3. 「認証情報」→ OAuthクライアントID(種類: **ウェブアプリケーション**)を作成し、
   承認済みリダイレクトURIに `http://localhost:8000/api/google/oauth/callback` を登録
4. クライアントIDとシークレットを `.env` の `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` に設定
5. サーバーを再起動 → 🔌タブで `google_workspace` プラグインを有効化
6. 📊タブの「Googleと連携する」を押して同意フローを完了する

- トークンは暗号化(SHION_SECRET_KEY 由来の鍵)してDBに保存され、自動リフレッシュされます
- 会話で「明日の予定は?」「未読メールある?」、毎朝のブリーフィング通知、重要メール即時通知、予定の30分前リマインドが使えるようになります

## Discord Bot を使う場合

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成し、Bot を追加
2. **Privileged Gateway Intents の「MESSAGE CONTENT INTENT」を有効にする**(DM対話に必須)
3. Bot タブでトークンを発行し、`.env` の `DISCORD_BOT_TOKEN` に設定
4. 自分のユーザーID(Discordの設定→詳細設定→開発者モードON → 自分を右クリック→IDコピー)を
   `.env` の `DISCORD_OWNER_ID` に設定(未設定のままDMすると、Botが設定すべきIDを教えてくれる)
5. OAuth2 → URL Generator で `bot` + `applications.commands` スコープのURLを作り、自分のサーバーへ招待
   (DMだけで使う場合も、DMを開くために一度どこかのサーバーで同居する必要がある)
6. サーバーを再起動すると Bot がログインする

- DM に送ったメッセージは全て紫桜への発話になる(オーナー以外には反応しない)
- サーバーチャンネルでは `@紫桜` とメンションしたときだけ反応
- `/new` で会話の文脈をリセット、`/status` で稼働状態を表示
- スラッシュコマンドの反映はグローバル登録だと最大1時間かかる。すぐ試すなら
  `.env` の `DISCORD_GUILD_ID` に自分のサーバーIDを設定する(そのサーバーへ即時反映)
- 通知の配送先は `config/config.yaml` の `notifications.routes` で変更できる(`discord_dm` がDM配送)

## テスト

```bash
cd backend && .venv/bin/pytest
```

## キャラクターの差し替え

### VRM立ち絵(推奨)

`frontend/public/character/model.vrm` にVRMモデルを置くだけで、3D立ち絵に自動で切り替わる
(まばたき・呼吸・感情タグ連動の表情・読み上げ中の口パク付き)。

- モデルの入手: [VRoid Studio](https://vroid.com/studio) で自作(無料)、または
  [VRoid Hub](https://hub.vroid.com/) 等で利用条件を確認してダウンロード
- 開発時(`npm run dev`)もファイルを置くだけで反映される。本番は置いた後に `npm run build`
- 外すと静止画差分に戻る

### 静止画差分

`frontend/public/character/` に感情名のファイル(`normal.svg` など7種)を置く。
現在の画像は `assets/character/generate_placeholders.py` で生成したプレースホルダ。
本番の立ち絵(PNG可、透過推奨)ができたら同名で置き換えるだけでよい
(拡張子を変える場合は `CharacterView.tsx` の `portraitUrl` を修正)。

## Dockerで動かす場合

```bash
cp .env.example .env   # パスワード等を設定
docker compose up -d --build          # http://localhost:8000
docker compose --profile ollama up -d   # ローカルLLM(ollama)も同居させる場合
docker compose --profile voice up -d    # VOICEVOXエンジンも同居させる場合
```

同居サービスを使う場合は `config/config.yaml` のURLをサービス名に変える
(ollama: `http://ollama:11434/v1`、voicevox: `http://voicevox:50021`)。
会話履歴等は `./data` にそのまま保存される。

## ディレクトリ構成

```
backend/   FastAPIアプリ(コア・LLM層・Webインターフェース)
frontend/  React SPA(チャットUI・キャラ表示)
config/    config.yaml(モデル設定)/ persona.yaml(紫桜の人格)
plugins/   プラグイン置き場(フェーズ1で導入)
assets/    キャラクター素材
docs/      設計書
data/      SQLite等の実データ(gitignore)
```

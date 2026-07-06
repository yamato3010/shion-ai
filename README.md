# 🌸 shion-ai

自分専用AIアシスタント「紫桜(しおん)」。
Web UI と Discord(予定)から、同じ人格・同じ記憶で対話できるパーソナルアシスタント。

設計書は [docs/](./docs/README.md) を参照。

## 現在の実装状況

フェーズ0(骨格)+ 感情システムまで実装済み:

- Web UI(React)でのチャット。立ち絵 + 表情差分(7種)が応答の感情に連動
- FastAPI + WebSocket によるストリーミング応答
- LLM抽象化層: OpenAI / Gemini / Ollama(OpenAI互換API)+ フォールバック
- SQLite への会話履歴保存、パスワード認証

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

## テスト

```bash
cd backend && .venv/bin/pytest
```

## キャラクター画像の差し替え

`frontend/public/character/` に感情名のファイル(`normal.svg` など7種)を置く。
現在の画像は `assets/character/generate_placeholders.py` で生成したプレースホルダ。
本番の立ち絵(PNG可、透過推奨)ができたら同名で置き換えるだけでよい
(拡張子を変える場合は `CharacterView.tsx` の `portraitUrl` を修正)。

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

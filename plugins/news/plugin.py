"""ニュースプラグイン(docs/07)

パイプライン: 収集(RSS/Atom) → 正規化・重複排除 → 興味スコアリング → ダイジェスト配信。
RSSパースは依存を増やさないため標準ライブラリ(xml.etree)で行う。

興味スコア:
- キーワード一致(interests の語が記事に含まれるか)は常に有効
- 埋め込みが使える環境では interests との類似度も加点(コアの LLM Router 経由)
LLM要約はダイジェストの「紫桜のひとこと」にのみ使用し、使えない環境では省略する。
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from shion.plugins import PluginBase, command, daily_cron, job, tool

SEEN_KEY = "seen_hashes"  # 既出記事のURLハッシュ
ARTICLES_KEY = "articles"  # 蓄積記事(新しい順)
PROFILE_KEY = "feedback_profile"  # 👍/👎から学習した語の重み {term: weight}
MAX_SEEN = 3000
MAX_ARTICLES = 300
MAX_PROFILE_TERMS = 200
TIME_FMT = "%Y-%m-%d %H:%M"

# トラッキング系クエリパラメータはURL正規化時に除去する
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|ref$)")


def normalize_url(url: str) -> str:
    parts = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    return urlunparse((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def _text(elem, *paths: str) -> str:
    for path in paths:
        found = elem.find(path)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 / RDF / Atom をパースして [{title, url, summary}] を返す(壊れたら空)"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    tag = root.tag.split("}")[-1]
    items: list[dict] = []

    if tag in ("rss", "RDF"):  # RSS 2.0 / RSS 1.0(RDF)
        for item in root.iter():
            if item.tag.split("}")[-1] != "item":
                continue
            title = _text(item, "title", "{http://purl.org/rss/1.0/}title")
            link = _text(item, "link", "{http://purl.org/rss/1.0/}link")
            summary = _text(item, "description", "{http://purl.org/rss/1.0/}description")
            if title and link:
                items.append({"title": title, "url": link, "summary": _strip_html(summary)[:300]})
    elif tag == "feed":  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f"{ns}entry"):
            title = _text(entry, f"{ns}title")
            link = ""
            for link_el in entry.findall(f"{ns}link"):
                if link_el.get("rel") in (None, "alternate"):
                    link = link_el.get("href") or ""
                    break
            summary = _text(entry, f"{ns}summary", f"{ns}content")
            if title and link:
                items.append({"title": title, "url": link, "summary": _strip_html(summary)[:300]})
    return items


def keyword_score(text: str, interests: list[str]) -> float:
    """興味語のゆるい部分一致。「AI・機械学習」のような複合語は分割して照合する"""
    haystack = text.lower()
    terms = [t for phrase in interests for t in re.split(r"[・/,、\s]+", str(phrase)) if t]
    if not terms:
        return 0.0
    hits = sum(1 for t in terms if t.lower() in haystack)
    return hits / len(terms)


# 内容語の抽出(漢字・カタカナ・英数字の連なり)。フィードバック学習の特徴量に使う
_TERM_RE = re.compile(r"[一-鿿]{2,}|[ァ-ヶー]{2,}|[a-zA-Z][a-zA-Z0-9+.#-]{2,}")


def extract_terms(text: str) -> list[str]:
    return [t.lower() for t in _TERM_RE.findall(text)]


def update_profile(profile: dict, text: str, rating: str) -> dict:
    """👍/👎された記事の内容語で興味プロファイル(語→重み)を更新する"""
    delta = 1 if rating == "up" else -1
    for term in set(extract_terms(text)):
        profile[term] = max(-5, min(5, profile.get(term, 0) + delta))
    if len(profile) > MAX_PROFILE_TERMS:  # 重みの小さい語から捨てる
        profile = dict(
            sorted(profile.items(), key=lambda kv: abs(kv[1]), reverse=True)[:MAX_PROFILE_TERMS]
        )
    return profile


def profile_bonus(text: str, profile: dict) -> float:
    """プロファイルとの一致による加減点(-0.3〜+0.3)"""
    if not profile:
        return 0.0
    matched = sum(profile.get(term, 0) for term in set(extract_terms(text)))
    return max(-0.3, min(0.3, matched * 0.1))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def format_digest(articles: list[dict], heading: str, comment: str = "") -> str:
    lines = []
    if comment:
        lines.append(comment)
        lines.append("")
    for a in articles:
        lines.append(f"● {a['title']}")
        if a.get("summary"):
            lines.append(f"  {a['summary'][:80]}")
        lines.append(f"  {a['url']}")
    return "\n".join(lines)


class NewsPlugin(PluginBase):
    async def on_load(self):
        self.client = httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "shion-ai/0.1 (personal assistant)"},
        )
        self._interest_vec: list[float] | None = None  # 興味プロファイルの埋め込み(遅延計算)

    async def on_unload(self):
        await self.client.aclose()

    # --- 収集(30分間隔) ---

    @job(cron="*/30 * * * *")
    async def collect(self) -> str:
        seen: list[str] = await self.storage.get(SEEN_KEY, [])
        articles: list[dict] = await self.storage.get(ARTICLES_KEY, [])
        seen_set = set(seen)
        added = 0

        for feed_url in self.config.get("feeds") or []:
            try:
                resp = await self.client.get(feed_url)
                resp.raise_for_status()
                entries = parse_feed(resp.text)
            except Exception as e:  # noqa: BLE001 - 1フィードの失敗で巡回を止めない
                self.logger.warning("フィード取得失敗 %s: %s", feed_url, e)
                continue

            for entry in entries:
                h = url_hash(entry["url"])
                if h in seen_set:
                    continue
                seen_set.add(h)
                seen.append(h)
                score = await self._score(f"{entry['title']} {entry['summary']}")
                articles.insert(
                    0,
                    {
                        **entry,
                        "hash": h,
                        "score": round(score, 3),
                        "collected_at": datetime.now().strftime(TIME_FMT),
                        "digested": False,
                    },
                )
                added += 1

        await self.storage.set(SEEN_KEY, seen[-MAX_SEEN:])
        await self.storage.set(ARTICLES_KEY, articles[:MAX_ARTICLES])
        self.logger.info("ニュース収集: %d件追加(累計%d件)", added, len(articles))
        return f"{added}件追加"

    async def _score(self, text: str) -> float:
        interests = [str(i) for i in (self.config.get("interests") or [])]
        score = keyword_score(text, interests)
        try:
            if self._interest_vec is None and interests:
                vecs = await self.llm.embed(["。".join(interests)])
                self._interest_vec = vecs[0] if vecs else []
            if self._interest_vec:
                vecs = await self.llm.embed([text[:500]])
                if vecs:
                    score = max(score, _cosine(self._interest_vec, vecs[0]))
        except Exception:  # noqa: BLE001 - 埋め込み不可はキーワードのみで続行
            pass
        # 👍/👎から学習したプロファイルで加減点
        profile = await self.storage.get(PROFILE_KEY, {})
        return max(0.0, min(1.0, score + profile_bonus(text, profile)))

    # --- ダイジェスト配信(朝刊・夕刊) ---

    @job(cron=lambda self: daily_cron(self.config.get("morning_time") or "07:00"))
    async def morning_digest(self) -> str:
        return await self._send_digest("🌅 朝刊")

    @job(cron=lambda self: daily_cron(self.config.get("evening_time") or "19:00"))
    async def evening_digest(self) -> str:
        return await self._send_digest("🌇 夕刊")

    async def _send_digest(self, heading: str) -> str:
        # 収集ジョブと同時刻に走る可能性があるため、直前に一度収集しておく
        await self.collect()
        articles: list[dict] = await self.storage.get(ARTICLES_KEY, [])
        fresh = [a for a in articles if not a.get("digested")]
        if not fresh:
            return "新着なし(通知スキップ)"

        limit = int(self.config.get("max_items_per_digest") or 8)
        picked = sorted(fresh, key=lambda a: a["score"], reverse=True)[:limit]

        comment = ""
        if self.llm.has_real_llm("summarize"):
            try:
                titles = "\n".join(f"- {a['title']}" for a in picked)
                comment = await self.llm_text(
                    f"次のニュース見出し一覧への短いコメントを、親しみやすい口調で2文以内で書いて。\n{titles}",
                    purpose="summarize",
                )
            except Exception:  # noqa: BLE001 - コメントはおまけ。失敗しても配信する
                comment = ""

        await self.notify(
            title=f"{heading}({len(picked)}件)",
            body=format_digest(picked, heading, comment.strip()),
            channel="daily",
        )
        picked_hashes = {a["hash"] for a in picked}
        for a in articles:
            if a["hash"] in picked_hashes:
                a["digested"] = True
        await self.storage.set(ARTICLES_KEY, articles)
        return f"{len(picked)}件配信"

    # --- Tool / Command ---

    @tool(description="蓄積済みのニュース記事を検索して返す。topic を省略すると最新の注目記事")
    async def get_news(self, topic: str = "", limit: int = 5) -> list:
        articles: list[dict] = await self.storage.get(ARTICLES_KEY, [])
        if topic:
            articles = [
                a for a in articles
                if keyword_score(f"{a['title']} {a.get('summary', '')}", [topic]) > 0
            ]
        else:
            articles = sorted(articles, key=lambda a: a["score"], reverse=True)
        return [
            {"title": a["title"], "url": a["url"], "summary": a.get("summary", "")}
            for a in articles[: max(1, min(int(limit), 10))]
        ]

    @tool(
        description=(
            "ニュース記事への興味フィードバックを記録する。rating は 'up'(面白かった)か "
            "'down'(興味ない)。ユーザーが記事の感想を言ったときに使う"
        )
    )
    async def rate_news(self, url: str, rating: str) -> dict:
        if rating not in ("up", "down"):
            return {"error": "rating は 'up' か 'down' で指定してください"}
        articles: list[dict] = await self.storage.get(ARTICLES_KEY, [])
        target_hash = url_hash(url)
        article = next((a for a in articles if a["hash"] == target_hash), None)
        if article is None:
            return {"error": "その記事は蓄積されていません"}

        profile = await self.storage.get(PROFILE_KEY, {})
        profile = update_profile(profile, f"{article['title']} {article.get('summary', '')}", rating)
        await self.storage.set(PROFILE_KEY, profile)
        article["rating"] = rating
        await self.storage.set(ARTICLES_KEY, articles)
        self.logger.info("フィードバック: %s %s", rating, article["title"][:40])
        return {"recorded": rating, "title": article["title"], "learned_terms": len(profile)}

    @command(name="news", description="ニュースの即時ダイジェスト(トピック指定可)")
    async def news_command(self, text: str = "") -> str:
        found = await self.get_news(topic=text.strip(), limit=8)
        if not found:
            return "まだ記事がないよ。収集ジョブ(collect)を実行してみてね。"
        return format_digest(found, "📰")

    # --- ダッシュボードカード ---

    async def dashboard(self) -> dict:
        articles: list[dict] = await self.storage.get(ARTICLES_KEY, [])
        top = sorted(articles[:50], key=lambda a: a["score"], reverse=True)[:5]
        return {
            "title": "📰 最新ニュース",
            "items": [
                {
                    "text": a["title"],
                    "url": a["url"],
                    # 👍/👎ボタン(汎用アクション: 押すと rate_news ツールが呼ばれる)
                    "actions": [
                        {"label": "👍", "tool": "rate_news", "args": {"url": a["url"], "rating": "up"}},
                        {"label": "👎", "tool": "rate_news", "args": {"url": a["url"], "rating": "down"}},
                    ],
                    "rated": a.get("rating"),
                }
                for a in top
            ],
            "footer": f"蓄積 {len(articles)}件" if articles else "まだ記事がありません",
        }

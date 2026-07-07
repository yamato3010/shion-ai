"""newsプラグインのテスト(RSS/Atomパース・URL正規化・興味スコア・ダイジェスト)"""

import importlib.util
from pathlib import Path

PLUGIN_PATH = Path(__file__).resolve().parents[2] / "plugins" / "news" / "plugin.py"
spec = importlib.util.spec_from_file_location("test_news_plugin", PLUGIN_PATH)
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)

RSS2 = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>テック</title>
<item><title>AIの新モデル発表</title><link>https://example.com/a?utm_source=rss</link>
<description>&lt;p&gt;すごい&lt;b&gt;モデル&lt;/b&gt;が出た&lt;/p&gt;</description></item>
<item><title>リンク無し</title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Zenn</title>
<entry><title>Pythonの新機能</title>
<link rel="alternate" href="https://zenn.dev/x"/><summary>まとめ記事</summary></entry>
</feed>"""

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
<item><title>はてな記事</title><link>https://b.hatena.ne.jp/y</link><description>説明</description></item>
</rdf:RDF>"""


def test_parse_rss2():
    items = news.parse_feed(RSS2)
    assert len(items) == 1  # リンク無しは除外
    assert items[0]["title"] == "AIの新モデル発表"
    assert items[0]["summary"] == "すごいモデルが出た"  # HTMLタグ除去


def test_parse_atom_and_rdf():
    assert news.parse_feed(ATOM)[0] == {
        "title": "Pythonの新機能",
        "url": "https://zenn.dev/x",
        "summary": "まとめ記事",
    }
    assert news.parse_feed(RDF)[0]["title"] == "はてな記事"


def test_parse_broken_xml():
    assert news.parse_feed("<rss><channel>") == []
    assert news.parse_feed("not xml at all") == []


def test_normalize_url_strips_tracking():
    a = news.url_hash("https://example.com/a?utm_source=rss&utm_medium=x")
    b = news.url_hash("https://example.com/a")
    c = news.url_hash("https://example.com/a?id=1")
    assert a == b
    assert a != c


def test_keyword_score():
    interests = ["AI・機械学習", "ソフトウェア開発"]
    assert news.keyword_score("生成AIが進化", interests) > 0
    assert news.keyword_score("機械学習の実践入門", interests) > 0
    assert news.keyword_score("今日の晩ごはん", interests) == 0.0
    assert news.keyword_score("なんでも", []) == 0.0


def test_feedback_profile_learning():
    profile = {}
    profile = news.update_profile(profile, "生成AIエージェントの新フレームワーク", "up")
    profile = news.update_profile(profile, "プロ野球 順位予想", "down")

    assert news.profile_bonus("AIエージェント入門", profile) > 0
    assert news.profile_bonus("プロ野球 今日の結果", profile) < 0
    assert news.profile_bonus("料理レシピまとめ", profile) == 0.0
    # 加減点は±0.3に収まる
    for _ in range(10):
        profile = news.update_profile(profile, "AIエージェント", "up")
    assert news.profile_bonus("AIエージェント", profile) == 0.3


def test_extract_terms():
    terms = news.extract_terms("Rustで書くWebサーバー入門(2026年版)")
    assert "rust" in terms
    assert "サーバー" in terms
    assert "入門" in terms


def test_format_digest():
    articles = [
        {"title": "見出し1", "url": "https://a", "summary": "概要テキスト"},
        {"title": "見出し2", "url": "https://b", "summary": ""},
    ]
    out = news.format_digest(articles, "🌅 朝刊", comment="今日も面白い話題があるよ!")
    assert "今日も面白い話題があるよ!" in out
    assert "● 見出し1" in out
    assert "https://b" in out

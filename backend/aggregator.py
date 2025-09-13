# aggregator.py — Zenn新着横断 → タグ集計（完全版）
# - 直近31日だけDB保持（古い metrics / articles は自動削除）
# - /api/articles?order=latest をページング -> 各記事HTMLから tags / liked_count 補完
# - 新着のみ INSERT OR IGNORE、既存は残す（重複防止: articles.url UNIQUE）
# - 1/7/30日の metrics を毎回再計算（DB内の該当期間データで集計）
# - 読み出し: get_rankings / get_tool_detail / get_stats

import csv
import os
import re
import time
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import datetime as dt

import requests

# ===========================
# 定数・設定
# ===========================
JST = timezone(timedelta(hours=9))
DB_PATH = os.getenv("DB_PATH", os.path.abspath("trend.db"))

USER_AGENT = "oss-rank-bot/1.0 (+https://example.com)"
ZENN_ARTICLES_API = "https://zenn.dev/api/articles"  # ?order=latest&page=1

RETENTION_DAYS = 31
DAYS_BUCKETS = (1, 7, 30)
MAX_PAGES = 100            # 新着をどの程度さかのぼるかの上限
SLEEP_SEC = 0.25          # マナー

# ===========================
# 抽出用 正規表現
# ===========================
TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
TIME_RE  = re.compile(r'<time[^>]+datetime="([^"]+)"', re.I)
LIKES_RE = re.compile(r'"liked_count"\s*:\s*(\d+)', re.I)
TAG_LINK_RE = re.compile(r'href="/topics/([a-z0-9\-_]+)"', re.I)

# ===========================
# モデル
# ===========================
@dataclass
class Metric:
    slug: str
    days: int
    date: str           # YYYY-MM-DD
    articles: int
    likes_sum: int
    score: float

@dataclass
class ArticleRow:
    slug: str           # タグ（=topics名）
    title: str
    url: str
    likes: int
    published_at: str   # ISO

# ===========================
# ユーティリティ
# ===========================
def _now_jst() -> datetime:
    return datetime.now(JST)

def _date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def _log(*s):
    print("[aggregator]", *s)

# ===========================
# DB スキーマ・初期化
# ===========================
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS tools (
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
  date TEXT NOT NULL,
  days INTEGER NOT NULL,
  slug TEXT NOT NULL,
  articles INTEGER NOT NULL,
  likes_sum INTEGER NOT NULL,
  score REAL NOT NULL,
  PRIMARY KEY (date, days, slug),
  FOREIGN KEY (slug) REFERENCES tools(slug)
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  likes INTEGER NOT NULL,
  published_at TEXT NOT NULL,
  FOREIGN KEY (slug) REFERENCES tools(slug)
);

CREATE INDEX IF NOT EXISTS idx_metrics_days_date ON metrics(days, date);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_slug_pub ON articles(slug, published_at);
"""

def init_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

# ===========================
# 古いデータの削除（保持31日）
# ===========================
def _prune_old(conn: sqlite3.Connection):
    cutoff_dt = _now_jst() - timedelta(days=RETENTION_DAYS)
    cutoff_iso = cutoff_dt.isoformat(timespec="seconds")
    cutoff_date = cutoff_dt.strftime("%Y-%m-%d")

    # 記事（保持期間外）
    conn.execute("DELETE FROM articles WHERE published_at < ?", (cutoff_iso,))
    # metrics（古いスナップショット）
    conn.execute("DELETE FROM metrics WHERE date < ?", (cutoff_date,))
    _log(f"[prune] articles< {cutoff_iso}, metrics< {cutoff_date}")

# ===========================
# tools.csv 読み込み（表示名マッピング）
# ===========================
def load_tools_csv(path: str) -> Dict[str, str]:
    """
    任意: name,slug のCSV（存在すれば表示名として使用。無ければ slug をそのまま name に）
    """
    mapping = {}
    if not os.path.exists(path):
        return mapping
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            slug = (row.get("slug") or "").strip().lower()
            if name and slug:
                mapping[slug] = name
    return mapping

def _upsert_tool(conn: sqlite3.Connection, slug: str, name: Optional[str]):
    display = name or slug
    conn.execute(
        "INSERT INTO tools(slug, name) VALUES(?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET name=excluded.name",
        (slug, display),
    )

# ===========================
# Zenn 新着一覧（API）
# ===========================
def _fetch_latest_list_api(page: int) -> Optional[dict]:
    try:
        r = requests.get(
            ZENN_ARTICLES_API,
            params={"order": "latest", "page": page},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            _log(f"[API] page={page} -> HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        _log(f"[API] EXC page={page} -> {e}")
        return None

# ===========================
# 記事詳細（HTMLからタグ・いいね等を抽出）
# ===========================
def _fetch_article_detail(url: str) -> dict:
    """
    記事ページから title / published_at / liked_count / tags を抽出。
    __NEXT_DATA__ が使えない場合に備え、HTMLの正規表現でフォールバック。
    """
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if r.status_code != 200:
            return {}
        html = r.text

        # タイトル
        title = ""
        mt = TITLE_RE.search(html)
        if mt:
            title = re.sub(r"<.*?>", "", mt.group(1)).strip()

        # 公開日時
        published_at_iso = None
        mt = TIME_RE.search(html)
        if mt:
            try:
                published_at_iso = datetime.fromisoformat(
                    mt.group(1).replace("Z", "+00:00")
                ).astimezone(JST).isoformat()
            except Exception:
                pass

        # いいね
        likes = 0
        ml = LIKES_RE.search(html)
        if ml:
            try:
                likes = int(ml.group(1))
            except Exception:
                likes = 0

        # タグ
        tags = list({m.group(1).lower() for m in TAG_LINK_RE.finditer(html)})

        return {
            "title": title,
            "published_at": published_at_iso,
            "likes": likes,
            "tags": tags,
        }
    except Exception:
        return {}

# ===========================
# 期間集計（DB内データで再計算）
# ===========================
def _compute_metrics_for_slug(conn: sqlite3.Connection, slug: str, days: int) -> Metric:
    since_iso = (_now_jst() - timedelta(days=days)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(likes),0) AS s "
        "FROM articles WHERE slug=? AND published_at >= ?",
        (slug, since_iso),
    ).fetchone()
    articles = int(row["c"])
    likes_sum = int(row["s"])
    score = likes_sum
    return Metric(slug=slug, days=days, date=_date_str(_now_jst()),
                  articles=articles, likes_sum=likes_sum, score=score)

# ===========================
# 集計（クロール→新着追加→1/7/30再計算→古いデータ削除）
# ===========================
def aggregate(
    *, 
    days: int, 
    tools_csv: str = "tools.csv", 
    db_path: str = DB_PATH, 
    max_pages: int = 1, 
    sleep_sec: float = 0.3
):
    """
    1. Zenn新着をページングし、31日内の記事だけを処理（それ以上古いページに到達したら打ち切り）
    2. 各記事HTMLから tags / liked_count を抽出（APIの meta も併用）
    3. 記事は INSERT OR IGNORE（url UNIQUE）で新着だけ追加
    4. 発見したタグを tools に upsert（name は tools.csv にあればそれを使用）
    5. 1/7/30日の metrics を DB から再計算し、INSERT OR REPLACE
    6. 31日超の古い articles / metrics を削除
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tag_display_map = load_tools_csv(tools_csv)
        today = _date_str(_now_jst())
        seen_urls: set[str] = set()
        touched_slugs: set[str] = set()  # 今回見つかったタグ集合

        retention_cut = _now_jst() - timedelta(days=RETENTION_DAYS)

        # ===== 新着クロール =====
        for page in range(1, max_pages + 1):
            data = _fetch_latest_list_api(page)
            if not data:
                break

            items = data.get("articles") or []
            if not items:
                break

            added_in_page = 0
            for it in items:
                path = it.get("path") or ""
                if not path.startswith("/"):
                    continue
                url = f"https://zenn.dev{path}"
                if url in seen_urls:
                    continue

                # API側のメタ（likes / title / topics など）
                api_likes = int(it.get("liked_count") or 0)
                api_title = it.get("title") or ""
                api_topics = [t.get("id") for t in (it.get("topics") or []) if isinstance(t, dict) and t.get("id")]

                # 記事ページから詳細抽出
                detail = _fetch_article_detail(url)

                # 公開日時（APIにない想定のため、HTML優先）
                pub_iso = detail.get("published_at")
                if not pub_iso:
                    # 取れない記事はスキップ
                    seen_urls.add(url)
                    continue

                pub_dt = _parse_iso(pub_iso)
                if not pub_dt:
                    seen_urls.add(url)
                    continue

                # 保持期間より古いものが出始めたら終了
                if pub_dt < retention_cut:
                    _log(f"[cutoff] page={page} pub={pub_dt.isoformat()} < retention({RETENTION_DAYS}d) -> stop")
                    page = max_pages + 1
                    break

                title = (detail.get("title") or api_title or "").strip()
                likes = int(detail.get("likes") or 0)
                if likes == 0:
                    likes = api_likes  # 補完

                tags = detail.get("tags") or api_topics or []
                if not title or not tags:
                    seen_urls.add(url)
                    continue

                # 新着記事の登録（タグごとに複製して保持する方針）
                for tag in tags:
                    slug = str(tag).lower().strip()
                    if not slug:
                        continue

                    # tools に表示名登録（tools.csv にあれば使用、無ければslug）
                    _upsert_tool(conn, slug, tag_display_map.get(slug))

                    # 記事 INSERT（url UNIQUE なので1回目のみ入る）
                    conn.execute(
                        "INSERT OR IGNORE INTO articles(slug, title, url, likes, published_at) "
                        "VALUES(?,?,?,?,?)",
                        (slug, title, url, likes, pub_dt.isoformat())
                    )

                    touched_slugs.add(slug)

                added_in_page += 1
                seen_urls.add(url)
                time.sleep(sleep_sec)

            _log(f"[list] page={page} processed={added_in_page}")
            if added_in_page == 0:
                # このページで新規が無ければ、以降も無いと判断して終了
                break

        # ===== 古いデータの削除 =====
        _prune_old(conn)

        # ===== 1/7/30 の metrics 再計算（今回触れたタグのみで十分だが、
        #      初回などを考慮して“DBに存在する全タグ”を対象にする）
        if not touched_slugs:
            # DBに存在する全スラッグ
            rows = conn.execute("SELECT slug FROM tools").fetchall()
            touched_slugs = {r["slug"] for r in rows}

        for slug in touched_slugs:
            # 表示名の同期（CSVに追記された場合に反映）
            _upsert_tool(conn, slug, tag_display_map.get(slug))

            # 各バケットをDBから算出
            for d in DAYS_BUCKETS:
                m = _compute_metrics_for_slug(conn, slug, d)
                conn.execute(
                    "INSERT OR REPLACE INTO metrics(date, days, slug, articles, likes_sum, score) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (m.date, m.days, m.slug, m.articles, m.likes_sum, m.score),
                )
            _log(f"[metrics] slug={slug} -> updated for {DAYS_BUCKETS}")

        conn.commit()
        return {"ok": True, "date": today, "tags": len(touched_slugs)}
    finally:
        conn.close()

# ===========================
# 読み出し API
# ===========================
def get_rankings(days: int, limit: int = 100, db_path: str = DB_PATH) -> List[Dict]:
    """
    最新保存日のメトリクスからランキングを返す + 各タグTop5記事（該当期間で抽出）
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT date FROM metrics WHERE days=? ORDER BY date DESC LIMIT 1",
            (days,)
        ).fetchone()
        if not row:
            return []
        latest = row["date"]

        rows = conn.execute(
            """
            SELECT m.slug, t.name, m.articles, m.likes_sum, m.score
            FROM metrics m
            JOIN tools  t ON t.slug = m.slug
            WHERE m.days=? AND m.date=?
            ORDER BY m.score DESC
            LIMIT ?
            """,
            (days, latest, limit)
        ).fetchall()

        # 期間境界
        try:
            latest_dt = dt.datetime.fromisoformat(str(latest))
        except Exception:
            latest_dt = dt.datetime.utcnow()
        since_iso = (latest_dt - dt.timedelta(days=days)).isoformat(timespec="seconds")

        results = []
        for r in rows:
            slug = r["slug"]
            top5 = conn.execute(
                """
                SELECT title, url, likes, published_at
                FROM articles
                WHERE slug=? AND published_at >= ?
                ORDER BY likes DESC, published_at DESC
                LIMIT 5
                """,
                (slug, since_iso)
            ).fetchall()

            results.append({
                "slug": slug,
                "name": r["name"],
                "articles": r["articles"],
                "likes_sum": r["likes_sum"],
                "score": float(r["score"]),
                "articles_top5": [
                    {
                        "title": a["title"],
                        "url": a["url"],
                        "likes": int(a["likes"]) if a["likes"] is not None else 0,
                        "published_at": a["published_at"],
                    } for a in top5
                ],
            })
        return results
    finally:
        conn.close()

def get_tool_detail(slug: str, days: int, db_path: str = DB_PATH) -> Dict:
    """
    タグ詳細（最新スナップショット＋該当期間の人気Top10記事）
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tool = conn.execute("SELECT slug, name FROM tools WHERE slug=?", (slug,)).fetchone()
        if not tool:
            return {}

        row = conn.execute(
            "SELECT date, articles, likes_sum, score FROM metrics "
            "WHERE slug=? AND days=? ORDER BY date DESC LIMIT 1",
            (slug, days)
        ).fetchone()
        if not row:
            metric = {"articles": 0, "likes_sum": 0, "score": 0.0, "date": None}
            latest_dt = _now_jst()
        else:
            metric = {
                "date": row["date"],
                "articles": row["articles"],
                "likes_sum": row["likes_sum"],
                "score": float(row["score"]),
            }
            try:
                latest_dt = dt.datetime.fromisoformat(metric["date"])
            except Exception:
                latest_dt = _now_jst()

        since_iso = (latest_dt - dt.timedelta(days=days)).isoformat(timespec="seconds")

        arts = conn.execute(
            "SELECT title, url, likes, published_at FROM articles "
            "WHERE slug=? AND published_at >= ? "
            "ORDER BY likes DESC, published_at DESC LIMIT 10",
            (slug, since_iso)
        ).fetchall()

        return {
            "tool": {"slug": tool["slug"], "name": tool["name"]},
            "metric": metric,
            "articles_top": [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "likes": int(a["likes"]) if a["likes"] is not None else 0,
                    "published_at": a["published_at"],
                } for a in arts
            ],
        }
    finally:
        conn.close()

def get_stats(days: int, db_path: str = DB_PATH) -> Dict:
    """
    そのdaysで最後に保存した日付を返す（フロントの“更新日”表示用）
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT date FROM metrics WHERE days=? ORDER BY date DESC LIMIT 1",
            (days,)
        ).fetchone()
        return {"last_updated": row[0] if row else None}
    finally:
        conn.close()
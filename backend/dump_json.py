# backend/dump_json.py
import os, json
from aggregator import aggregate, get_rankings, get_stats, get_tool_detail

ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR   = os.path.join(ROOT, "frontend", "web", "api")
TOOLS_DIR = os.path.join(OUT_DIR, "tools")

def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _sanitize_slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9\-_]", "-", (s or "").lower())

def main():
    # 集計（必要に応じて max_pages を増やす）
    aggregate(days=30, max_pages=100)

    # ランキング & 統計
    for d in (30, 7, 1):
        dump(os.path.join(OUT_DIR, f"rankings_{d}.json"), get_rankings(d))
        dump(os.path.join(OUT_DIR, f"stats_{d}.json"),    get_stats(d))

    # ここから “詳細ページ用 JSON” を静的化 ーーーーーーーーーーー
    total = 0
    for d in (30, 7, 1):
        top = get_rankings(d, limit=200)          # 期間ごとの上位から生成
        if not top:
            continue
        for r in top:
            slug = _sanitize_slug(r.get("slug", ""))
            if not slug:
                continue
            detail = get_tool_detail(slug, d)
            dump(os.path.join(TOOLS_DIR, f"{slug}-{d}.json"), detail)
            total += 1
    print(f"[dump_json] wrote {total} tool detail files under /api/tools")
    # ーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーー

if __name__ == "__main__":
    main()

"""Google News (US) RSS reader - khabar "as it is" uthata hai.

Sirf headlines + source + link + time. Rewrite baad me AI karta hai.
"""
import re
import time
from datetime import datetime, timezone

import feedparser
import requests


def _clean_title(raw, source):
    """Google News title ke aakhir se ' - Source' hata do."""
    t = (raw or "").strip()
    if source and t.endswith(f" - {source}"):
        t = t[: -(len(source) + 3)].strip()
    return t


def _fetch(url, retries=3):
    """RSS fetch (requests - proxy-aware) with retries."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return feedparser.parse(r.content)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"RSS fetch fail: {url} ({last})")


def fetch_news(cfg):
    """Saare feeds se news items lao (deduped).

    Return: list of dicts {title, link, source, published, summary}
    """
    ncfg = cfg.get("news", {})
    feeds = ncfg.get("feeds", [])
    max_items = int(ncfg.get("max_items", 25))
    exclude = [w.lower() for w in ncfg.get("exclude_keywords", [])]

    items, seen = [], set()
    for feed_url in feeds:
        try:
            feed = _fetch(feed_url)
        except Exception as e:  # noqa: BLE001
            print(f"  [news] feed skip ({str(e)[:80]})")
            continue
        for e in feed.entries:
            link = e.get("link", "")
            if link in seen:
                continue
            source = ""
            if e.get("source") and e["source"].get("title"):
                source = e["source"]["title"]
            title = _clean_title(e.get("title", ""), source)
            if not title:
                continue
            low = title.lower()
            if any(w in low for w in exclude):
                continue
            seen.add(link)
            items.append({
                "title": title,
                "link": link,
                "source": source or "Google News",
                "published": e.get("published", ""),
                "summary": re.sub(r"<[^>]+>", "", e.get("summary", "") or "").strip(),
            })
    print(f"  [news] {len(items)} unique headlines mili ({len(feeds)} feeds)")
    return items[:max_items]


def now_iso():
    return datetime.now(timezone.utc).isoformat()

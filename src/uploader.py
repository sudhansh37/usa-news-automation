"""YouTube uploader - Data API v3 (OAuth refresh token se).

Secrets: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
Ye module sirf tab chalta hai jab main.py --upload de ya UPLOAD=1 ho.
"""
import time
from pathlib import Path

from .config import env


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=env("YT_REFRESH_TOKEN"),
        client_id=env("YT_CLIENT_ID"),
        client_secret=env("YT_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(video_path, script, news_item, cfg):
    """Video upload karo. Return YouTube video id."""
    from googleapiclient.http import MediaFileUpload

    ycfg = cfg.get("youtube", {})
    ch = cfg.get("channel", {})

    title = script["title"][:95]
    desc = script.get("description", "").strip()
    desc += f"\n\nSource: {news_item.get('source', 'Google News')}"
    if ycfg.get("ai_disclosure", True):
        desc += "\n\nThis video was produced with AI-assisted tools."
    desc += f"\n\nSubscribe to {ch.get('name', '')} for daily US news."

    tags = list(script.get("tags", [])) + list(ycfg.get("tags", []))
    tags = list(dict.fromkeys(tags))[:15]

    body = {
        "snippet": {
            "title": title,
            "description": desc[:4900],
            "tags": tags,
            "categoryId": str(ycfg.get("category_id", "25")),
            "defaultLanguage": ch.get("language", "en-US"),
        },
        "status": {
            "privacyStatus": ycfg.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(ycfg.get("made_for_kids", False)),
        },
    }

    yt = _service()
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  [upload] {int(status.progress() * 100)}%")
    vid = resp["id"]
    print(f"  [upload] done -> https://youtu.be/{vid}")
    return vid


def try_upload(video_path, script, news_item, cfg):
    """Upload with retries; fail ho to None (video zaya na ho)."""
    for i in range(3):
        try:
            return upload(video_path, script, news_item, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"  [upload] attempt {i+1} fail: {str(e)[:150]}")
            time.sleep(10 * (i + 1))
    return None

"""Script writer - khabar ko hook-style video script me rewrite karta hai.

Providers (config.yaml -> script.provider):
  gemini       : Google Gemini (primary, GEMINI_API_KEY). Baad me add karoge.
  pollinations : key-free LLM (default fallback, abhi isse chal raha hai)
  khushi       : apna Khushi AI (khushi-ai repo) OpenAI-compatible server
  openai       : koi bhi OpenAI-compatible endpoint

Output JSON:
  { title, hook, scenes:[{narration, image_query}], description, tags, thumbnail_text }
"""
import json
import re
import time

import requests

from .config import env

SYSTEM_PROMPT = (
    "You are a sharp US news YouTube scriptwriter. You turn a raw headline "
    "into a tight, energetic 60-second video script for an American audience. "
    "You ALWAYS open with a strong scroll-stopping HOOK (first 3 seconds). "
    "You never invent facts that are not in the given news - you only reframe "
    "and dramatise what is already there. You reply with STRICT JSON only."
)

USER_TEMPLATE = """\
Rewrite this US news into a short video script.

HEADLINE: {title}
SOURCE: {source}
DETAIL: {summary}

Return ONLY a JSON object with exactly these keys:
{{
  "title": "YouTube title, <=95 chars, punchy, no clickbait lies",
  "hook": "one powerful opening line (<=14 words) that grabs attention",
  "scenes": [
     {{"narration": "1-2 spoken sentences for this scene", "image_query": "short visual search prompt (3-6 words) for a photo/illustration"}},
     ... exactly {scenes} scenes total, telling the story start to finish ...
  ],
  "description": "3-4 line YouTube description with a call to follow, plain text",
  "tags": ["8 to 12 short lowercase tags"],
  "thumbnail_text": "3-4 word ALL CAPS text for the thumbnail"
}}
Rules:
- Narration must be natural spoken American English, total ~{seconds} seconds.
- image_query must describe a concrete visual (e.g. "roller coaster at theme park"),
  never a text-only or abstract concept.
- Keep normal English spacing inside all text values.
- Output the WHOLE JSON object on ONE line (compact, no newlines).
- Do not use markdown. Do not add commentary or explanation. JSON only.
"""


def _extract_json(text):
    """LLM reply se JSON object nikaalo (code fences / extra text ke saath bhi)."""
    if not text:
        raise ValueError("empty LLM reply")
    t = text.strip()
    # ```json ... ``` fences hatao
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            raise ValueError(f"no JSON in reply: {text[:200]}")
        return json.loads(m.group(0))


def _normalize(data, cfg):
    """LLM output ko safe/consistent banao."""
    scfg = cfg.get("script", {})
    n_scenes = int(scfg.get("scenes", 7))
    scenes = data.get("scenes") or []
    fixed = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        nar = str(s.get("narration", "")).strip()
        q = str(s.get("image_query", "")).strip()
        if nar:
            fixed.append({"narration": nar, "image_query": q or nar[:40]})
    if not fixed:
        raise ValueError("LLM ne koi scene nahi diya")
    fixed = fixed[:n_scenes]
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "title": str(data.get("title", "")).strip()[:95] or "US News Update",
        "hook": str(data.get("hook", "")).strip(),
        "scenes": fixed,
        "description": str(data.get("description", "")).strip(),
        "tags": [str(t).strip().lower() for t in tags][:15],
        "thumbnail_text": str(data.get("thumbnail_text", "")).strip()[:40],
    }


# --------------------------------------------------------------------------
# Provider: Gemini
# --------------------------------------------------------------------------
def _gemini(messages, cfg):
    from google import genai
    from google.genai import types

    gcfg = cfg.get("script", {}).get("gemini", {})
    models = [gcfg.get("model", "gemini-2.5-flash")] + list(gcfg.get("fallback_models", []))
    keys = [k for k in (env("GEMINI_API_KEY"), env("GEMINI_API_KEY_2")) if k]
    if not keys:
        raise RuntimeError("GEMINI_API_KEY set nahi hai")

    prompt = "\n\n".join(m["content"] for m in messages)
    last = None
    for key in keys:
        client = genai.Client(api_key=key)
        for model in models:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.9,
                    ),
                )
                return resp.text
            except Exception as e:  # noqa: BLE001
                last = e
                print(f"  [script] gemini {model} fail: {str(e)[:100]}")
    raise RuntimeError(f"Gemini fail: {last}")


# --------------------------------------------------------------------------
# Provider: Pollinations (free, no key)
# --------------------------------------------------------------------------
def _pollinations(messages, cfg):
    pcfg = cfg.get("script", {}).get("pollinations", {})
    url = pcfg.get("base_url", "https://text.pollinations.ai/openai")
    payload = {
        "model": pcfg.get("model", "openai"),
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "temperature": 0.9,
        # max_tokens ZAROORI hai - warna reasoning model beech me truncate kar
        # deta hai aur JSON adhoora aa jata hai
        "max_tokens": int(pcfg.get("max_tokens", 4000)),
    }
    last = None
    for i in range(3):
        try:
            r = requests.post(url, json=payload, timeout=180)
            r.raise_for_status()
            d = r.json()
            choices = d.get("choices") or []
            if not choices:
                raise RuntimeError(f"bad response: {str(d)[:200]}")
            msg = choices[0].get("message") or {}
            content = msg.get("content") or msg.get("reasoning") or ""
            if not content.strip():
                raise RuntimeError("empty content")
            return content
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"Pollinations fail: {last}")


# --------------------------------------------------------------------------
# Provider: Khushi AI (apna local/self-hosted, OpenAI-compatible)
# --------------------------------------------------------------------------
def _khushi(messages, cfg):
    kcfg = cfg.get("script", {}).get("khushi", {})
    base = env("KHUSHI_BASE_URL") or kcfg.get("base_url", "http://localhost:8000/v1")
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": kcfg.get("model", "khushi"),
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "temperature": 0.9,
    }
    r = requests.post(url, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _openai_compatible(messages, cfg):
    base = env("OPENAI_BASE_URL", default="https://api.openai.com/v1")
    key = env("OPENAI_API_KEY", default="")
    payload = {
        "model": env("OPENAI_MODEL", default="gpt-4o-mini"),
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload, timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


_PROVIDERS = {
    "gemini": _gemini,
    "pollinations": _pollinations,
    "khushi": _khushi,
    "openai": _openai_compatible,
}


def write_script(news_item, cfg):
    """Ek khabar -> script dict. Provider fail ho to chain me agla try karta hai."""
    scfg = cfg.get("script", {})
    primary = scfg.get("provider", "gemini")
    order = [primary] + [p for p in ("pollinations", "gemini", "khushi") if p != primary]

    user = USER_TEMPLATE.format(
        title=news_item["title"],
        source=news_item.get("source", ""),
        summary=(news_item.get("summary") or "")[:600],
        scenes=scfg.get("scenes", 7),
        seconds=scfg.get("target_seconds", 65),
    )
    messages = [{"role": "user", "content": user}]

    last = None
    for name in order:
        fn = _PROVIDERS.get(name)
        if not fn:
            continue
        try:
            raw = fn(messages, cfg)
            script = _normalize(_extract_json(raw), cfg)
            print(f"  [script] '{name}' se script ready ({len(script['scenes'])} scenes)")
            return script
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [script] provider '{name}' fail: {str(e)[:140]}")
    raise RuntimeError(f"Saare script providers fail: {last}")

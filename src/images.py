"""Image fetcher - stock API ("pixals") -> web search -> Pollinations generate.

Har image ko target size (1920x1080) me crop/resize karke, thoda dark gradient
lagata hai taaki text upar readable rahe.
"""
import io
import os
import random
import time
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter

from .config import env


def _save_cover(raw_bytes, out_path, w, h, dim=0.0, bottom_trim=0.0):
    """Bytes -> 1920x1080 cover crop (aspect fill) + optional darkening.

    bottom_trim: image ka neeche ka hissa (%) kaato - Pollinations ka watermark
    bottom-right me hota hai, isse nikal jata hai.
    """
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    if bottom_trim:
        iw, ih = img.size
        img = img.crop((0, 0, iw, max(1, int(ih * (1 - bottom_trim)))))
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale + 0.5), int(ih * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    img = img.crop((left, top, left + w, top + h))
    if dim:
        img = ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 - float(dim)))
    img.save(out_path, "JPEG", quality=92)
    return str(out_path)


# --------------------------------------------------------------------------
# Provider 1: stock API ("pixals" - Pexels / Pixabay / custom)
# --------------------------------------------------------------------------
def _stock(query, out_path, cfg):
    scfg = cfg.get("images", {}).get("stock", {})
    key = env("STOCK_API_KEY")
    if not key:
        raise RuntimeError("STOCK_API_KEY set nahi hai")
    kind = scfg.get("kind", "pexels")
    w = int(cfg["images"]["width"]); h = int(cfg["images"]["height"])
    dim = float(cfg["images"].get("dim", 0.0))

    if kind == "pexels":
        r = requests.get(
            scfg.get("base_url", "https://api.pexels.com/v1/search"),
            headers={"Authorization": key},
            params={"query": query, "per_page": scfg.get("per_page", 8),
                    "orientation": "landscape"},
            timeout=30,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            raise RuntimeError("stock: no results")
        url = random.choice(photos)["src"].get(scfg.get("image_field", "large"))
        img = requests.get(url, timeout=60); img.raise_for_status()
        return _save_cover(img.content, out_path, w, h, dim)

    if kind == "pixabay":
        r = requests.get(
            "https://pixabay.com/api/",
            params={"key": key, "q": query, "image_type": "photo",
                    "orientation": "horizontal", "per_page": scfg.get("per_page", 8)},
            timeout=30,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        if not hits:
            raise RuntimeError("stock: no results")
        url = random.choice(hits).get(scfg.get("image_field", "largeImageURL"))
        img = requests.get(url, timeout=60); img.raise_for_status()
        return _save_cover(img.content, out_path, w, h, dim)

    # custom provider
    headers = {scfg.get("key_header", "Authorization"): key}
    r = requests.get(scfg["base_url"], headers=headers,
                     params={"query": query, "q": query, "per_page": 8}, timeout=30)
    r.raise_for_status()
    data = r.json()
    for part in scfg.get("results_path", "").split("."):
        if part:
            data = data.get(part, data)
    if not isinstance(data, list) or not data:
        raise RuntimeError("stock(custom): no results")
    url = data[0].get(scfg.get("image_field", "url"))
    img = requests.get(url, timeout=60); img.raise_for_status()
    return _save_cover(img.content, out_path, w, h, dim)


# --------------------------------------------------------------------------
# Provider 2: key-free web image search (ddgs - "Google jaisa")
# --------------------------------------------------------------------------
def _web(query, out_path, cfg):
    from ddgs import DDGS
    w = int(cfg["images"]["width"]); h = int(cfg["images"]["height"])
    dim = float(cfg["images"].get("dim", 0.0))
    maxr = int(cfg["images"].get("web", {}).get("max_results", 6))
    with DDGS() as d:
        results = list(d.images(query, max_results=maxr))
    if not results:
        raise RuntimeError("web: no results")
    random.shuffle(results)
    for res in results:
        url = res.get("image")
        if not url:
            continue
        try:
            img = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            img.raise_for_status()
            return _save_cover(img.content, out_path, w, h, dim)
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("web: saare image URLs fail")


# --------------------------------------------------------------------------
# Provider 3: Pollinations AI generate (fallback - "jo na mile")
# --------------------------------------------------------------------------
def _pollinations(query, out_path, cfg):
    pcfg = cfg.get("images", {}).get("pollinations", {})
    w = int(cfg["images"]["width"]); h = int(cfg["images"]["height"])
    dim = float(cfg["images"].get("dim", 0.0))
    base = pcfg.get("base_url", "https://image.pollinations.ai/prompt")
    model = pcfg.get("model", "flux")
    retries = int(pcfg.get("retries", 4))
    prompt = requests.utils.quote(f"{query}, photorealistic, news photo, cinematic, 16:9")
    seed = random.randint(1, 999999)
    url = (f"{base}/{prompt}?width={w}&height={h}&model={model}"
           f"&nologo=true&seed={seed}")
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=90)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ctype.startswith("image") and len(r.content) > 3000:
                return _save_cover(r.content, out_path, w, h, dim, bottom_trim=0.085)
            last = f"status={r.status_code} ctype={ctype}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:100]
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"pollinations fail: {last}")


_PROVIDERS = {"stock": _stock, "web": _web, "pollinations": _pollinations}


def get_image(query, out_path, cfg, cache=None):
    """Provider order me pehla jo chale wahi image deta hai. Path return."""
    out_path = Path(out_path)
    # cache: pehle se bani (aur valid) image ho to reuse (resumable)
    if out_path.exists() and out_path.stat().st_size > 3000:
        try:
            from PIL import Image
            Image.open(out_path).verify()
            print(f"  [image] cached -> {out_path.name}")
            return str(out_path)
        except Exception:  # noqa: BLE001
            out_path.unlink(missing_ok=True)
    providers = cfg.get("images", {}).get("providers", ["pollinations"])
    last = None
    for name in providers:
        fn = _PROVIDERS.get(name)
        if not fn:
            continue
        try:
            path = fn(query, out_path, cfg)
            print(f"  [image] '{name}' -> {out_path.name}  ({query[:40]})")
            return path
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [image] '{name}' skip: {str(e)[:90]}")
    raise RuntimeError(f"Koi image provider kaam nahi kiya ({query}): {last}")

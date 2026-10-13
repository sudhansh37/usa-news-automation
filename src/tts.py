"""Narration (TTS) - scene-wise voice banata hai (perfect sync ke liye).

Provider chain (config.yaml -> tts.providers):
  edge_tts   : Microsoft Edge TTS (DEFAULT, free, no key) - best quality
  gtts       : Google Translate TTS (proxy-friendly fallback)
  gemini     : Gemini TTS (GEMINI_API_KEY ho to)
  hf_space   : apna / kisi ka bhi Hugging Face Space TTS (gradio)
  custom_http: apna koi bhi TTS API

Har scene ka alag audio banta hai -> duration exact pata chalti hai ->
video usi hisaab se banti hai (caption + image sync perfect).
"""
import asyncio
import base64
import copy
import os
import shutil
import subprocess
import time
from pathlib import Path

import requests

from .config import env
from .editor import ffmpeg_exe, probe_duration


def _concat_audio(parts, out_path):
    list_file = Path(out_path).parent / "tts_list.txt"
    list_file.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    cmd = [ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-c:a", "libmp3lame", "-q:a", "3", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)


# --------------------------------------------------------------------------
# edge-tts (default)
# --------------------------------------------------------------------------
def _edge_tts(text, cfg, out_path):
    import edge_tts
    c = cfg.get("edge_tts", {})
    voice = env("VOICE") or c.get("voice", "en-US-GuyNeural")
    rate = c.get("rate", "+10%")
    volume = c.get("volume", "+0%")

    async def _go():
        comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        await comm.save(str(out_path))
    asyncio.run(_go())
    return str(out_path)


# --------------------------------------------------------------------------
# gTTS (fallback)
# --------------------------------------------------------------------------
def _gtts(text, cfg, out_path):
    from gtts import gTTS
    c = cfg.get("gtts", {})
    last = None
    for i in range(5):  # 429 (rate-limit) pe backoff ke saath retry
        try:
            gTTS(text=text, lang=c.get("lang", "en"), tld=c.get("tld", "com"),
                 slow=False).save(str(out_path))
            if out_path.exists() and out_path.stat().st_size > 800:
                return str(out_path)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f"gtts fail: {last}")


def _gtx(text, cfg, out_path):
    """Google Translate TTS direct (key-free). 200-char limit -> chunk karke jodo."""
    lang = cfg.get("gtts", {}).get("lang", "en")
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= 180:
            cur = f"{cur} {w}".strip()
        else:
            chunks.append(cur); cur = w
    if cur:
        chunks.append(cur)
    parts = []
    for i, ch in enumerate(chunks):
        last = None
        for a in range(4):
            try:
                r = requests.get(
                    "https://translate.google.com/translate_tts",
                    params={"ie": "UTF-8", "q": ch, "tl": lang,
                            "client": "tw-ob", "ttsspeed": "1"},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
                r.raise_for_status()
                if len(r.content) < 800:
                    raise RuntimeError("gtx audio chhota")
                p = Path(out_path).parent / f"gtx_{i}.mp3"
                p.write_bytes(r.content); parts.append(p); break
            except Exception as e:  # noqa: BLE001
                last = e; time.sleep(3 * (a + 1))
        else:
            raise RuntimeError(f"gtx chunk {i} fail: {last}")
    if len(parts) == 1:
        shutil.copy(parts[0], out_path)
    else:
        _concat_audio(parts, out_path)
    return str(out_path)


# --------------------------------------------------------------------------
# Gemini TTS
# --------------------------------------------------------------------------
def _gemini_tts(text, cfg, out_path):
    import wave

    from google import genai
    from google.genai import types

    c = cfg.get("gemini", {})
    key = env("GEMINI_API_KEY", "GEMINI_API_KEY_2")
    if not key:
        raise RuntimeError("GEMINI_API_KEY set nahi hai")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=c.get("model", "gemini-2.5-flash-preview-tts"),
        contents=f"{c.get('style', '')} {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=c.get("voice", "Charon")))),
        ),
    )
    data = resp.candidates[0].content.parts[0].inline_data
    raw = data.data
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    sr = 24000
    if data.mime_type and "rate=" in data.mime_type:
        sr = int(data.mime_type.split("rate=")[-1].split(";")[0])
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(raw)
    return str(out_path)


# --------------------------------------------------------------------------
# HF Space (gradio) - apna narration space
# --------------------------------------------------------------------------
def _hf_space(text, cfg, out_path):
    from gradio_client import Client
    c = cfg.get("hf_space", {})
    space = env("HF_TTS_SPACE") or c.get("space")
    if not space:
        raise RuntimeError("hf_space.space set nahi hai")
    client = Client(space, token=env("HF_TOKEN") or None)
    kwargs = {c.get("text_param", "text"): text}
    result = client.predict(api_name=c.get("api_name", "/predict"), **kwargs)
    path = result[0] if isinstance(result, (tuple, list)) else result
    if not (path and Path(path).exists()):
        raise RuntimeError("hf_space: audio nahi mila")
    shutil.copy(path, out_path)
    return str(out_path)


# --------------------------------------------------------------------------
# Custom HTTP TTS
# --------------------------------------------------------------------------
def _custom_http(text, cfg, out_path):
    c = cfg.get("custom_http", {})
    if not c.get("endpoint"):
        raise RuntimeError("custom_http.endpoint set nahi hai")
    headers = {"Content-Type": "application/json"}
    auth = c.get("auth_header", "")
    if auth:
        headers["Authorization"] = auth.replace("{{TTS_API_KEY}}", env("TTS_API_KEY", default=""))
    body = copy.deepcopy(c.get("body", {}))
    for k, v in body.items():
        if isinstance(v, str):
            body[k] = v.replace("{text}", text)
    r = requests.post(c["endpoint"], headers=headers, json=body, timeout=300)
    r.raise_for_status()
    spec = c.get("response", "binary")
    if spec == "binary":
        out_path.write_bytes(r.content)
    elif spec.startswith("base64_json:"):
        data = r.json()
        for part in spec.split(":", 1)[1].split("."):
            data = data[part]
        out_path.write_bytes(base64.b64decode(data) if isinstance(data, str) else data)
    else:
        raise ValueError(f"response spec: {spec}")
    return str(out_path)


_FUNCS = {
    "edge_tts": _edge_tts,
    "gtts": _gtts,
    "gtx": _gtx,
    "gemini": _gemini_tts,
    "hf_space": _hf_space,
    "custom_http": _custom_http,
}


def synthesize_scenes(scenes, cfg, workdir):
    """Har scene ka narration -> audio. Return (list[{audio,duration}], full_audio)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    providers = cfg.get("tts", {}).get("providers", ["edge_tts", "gtts"])

    last = None
    for name in providers:
        fn = _FUNCS.get(name)
        if not fn:
            continue
        try:
            parts = []
            for i, sc in enumerate(scenes):
                out = workdir / f"scene_{i:02d}.mp3"
                # cache: pehle se bani narration ho to reuse (resumable)
                if out.exists() and out.stat().st_size > 800:
                    parts.append(out)
                    continue
                text = " ".join(sc["narration"].split())
                if not text:
                    raise RuntimeError("khali narration")
                fn(text, cfg.get("tts", {}), out)
                if not out.exists() or out.stat().st_size < 800:
                    raise RuntimeError(f"scene {i}: audio bahut chhota")
                parts.append(out)
            # durations
            durations = [probe_duration(p) for p in parts]
            full = workdir / "narration.mp3"
            if len(parts) == 1:
                shutil.copy(parts[0], full)
            else:
                _concat_audio(parts, full)
            print(f"  [tts] '{name}' se narration ready "
                  f"({len(parts)} scenes, {sum(durations):.1f}s)")
            return [{"audio": str(p), "duration": d} for p, d in zip(parts, durations)], str(full)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [tts] provider '{name}' fail: {str(e)[:120]}")
    raise RuntimeError(f"Saare TTS providers fail: {last}")

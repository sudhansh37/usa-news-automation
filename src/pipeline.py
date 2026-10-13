"""Pipeline orchestrator - ek khabar -> ek poori video.

news (Google News RSS) -> script (AI) -> images -> narration -> FFmpeg -> upload
"""
import json
import re
import shutil
from pathlib import Path

from . import editor, history, images as images_mod, news_feed, overlays, scriptwriter
from . import tts as tts_mod


def _slug(text, n=60):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:n].strip("-") or "us-news"


def build_video(news_item, script, cfg, workdir):
    """Ek video banao. (final_path, audio_info, narration_audio) return."""
    workdir = Path(workdir)
    img_dir = workdir / "images"; img_dir.mkdir(parents=True, exist_ok=True)
    tts_dir = workdir / "tts"; tts_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = workdir / "clips"; clips_dir.mkdir(parents=True, exist_ok=True)

    W = int(cfg["images"]["width"])
    H = int(cfg["images"]["height"])
    ch = cfg.get("channel", {})
    ocfg = cfg.get("overlay", {})
    variants = cfg.get("effects", {}).get("variants", ["zoom_in"])
    headline = news_item["title"]
    scenes = script["scenes"]

    # ---- narration (intro hook + scenes) ----
    narrations = [script.get("hook") or headline] + [s["narration"] for s in scenes]
    audio_info, full_audio = tts_mod.synthesize_scenes(
        [{"narration": n} for n in narrations], cfg, tts_dir)

    # ---- images ----
    scene_imgs = []
    for i, sc in enumerate(scenes):
        q = sc.get("image_query") or headline
        p = img_dir / f"scene_{i:02d}.jpg"
        try:
            images_mod.get_image(q, p, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"  [image] fallback headline ({str(e)[:70]})")
            images_mod.get_image(headline, p, cfg)
        scene_imgs.append(p)

    # ---- overlays ----
    banner_png = lower_png = None
    banner_path = lower_path = None
    if ocfg.get("headline_bar", True):
        banner_path = workdir / "banner.png"
        overlays.banner(headline, W).save(banner_path)
    if ocfg.get("lower_third", True):
        lower_path = workdir / "lower.png"
        overlays.lower_third(ch.get("name", ""), ch.get("handle", ""), W).save(lower_path)

    cap_paths = []
    for i, sc in enumerate(scenes):
        if ocfg.get("captions", True):
            cp = workdir / f"cap_{i:02d}.png"
            overlays.caption(sc["narration"], W).save(cp)
            cap_paths.append(cp)
        else:
            cap_paths.append(None)

    # ---- clips ----
    clips = []
    if ocfg.get("intro_card", True):
        card = overlays.title_card(headline, ch.get("name", ""), ch.get("handle", ""),
                                   W, H, bg_image=scene_imgs[0])
        card_path = workdir / "intro_card.jpg"
        card.save(card_path, quality=92)
        intro = clips_dir / "intro.mp4"
        if not (intro.exists() and intro.stat().st_size > 1000 and editor.is_valid_video(intro)):
            editor.make_scene_clip(card_path, audio_info[0]["duration"], intro, cfg,
                                   variant="zoom_in")
        clips.append(intro)

    offset = 1 if ocfg.get("intro_card", True) else 0
    for i, (sc, img, cap) in enumerate(zip(scenes, scene_imgs, cap_paths)):
        dur = audio_info[i + offset]["duration"]
        clip = clips_dir / f"scene_{i:02d}.mp4"
        if not (clip.exists() and clip.stat().st_size > 1000 and editor.is_valid_video(clip)):
            editor.make_scene_clip(
                img, dur, clip, cfg, variant=variants[i % len(variants)],
                banner_png=banner_path, caption_png=cap, lower_png=lower_path)
        clips.append(clip)

    silent = workdir / "silent.mp4"
    if not (silent.exists() and silent.stat().st_size > 1000 and editor.is_valid_video(silent)):
        editor.concat_clips([str(c) for c in clips], silent)

    final = workdir / "final.mp4"
    if not (final.exists() and final.stat().st_size > 1000 and editor.is_valid_video(final)):
        editor.mux_audio(silent, full_audio, final, cfg)
    return str(final), audio_info, full_audio


def run_once(cfg, count=1, do_upload=False, out_dir=None, work_root=None):
    """Poora run: news -> N videos. Results list return."""
    work_root = Path(work_root or (Path(cfg["_root"]) / "work"))
    items = news_feed.fetch_news(cfg)
    hist = history.load(cfg)
    picks = [it for it in items if not history.is_seen(hist, it)][:count]
    if not picks:
        print("  [pipeline] koi nayi khabar nahi mili (sab dekh li).")
        return []

    results = []
    for i, item in enumerate(picks):
        print(f"\n=== Video {i + 1}/{len(picks)}: {item['title'][:72]} ===")
        workdir = work_root / f"video_{i:02d}"
        workdir.mkdir(parents=True, exist_ok=True)
        script_path = workdir / "script.json"
        if script_path.exists():
            script = json.loads(script_path.read_text(encoding="utf-8"))
            print("  [script] cached")
        else:
            script = scriptwriter.write_script(item, cfg)
            script_path.write_text(json.dumps(script, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"  [script] title: {script['title']}")
        final, audio_info, _ = build_video(item, script, cfg, workdir)

        if out_dir:
            od = Path(out_dir); od.mkdir(parents=True, exist_ok=True)
            out_name = f"{_slug(script['title'])}.mp4"
            shutil.copy(final, od / out_name)
            print(f"  [pipeline] saved -> {od / out_name}")

        history.add(cfg, hist, item)

        if do_upload:
            from . import uploader
            uploader.try_upload(final, script, item, cfg)

        results.append({"title": script["title"], "video": final,
                        "out": str(Path(out_dir) / f"{_slug(script['title'])}.mp4") if out_dir else final,
                        "script": script, "news": item})
    return results

"""FFmpeg editor - images + narration se final 1080p news video banata hai.

Steps:
  1. Intro card (channel + headline) + hook narration
  2. Har scene: image pe Ken Burns (zoom/pan) + top headline bar + bottom caption
     + channel lower-third
  3. Saare clips concat
  4. Narration + (copyright-free) background music mux

NOTE: ye ffmpeg build me `drawtext` nahi hai, isliye text PIL se PNG me banta
hai (overlays.py) aur `overlay` filter se lagta hai.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

W, H = 1920, 1080


def ffmpeg_exe():
    """System ffmpeg, warna imageio-ffmpeg ka bundled binary."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


FFMPEG = ffmpeg_exe()


def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg fail:\n{' '.join(cmd)[:400]}\n{r.stderr[-1500:]}")
    return r


def probe_duration(path):
    """Audio/video ki duration (seconds). ffprobe na ho to ffmpeg -i parse."""
    if shutil.which("ffprobe"):
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        try:
            return float(json.loads(r.stdout)["format"]["duration"])
        except Exception:  # noqa: BLE001
            pass
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise RuntimeError(f"duration parse fail: {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def is_valid_video(path):
    """Clip/video poora likha gaya hai? (adhoora file cache me na atke)"""
    try:
        return probe_duration(path) > 0.1
    except Exception:  # noqa: BLE001
        return False


def _img_h(path):
    """PNG overlay ki height (pixels) - lower-third ko caption ke upar rakhne ke liye."""
    try:
        from PIL import Image
        return Image.open(path).size[1]
    except Exception:  # noqa: BLE001
        return 0


def _zoompan(variant, n_frames, out_w, out_h, za):
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"
    n = max(n_frames, 1)
    zmax = round(1 + za, 4)
    if variant == "zoom_out":
        z, x, y = f"max({zmax}-{za}*on/{n},1.0)", cx, cy
    elif variant == "pan_up":
        z, x, y = f"{zmax}", cx, f"(ih-ih/zoom)*(1-on/{n})"
    elif variant == "pan_down":
        z, x, y = f"{zmax}", cx, f"(ih-ih/zoom)*(on/{n})"
    elif variant == "pan_left":
        z, x, y = f"{zmax}", f"(iw-iw/zoom)*(1-on/{n})", cy
    elif variant == "pan_right":
        z, x, y = f"{zmax}", f"(iw-iw/zoom)*(on/{n})", cy
    elif variant == "ken_burns":
        z, x, y = f"min(1+{za}*on/{n},{zmax})", f"(iw-iw/zoom)*(on/{n})", cy
    else:  # zoom_in (default)
        z, x, y = f"min(1+{za}*on/{n},{zmax})", cx, cy
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={out_w}x{out_h}:fps={_FPS}"


_FPS = 30


def make_scene_clip(image, duration, out_path, cfg, variant="zoom_in",
                    banner_png=None, caption_png=None, lower_png=None):
    """Ek scene clip (no audio): image + Ken Burns + overlays. Path return."""
    eff = cfg.get("effects", {})
    fps = int(eff.get("fps", 30))
    global _FPS
    _FPS = fps
    za = float(eff.get("zoom_amount", 0.14))
    n_frames = int(duration * fps) + 2
    big_w = int(W * (1 + za + 0.04))
    big_h = int(big_w * H / W)

    vf = (
        f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={big_w}:{big_h},fps={fps},"
        f"{_zoompan(variant, n_frames, W, H, za)},"
        f"eq=saturation={eff.get('saturation', 1.18)}:contrast={eff.get('contrast', 1.1)}"
        f":brightness={eff.get('brightness', 0.02)},"
        f"unsharp=5:5:{eff.get('sharpen', 0.8)}:5:5:0[bg]"
    )
    inputs = ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(image)]
    last = "bg"
    idx = 1
    # caption height - lower-third ko iske UPAR rakhte hain taaki overlap na ho
    cap_h = _img_h(caption_png) if caption_png else 0
    # overlays: banner top, caption bottom, lower-third stacked above caption
    if banner_png:
        vf += f";[{last}][{idx}:v]overlay=0:0[o{idx}]"
        last = f"o{idx}"; inputs += ["-i", str(banner_png)]; idx += 1
    if lower_png:
        y = f"H-h-{cap_h + 12}" if caption_png else "H-h"
        vf += f";[{last}][{idx}:v]overlay=0:{y}[o{idx}]"
        last = f"o{idx}"; inputs += ["-i", str(lower_png)]; idx += 1
    if caption_png:
        vf += f";[{last}][{idx}:v]overlay=0:H-h[o{idx}]"
        last = f"o{idx}"; inputs += ["-i", str(caption_png)]; idx += 1

    cmd = [FFMPEG, "-y", *inputs, "-filter_complex", vf, "-map", f"[{last}]",
           "-r", str(fps), "-t", f"{duration:.3f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", str(eff.get("crf", 18)), "-preset", str(eff.get("preset", "medium")),
           "-an", str(out_path)]
    run(cmd)
    return str(out_path)


def concat_clips(clips, out_path):
    """Same-params clips ko bina re-encode jodo."""
    list_file = Path(out_path).parent / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{Path(c).resolve()}'" for c in clips), encoding="utf-8")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(out_path)])
    return str(out_path)


def _bgm_source():
    """Copyright-free ambient news bed (Am-F-C-G pad) - ffmpeg synth."""
    expr = (
        "st(0,floor(mod(t,16)/4));"
        "st(1,0.5-0.5*cos(2*PI*mod(t,4)/4));"
        "st(2,if(eq(ld(0),0),220,if(eq(ld(0),1),174.61,if(eq(ld(0),2),261.63,196))));"
        "st(3,if(eq(ld(0),0),261.63,if(eq(ld(0),1),220,if(eq(ld(0),2),329.63,246.94))));"
        "st(4,if(eq(ld(0),0),329.63,if(eq(ld(0),1),261.63,if(eq(ld(0),2),392,293.66))));"
        "ld(1)*0.22*(sin(2*PI*ld(2)*t)+sin(2*PI*ld(3)*t)+sin(2*PI*ld(4)*t))"
        "+ld(1)*0.06*(sin(2*PI*(ld(2)+0.7)*t)+sin(2*PI*(ld(4)+0.7)*t))"
    )
    return f"aevalsrc='{expr}':s=48000"


def mux_audio(silent_video, narration, out_path, cfg):
    """Silent video + narration (+ optional bgm) -> final mp4."""
    eff = cfg.get("effects", {})
    use_bgm = bool(eff.get("bgm", True))
    bgm_vol = float(eff.get("bgm_volume", 0.10))
    abr = eff.get("audio_bitrate", "192k")

    if use_bgm:
        fc = (
            f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[nar];"
            f"[2:a]volume={bgm_vol}[bed];"
            f"[nar][bed]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
        cmd = [FFMPEG, "-y", "-i", str(silent_video), "-i", str(narration),
               "-f", "lavfi", "-i", _bgm_source(),
               "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", abr, "-ar", "48000", "-ac", "2",
               "-shortest", "-movflags", "+faststart", str(out_path)]
    else:
        cmd = [FFMPEG, "-y", "-i", str(silent_video), "-i", str(narration),
               "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]",
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
               "-b:a", abr, "-ar", "48000", "-ac", "2",
               "-shortest", "-movflags", "+faststart", str(out_path)]
    run(cmd)
    return str(out_path)

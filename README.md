# 🇺🇸 USA News Automation

**Fully automated USA news video channel.** Google News (US) RSS → AI hook-style
script → images → English narration → FFmpeg edit → YouTube upload.

Ek command (ya GitHub Actions schedule) se rozana US news ki videos apne aap ban
jaati hain aur YouTube pe chali jaati hain.

> 📊 **Workflow diagram:** [`docs/workflow.html`](docs/workflow.html) — kholne ke liye
> file ko browser me open karo.

---

## Pipeline (ek nazar me)

```
Google News (US) RSS ─► picker/history ─► AI scriptwriter (hook) ─► images
        │                                                              │
        ▼                                                              ▼
   [ Top/NATION/BUSINESS ]                         [ stock API → web → Pollinations ]
                                                                       │
   YouTube upload ◄── FFmpeg editor ◄── narration (edge-tts) ◄─────────┘
```

Har stage me **primary + fallback** chain hai — koi ek key na ho to bhi video ban jaati hai:

| Stage | Primary | Fallbacks |
|---|---|---|
| Script | Gemini (`GEMINI_API_KEY`) | Pollinations free LLM → Khushi AI (apna repo) |
| Images | "pixals" stock API (`STOCK_API_KEY`) | web image search → **Pollinations AI generate** |
| Narration | edge-tts (en-US news voice, free) | gTTS → Google Translate TTS → apna HF Space → Gemini TTS |
| Edit | FFmpeg (Ken Burns + overlays + BGM) | imageio-ffmpeg bundled binary |
| Upload | YouTube Data API v3 | retries |

---

## Video me kya hota hai

- **Intro card** — channel name + headline (hook narration ke saath)
- **Har scene** — AI image pe halka zoom/pan (Ken Burns) + colour grade + sharpen
- **Top headline bar** — us khabar ka asli headline (red accent)
- **Time-synced captions** — jo voice bolti hai wahi bottom pe dikhta hai
- **Channel lower-third** — branding
- **Background music** — 100% copyright-free (ffmpeg synth), narration ke neeche
- Output: **1920×1080, 30fps**, ~45–70 seconds, stereo audio

---

## Quick start (local)

```bash
git clone https://github.com/sudhansh37/usa-news-automation.git
cd usa-news-automation
pip install -r requirements.txt

# 2 videos banao (upload nahi)
python main.py --count 2 --out output

# banao + YouTube pe upload karo
python main.py --count 1 --upload
```

Bina kisi API key ke bhi chalta hai (Pollinations free LLM + image, edge-tts narration).

## GitHub Actions (recommended — automatic)

1. Repo → **Settings ▸ Secrets and variables ▸ Actions** → ye secrets add karo
   (jo abhi nahi hain wo baad me):
   - `GEMINI_API_KEY` — script + (optional) TTS rewrite
   - `STOCK_API_KEY` — "pixals" stock image API
   - `HF_TOKEN` — apna narration HF Space (optional)
   - `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` — YouTube upload
2. Workflow `.github/workflows/daily.yml` rozana 3 baar (IST ~2:30pm, 7:30pm, 1:00am)
   automatically chalega. Manual run ke liye **Actions ▸ Daily US News Video ▸ Run workflow**.

---

## Configuration — `config.yaml`

Sab kuch ek file se control hota hai:

- `news.feeds` — Google News US RSS feeds (Top / NATION / BUSINESS…)
- `news.videos_per_run`, `max_items`, `exclude_keywords`
- `script.provider`, `scenes`, `target_seconds`, `tone`
- `images.providers` — `["stock","web","pollinations"]` order
- `images.stock.kind` — `pexels` / `pixabay` / `custom` (apni "pixals" service)
- `tts.providers`, `tts.edge_tts.voice` (male/female news voice)
- `effects` — zoom, colour, crf/preset, BGM volume, fps
- `overlay` — headline bar / captions / lower-third / intro card on/off
- `youtube` — privacy, category_id, tags, AI disclosure

---

## Project layout

```
usa-news-automation/
├── main.py                 # entrypoint (CLI)
├── config.yaml             # sab settings
├── .env.example            # secrets template
├── src/
│   ├── config.py           # config + env loader
│   ├── news_feed.py        # Google News (US) RSS
│   ├── scriptwriter.py     # AI rewrite (Gemini / Pollinations / Khushi)
│   ├── images.py           # stock → web → Pollinations
│   ├── tts.py              # edge-tts / gTTS / GTX / HF Space / Gemini
│   ├── overlays.py         # PIL: banner, captions, lower-third, intro card
│   ├── editor.py           # FFmpeg: Ken Burns, concat, mux
│   ├── uploader.py         # YouTube Data API v3
│   ├── history.py          # seen-news dedupe
│   └── pipeline.py         # orchestrator
├── docs/workflow.html      # workflow diagram
└── .github/workflows/daily.yml
```

---

## Notes

- **Khushi AI** (repo: [`khushi-ai`](https://github.com/sudhansh37/khushi-ai)) ko
  scriptwriter ke roop me use kar sakte ho — usko kahin host karke
  `KHUSHI_BASE_URL` set kar do (OpenAI-compatible endpoint).
- **Apna narration HF Space** use karna ho to `tts.hf_space.space` set karo aur
  `HF_TOKEN` do.
- **Images:** Pollinations ke generated images ka bottom-right watermark automatic
  trim hota hai.
- Ye repo tumhare `yt-auto-video` pipeline ke conventions pe bana hai (config.yaml +
  provider chains + GitHub Actions), sirf news ke liye.

MIT License.

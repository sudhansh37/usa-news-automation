"""USA News Automation - entrypoint.

Examples:
  python main.py --count 2                 # 2 videos banao (upload nahi)
  python main.py --count 1 --upload        # banao + YouTube pe daalo
  python main.py --out output              # videos ko output/ me rakho
"""
import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.config import load_config  # noqa: E402
from src.pipeline import run_once  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="USA news -> YouTube automation")
    ap.add_argument("--config", default=None)
    ap.add_argument("--count", type=int, default=None, help="kitni videos")
    ap.add_argument("--upload", action="store_true", help="YouTube pe upload karo")
    ap.add_argument("--out", default=None, help="output folder")
    ap.add_argument("--work", default=None, help="working folder")
    args = ap.parse_args()

    cfg = load_config(args.config)
    count = args.count or int(cfg.get("news", {}).get("videos_per_run", 1))
    do_upload = args.upload or os.environ.get("UPLOAD") == "1"

    print(f"USA News Automation - {count} video(s), upload={do_upload}")
    results = run_once(cfg, count=count, do_upload=do_upload,
                       out_dir=args.out, work_root=args.work)
    print(f"\nDone. {len(results)} video(s) banayi.")
    for r in results:
        print(f"  - {r['title']}  ->  {r['out']}")


if __name__ == "__main__":
    main()

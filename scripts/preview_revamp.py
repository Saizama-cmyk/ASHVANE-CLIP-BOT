"""Run an isolated preview with capture, model downloads, and publishing disabled."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipbot.app import ClipBotApp, setup_logging
from clipbot.config import Settings, merge_incoming, save_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--data", default=str(Path(__file__).resolve().parents[1] / "artifacts" / "preview-data"))
    args = parser.parse_args()
    os.environ["CLIPBOT_HOME"] = args.data
    settings = merge_incoming(Settings(), {"dashboard": {"port": args.port},
                                          "twitch": {"enabled": False}, "kick": {"enabled": False},
                                          "clip_import": {"enabled": False}, "trends": {"enabled": False},
                                          "research": {"enabled": False}, "analytics": {"enabled": False},
                                          "ai": {"auto_pull": False}, "app": {"start_with_windows": False}})
    save_settings(settings)
    setup_logging(settings, console=True)
    asyncio.run(ClipBotApp(settings).run())


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import os
from pathlib import Path


def resolve_env_path() -> Path:
    """Resolve the .env path: ENV_FILE env var > --env-file CLI flag > nearest .env from cwd."""
    env_file_var = os.environ.get("ENV_FILE")
    if env_file_var:
        return Path(env_file_var)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=str, default=None)
    try:
        # parse_known_args() still raises SystemExit for a malformed value on a
        # recognized flag (e.g. bare trailing "--env-file" with nothing after it) — this
        # runs on every ConfigManager init, so a stray CLI arg must never crash the app.
        args, _ = parser.parse_known_args()
    except SystemExit:
        args = argparse.Namespace(env_file=None)
    if args.env_file:
        return Path(args.env_file)
    from dotenv import find_dotenv

    found = find_dotenv(usecwd=True)
    return Path(found) if found else Path(".env")

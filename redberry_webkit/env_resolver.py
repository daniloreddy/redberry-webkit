import argparse
import os
from pathlib import Path


def resolve_env_path() -> Path:
    env_file_var = os.environ.get("ENV_FILE")
    if env_file_var:
        return Path(env_file_var)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=str, default=None)
    args, _ = parser.parse_known_args()
    if args.env_file:
        return Path(args.env_file)
    from dotenv import find_dotenv

    found = find_dotenv(usecwd=True)
    return Path(found) if found else Path(".env")

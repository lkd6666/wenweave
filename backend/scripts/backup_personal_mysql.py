"""Export the configured MySQL database without exposing credentials in arguments."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the configured MySQL database")
    parser.add_argument("--mysqldump", type=Path, required=True, help="Path to mysqldump executable")
    parser.add_argument("--output", type=Path, required=True, help="Destination SQL dump")
    args = parser.parse_args()

    if not args.mysqldump.is_file():
        raise RuntimeError("mysqldump executable was not found")

    url = make_url(get_settings().DATABASE_URL)
    if not url.drivername.startswith("mysql") or not url.database:
        raise RuntimeError("DATABASE_URL must point to a MySQL database")

    command = [
        str(args.mysqldump),
        "--single-transaction",
        "--routines",
        "--events",
        "--triggers",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--set-gtid-purged=OFF",
        "--host",
        url.host or "127.0.0.1",
        "--user",
        url.username or "",
    ]
    if url.port:
        command.extend(("--port", str(url.port)))
    command.append(url.database)

    environment = os.environ.copy()
    if url.password is not None:
        environment["MYSQL_PWD"] = url.password

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.PIPE, env=environment, check=True)
    print(f"MySQL backup written to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace").strip()
        print(f"mysqldump failed: {message or exc.returncode}", file=sys.stderr)
        raise SystemExit(1)

"""Forward-only dbmate runner; never puts a connection URL in process arguments/logs."""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env.local", override=False)
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Missing MIGRATION_DATABASE_URL; migration blocked")
    bundled = ROOT / ".tools/dbmate.exe"
    binary = os.environ.get(
        "DBMATE_BIN", str(bundled) if bundled.exists() else "dbmate"
    )
    env = dict(os.environ, DATABASE_URL=url)
    try:
        result = subprocess.run(
            [
                binary,
                "--no-dump-schema",
                "--migrations-dir",
                str(ROOT / "db/migrations"),
                "migrate",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        raise SystemExit(
            "dbmate unavailable; install the documented pinned release"
        ) from None
    # Raw dbmate diagnostics can contain a DSN: no forwarding output.
    if result.returncode:
        raise SystemExit(
            "Migration failed; inspect diagnostics privately (credentials suppressed)"
        )
    print("Forward-only migrations applied successfully")


if __name__ == "__main__":
    main()

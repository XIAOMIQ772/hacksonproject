#!/bin/sh
# Usage: reference-apps/pack.sh <app-dir> <out.zip> — wrap a hand-written app as a copy-only agent.
set -e
APP=$(cd "$1" && pwd); OUT=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); B=$(mktemp -d)
mkdir -p "$B/app"
rsync -a --exclude node_modules --exclude dist --exclude .arc-test-db --exclude test-results \
  --exclude playwright-report --exclude '*.db' --exclude '*.db-journal' --exclude .DS_Store "$APP/" "$B/app/"
cat > "$B/main.py" <<'PY'
import shutil, sys
from pathlib import Path

out = Path(sys.argv[sys.argv.index("--output-dir") + 1]) if "--output-dir" in sys.argv else Path(".")
out.mkdir(parents=True, exist_ok=True)
for item in (Path(__file__).resolve().parent / "app").iterdir():
    if item.is_dir():
        shutil.copytree(item, out / item.name, dirs_exist_ok=True)
    else:
        shutil.copy2(item, out / item.name)
print("reference app copied to", out, flush=True)
PY
: > "$B/requirements.txt"
rm -f "$OUT"; (cd "$B" && zip -qr "$OUT" .)
rm -rf "$B"; echo "packed $OUT"

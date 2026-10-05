#!/usr/bin/env bash
#
# Build "Karaoke Grabber.app" and open it, using the project's virtualenv.
#
# Run it from anywhere — it finds its own project directory:
#
#     ~/Development/karaoke-grabber/run.sh
#
# This is a script, so the virtualenv it activates lives only inside this
# process. When it finishes you are back in your normal shell with nothing
# to "deactivate".
#
set -euo pipefail

# --- locate the project: this script's own directory, resolving symlinks ---
src="${BASH_SOURCE[0]}"
while [ -h "$src" ]; do
  dir="$(cd -P "$(dirname "$src")" && pwd)"
  src="$(readlink "$src")"
  [[ $src == /* ]] || src="$dir/$src"
done
PROJECT_DIR="$(cd -P "$(dirname "$src")" && pwd)"
cd "$PROJECT_DIR"

APP="dist/Karaoke Grabber.app"

# --- make sure the virtualenv exists ---
if [ ! -x .venv/bin/python ]; then
  if ! command -v python3.14 >/dev/null 2>&1; then
    echo "run.sh: need Python 3.14 from python.org to create the virtualenv — see README.md" >&2
    exit 1
  fi
  echo "run.sh: no .venv found, creating one…"
  python3.14 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements-dev.txt
fi

# --- activate, build, open ---
# shellcheck source=/dev/null
source .venv/bin/activate
./build.sh
open "$APP"

echo "run.sh: opened $APP"

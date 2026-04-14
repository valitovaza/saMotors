#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "${PYTHON_BIN:-}" ]; then
  echo "No suitable Python interpreter found."
  exit 1
fi

cd "$ROOT_DIR"

TARGET_PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
RECREATE_VENV=0

if [ -d "$VENV_DIR" ]; then
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    RECREATE_VENV=1
  else
    CURRENT_VENV_VERSION="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [ "$CURRENT_VENV_VERSION" != "$TARGET_PY_VERSION" ]; then
      RECREATE_VENV=1
    fi
  fi
fi

if [ "$RECREATE_VENV" -eq 1 ]; then
  rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
if ! python - <<'PY' >/dev/null 2>&1
import importlib.util
modules = ["fastapi", "uvicorn", "openpyxl", "multipart", "pydantic"]
missing = [name for name in modules if importlib.util.find_spec(name) is None]
raise SystemExit(0 if not missing else 1)
PY
then
  python -m pip install --upgrade pip
  python -m pip install -r "$ROOT_DIR/requirements.txt"
fi
python "$ROOT_DIR/scripts/bootstrap.py"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

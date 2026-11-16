#!/usr/bin/env bash
set -euo pipefail
BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND"

find_python() {
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version="$($candidate -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
      major="${version%.*}"; minor="${version#*.}"
      if (( major > 3 || (major == 3 && minor >= 11) )); then echo "$candidate"; return 0; fi
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(find_python)"; then
  OS="$(uname -s)"
  case "$OS" in
    Darwin)
      if ! command -v brew >/dev/null 2>&1; then
        echo 'Install Homebrew first: https://brew.sh/' >&2
        exit 1
      fi
      echo 'Installing Python 3.12 with Homebrew...'
      brew install python@3.12
      PYTHON_BIN="$(command -v python3.12 || true)"
      ;;
    Linux)
      echo 'Python 3.11+ is required. This installer can install distro packages if available.'
      if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
      elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --needed --noconfirm python python-pip
      elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3 python3-pip
      else
        echo 'Unsupported package manager. Install Python 3.11+ and venv support manually.' >&2
        exit 1
      fi
      PYTHON_BIN="$(find_python || true)"
      ;;
    *) echo "Unsupported operating system: $OS" >&2; exit 1 ;;
  esac
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo 'Python 3.11+ was not found after package installation. Install it manually and rerun.' >&2
  exit 1
fi
"$PYTHON_BIN" --version
if [[ ! -f .env ]]; then "$PYTHON_BIN" setup.py; fi
if [[ ! -x .venv/bin/python ]]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo 'RIS dependencies installed. Start RIS with ./start_unix.sh'

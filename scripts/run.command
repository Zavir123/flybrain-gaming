#!/bin/sh
# macOS / Linux: bootstraps only the project-local environment.
set -e
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import pygame, numpy, scipy, pyarrow' >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip --upgrade
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python main.py "$@"

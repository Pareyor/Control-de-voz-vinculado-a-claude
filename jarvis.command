#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python jarvis.py "$@"

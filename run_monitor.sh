#!/bin/bash
unset PYTHONPATH
uv run python monitor_playlist.py "$@"

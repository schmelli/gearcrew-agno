#!/bin/bash
unset PYTHONPATH
uv run streamlit run streamlit_app.py "$@"

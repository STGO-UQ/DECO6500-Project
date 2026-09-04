#!/usr/bin/env sh
set -e
if [ ! -d .venv ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
  python -m playwright install chromium
else
  . .venv/bin/activate
fi
python -m app init
exec uvicorn app.main:app --reload

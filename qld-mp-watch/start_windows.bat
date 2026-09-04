@echo off
if not exist .venv (
  py -m venv .venv
  call .venv\Scripts\activate
  python -m pip install -r requirements.txt
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate
)
python -m app init
uvicorn app.main:app --reload

@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Creating Python environment...
  py -m venv .venv
  call .venv\Scripts\activate
  python -m pip install -r requirements.txt
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate
)

python -m app init
python -m app members
python -m app attendance
python -m app votes

echo.
echo Parliament attendance and voting update finished.
pause

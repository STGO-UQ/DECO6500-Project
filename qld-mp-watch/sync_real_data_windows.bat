@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Setting up Python environment first...
  py -m venv .venv
  if errorlevel 1 goto :error
  call .venv\Scripts\activate
  python -m pip install -r requirements.txt
  if errorlevel 1 goto :error
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate
)

python -m app init

echo.
echo [1/4] Refreshing current Queensland MPs...
python -m app members

echo.
echo [2/4] Scraping official sitting attendance from Hansard...
python -m app attendance

echo.
echo [3/4] Scraping recorded divisions and Aye/No/Pair data from Hansard...
python -m app votes

echo.
echo [4/4] Downloading ECQ public gift disclosures...
python -m app donations
if errorlevel 1 (
  echo.
  echo ECQ automatic download did not complete. Parliament attendance and vote data may still be loaded.
  echo You can export Gifts as CSV from the ECQ public EDS and run:
  echo   python -m app donations --csv "C:\path\to\your\ecq-gifts.csv"
)

echo.
echo Data sync finished. Start the website with start_windows.bat
pause
exit /b 0

:error
echo.
echo Setup failed. Copy the error above into ChatGPT and I can diagnose it.
pause
exit /b 1

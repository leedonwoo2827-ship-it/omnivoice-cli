@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem 장치(cuda) · 모델 캐시 · 목소리 · W1 시험 합성
if not exist .venv\Scripts\python.exe (
  echo [doctor] .venv 가 없습니다. 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m omnivoice_tts doctor
echo.
.venv\Scripts\python.exe -m omnivoice_tts voices
.venv\Scripts\python.exe -m omnivoice_tts dict status
pause

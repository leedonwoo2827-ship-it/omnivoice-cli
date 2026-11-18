@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem 사내 다른 PC 에서도 쓰게 연다 — 비밀번호는 config\share_token.txt (처음 한 번 자동 생성)
if not exist .venv\Scripts\python.exe (
  echo [run-share] .venv 가 없습니다. 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
if not defined OMNIVOICE_TTS_PORT set "OMNIVOICE_TTS_PORT=7879"
echo [run-share] 아래에 찍히는 주소(?token=...)를 다른 PC 에 보내 주세요. 이 창을 닫으면 서버가 꺼집니다.
start "" "http://localhost:%OMNIVOICE_TTS_PORT%"
.venv\Scripts\python.exe -m omnivoice_tts serve --share
pause

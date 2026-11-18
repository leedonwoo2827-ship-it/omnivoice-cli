@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem OmniVoice TTS 웹 화면 + HTTP API — http://localhost:7879
if not exist .venv\Scripts\python.exe (
  echo [run] .venv 가 없습니다. 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
if not defined OMNIVOICE_TTS_PORT set "OMNIVOICE_TTS_PORT=7879"
echo [run] 탭: 한 개 합성 / 대본 일괄 / 발음 사전   (API 문서 http://localhost:%OMNIVOICE_TTS_PORT%/docs)
echo [run] 첫 합성 때 모델을 GPU 에 올리느라 20초쯤 걸립니다. 이 창을 닫으면 서버가 꺼집니다.
start "" "http://localhost:%OMNIVOICE_TTS_PORT%"
.venv\Scripts\python.exe -m omnivoice_tts serve
pause

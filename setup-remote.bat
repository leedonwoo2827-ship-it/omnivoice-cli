@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem GPU 없는 PC용 — 합성은 코랩 T4 서버에 맡기고, 이 PC 에는 가벼운 것만 설치합니다 (torch 없음)
if not exist .venv\Scripts\python.exe (
  echo [setup] 가상환경 생성 ^(.venv^)
  py -3.12 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install numpy soundfile || exit /b 1
echo [setup] 완료. 코랩 서버 노트북을 켠 뒤:
echo   omnivoice say "안녕하세요" -r voice_01.wav --server ^<주소^> --token ^<비밀번호^>

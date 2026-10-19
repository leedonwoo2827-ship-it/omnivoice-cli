@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem 사용법: setup.bat [cuda^|cpu^|xpu]   (기본 cuda = NVIDIA GPU)
set "DEV=%~1"
if "%DEV%"=="" set "DEV=cuda"

if /i "%DEV%"=="cuda" (
  where nvidia-smi >nul 2>&1 || (
    echo [setup] NVIDIA GPU를 찾지 못했습니다. GPU가 없으면 setup-cpu.bat 을 쓰세요.
    exit /b 1
  )
  set "TORCH=torch==2.8.0+cu128 torchaudio==2.8.0+cu128"
  set "INDEX=https://download.pytorch.org/whl/cu128"
) else if /i "%DEV%"=="cpu" (
  set "TORCH=torch==2.8.0 torchaudio==2.8.0"
  set "INDEX=https://download.pytorch.org/whl/cpu"
) else if /i "%DEV%"=="xpu" (
  set "TORCH=torch==2.8.0 torchaudio==2.8.0"
  set "INDEX=https://download.pytorch.org/whl/xpu"
) else (
  echo [setup] 알 수 없는 장치: %DEV%  ^(cuda / cpu / xpu^)
  exit /b 2
)

if not exist .venv\Scripts\python.exe (
  echo [setup] 가상환경 생성 ^(.venv^)
  py -3.12 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)

echo [setup] PyTorch 설치 ^(%DEV%, 수 GB일 수 있습니다^)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install %TORCH% --index-url %INDEX% || exit /b 1

echo [setup] OmniVoice 설치
.venv\Scripts\python -m pip install -r requirements.txt || exit /b 1

.venv\Scripts\python -c "import omnivoice_cli as c, omnivoice; print('[setup] OK  장치:', c.resolve_device('%DEV%'))" || exit /b 1
echo [setup] 완료. 예: omnivoice say "안녕하세요" -r voice_01.wav -o hello.wav

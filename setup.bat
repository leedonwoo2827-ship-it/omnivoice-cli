@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo [setup] NVIDIA GPU를 찾지 못했습니다. OmniVoice는 CUDA GPU가 필요합니다.
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo [setup] 가상환경 생성 ^(.venv^)
  py -3.12 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)

echo [setup] PyTorch 2.8 + CUDA 12.8 설치 ^(수 GB, 몇 분 걸립니다^)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128 || exit /b 1

echo [setup] OmniVoice 설치
.venv\Scripts\python -m pip install -r requirements.txt || exit /b 1

.venv\Scripts\python -c "import torch, omnivoice; print('[setup] OK  torch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0))" || exit /b 1
echo [setup] 완료. 예: omnivoice say "안녕하세요" -r voice_01.wav -o hello.wav

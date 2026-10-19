# omnivoice-cli

[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)를 쓰는 보이스 클로닝 CLI입니다. 3~10초짜리 내 목소리 wav 하나만 있으면, 텍스트를 그 목소리로 읽은 wav 파일을 만들어 줍니다.

- 하나의 코드로 **NVIDIA GPU / Intel Arc GPU / CPU**에서 돌아갑니다. 장치별로 다른 것은 설치 스크립트뿐입니다.
- 브라우저에서 쓰려면 [`OmniVoice_Colab.ipynb`](OmniVoice_Colab.ipynb)를 Google Colab에 올리세요. T4나 A100에서 돌아갑니다.

## 설치

```bat
git clone https://github.com/leedonwoo2827-ship-it/omnivoice-cli
cd omnivoice-cli
setup.bat
```

PC에 맞는 설치 스크립트를 하나만 실행하세요.

| PC | 설치 | 속도 (실측) |
|---|---|---|
| NVIDIA GPU | `setup.bat` (CUDA 12.8) | RTX 4070 Laptop: 1.9초 음성을 3.1초에 생성 |
| GPU 없음 | `setup-cpu.bat` | 노트북 CPU: 2.3초 음성을 30.8초에 생성 (약 13배 느림) |
| Intel Arc GPU | `setup-xpu.bat` (Intel GPU 드라이버 필요) | 확인하지 못함 |

내려받는 양이 몇 GB라 시간이 좀 걸립니다. 모델(약 3GB)은 처음 합성할 때 HuggingFace 캐시로 받습니다.

실행 장치는 자동으로 고릅니다(cuda → xpu → mps → cpu 순서). 장치를 직접 지정하려면 `--device cpu`처럼 붙이세요. CPU에서는 float32로, GPU에서는 float16으로 돌립니다.

## 사용법

아래 예시에서 `omnivoice`는 `omnivoice.bat`을 가리킵니다. `.venv` 안의 파이썬으로 `omnivoice_cli.py`를 실행합니다.

```bat
:: 문장 하나 → wav 하나
omnivoice say "안녕하세요. 제 목소리로 읽어 봅니다." -r voice_01.wav -o hello.wav

:: 긴 원고는 파일로 넘기고, 다 만들면 바로 재생
omnivoice say -f script.txt -r voice_01.wav -o lesson.wav --play

:: 대본 파일에서 한 줄에 한 문장씩 → 문장별 wav + 이어 붙인 all.wav
omnivoice batch script.txt -r voice_01.wav -o outputs\lesson1 --gap 0.4

:: 목소리를 .pt 파일로 저장 → 다음부터는 받아쓰기 없이 바로 합성
omnivoice prompt -r voice_01.wav -o my_voice.pt
omnivoice say "다시 만났네요" -r my_voice.pt
```

| 옵션 | 설명 |
|---|---|
| `-d, --device` | `auto`(기본) / `cuda` / `xpu` / `mps` / `cpu` |
| `-r, --ref` | 레퍼런스 음성 wav(3~10초, 잡음 없이) 또는 `prompt`로 저장한 `.pt` |
| `--ref-text` | 레퍼런스에서 실제로 말한 문장. 생략하면 Whisper가 자동으로 받아씁니다. 정확하게 적어 주면 품질이 좋아집니다. |
| `--speed` | 말 빠르기. 기본 1.0 |
| `--steps` | 생성 스텝. 32는 품질 우선(기본), 16은 속도 우선 |
| `--no-cache` | 목소리를 처음부터 다시 등록 |

wav를 레퍼런스로 주면 받아쓰기와 인코딩 결과가 `%USERPROFILE%\.cache\omnivoice-cli\`에 캐시됩니다. 그래서 두 번째 실행부터는 Whisper를 다시 띄우지 않습니다. 결과물은 24kHz 모노 PCM 16비트 wav입니다.

## 팁

- 긴 원고를 `say`로 한 번에 생성하면 뒷부분 품질이 떨어질 수 있습니다. 그럴 때는 `batch`로 문장 단위로 만드세요.
- 텍스트 안에 `[laughter]` 같은 비언어 태그를 넣을 수 있습니다.
- 개인 목소리 파일(`*.wav`, `*.pt`)은 `.gitignore`에 들어 있어 저장소에 올라가지 않습니다.

## 라이선스

이 CLI 코드는 MIT입니다. 모델과 라이브러리 라이선스는 [OmniVoice](https://github.com/k2-fsa/OmniVoice)를 따릅니다.

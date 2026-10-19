# GPU 없는 PC + 코랩 T4로 쓰기

GPU가 없는 PC에서 직접 합성하면 아주 느립니다. 이 PC의 CPU로 재 보니 2.3초짜리 음성에 31초가 걸렸습니다.

그래서 합성은 **코랩 T4**에 맡기고, PC에서는 명령을 보내고 wav 파일만 받습니다.

```
[내 PC (CPU)]  omnivoice say "…" --server <주소> --token <비밀번호>
      │  텍스트 + 내 목소리 wav 를 보냄
      ▼
[코랩 T4]  OmniVoice_Colab_Server.ipynb  (GitHub 소스로 서버 실행)
      │  합성한 wav 를 돌려줌
      ▼
[내 PC]  hello.wav 저장
```

---

## 처음 한 번만: PC 준비

1. 저장소를 받습니다.
   ```bat
   git clone https://github.com/leedonwoo2827-ship-it/omnivoice-cli
   cd omnivoice-cli
   ```
2. 가벼운 설치 스크립트를 실행합니다. torch를 설치하지 않으므로 1분 정도면 끝납니다.
   ```bat
   setup-remote.bat
   ```
3. 내 목소리 wav(3~10초)를 이 폴더에 둡니다. 예: `voice_01.wav`

## 쓸 때마다: 코랩 서버 켜기

1. 아래 버튼을 눌러 서버 노트북을 엽니다. GitHub에서 바로 열리므로 파일을 업로드할 필요가 없습니다.

   [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leedonwoo2827-ship-it/omnivoice-cli/blob/main/OmniVoice_Colab_Server.ipynb)

2. **런타임 → 런타임 유형 변경 → T4 GPU**를 고르고 저장합니다.
3. **1 → 2 → 3번 셀**을 차례로 ▶ 실행합니다.
   - 2번 셀은 GitHub 소스를 받고 OmniVoice를 설치합니다. 2~3분 걸립니다.
   - 3번 셀은 서버를 띄웁니다. 첫 실행 때는 모델을 내려받느라 2~3분 걸립니다. 준비가 끝나면 아래와 같은 안내가 나옵니다.
     ```
     ======================================================================
       OmniVoice 서버 준비됨 (cuda)
       주소     : https://xxxx-xxxx-xxxx.trycloudflare.com
       비밀번호 : AbCdEf123456
     ...
     ```
4. 3번 셀은 **계속 실행 중인 상태로 둡니다.** 멈추면 서버도 꺼집니다.

## PC에서 합성하기

코랩에 나온 주소와 비밀번호를 붙여 넣습니다.

```bat
omnivoice say "안녕하세요. 코랩에서 만든 제 목소리입니다." -r voice_01.wav -o hello.wav ^
  --server https://xxxx-xxxx-xxxx.trycloudflare.com --token AbCdEf123456

:: 대본 파일에서 한 줄에 한 문장씩 → 문장별 wav + 이어 붙인 all.wav
omnivoice batch 대본.txt -r voice_01.wav -o outputs\lesson1 --server <주소> --token <비밀번호>
```

비밀번호를 매번 적기 번거로우면 환경변수로 설정해 두세요. 그러면 `--token`을 생략할 수 있습니다.

```bat
set OMNIVOICE_TOKEN=AbCdEf123456
```

그 밖의 옵션(`--speed`, `--steps`, `--ref-text`, `--play`)은 로컬에서 쓸 때와 같습니다.

---

## 알아둘 점

- **주소는 매번 바뀝니다.** 코랩 런타임이 끊기거나 3번 셀을 다시 실행하면 새 주소가 나옵니다. 그때마다 PC 명령의 `--server`를 바꿔 주세요.
- **비밀번호를 고정하려면** 3번 셀의 `TOKEN` 칸에 원하는 값을 적어 두세요. 주소는 여전히 바뀝니다.
- **보안**
  - 주소는 인터넷에 공개됩니다. 하지만 비밀번호가 맞아야만 합성하고, 틀리면 401 오류로 거절합니다.
  - 주소와 비밀번호를 남에게 알려 주지 마세요.
  - 다 쓴 뒤에는 3번 셀을 멈추거나 런타임을 종료하세요.
- **내 목소리 wav는 합성할 때마다 코랩으로 전송됩니다.** 목소리 등록(받아쓰기)은 처음 한 번만 하고, 다음부터는 코랩 안의 캐시를 씁니다. 코랩 런타임이 끝나면 이 캐시도 사라집니다.
- **한 요청은 5,000자까지**입니다. 긴 원고는 `batch`로 문장 단위로 보내세요. 품질도 더 안정적입니다.
- 임시 주소는 cloudflared의 무료 Quick Tunnel로 만듭니다. 계정은 필요 없습니다.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| `서버에 연결하지 못했습니다` | 코랩 3번 셀이 아직 실행 중인지, 주소를 정확히 붙여 넣었는지 |
| `서버 오류 401 … (--token 확인)` | 비밀번호 오타. 3번 셀을 다시 실행했다면 새 비밀번호가 나왔을 수 있습니다 |
| `서버 오류 500 … CUDA out of memory` | 텍스트가 너무 깁니다. `batch`로 나눠 보내세요 |
| 3번 셀에 주소가 안 나옴 | 1번 셀에서 T4가 잡혔는지 확인하고, 3번 셀을 다시 실행하세요 |

## 같은 네트워크 안에서 쓰기 (선택)

사무실에 GPU PC가 한 대 있으면, 코랩 대신 그 PC를 서버로 쓸 수 있습니다.

- **GPU PC:** `.venv\Scripts\python omnivoice_server.py --host 0.0.0.0 --port 8765 --token 비밀번호`
- **다른 PC:** `omnivoice say "…" -r voice_01.wav --server http://<GPU PC IP>:8765 --token 비밀번호`

Windows 방화벽에서 8765 포트를 허용해야 할 수 있습니다.

# OmniVoice TTS

[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)(제로샷 보이스 클로닝)로 **등록한 목소리 그대로** 글을 읽어 주는 앱입니다. 음성(wav)과 자막(SRT)을 한 번에 만듭니다. 모든 제작 도구(요약반 영상, 문제풀이 영상, 강의 노트 듣기 검수 등)가 같은 목소리와 같은 발음 사전을 쓰도록 한 곳에 모았습니다.

- **목소리 등록부**: `voices/<코드>/` 폴더 하나가 목소리 하나입니다. 첫 목소리 **W1** 은 `voice_01.wav` 입니다(backplate 요약반과 같은 소리).
- **웹 화면** `run.bat` → http://localhost:7879 에는 **한 개 합성 · 대본 일괄 · 발음 사전** 탭이 있습니다.
- **발음 본사전** 하나를 여러 영상 앱의 사전과 **[업데이트] / [다운받기]** 로 오갑니다.
- **HTTP API · 파이썬 패키지**로 다른 앱과 에이전트가 가져다 씁니다.
- GPU 없는 PC 는 **코랩 T4 원격 합성**을 씁니다. 예전 CLI(`omnivoice.bat say/batch/prompt`)도 그대로 동작합니다.

## 설치

```bat
setup.bat          :: NVIDIA GPU (CUDA 12.8, torch 2.8.0)
setup-cpu.bat      :: GPU 없음 — 이 PC 에서 직접 (매우 느림)
setup-xpu.bat      :: Intel Arc GPU
setup-remote.bat   :: GPU 없음 + 코랩 T4 서버 (torch 없이 가볍게, 예전 CLI 용)
```

`setup.bat` 이 하는 일은 다음과 같습니다.
1. `.venv` 가 없으면 만듭니다. 있으면 그대로 씁니다.
2. 장치에 맞는 torch 를 설치합니다.
3. `omnivoice` 와 이 앱을 설치합니다(`pip install -e .[dev]`).
4. 점검을 돌립니다.

모델(약 3GB)은 첫 합성 때 HuggingFace 캐시로 받습니다.

| PC | 속도 (실측) |
|---|---|
| RTX 4070 Laptop | 모델 로드 약 16초. 그 뒤 4.7초 음성을 3.5초에 만듭니다 |
| 노트북 CPU | 2.3초 음성을 30.8초에 만듭니다 (약 13배 느림) |

## 쓰기

```bat
run.bat        :: 브라우저가 열리고 서버가 뜹니다(이 PC 전용). 창을 닫으면 꺼집니다
run-share.bat  :: 같은 화면을 사내 다른 PC 에도 비밀번호를 걸고 엽니다 (아래 「사내 다른 PC」)
doctor.bat     :: 장치(cuda) · 모델 캐시 · 목소리 · 발음 사전 · W1 시험 합성
```

- **한 개 합성**: 발음(TTS 입력)과 자막(SRT 출력)을 따로 고칠 수 있습니다. 「한국어 발음 전환」으로 실제로 읽힐 글을 미리 봅니다.
- **대본 일괄**: 대본 JSON 을 끌어놓으면 장면 카드가 나옵니다. 장면마다 다시 합성할 수 있고, 전체를 zip 으로 받습니다. 결과는 `workspace/ch{NN}/audio/*.wav` 와 `subtitles/*.srt` 에 저장됩니다.
- **발음 사전**: 본사전을 편집합니다. 저장하면 다음 합성부터 바로 반영되고, 다른 앱 사전과 오갈 수 있습니다(아래 설명).
- **왼쪽 사이드바**:
  - 목소리를 고르면 스텝과 속도가 그 목소리의 설정값으로 바뀝니다.
  - ▶ 로 미리 들어 봅니다.
  - **+ 목소리 추가** 로 새 목소리를 등록합니다.

### 명령 (`.venv\Scripts\omnivoice-tts.exe` 또는 `python -m omnivoice_tts`)

```bat
omnivoice-tts synth "안녕하세요 [laughter] 반갑습니다." -v W1 -o hello.wav [--speed 1.0 --steps 32]
omnivoice-tts batch ch05_script.json [--voice W1 --output-root D:\out]
omnivoice-tts voices                       :: 목소리 목록
omnivoice-tts voices add W2 my.wav --name "차분한 해설" --ref-text "녹음에서 말한 문장"
omnivoice-tts dict status                  :: 연결된 앱 사전과 본사전의 차이
omnivoice-tts dict push backplate-요약반   :: [업데이트]
omnivoice-tts dict pull backplate-요약반   :: [다운받기]
omnivoice-tts doctor
omnivoice-tts serve [--host 0.0.0.0 --port 7879]
```

## 대본 JSON

```json
{
  "chapter": 5,
  "scenes": [
    { "scene": 1, "narration_text": "읽을 문장", "srt_text": "자막 문장(생략 시 위와 같음)", "voice_style": "W1" }
  ]
}
```

- 꼭 필요한 것은 `scene` 과 `narration_text` 뿐입니다. 별칭도 받습니다: `text`·`narration` / `scene_number` / `subtitle_text` / `duration`.
- `voice_style` 에는 목소리 코드를 적거나, `config/voice_map.yaml` 의 이름(narrator 등)을 적습니다. 모르는 이름이면 기본 목소리(W1)로 읽고 경고를 띄웁니다.
- 자막 시간은 **실제 음성 길이**에 맞춥니다. 자막에는 발음 변환 전 원문이 들어가고, `[태그]` 는 빠집니다.

## 발음 본사전과 앱 사전 오가기

본사전은 `config/pronunciation_map.yaml` 하나입니다. 처음 만들 때 backplate 사전과 슈퍼토닉3 사전을 합쳤습니다(413개, 값이 다르면 backplate 값). 합성 직전에 다음 순서로 바꿉니다.
1. 사전에 있는 말을 바꿉니다. 긴 키부터 맞추고, 영문 키는 "CERN의" 처럼 조사가 붙어도 맞습니다.
2. 사전에 없는 대문자 약어는 한 글자씩 읽습니다(ABC → 에이비씨).
3. 연도와 숫자+단위를 한글로 읽습니다(1989년 → 천구백팔십구년).

`[대괄호]` 는 건드리지 않습니다.

영상 앱마다 따로 있는 사전은 「발음 사전」 탭의 **다른 앱 사전과 오가기**에서 연결합니다.

| 버튼 | 하는 일 |
|---|---|
| **↑ 업데이트** | 그 앱에서 **지난 동기화 이후 바뀐 것만** 본사전에 올립니다(새로 넣은 것·바꾼 것·지운 것) |
| **↓ 다운받기** | 작업 시작 전에 본사전 전체를 그 앱 사전 파일로 받습니다. 받기 전 파일은 `config/dict_base/backup/` 에 남깁니다. 그 앱의 머리말 주석과 파일 모양(`rules:` 아래 / 맨 위에 나열)은 그대로 둡니다 |

- 양쪽에서 같은 말을 다르게 고쳤으면 **충돌**로 보여 줍니다. 「앱 / 본사전」 중에서 고르고 업데이트하면 됩니다. 고르지 않은 충돌은 그대로 남습니다.
- 아직 올리지 않은 변경이 있으면 다운받기가 멈춥니다. 덮어써서 잃지 않게 하려는 것입니다.
- 「이 PC 에서 후보 찾기」를 누르면 `D:\00work` 아래에서 발음 사전처럼 보이는 파일을 찾아 줍니다.
- 문법이 깨진 사전 파일도 깨진 줄만 건너뛰고 읽습니다. 다운받기를 하면 올바른 파일로 다시 씁니다.

## 표현 태그 (OmniVoice 형식 = 대괄호)

`[laughter]` `[sigh]` `[surprise-ah]` `[surprise-oh]` `[surprise-wa]` `[surprise-yo]` `[question-ah]` `[question-oh]` `[question-ei]` `[question-yi]` `[question-en]` `[confirmation-en]` `[dissatisfaction-hnn]` 의 13종입니다. 출처는 `omnivoice` 0.2.1 의 `_NONVERBAL_PATTERN` 입니다.

- 슈퍼토닉의 `<laugh>` 꺾쇠 형식은 글자로 읽힙니다. 화면에서 경고하니 `[laughter]` 로 바꾸세요.
- `[breath]` 는 없습니다.
- `[B EY1 S]` 처럼 대괄호 안에 CMU 발음 기호를 적어 영어 발음을 직접 지정할 수도 있습니다.

## 목소리 추가와 튜닝

1. **녹음**: 3~10초, 조용한 곳에서 한 사람이 또박또박 말한 wav 하나를 준비합니다. 20초가 넘으면 앞부분만 씁니다. 실제 내레이션과 같은 말투로 녹음하면 결과도 그 말투가 됩니다.
2. **등록**: 화면 사이드바의 **+ 목소리 추가**를 쓰거나 `omnivoice-tts voices add W2 my.wav`. 그러면 아래 파일들이 생깁니다.
   ```
   voices/W2/ref.wav      기준 녹음
   voices/W2/ref.txt      녹음에서 실제로 말한 문장 (비우면 Whisper 가 받아씀 — 정확히 적으면 품질↑)
   voices/W2/voice.yaml   name · gender · speed · steps · memo (· ref_audio: 다른 자리 wav)
   ```
3. **튜닝**: 같은 문장을 사이드바에서 목소리·speed·steps 만 바꿔 가며 들어 봅니다. 마음에 드는 값은 `voice.yaml` 의 `speed`·`steps` 에 적어 둡니다. 우선순위는 요청 값 → voice.yaml → 기본값(1.0 / 32)입니다.
4. **녹음을 바꿨으면**: 따로 할 일이 없습니다. 캐시 이름에 녹음+문장의 해시가 들어 있어서 다음 합성 때 새로 등록됩니다.
5. **기본 목소리를 바꾸려면**: `config/voice_map.yaml` 의 `default` 를 고치거나, 환경변수 `OMNIVOICE_TTS_DEFAULT_VOICE` 를 씁니다.

목소리 프롬프트 캐시는 `%USERPROFILE%\.cache\omnivoice-cli\<녹음 이름>_<해시>.pt` 입니다. 예전 CLI 와 backplate 도 이 캐시를 같이 씁니다. W1 은 `voice_01.wav` 를 **복사하지 않고 그대로 가리키므로**(`ref_audio: ../../voice_01.wav`) 캐시 파일이 backplate 와 같습니다.

## 다른 앱·에이전트에서 부르기

### HTTP API (추천)

`run.bat` 으로 띄워 두면 부르는 쪽에 torch 가 필요 없습니다. 모델은 이 앱 하나만 GPU 에 올립니다. 전체 목록과 시험 호출은 http://localhost:7879/docs 에 있습니다.

| 메서드 · 경로 | 보내는 것 | 받는 것 |
|---|---|---|
| `POST /api/synthesize` | JSON `{text, voice?, speed?, steps?, lang?}` | wav (24kHz 16bit 모노). 헤더 `X-Audio-Seconds` `X-Synth-Seconds` `X-Voice` `X-Speed` `X-Steps` |
| `POST /api/batch` | form: `script`(대본 JSON 파일), `chapter?` `output_root?` `voice_override?` `speed?` `steps?` | `{job_id, status_url}` |
| `GET /api/jobs/{id}` · `/zip` | — | 진행 상태 / 결과 wav+srt zip |
| `POST /api/synthesize_scene` | form: `chapter, scene, text, srt_text?, voice?, speed?, steps?, output_root?` | `{wav_url, srt_url, cues, duration_seconds}` |
| `GET /api/voices` · `POST /api/voices` | (추가는 form: `code, wav, name?, gender?, ref_text?, speed?, steps?, memo?`) | 목소리 목록 / 등록 결과 |
| `POST /api/to_pronunciation` | `{text}` | 합성 직전과 같은 발음 변환 결과 |
| `GET /api/dict` · `POST /api/dict` · `DELETE /api/dict/{key}` | `{key, value}` | 본사전 |
| `GET /api/dict/links` · `POST /api/dict/links/{id}/push` · `/pull` | — | 앱 사전 [업데이트]/[다운받기] |
| `GET /api/health` | — | 장치 · 엔진 상태 · 목소리 목록 |

PowerShell 에서 부르는 예:

```powershell
$body = @{ text = "안녕하세요. W1 목소리입니다."; voice = "W1" } | ConvertTo-Json
Invoke-WebRequest http://localhost:7879/api/synthesize -Method Post -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes($body)) -OutFile hello.wav
```

curl 에서 부르는 예입니다. Windows 에서는 한글을 명령줄에 바로 쓰면 깨지므로 **UTF-8 파일로** 보내세요.

```bat
curl -X POST http://localhost:7879/api/synthesize -H "Content-Type: application/json; charset=utf-8" --data-binary @req.json -o out.wav
```

Python(`requests`) 에서 부르는 예:

```python
import requests
r = requests.post("http://localhost:7879/api/synthesize", json={"text": "안녕하세요", "voice": "W1"})
open("out.wav", "wb").write(r.content)
```

**사내 다른 PC 에서 쓰게 하려면 `run-share.bat`**: 기본(`run.bat`)은 이 PC 에서만 열립니다. `run-share.bat` 은 비밀번호를 걸고 사내망에 엽니다. 비밀번호는 `config/share_token.txt` 에 처음 한 번 만들어지고, 지우면 새로 만듭니다. 창을 켜 두는 동안만 열리고, 닫으면 바로 막힙니다. 창에 다음 주소가 찍힙니다.

```
다른 PC 브라우저 : http://<이 PC IP>:7879/?token=<비밀번호>   ← 한 번 열면 그 브라우저가 기억
다른 PC 프로그램 : http://<이 PC IP>:7879/api/synthesize  + 헤더 Authorization: Bearer <비밀번호>
```

다른 PC 에서 만든 음성은 **그 PC 로 바로 내려받습니다**.
- 한 개 합성 탭에서는 「⬇ WAV 다운로드」와 「⬇ SRT 자막 다운로드」를 씁니다.
- 대본 일괄 탭에서는 장면 카드마다 받거나 「📦 전체 zip」으로 한꺼번에 받습니다.

합성은 이 PC 의 GPU 가 하고, 대본 일괄 결과는 이 PC 의 `workspace\ch{NN}\` 에도 남습니다.

열리는 것은 이 앱(화면·합성·사전)뿐이고, 이 PC 의 터미널이나 다른 파일에 접근할 수는 없습니다. 비밀번호 없이 오면 화면도 API 도 막습니다. GPU 가 하나라서 여러 PC 가 동시에 요청하면 차례로 합성합니다.

### 파이썬 패키지

```bat
<다른 앱 venv>\Scripts\python -m pip install -e D:\00work\261118-OmniVoice
```
```python
from omnivoice_tts import synth, synth_script, list_voices, to_pronunciation
wav, sr = synth("안녕하세요", voice="W1", out="hello.wav")
synth_script("ch05_script.json", out_dir="workspace")
```

이 방법은 부르는 쪽 venv 에도 torch(CUDA)가 있어야 합니다. 목소리와 본사전은 언제나 이 폴더 것을 씁니다. 찾는 순서는 `OMNIVOICE_TTS_HOME` → 설치 위치 → 이 폴더에서 serve/doctor 를 한 번 돌리면 적히는 `%USERPROFILE%\.omnivoice-tts-home` 입니다.

## GPU 없는 PC — 코랩 원격 합성

코랩에서 `OmniVoice_Colab_Server.ipynb` 를 켜면 주소와 비밀번호가 나옵니다([설명서](docs/colab-remote.md)).
- **이 앱을 원격으로 돌릴 때**: `set OMNIVOICE_TTS_SERVER=<주소>` 와 `set OMNIVOICE_TTS_SERVER_TOKEN=<비밀번호>` 를 지정한 뒤 `run.bat` 을 실행합니다. 화면과 API 가 그대로 동작하고, 합성만 코랩이 합니다.
- **예전 CLI 로 돌릴 때**: `omnivoice say "안녕하세요" -r voice_01.wav --server <주소> --token <비밀번호>`

| 노트북 | 용도 |
|---|---|
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leedonwoo2827-ship-it/omnivoice-cli/blob/main/OmniVoice_Colab_Server.ipynb) `OmniVoice_Colab_Server.ipynb` | 코랩을 합성 서버로 띄웁니다 |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/leedonwoo2827-ship-it/omnivoice-cli/blob/main/OmniVoice_Colab.ipynb) `OmniVoice_Colab.ipynb` | 코랩 화면에서 텍스트를 넣으면 음성 파일이 나옵니다 |

## 예전 CLI (그대로 동작)

backplate 등이 쓰는 경로와 사용법은 바꾸지 않았습니다. `omnivoice.bat` → `omnivoice_cli.py` 이고, `.venv\Scripts\python.exe` 와 루트의 `voice_01.wav` 도 그대로입니다.

```bat
omnivoice say "안녕하세요" -r voice_01.wav -o hello.wav [--speed 1.0 --steps 32 --device cuda --play]
omnivoice batch script.txt -r voice_01.wav -o outputs\lesson1 --gap 0.4
omnivoice prompt -r voice_01.wav -o my_voice.pt
```

## 폴더

```
src/omnivoice_tts/   engine(합성) voices(등록부) pronunciation·dictsync(사전) tags srt batch server/ web/ cli
voices/W1/           첫 목소리 (voice_01.wav 를 가리킴)
config/              pronunciation_map.yaml(본사전) voice_map.yaml  · dict_links.yaml·dict_base/ (로컬, git 제외)
workspace/           합성 결과 (git 제외)
tests/               python -m pytest   ·  실제 모델까지: set OMNIVOICE_RUN_SMOKE=1
omnivoice_cli.py · omnivoice_server.py · omnivoice.bat   예전 CLI · 코랩 서버
```

## 라이선스

이 앱 코드는 MIT 입니다. 모델과 라이브러리는 [OmniVoice](https://github.com/k2-fsa/OmniVoice)(Apache-2.0) 를 따릅니다. 웹 화면 일부는 같은 저자의 슈퍼토닉3 TTS 앱(MIT)에서 가져왔습니다. 개인 목소리 파일(`*.wav`, `*.pt`)은 `.gitignore` 에 들어 있어 저장소에 올라가지 않습니다.

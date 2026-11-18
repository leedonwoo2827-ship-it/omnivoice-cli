"""설정 — 모두 환경변수(OMNIVOICE_TTS_*)로 바꿀 수 있고, 매 요청마다 다시 읽는다.

## 집(home) 폴더
목소리(`voices/`)와 발음 본사전(`config/`)은 **한 곳**에 두고 모든 앱이 같이 쓴다.
그 자리를 이렇게 찾는다.

1. `OMNIVOICE_TTS_HOME` 환경변수
2. 이 파일 위로 올라가며 `pyproject.toml` 의 이름이 omnivoice-tts 인 폴더
   (`pip install -e` 로 설치했으면 여기서 찾힌다)
3. `~/.omnivoice-tts-home` 파일에 적힌 경로 — 집 폴더에서 serve/doctor 를
   한 번이라도 돌리면 적어 둔다. 다른 앱의 venv 에 일반 설치했을 때 쓰인다.
4. 그래도 없으면 현재 폴더
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HOME_POINTER = Path.home() / ".omnivoice-tts-home"
MODEL_ID = "k2-fsa/OmniVoice"
SAMPLE_RATE = 24000


def _is_home(p: Path) -> bool:
    pp = p / "pyproject.toml"
    if not pp.is_file():
        return False
    try:
        return 'name = "omnivoice-tts"' in pp.read_text(encoding="utf-8")
    except OSError:
        return False


def find_home() -> Path:
    env = os.environ.get("OMNIVOICE_TTS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if _is_home(parent):
            return parent
    try:
        pointed = Path(HOME_POINTER.read_text(encoding="utf-8").strip())
        if pointed.is_dir():
            return pointed
    except OSError:
        pass
    return Path.cwd()


def remember_home(home: Path) -> None:
    """다른 venv 에 설치된 패키지도 이 집을 찾게 경로를 적어 둔다."""
    try:
        if _is_home(home) and (not HOME_POINTER.is_file()
                               or HOME_POINTER.read_text(encoding="utf-8").strip() != str(home)):
            HOME_POINTER.write_text(str(home), encoding="utf-8")
    except OSError:
        pass


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    home: Path
    voices_dir: Path
    voice_map_path: Path
    pronunciation_map_path: Path
    dict_links_path: Path
    dict_base_dir: Path
    workspace_root: Path
    prompt_cache_dir: Path
    device: str
    default_voice: str
    default_speed: float
    default_steps: int
    max_chars: int
    batch_chunk_size: int
    host: str
    port: int
    token: str
    remote_server: str
    remote_token: str

    @property
    def project_root(self) -> Path:  # 슈퍼토닉 코드와의 호환 이름
        return self.home


def load() -> Settings:
    home = find_home()
    return Settings(
        home=home,
        voices_dir=_env_path("OMNIVOICE_TTS_VOICES", home / "voices"),
        voice_map_path=_env_path("OMNIVOICE_TTS_VOICE_MAP", home / "config" / "voice_map.yaml"),
        pronunciation_map_path=_env_path("OMNIVOICE_TTS_PRONUNCIATION_MAP", home / "config" / "pronunciation_map.yaml"),
        dict_links_path=home / "config" / "dict_links.yaml",
        dict_base_dir=home / "config" / "dict_base",
        workspace_root=_env_path("OMNIVOICE_TTS_WORKSPACE", home / "workspace"),
        # omnivoice_cli.py · backplate 브리지와 같은 캐시 자리 (규칙도 같다)
        prompt_cache_dir=_env_path("OMNIVOICE_CLI_CACHE", Path.home() / ".cache" / "omnivoice-cli"),
        device=_env("OMNIVOICE_TTS_DEVICE", "auto"),
        default_voice=_env("OMNIVOICE_TTS_DEFAULT_VOICE", "W1"),
        default_speed=float(_env("OMNIVOICE_TTS_SPEED", "1.0")),
        default_steps=int(_env("OMNIVOICE_TTS_STEPS", "32")),
        max_chars=int(_env("OMNIVOICE_TTS_MAX_CHARS", "200")),
        batch_chunk_size=int(_env("OMNIVOICE_TTS_BATCH_CHUNK", "4")),
        host=_env("OMNIVOICE_TTS_HOST", "127.0.0.1"),
        port=int(_env("OMNIVOICE_TTS_PORT", "7879")),
        token=_env("OMNIVOICE_TTS_TOKEN", ""),
        remote_server=_env("OMNIVOICE_TTS_SERVER", ""),
        remote_token=_env("OMNIVOICE_TTS_SERVER_TOKEN", _env("OMNIVOICE_TOKEN", "")),
    )

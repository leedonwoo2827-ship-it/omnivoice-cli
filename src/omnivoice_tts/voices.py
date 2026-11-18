"""목소리 = 기준 녹음 등록부.

    voices/<코드>/voice.yaml   이름·성별·speed·steps·메모 (+ ref_audio 로 다른 자리 wav 지정 가능)
    voices/<코드>/ref.wav      3~10초 기준 녹음 (잡음 없이)
    voices/<코드>/ref.txt      그 녹음에서 실제로 말한 문장. 비우면 Whisper 가 받아쓴다.

새 목소리는 폴더 하나 추가로 끝난다. 목록은 부를 때마다 폴더를 다시 훑으므로
서버를 다시 켜지 않아도 된다.

★ W1 은 `ref_audio: ../../voice_01.wav` 로 **루트의 voice_01.wav 를 그대로** 가리킨다.
  복사하면 파일 이름이 바뀌어 프롬프트 캐시(`voice_01_<해시>.pt`)를 backplate 와
  같이 쓰지 못하고, Whisper 받아쓰기도 다시 돈다.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,23}$")


@dataclass(frozen=True)
class Voice:
    code: str
    name: str
    gender: str
    ref_audio: Path
    ref_text: str
    speed: float | None
    steps: int | None
    language: str | None
    memo: str
    folder: Path

    @property
    def ok(self) -> bool:
        return self.ref_audio.is_file()

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "gender": self.gender,
            "speed": self.speed, "steps": self.steps, "language": self.language,
            "memo": self.memo, "ref_audio": str(self.ref_audio),
            "ref_text": self.ref_text, "ref_ok": self.ok,
        }


def _load_one(folder: Path) -> Voice | None:
    meta_p = folder / "voice.yaml"
    if not meta_p.is_file():
        return None
    try:
        meta = yaml.safe_load(meta_p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice.yaml 읽기 실패 (%s): %s", meta_p, exc)
        return None
    ref = Path(str(meta.get("ref_audio") or "ref.wav"))
    ref = (folder / ref).resolve() if not ref.is_absolute() else ref
    txt_p = folder / "ref.txt"
    ref_text = txt_p.read_text(encoding="utf-8").strip() if txt_p.is_file() else ""

    def num(key, cast):
        v = meta.get(key)
        return None if v in (None, "") else cast(v)

    return Voice(
        code=folder.name.upper(),
        name=str(meta.get("name") or folder.name),
        gender=str(meta.get("gender") or ""),
        ref_audio=ref,
        ref_text=ref_text,
        speed=num("speed", float),
        steps=num("steps", int),
        language=(str(meta["language"]) if meta.get("language") else None),
        memo=str(meta.get("memo") or ""),
        folder=folder,
    )


def list_voices(voices_dir: Path) -> list[Voice]:
    if not voices_dir.is_dir():
        return []
    out = [v for d in sorted(voices_dir.iterdir()) if d.is_dir() and (v := _load_one(d))]
    return out


def get_voice(voices_dir: Path, code: str) -> Voice:
    code = (code or "").strip().upper()
    for v in list_voices(voices_dir):
        if v.code == code:
            return v
    have = ", ".join(v.code for v in list_voices(voices_dir)) or "(없음)"
    raise KeyError(f"알 수 없는 목소리: {code}. 등록된 목소리: {have}")


def add_voice(voices_dir: Path, code: str, wav: Path | bytes, *, name: str = "",
              gender: str = "", ref_text: str = "", speed: float | None = None,
              steps: int | None = None, memo: str = "") -> Voice:
    """voices/<코드>/ 를 만든다. 같은 코드가 있으면 거절한다."""
    code = (code or "").strip().upper()
    if not CODE_RE.match(code):
        raise ValueError("코드는 영문으로 시작하는 짧은 이름이어야 합니다 (예: W2, KIM)")
    folder = voices_dir / code
    if folder.exists():
        raise FileExistsError(f"이미 있는 목소리입니다: {code}")
    folder.mkdir(parents=True)
    try:
        if isinstance(wav, (bytes, bytearray)):
            (folder / "ref.wav").write_bytes(wav)
        else:
            shutil.copyfile(wav, folder / "ref.wav")
        meta = {"name": name or code, "gender": gender, "speed": speed, "steps": steps, "memo": memo}
        (folder / "voice.yaml").write_text(
            yaml.safe_dump({k: v for k, v in meta.items() if v not in (None, "")},
                           allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        (folder / "ref.txt").write_text(ref_text.strip(), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return get_voice(voices_dir, code)


@dataclass
class VoiceMap:
    """대본의 voice_style(예: narrator) → 목소리 코드."""
    default: str
    styles: dict[str, str] = field(default_factory=dict)
    known: set[str] = field(default_factory=set)

    def resolve(self, voice_style: str | None) -> tuple[str, str | None]:
        key = (voice_style or "").strip()
        if not key:
            return self.default, None
        if key.upper() in self.known:
            return key.upper(), None
        if key.lower() in self.styles:
            return self.styles[key.lower()], None
        return self.default, f"모르는 voice_style '{voice_style}' → {self.default} (기본)"


def load_voice_map(path: Path, voices_dir: Path, default: str = "W1") -> VoiceMap:
    known = {v.code for v in list_voices(voices_dir)}
    data = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dflt = str(data.get("default") or default).upper()
    styles = {}
    for k, v in (data.get("styles") or {}).items():
        code = str(v).upper()
        if known and code not in known:
            logger.warning("voice_map.yaml styles.%s=%s — 없는 목소리라 무시", k, v)
            continue
        styles[str(k).strip().lower()] = code
    return VoiceMap(default=dflt, styles=styles, known=known)

"""OmniVoice 엔진 — 슈퍼토닉3 `Engine` 과 같은 모양(synth_timed · synth_batch_same_voice).

합성 한 번의 흐름

    글 → 발음 사전(대괄호 보호) → 길면 문장 단위로 묶기 → model.generate(조각마다) → 잇기

★ backplate(`scripts/tts_bridge_omnivoice.py`)와 같은 소리가 나야 한다. 그래서
  - 장치·dtype 규칙, 프롬프트 캐시 이름 규칙은 `omnivoice_cli.py` 와 똑같다.
  - 발음 변환 옵션(spell_unknown_acronyms, convert_years)도 브리지와 같다.
  - max_chars(기본 200자) 이하의 글은 쪼개지 않고 한 번에 넘긴다 = 브리지와 같은 호출.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from . import settings as settings_module
from . import tags
from .pronunciation import PronunciationMap, load_pronunciation_map
from .voices import Voice, get_voice

logger = logging.getLogger(__name__)

SAMPLE_RATE = settings_module.SAMPLE_RATE

_SENT_END_RE = re.compile(r"(?<=[.!?。！？…])\s+|\n+")
_COMMA_RE = re.compile(r"(?<=[,，、])\s+")


# ---------------------------------------------------------------- 공용 규칙

def cache_path(ref: Path, ref_text: str | None, cache_dir: Path) -> Path:
    """`omnivoice_cli._cache_path` 와 같은 규칙 — 바꾸면 backplate 와 캐시를 못 나눈다."""
    h = hashlib.sha1(Path(ref).read_bytes())
    h.update((ref_text or "").encode("utf-8"))
    return Path(cache_dir) / f"{Path(ref).stem}_{h.hexdigest()[:12]}.pt"


def resolve_device(want: str = "auto") -> str:
    """auto 면 cuda → xpu → mps → cpu 순으로 쓸 수 있는 것."""
    import torch

    has = {
        "cuda": torch.cuda.is_available(),
        "xpu": hasattr(torch, "xpu") and torch.xpu.is_available(),
        "mps": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
        "cpu": True,
    }
    want = (want or "auto").lower()
    if want == "auto":
        return next(d for d in ("cuda", "xpu", "mps", "cpu") if has[d])
    if want not in has:
        raise ValueError(f"알 수 없는 장치: {want} (auto/cuda/xpu/mps/cpu)")
    if not has[want]:
        raise RuntimeError(f"{want} 장치를 쓸 수 없습니다. 그 장치용 setup 으로 torch 를 설치했는지 확인하세요.")
    return want


def split_for_tts(text: str, max_chars: int = 200) -> list[str]:
    """max_chars 이하면 그대로 한 조각. 넘으면 문장(→쉼표) 단위로 max_chars 까지 묶는다."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sents: list[str] = []
    for sent in _SENT_END_RE.split(text):
        sent = (sent or "").strip()
        if not sent:
            continue
        if len(sent) <= max_chars:
            sents.append(sent)
        else:
            sents.extend(p.strip() for p in _COMMA_RE.split(sent) if p.strip())

    out: list[str] = []
    cur = ""
    for s in sents:
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= max_chars:
            cur = f"{cur} {s}"
        else:
            out.append(cur)
            cur = s
    if cur:
        out.append(cur)

    # 태그만 남은 조각은 앞(맨 앞이면 뒤) 조각에 붙인다
    merged: list[str] = []
    for piece in out:
        if merged and not tags.strip(piece).strip(" .,!?;:…"):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    if len(merged) > 1 and not tags.strip(merged[0]).strip(" .,!?;:…"):
        merged[1] = f"{merged[0]} {merged[1]}"
        merged.pop(0)
    return merged


# ---------------------------------------------------------------- 백엔드

class Backend(Protocol):
    device: str
    device_name: str

    def prompt(self, voice: Voice, cache_dir: Path) -> Any: ...
    def generate(self, text: str, prompt: Any, *, speed: float, steps: int, lang: str | None) -> np.ndarray: ...


class LocalBackend:
    """이 PC 의 GPU(없으면 CPU)에서 OmniVoice 를 돌린다."""

    def __init__(self, want_device: str = "auto"):
        import torch
        from omnivoice import OmniVoice

        dev = resolve_device(want_device)
        self.device = dev
        self.device_name = {
            "cuda": lambda: torch.cuda.get_device_name(0),
            "xpu": lambda: torch.xpu.get_device_name(0),
        }.get(dev, lambda: dev.upper())()
        dtype = torch.float16 if dev in ("cuda", "xpu") else torch.float32
        device_map = f"{dev}:0" if dev in ("cuda", "xpu") else dev
        logger.info("OmniVoice 모델 로드 중… (%s)", self.device_name)
        t0 = time.time()
        # Whisper 는 받아쓰기가 필요할 때 create_voice_clone_prompt 가 알아서 올린다
        self.model = OmniVoice.from_pretrained(settings_module.MODEL_ID, device_map=device_map,
                                               dtype=dtype, load_asr=False)
        logger.info("모델 로드 완료 (%.1f초)", time.time() - t0)

    def prompt(self, voice: Voice, cache_dir: Path):
        from omnivoice import VoiceClonePrompt

        if voice.ref_audio.suffix.lower() == ".pt":
            return VoiceClonePrompt.load(str(voice.ref_audio))
        cached = cache_path(voice.ref_audio, voice.ref_text, cache_dir)
        if cached.is_file():
            return VoiceClonePrompt.load(str(cached))
        logger.info("목소리 등록 중: %s%s", voice.code, "" if voice.ref_text else " (Whisper 받아쓰기)")
        p = self.model.create_voice_clone_prompt(ref_audio=str(voice.ref_audio),
                                                 ref_text=voice.ref_text or None)
        cached.parent.mkdir(parents=True, exist_ok=True)
        p.save(str(cached))
        return p

    def generate(self, text, prompt, *, speed, steps, lang):
        kw = {"language": lang} if lang else {}
        wav = self.model.generate(text=text, voice_clone_prompt=prompt, speed=speed, num_step=steps, **kw)[0]
        return np.asarray(wav, dtype=np.float32).reshape(-1)


# ---------------------------------------------------------------- 엔진

class Engine:
    _instance: "Engine | None" = None
    _init_lock = threading.Lock()

    def __init__(self, backend: Backend | None = None):
        s = settings_module.load()
        if backend is None:
            if s.remote_server:
                from .remote import RemoteBackend
                backend = RemoteBackend(s.remote_server, s.remote_token)
            else:
                backend = LocalBackend(s.device)
        self.backend = backend
        self.sample_rate = SAMPLE_RATE
        self.device = backend.device
        self.device_name = backend.device_name
        self.use_gpu_active = backend.device in ("cuda", "xpu", "mps") or backend.device.startswith("remote")
        self.providers = [self.device_name]          # 슈퍼토닉 코드 호환
        self._lock = threading.Lock()
        self._prompts: dict[str, Any] = {}
        self._pmap: PronunciationMap | None = None
        self._pmap_key: tuple[str, float] = ("", -1.0)

    # --- 싱글턴
    @classmethod
    def get_sync(cls) -> "Engine":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    async def get(cls) -> "Engine":
        if cls._instance is not None:
            return cls._instance
        return await asyncio.to_thread(cls.get_sync)

    @classmethod
    def loaded(cls) -> bool:
        return cls._instance is not None

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # --- 발음
    def _get_pmap(self) -> PronunciationMap:
        path = settings_module.load().pronunciation_map_path
        mtime = path.stat().st_mtime if path.exists() else 0.0
        if self._pmap is None or self._pmap_key != (str(path), mtime):
            self._pmap = load_pronunciation_map(path)
            self._pmap_key = (str(path), mtime)
            logger.info("발음 사전 %d개 규칙 (%s)", len(self._pmap.rules), path)
        return self._pmap

    def prepare_text(self, text: str) -> str:
        """합성에 실제로 들어가는 글. 대괄호(태그·발음 지정)는 그대로 둔다."""
        return self._get_pmap().apply(text or "", spell_unknown_acronyms=True, convert_years=True)

    # --- 목소리
    def voice(self, code: str | None) -> Voice:
        s = settings_module.load()
        return get_voice(s.voices_dir, code or s.default_voice)

    def _prompt_for(self, v: Voice):
        s = settings_module.load()
        key = str(v.ref_audio) if v.ref_audio.suffix.lower() == ".pt" else \
            str(cache_path(v.ref_audio, v.ref_text, s.prompt_cache_dir))
        if key not in self._prompts:
            if not v.ok:
                raise FileNotFoundError(f"{v.code} 의 기준 녹음이 없습니다: {v.ref_audio}")
            self._prompts[key] = self.backend.prompt(v, s.prompt_cache_dir)
        return self._prompts[key]

    def resolve_params(self, v: Voice, speed: float | None, steps: int | None) -> tuple[float, int]:
        s = settings_module.load()
        sp = speed if speed is not None else (v.speed if v.speed is not None else s.default_speed)
        st = steps if steps is not None else (v.steps if v.steps is not None else s.default_steps)
        return float(sp), int(st)

    # --- 합성
    def synth_sync(self, text: str, *, voice_code: str | None = None, speed: float | None = None,
                   steps: int | None = None, lang: str | None = None,
                   total_step: int | None = None) -> tuple[np.ndarray, dict]:
        if steps is None and total_step is not None:   # 슈퍼토닉 이름도 받는다
            steps = total_step
        v = self.voice(voice_code)
        sp, st = self.resolve_params(v, speed, steps)
        lg = lang or v.language
        spoken = self.prepare_text(text)
        pieces = split_for_tts(spoken, settings_module.load().max_chars)
        meta = {"voice": v.code, "speed": sp, "steps": st, "lang": lg or "auto",
                "tags": tags.find(spoken), "pieces": len(pieces)}
        if not pieces:
            return np.zeros(0, dtype=np.float32), {**meta, "synth_seconds": 0.0,
                                                    "duration_seconds": 0.0, "rtf": 0.0}
        t0 = time.perf_counter()
        with self._lock:
            prompt = self._prompt_for(v)
            parts = [self.backend.generate(p, prompt, speed=sp, steps=st, lang=lg) for p in pieces]
        elapsed = time.perf_counter() - t0
        out = np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, dtype=np.float32)
        dur = len(out) / self.sample_rate
        return out, {**meta, "synth_seconds": round(elapsed, 3), "duration_seconds": round(dur, 3),
                     "rtf": round(dur / elapsed, 2) if elapsed > 0 else 0.0}

    async def synth_timed(self, text: str, *, voice_code: str | None = None, speed: float | None = None,
                          steps: int | None = None, lang: str | None = None,
                          total_step: int | None = None) -> tuple[np.ndarray, dict]:
        return await asyncio.to_thread(self.synth_sync, text, voice_code=voice_code, speed=speed,
                                       steps=steps, lang=lang, total_step=total_step)

    async def synth(self, text: str, **kw) -> np.ndarray:
        wav, _ = await self.synth_timed(text, **kw)
        return wav

    async def synth_batch_same_voice(self, text_list: list[str], *, voice_code: str | None = None,
                                     speed: float | None = None, steps: int | None = None,
                                     lang: str | None = None, total_step: int | None = None) -> list[np.ndarray]:
        out = []
        for t in text_list:
            out.append(await self.synth(t, voice_code=voice_code, speed=speed, steps=steps,
                                        lang=lang, total_step=total_step))
        return out

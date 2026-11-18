"""OmniVoice TTS — 이 PC 의 목소리(W1 …)로 음성 + 자막.

다른 앱·에이전트에서 파이썬으로 바로 쓸 때:

    from omnivoice_tts import synth, synth_script, list_voices, to_pronunciation

    wav, sr = synth("안녕하세요", voice="W1")               # numpy float32, 24000
    synth("안녕하세요", out="hello.wav")                      # 파일로
    res = synth_script("ch01.json", out_dir="workspace")    # 장면별 wav + SRT

이렇게 쓰려면 부르는 쪽 환경에 torch(CUDA)가 있어야 한다. 없으면 HTTP API
(`run.bat` 로 띄운 http://localhost:7879/api/synthesize)를 부르는 편이 가볍다.
목소리·발음 본사전은 집 폴더(OMNIVOICE_TTS_HOME, 기본은 이 프로젝트) 것을 같이 쓴다.
"""
from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["synth", "synth_script", "list_voices", "to_pronunciation", "__version__"]


def synth(text: str, voice: str | None = None, *, speed: float | None = None, steps: int | None = None,
          lang: str | None = None, out: str | None = None):
    """글 → (wav, sample_rate). out 을 주면 wav 파일도 쓴다."""
    from .audio_io import write_wav
    from .engine import Engine

    eng = Engine.get_sync()
    wav, _ = eng.synth_sync(text, voice_code=voice, speed=speed, steps=steps, lang=lang)
    if out:
        write_wav(out, wav, eng.sample_rate)
    return wav, eng.sample_rate


def synth_script(script, out_dir: str | None = None, *, voice: str | None = None, speed: float | None = None,
                 steps: int | None = None, chapter: str | int | None = None):
    """대본 JSON(경로·문자열·dict) → <out_dir>/ch{NN}/audio/*.wav + subtitles/*.srt."""
    import asyncio
    import json
    from pathlib import Path

    from .batch import parse_script, run_batch
    from .engine import Engine

    hint = None
    if isinstance(script, dict):
        raw = json.dumps(script, ensure_ascii=False)
    elif isinstance(script, str) and not script.lstrip().startswith("{"):
        hint = Path(script).name
        raw = Path(script).read_text(encoding="utf-8")
    else:
        raw = script
    return asyncio.run(run_batch(engine=Engine.get_sync(), script=parse_script(raw), chapter_id_explicit=chapter,
                                 filename_hint=hint, output_root=Path(out_dir) if out_dir else None,
                                 voice_override=voice, speed=speed, steps=steps))


def list_voices() -> list[dict]:
    from . import settings
    from .voices import list_voices as _lv

    return [v.to_dict() for v in _lv(settings.load().voices_dir)]


def to_pronunciation(text: str) -> str:
    """합성 직전과 같은 발음 변환(본사전 + 약어 음역 + 숫자)."""
    from . import settings
    from .pronunciation import load_pronunciation_map

    return load_pronunciation_map(settings.load().pronunciation_map_path).apply(
        text, spell_unknown_acronyms=True, convert_years=True)

import os
from pathlib import Path

import pytest

from omnivoice_tts import settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "ch99_script.json"


def test_home_from_env(home):
    s = settings.load()
    assert s.home == home and s.voices_dir == home / "voices" and s.port == 7879 and s.host == "127.0.0.1"


def test_home_found_from_package_location(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_TTS_HOME", raising=False)
    assert settings.find_home() == ROOT


def test_public_synth_and_script(fake_engine, home, tmp_path):
    from omnivoice_tts import list_voices, synth, synth_script, to_pronunciation

    wav, sr = synth("안녕하세요", out=str(tmp_path / "a.wav"))
    assert sr == 24000 and len(wav) > 0 and (tmp_path / "a.wav").is_file()
    assert [v["code"] for v in list_voices()] == ["W1"]
    assert to_pronunciation("MOOC") == "무크"
    res = synth_script(str(FIXTURE), out_dir=str(tmp_path / "out"))
    assert res.chapter_id == "99" and len(res.files) == 3


def test_voices_add_rejects_bad_code(home, make_wav):
    from omnivoice_tts.voices import add_voice

    with pytest.raises(ValueError):
        add_voice(home / "voices", "2bad", make_wav())
    with pytest.raises(FileExistsError):
        add_voice(home / "voices", "w1", make_wav())


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OMNIVOICE_RUN_SMOKE") != "1", reason="OMNIVOICE_RUN_SMOKE=1 일 때만")
def test_real_model_w1(monkeypatch, tmp_path):
    """실제 모델 + 실제 W1. GPU 가 있으면 cuda 를 써야 한다."""
    import torch

    from omnivoice_tts.audio_io import write_wav
    from omnivoice_tts.engine import Engine

    for k in ("OMNIVOICE_TTS_HOME", "OMNIVOICE_CLI_CACHE"):
        monkeypatch.delenv(k, raising=False)
    Engine.reset()
    try:
        eng = Engine.get_sync()
        if torch.cuda.is_available():
            assert eng.device == "cuda"
        wav, m = eng.synth_sync("안녕하세요. 실제 모델 시험입니다.", voice_code="W1")
        assert m["duration_seconds"] > 1.0 and m["voice"] == "W1"
        write_wav(tmp_path / "w1.wav", wav, eng.sample_rate)
    finally:
        Engine.reset()

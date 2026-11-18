from pathlib import Path

import pytest

from omnivoice_tts import settings
from omnivoice_tts.engine import cache_path, split_for_tts
from omnivoice_tts.voices import list_voices

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- backplate 와 같은 캐시 규칙

def test_cache_rule_matches_omnivoice_cli(make_wav, tmp_path, monkeypatch):
    import omnivoice_cli

    ref = make_wav("voice_x.wav")
    monkeypatch.setattr(omnivoice_cli, "CACHE", tmp_path / "c")
    for rt in ("", "안녕하세요"):
        assert cache_path(ref, rt, tmp_path / "c") == omnivoice_cli._cache_path(ref, rt or None)


@pytest.mark.skipif(not (ROOT / "voice_01.wav").is_file(), reason="voice_01.wav 없음")
def test_w1_uses_root_voice_01_and_same_cache_name(monkeypatch):
    """W1 은 루트 voice_01.wav 를 그대로 가리키고, backplate 와 같은 캐시 파일을 쓴다."""
    monkeypatch.delenv("OMNIVOICE_TTS_HOME", raising=False)
    monkeypatch.delenv("OMNIVOICE_TTS_VOICES", raising=False)
    s = settings.load()
    assert s.home == ROOT
    w1 = next(v for v in list_voices(s.voices_dir) if v.code == "W1")
    assert w1.ref_audio == (ROOT / "voice_01.wav").resolve()
    assert (w1.speed, w1.steps, w1.ref_text) == (1.0, 32, "")
    assert cache_path(w1.ref_audio, w1.ref_text, Path("x")).name == "voice_01_2a8181eabb75.pt"


# ---------------------------------------------------------------- 긴 글 나누기

def test_short_text_is_one_piece_unchanged():
    t = "첫 문장입니다. 두 번째 문장입니다! 세 번째?"
    assert split_for_tts(t, 200) == [t]


def test_long_text_split_by_sentence_and_packed():
    sents = [f"이것은 {i}번째 문장으로 길이를 채우기 위한 글입니다." for i in range(12)]
    pieces = split_for_tts(" ".join(sents), 100)
    assert len(pieces) > 1
    assert all(len(p) <= 100 for p in pieces)
    assert " ".join(pieces) == " ".join(sents)


def test_tag_only_piece_is_merged():
    long = "가" * 90 + "."
    pieces = split_for_tts(f"{long} [laughter] {long}", 100)
    assert all(p.replace("[laughter]", "").strip(" .") for p in pieces)
    assert "[laughter]" in " ".join(pieces)


# ---------------------------------------------------------------- 엔진 (가짜 백엔드)

def test_engine_applies_dictionary_and_voice_defaults(fake_engine):
    wav, m = fake_engine.synth_sync("MOOC 와 ChatGPT [laughter] 1989년", voice_code="w1")
    sent = fake_engine.backend.texts[-1]
    assert "무크" in sent and "챗지피티" in sent and "[laughter]" in sent and "천구백팔십구년" in sent
    assert m["voice"] == "W1" and m["speed"] == 1.0 and m["steps"] == 32
    assert m["tags"] == ["[laughter]"]
    assert len(wav) > 0 and m["duration_seconds"] > 0


def test_request_values_override_voice(fake_engine):
    _, m = fake_engine.synth_sync("안녕", speed=1.2, steps=16)
    assert (m["speed"], m["steps"]) == (1.2, 16)


def test_dictionary_edit_applies_without_restart(fake_engine, home):
    import os
    import time

    p = home / "config" / "pronunciation_map.yaml"
    fake_engine.synth_sync("LMS")
    assert fake_engine.backend.texts[-1] == "엘엠에스"           # 사전에 없으면 한 글자씩
    p.write_text("rules:\n  LMS: 학습관리시스템\n", encoding="utf-8")
    os.utime(p, (time.time() + 5, time.time() + 5))
    fake_engine.synth_sync("LMS")
    assert fake_engine.backend.texts[-1] == "학습관리시스템"


def test_unknown_voice_raises(fake_engine):
    with pytest.raises(KeyError):
        fake_engine.synth_sync("안녕", voice_code="ZZ")


def test_prompt_built_once_per_voice(fake_engine):
    fake_engine.synth_sync("하나")
    fake_engine.synth_sync("둘")
    assert fake_engine.backend.prompts == ["W1"]

"""공용 픽스처 — 모델 없이 도는 가짜 엔진 + 임시 집 폴더."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:          # omnivoice_cli.py (루트 스크립트) 비교용
    sys.path.insert(0, str(ROOT))

SR = 24000


class FakeBackend:
    """글자 수에 비례한 길이의 사인파를 돌려준다. 받은 글을 기록한다."""
    device = "cpu"
    device_name = "가짜 엔진"

    def __init__(self):
        self.texts: list[str] = []
        self.prompts: list[str] = []

    def prompt(self, voice, cache_dir):
        self.prompts.append(voice.code)
        return {"voice": voice.code}

    def generate(self, text, prompt, *, speed, steps, lang):
        self.texts.append(text)
        n = int(SR * 0.05 * max(len(text), 1) / speed)
        t = np.arange(n) / SR
        return (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _wav(path: Path, sec: float = 4.0) -> Path:
    t = np.arange(int(SR * sec)) / SR
    sf.write(str(path), (0.1 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), SR, subtype="PCM_16")
    return path


@pytest.fixture
def make_wav(tmp_path):
    def _make(name="ref.wav", sec=4.0):
        return _wav(tmp_path / name, sec)
    return _make


@pytest.fixture
def home(tmp_path, monkeypatch):
    """임시 집 폴더: voices/W1(ref.wav) + config(발음 사전 몇 개) + workspace."""
    h = tmp_path / "home"
    (h / "voices" / "W1").mkdir(parents=True)
    (h / "config").mkdir()
    _wav(h / "voices" / "W1" / "ref.wav")
    (h / "voices" / "W1" / "voice.yaml").write_text("name: 테스트 W1\nspeed: 1.0\nsteps: 32\n", encoding="utf-8")
    (h / "voices" / "W1" / "ref.txt").write_text("", encoding="utf-8")
    (h / "config" / "pronunciation_map.yaml").write_text(
        "# 테스트 사전\nrules:\n  MOOC: 무크\n  ChatGPT: 챗지피티\n", encoding="utf-8")
    (h / "config" / "voice_map.yaml").write_text("default: W1\nstyles:\n  narrator: W1\n", encoding="utf-8")
    monkeypatch.setenv("OMNIVOICE_TTS_HOME", str(h))
    monkeypatch.setenv("OMNIVOICE_CLI_CACHE", str(tmp_path / "cache"))
    for k in ("OMNIVOICE_TTS_SERVER", "OMNIVOICE_TTS_TOKEN", "OMNIVOICE_TTS_VOICES",
              "OMNIVOICE_TTS_PRONUNCIATION_MAP", "OMNIVOICE_TTS_WORKSPACE", "OMNIVOICE_TTS_MAX_CHARS"):
        monkeypatch.delenv(k, raising=False)
    return h


@pytest.fixture
def fake_engine(home):
    from omnivoice_tts.engine import Engine

    backend = FakeBackend()
    Engine._instance = Engine(backend=backend)
    yield Engine._instance
    Engine.reset()


@pytest.fixture
def client(fake_engine):
    from fastapi.testclient import TestClient

    from omnivoice_tts.server.app import create_app

    with TestClient(create_app()) as c:
        yield c

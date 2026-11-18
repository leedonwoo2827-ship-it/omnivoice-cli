from pathlib import Path

import numpy as np
import soundfile as sf

from omnivoice_tts.audio_io import to_wav_bytes, write_wav


def test_write_wav_pcm16(tmp_path: Path):
    sr = 44100
    samples = (np.random.randn(sr) * 0.1).astype(np.float32)
    out = tmp_path / "sub" / "test.wav"
    write_wav(out, samples, sr)
    assert out.exists()

    data, read_sr = sf.read(str(out))
    assert read_sr == sr
    assert len(data) == sr
    info = sf.info(str(out))
    assert info.subtype == "PCM_16"


def test_write_wav_accepts_2d_with_squeeze(tmp_path: Path):
    sr = 22050
    samples = np.random.randn(1, sr).astype(np.float32) * 0.1
    out = tmp_path / "test.wav"
    write_wav(out, samples, sr)
    info = sf.info(str(out))
    assert info.frames == sr


def test_to_wav_bytes_roundtrip():
    sr = 22050
    samples = np.zeros(sr // 4, dtype=np.float32)
    blob = to_wav_bytes(samples, sr)
    assert blob[:4] == b"RIFF"
    assert b"WAVE" in blob[:12]

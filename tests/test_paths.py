from pathlib import Path

import pytest

from omnivoice_tts.paths import (
    chapter_audio_dir,
    narration_filename,
    narration_path,
    normalize_chapter_id,
    resolve_chapter_id,
)


def test_normalize_chapter_id():
    assert normalize_chapter_id("05") == "05"
    assert normalize_chapter_id(5) == "05"
    assert normalize_chapter_id(99) == "99"
    assert normalize_chapter_id("ch12_script.json") == "12"
    assert normalize_chapter_id("") is None
    assert normalize_chapter_id(None) is None


def test_resolve_chapter_priority():
    # 명시값이 최우선
    assert resolve_chapter_id(explicit="03", script_field="07", filename_hint="ch99.json") == "03"
    # 그 다음 script_field
    assert resolve_chapter_id(explicit=None, script_field=7, filename_hint="ch99.json") == "07"
    # 그 다음 filename
    assert resolve_chapter_id(explicit=None, script_field=None, filename_hint="ch99_script.json") == "99"


def test_resolve_chapter_fails_when_unresolvable():
    with pytest.raises(ValueError):
        resolve_chapter_id(explicit=None, script_field=None, filename_hint="random.json")


def test_narration_filename_format():
    assert narration_filename("05", 1) == "ch05_01_narration.wav"
    assert narration_filename("05", 12) == "ch05_12_narration.wav"
    assert narration_filename("99", 7) == "ch99_07_narration.wav"


def test_narration_path(tmp_path: Path):
    out = narration_path(tmp_path, "05", 3)
    assert out.parent == chapter_audio_dir(tmp_path, "05")
    assert out.name == "ch05_03_narration.wav"

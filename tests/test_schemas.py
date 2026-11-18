import json
from pathlib import Path

from omnivoice_tts.schemas import Script

FIXTURE = Path(__file__).parent / "fixtures" / "ch99_script.json"


def test_script_parses_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    script = Script.model_validate(raw)
    assert len(script.scenes) == 3
    assert script.scenes[0].voice_style == "calm_female"
    assert script.scenes[0].narration_text.startswith("첫 번째")
    assert script.chapter == 99


def test_script_extra_fields_ignored():
    data = {
        "chapter": "05",
        "title": "ignored",
        "weird_extra_field": [1, 2, 3],
        "scenes": [{"scene": 1, "narration_text": "테스트", "voice_style": "narrator"}],
    }
    script = Script.model_validate(data)
    assert script.scenes[0].voice_style == "narrator"

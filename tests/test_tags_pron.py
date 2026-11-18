from pathlib import Path

from omnivoice_tts import tags
from omnivoice_tts.pronunciation import PronunciationMap, load_pronunciation_map, parse_rules_text
from omnivoice_tts.srt import split_into_cues

ROOT = Path(__file__).resolve().parents[1]


def test_thirteen_omnivoice_tags_match_library():
    assert len(tags.EXPRESSION_TAGS) == 13
    assert all(t.tag.startswith("[") and t.tag.endswith("]") for t in tags.EXPRESSION_TAGS)
    try:
        from omnivoice.models.omnivoice import _NONVERBAL_PATTERN
    except Exception:  # noqa: BLE001 — 라이브러리 없는 환경
        return
    for t in tags.EXPRESSION_TAGS:
        assert _NONVERBAL_PATTERN.fullmatch(t.tag), t.tag


def test_find_and_normalize():
    assert tags.find("웃자 [Laughter] 그리고 [sigh]") == ["[laughter]", "[sigh]"]


def test_strip_removes_brackets_for_subtitles():
    assert tags.strip("정말 잘했어요 [laughter] , 자랑스럽습니다 [B EY1 S].") == "정말 잘했어요, 자랑스럽습니다."
    assert split_into_cues("잘했어요 [laughter] 고마워요.") == ["잘했어요 고마워요."]


def test_protect_keeps_brackets_from_acronym_spelling():
    pm = PronunciationMap(rules={"SAD": "새드"})
    out = pm.apply("[B EY1 S] 와 [sigh] 그리고 SAD", spell_unknown_acronyms=True)
    assert out == "[B EY1 S] 와 [sigh] 그리고 새드"


def test_validate_warns_supertonic_style():
    w = tags.validate("좋아요 <laugh> (웃음) [giggle]")
    assert any("[laughter]" in x for x in w)
    assert any("(웃음)" in x for x in w)
    assert any("[giggle]" in x for x in w)
    assert tags.validate("좋아요 [laughter] [B EY1 S]") == []


def test_lenient_parse_skips_only_broken_line():
    raw = 'rules:\n  """: ":": 더블콜론"\n  MOOC: 무크\n  "::": 콜론둘\n'
    rules, shape, bad = parse_rules_text(raw)
    assert shape == "rules" and rules == {"MOOC": "무크", "::": "콜론둘"} and len(bad) == 1


def test_flat_shape_is_read():
    rules, shape, bad = parse_rules_text('"10세기": "십 세기"\n"AI": "에이아이"\n')
    assert shape == "flat" and rules == {"10세기": "십 세기", "AI": "에이아이"} and not bad


def test_master_dictionary_loads():
    pm = load_pronunciation_map(ROOT / "config" / "pronunciation_map.yaml")
    assert len(pm.rules) >= 400
    assert pm.rules["::"] == "더블콜론"
    assert pm.apply("CERN의 MOOC", spell_unknown_acronyms=True).startswith(pm.rules["CERN"])

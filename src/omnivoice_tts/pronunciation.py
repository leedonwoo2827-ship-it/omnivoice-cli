from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import tags

logger = logging.getLogger(__name__)


_LETTER_HANGUL = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프",
    "G": "지", "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘",
    "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
    "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유",
    "X": "엑스", "Y": "와이", "Z": "제트",
}
_ACRONYM_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z])")

_DIGIT_HANGUL_SINO = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]

# 한자어 수사 + 단위 변환.
#   - 연도(3~4자리 + "년")는 별도 처리 — "14년" 같은 기간 표기를 건드리지 않기 위해.
#   - 그 외 단위는 1~4자리 + 단위 매칭.
#   - 단위는 띄어쓰기 정책에 따라 두 그룹.
#       TIGHT  : 숫자에 붙여 읽음 (예: "27분" → "이십칠분")
#       SPACED : 한 칸 띄움      (예: "27킬로미터" → "이십칠 킬로미터")
#   - 시(시간), 살, 명, 개, 마리 등 고유어 수사를 쓰는 단위, 6월/10월 같은
#     특수 발음(유월/시월) 단위는 의도적으로 제외.
_YEAR_RE = re.compile(r"(?<!\d)(\d{3,4})년")
# "번"(문제·보기 번호) 추가 — #3가 생성하는 "정답은 2번"/"N번 문제"를 한자어로 읽게(이 번/오십 번).
# 콘텐츠의 정교한 낭독(된소리·소수점 등)은 #2(Claude)가 speech 필드에 완성해서 넘긴다.
_SINO_TIGHT_UNITS = ["분", "초", "도", "원", "일", "번"]
_SINO_SPACED_UNITS = ["킬로미터", "센티미터", "밀리미터", "킬로그램", "퍼센트", "미터", "그램"]
_SPACED_UNIT_SET = set(_SINO_SPACED_UNITS)
# 긴 단위부터 매칭해야 "킬로미터"가 "미터"보다 먼저 잡힌다.
_SINO_UNIT_RE = re.compile(
    r"(?<!\d)(\d{1,4})("
    + "|".join(sorted(_SINO_TIGHT_UNITS + _SINO_SPACED_UNITS, key=len, reverse=True))
    + r")"
)


def _spell_acronym(word: str) -> str:
    return "".join(_LETTER_HANGUL.get(c, c) for c in word)


def _sino_number(n: int) -> str:
    """1~9999 정수를 한자어 수사로 변환 (천/백/십 앞 1은 생략)."""
    if n == 0:
        return "영"
    digits = [int(c) for c in str(n)]
    units = ["천", "백", "십", ""][4 - len(digits):]
    parts: list[str] = []
    for d, u in zip(digits, units):
        if d == 0:
            continue
        if d == 1 and u in ("천", "백", "십"):
            parts.append(u)
        else:
            parts.append(_DIGIT_HANGUL_SINO[d] + u)
    return "".join(parts)


def _convert_years(text: str) -> str:
    return _YEAR_RE.sub(lambda m: _sino_number(int(m.group(1))) + "년", text)


def _convert_sino_units(text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        unit = m.group(2)
        sep = " " if unit in _SPACED_UNIT_SET else ""
        return f"{_sino_number(n)}{sep}{unit}"
    return _SINO_UNIT_RE.sub(repl, text)


@dataclass
class PronunciationMap:
    """약자/외래어를 한국어 발음으로 치환하는 사전.

    SRT 자막에는 적용하지 않는다 — 합성용 텍스트만 변환.
    """
    rules: dict[str, str] = field(default_factory=dict)
    _pattern: "re.Pattern[str] | None" = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._compile()

    def _compile(self) -> None:
        if not self.rules:
            self._pattern = None
            return
        # 긴 키부터 매칭 (e.g., HTTPS가 HTTP보다 먼저 잡혀야 함)
        keys = sorted(self.rules.keys(), key=len, reverse=True)
        escaped = [re.escape(k) for k in keys]
        # 라틴 알파벳 기준 경계 — `\b`를 쓰면 Python regex가 한글도 \w로 취급해서
        # "CERN의" 같은 조사 결합형이 매칭에서 누락된다. lookaround로 인접한
        # 라틴 글자만 차단해서 한글/숫자/공백은 모두 경계로 인정한다.
        self._pattern = re.compile(
            r"(?<![A-Za-z])(?:" + "|".join(escaped) + r")(?![A-Za-z])"
        )

    def apply(
        self,
        text: str,
        *,
        spell_unknown_acronyms: bool = False,
        convert_years: bool = False,
        protect_tags: bool = True,
    ) -> str:
        """사전 + 약어 음역 + 연도/단위 변환을 적용한다.

        protect_tags: 대괄호 [...] (표현 태그 [laughter] · 발음 지정 [B EY1 S])를
        변환에서 제외한다. 기본 켜짐. 날것으로 두면 대문자 음역 규칙이
        [B EY1 S] 를 "비 이와이..." 로 깨뜨린다.
        """
        if not text:
            return text

        mapping: dict[str, str] = {}
        if protect_tags:
            text, mapping = tags.protect(text)

        text = self._apply_inner(
            text,
            spell_unknown_acronyms=spell_unknown_acronyms,
            convert_years=convert_years,
        )
        return tags.restore(text, mapping) if mapping else text

    def _apply_inner(
        self,
        text: str,
        *,
        spell_unknown_acronyms: bool,
        convert_years: bool,
    ) -> str:
        if self._pattern is not None:
            text = self._pattern.sub(lambda m: self.rules[m.group(0)], text)
        if spell_unknown_acronyms:
            # 사전에 없는 2글자 이상 영문 대문자 약어는 알파벳 단위로 음역
            text = _ACRONYM_RE.sub(lambda m: _spell_acronym(m.group(0)), text)
        if convert_years:
            text = _convert_years(text)
            text = _convert_sino_units(text)
        return text


def parse_rules_text(raw: str) -> tuple[dict[str, str], str, list[str]]:
    """사전 yaml 글 → (규칙, 모양 "rules"|"flat", 건너뛴 줄).

    두 가지 모양을 다 받는다: `rules:` 아래에 두는 것(대부분의 앱)과 맨 위에 바로
    늘어놓는 것(product-hub `_발음사전.yaml`).

    ★ 파일 전체가 YAML 문법에 안 맞아도 **깨진 줄만 건너뛰고** 나머지는 읽는다.
      2026-11-16 backplate 사전에 `\"\"\": \":\": 더블콜론\"` 한 줄이 깨져 들어가자,
      통째로 읽던 쪽은 규칙 0개로 떨어져 사전이 조용히 꺼졌다.
    """
    try:
        data = yaml.safe_load(raw) or {}
        bad: list[str] = []
    except yaml.YAMLError:
        data, bad = {}, []
        in_rules = False
        for ln in raw.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if s == "rules:":
                in_rules = True
                data.setdefault("rules", {})
                continue
            try:
                one = yaml.safe_load(s)
            except yaml.YAMLError:
                one = None
            if isinstance(one, dict) and len(one) == 1:
                (data["rules"] if in_rules else data).update(one)
            else:
                bad.append(ln)
    shape = "rules" if isinstance(data, dict) and "rules" in data else "flat"
    src = data.get("rules") if shape == "rules" else data
    rules: dict[str, str] = {}
    if isinstance(src, dict):
        for k, v in src.items():
            key, val = str(k).strip(), ("" if v is None else str(v).strip())
            if key and val:
                rules[key] = val
    return rules, shape, bad


def load_pronunciation_map(path: Path) -> PronunciationMap:
    if not path.exists():
        return PronunciationMap(rules={})
    try:
        rules, _, bad = parse_rules_text(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("발음 사전 로드 실패 (%s): %s", path, exc)
        return PronunciationMap(rules={})
    if bad:
        logger.warning("발음 사전 %s: 읽지 못한 줄 %d개 건너뜀 — %s", path, len(bad), bad[:3])
    return PronunciationMap(rules=rules)


# ---------- 영상 낭독 교정 탭: "숫자를 소리대로" / "영문을 소리대로" ----------
# 대본 일괄 탭의 "한국어 발음 전환"은 연도·정해진 단위만 바꾼다. 교정 탭은 문장
# 전체를 소리대로 적어야 하므로 숫자 전반(쉼표·만 단위·소수·%)과 고유어 수사를 다룬다.

_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
# 고유어 수사로 읽는 단위 (1~99만). "시간"은 "시"보다 먼저 와야 한다.
_NATIVE_COUNTERS = ["가지", "시간", "개", "건", "장", "명", "살", "마리", "권", "곳", "잔", "대", "번째", "시"]
_NATIVE_RE = re.compile(r"(?<![\d.,])(\d{1,2})(\s?)(" + "|".join(_NATIVE_COUNTERS) + r")")
_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})월")
_PERCENT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?%")
_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]*")


def _native_number(n: int) -> str:
    if n == 20:
        return "스무"
    return _NATIVE_TENS[n // 10] + _NATIVE_ONES[n % 10]


def _sino_big(n: int) -> str:
    """0~9999조 정수를 한자어 수사로 (만·억·조 단위, "일만"은 "만")."""
    if n == 0:
        return "영"
    out: list[str] = []
    for unit in ("조", "억", "만", ""):
        size = {"조": 10**12, "억": 10**8, "만": 10**4, "": 1}[unit]
        q, n = divmod(n, size)
        if q:
            out.append(("" if (q == 1 and unit == "만") else _sino_number(q)) + unit)
    return " ".join(out)


def numbers_to_speech(text: str) -> str:
    """숫자를 소리대로: 61,120 → 육만 천백이십, 62% → 육십이 퍼센트, 3개 → 세 개, 6월 → 유월."""
    def native(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        if n == 0:
            return m.group(0)
        return f"{_native_number(n)} {m.group(3)}"

    def month(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        return {6: "유월", 10: "시월"}.get(n, _sino_number(n) + "월") if 1 <= n <= 12 else m.group(0)

    def number(m: "re.Match[str]") -> str:
        s = _sino_big(int(m.group(1).replace(",", "")))
        if m.group(2):
            s += " 점 " + " ".join("영" if c == "0" else _DIGIT_HANGUL_SINO[int(c)] for c in m.group(2))
        return s

    text = _PERCENT_RE.sub(lambda m: m.group(1) + " 퍼센트", text)
    text = _convert_years(text)
    text = _MONTH_RE.sub(month, text)
    text = _NATIVE_RE.sub(native, text)
    return _NUMBER_RE.sub(number, text)


def latin_to_speech(text: str, pmap: "PronunciationMap") -> tuple[str, list[str]]:
    """영문을 소리대로: 사전 규칙 + 대문자 약어 음역. 사전에 없는 영단어는 그대로 두고 목록으로 돌려준다
    (Codex·docx 처럼 철자만으로 읽을 수 없는 말은 사람이 발음 사전에 넣는다)."""
    text = pmap.apply(text, spell_unknown_acronyms=True, convert_years=False)
    left = sorted(set(_LATIN_WORD_RE.findall(tags.strip(text))))
    return text, left

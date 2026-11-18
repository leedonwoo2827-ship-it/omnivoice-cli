"""OmniVoice 표현 태그(비언어 소리) — 대괄호 형식 13종.

## 출처
pip `omnivoice` 0.2.1 `omnivoice/models/omnivoice.py` 의 `_NONVERBAL_PATTERN`:

    \\[(laughter|sigh|confirmation-en|question-en|question-ah|question-oh|
       question-ei|question-yi|surprise-ah|surprise-oh|surprise-wa|
       surprise-yo|dissatisfaction-hnn)\\]

모델은 이 13개를 별도 토큰으로 자른다(`_tokenize_with_nonverbal_tags`). 그래서
**대괄호 형식이 맞고**, 슈퍼토닉의 `<laugh>` 꺾쇠 형식은 글자로 읽힌다.
`[breath]` 는 없다.

## 대괄호는 태그만이 아니다
OmniVoice 는 `[B EY1 S]` 처럼 대괄호 안에 CMU 발음 기호를 써서 영어 단어
발음을 직접 지정하는 것도 받는다(`omnivoice/utils/text.py` 의 `_BRACKET_TAG_RE`).
그래서 발음 사전 변환에서는 **대괄호 덩어리 전체**를 보호한다. 보호하지 않으면
"모르는 대문자 약어 음역" 규칙이 `[B EY1 S]` 를 한글로 깨뜨린다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpressionTag:
    tag: str        # "[laughter]"
    name: str       # "웃음"
    effect: str     # 한 줄 설명

    @property
    def word(self) -> str:
        return self.tag[1:-1]


# 순서 = UI 칩 순서. 자주 쓰는 것을 앞에.
EXPRESSION_TAGS: tuple[ExpressionTag, ...] = (
    ExpressionTag("[laughter]", "웃음", "웃음소리"),
    ExpressionTag("[sigh]", "한숨", "한숨"),
    ExpressionTag("[surprise-ah]", "놀람 아", "놀라서 '아!'"),
    ExpressionTag("[surprise-oh]", "놀람 오", "놀라서 '오!'"),
    ExpressionTag("[surprise-wa]", "놀람 와", "놀라서 '와!'"),
    ExpressionTag("[surprise-yo]", "놀람 요", "놀라서 '요!'"),
    ExpressionTag("[question-ah]", "되물음 아", "되묻는 '아?'"),
    ExpressionTag("[question-oh]", "되물음 오", "되묻는 '오?'"),
    ExpressionTag("[question-ei]", "되물음 에", "되묻는 '에이?'"),
    ExpressionTag("[question-yi]", "되물음 이", "되묻는 '이?'"),
    ExpressionTag("[question-en]", "되물음 음", "되묻는 '음?'"),
    ExpressionTag("[confirmation-en]", "맞장구 음", "수긍하는 '음'"),
    ExpressionTag("[dissatisfaction-hnn]", "불만 흥", "못마땅한 '흥'"),
)

TAG_WORDS: tuple[str, ...] = tuple(t.word for t in EXPRESSION_TAGS)
BY_TAG: dict[str, ExpressionTag] = {t.tag: t for t in EXPRESSION_TAGS}

# 알려진 표현 태그. 대소문자 변형도 잡아 정규형으로 맞춘다.
TAG_RE = re.compile(r"\[\s*(" + "|".join(re.escape(w) for w in TAG_WORDS) + r")\s*\]", re.IGNORECASE)

# 대괄호 덩어리 전체 (표현 태그 + 발음 지정). 발음 사전 보호·자막 제거용.
BRACKET_RE = re.compile(r"\[[^\[\]\n]*\]")

# 슈퍼토닉 꺾쇠 태그 → OmniVoice 대응 (경고·자동 안내용)
_SUPERTONIC_HINT = {
    "laugh": "[laughter]", "sigh": "[sigh]", "surprise": "[surprise-ah]",
    "breath": None, "scream": None, "throatclear": None, "sad": None,
    "angry": None, "cough": None, "yawn": None,
}
_ANGLE_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9 _-]{0,30})\s*>")
_PAREN_RE = re.compile(r"\(\s*(웃음|한숨|기침|하품|헛기침|숨소리)\s*\)")

_SENTINEL_BASE = 0xE000  # Private Use Area — 일반 텍스트에 나오지 않는다


def normalize(text: str) -> str:
    """[ Laughter ] 같은 변형을 정규형 [laughter] 로."""
    return TAG_RE.sub(lambda m: "[" + m.group(1).lower() + "]", text or "")


def find(text: str) -> list[str]:
    """텍스트에 들어 있는 표현 태그 (정규형, 등장 순서, 중복 포함)."""
    return ["[" + m.group(1).lower() + "]" for m in TAG_RE.finditer(text or "")]


def strip(text: str) -> str:
    """대괄호 덩어리(태그·발음 지정)를 지운다. 자막(SRT)에 찍히면 안 된다."""
    out = BRACKET_RE.sub(" ", text or "")
    out = re.sub(r"\s+([,.!?;:…])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def protect(text: str) -> tuple[str, dict[str, str]]:
    """대괄호 덩어리를 PUA 문자로 바꿔 발음 변환에서 보호한다.

    returns: (바꾼 텍스트, {sentinel: 원래 덩어리})
    """
    text = normalize(text)
    mapping: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        sentinel = chr(_SENTINEL_BASE + len(mapping))
        mapping[sentinel] = m.group(0)
        return sentinel

    return BRACKET_RE.sub(_sub, text or ""), mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for sentinel, original in mapping.items():
        text = text.replace(sentinel, original)
    return text


def validate(text: str) -> list[str]:
    """사용자에게 보여 줄 경고. 합성을 막지는 않는다."""
    warnings: list[str] = []
    for m in _ANGLE_RE.finditer(text or ""):
        word = re.sub(r"[\s_-]+", "", m.group(1)).lower()
        if word in _SUPERTONIC_HINT:
            alt = _SUPERTONIC_HINT[word]
            warnings.append(
                f"'{m.group(0)}' 는 슈퍼토닉 형식이라 OmniVoice 에서는 글자로 읽힙니다. "
                + (f"'{alt}' 로 쓰세요." if alt else "OmniVoice 에는 같은 태그가 없습니다 — 지우세요.")
            )
    for m in BRACKET_RE.finditer(text or ""):
        inner = m.group(0)[1:-1].strip()
        if inner.lower() in TAG_WORDS:
            continue
        # 대문자·숫자·공백만이면 CMU 발음 지정([B EY1 S])으로 보고 통과
        if re.fullmatch(r"[A-Z0-9 ]+", inner):
            continue
        warnings.append(
            f"'{m.group(0)}' 는 지원 태그가 아닙니다. 지원 태그: {', '.join(t.tag for t in EXPRESSION_TAGS)}"
        )
    for m in _PAREN_RE.finditer(text or ""):
        warnings.append(f"'{m.group(0)}' 는 태그가 아니라 글자로 읽힙니다. 웃음은 '[laughter]', 한숨은 '[sigh]'.")
    return warnings


def as_dicts() -> list[dict]:
    return [{"tag": t.tag, "word": t.word, "name": t.name, "effect": t.effect} for t in EXPRESSION_TAGS]

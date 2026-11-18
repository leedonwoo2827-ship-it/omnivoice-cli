"""발음 사전 — 본사전(이 폴더) 읽기·쓰기와 앱 사전 연결([업데이트] · [다운받기]).

영상 앱마다 발음 사전이 따로 있다. 본사전을 한 곳(config/pronunciation_map.yaml)에
두고, 각 앱 사전을 "연결"해서 두 버튼으로 오간다.

    [업데이트]  그 앱에서 이번에 고친 것(지난 동기화 이후 바뀐 것)만 본사전에 올린다
    [다운받기]  작업 시작 전에 본사전 전체를 그 앱 사전 파일로 받는다

"지난 동기화 이후"를 알려고, 동기화할 때마다 그 앱 사전의 모습을
config/dict_base/<id>.yaml 에 적어 둔다(3-way 비교의 기준).

- 본사전에서도 같은 말이 그사이 다르게 바뀌었으면 **충돌**로 보여 주고 사람이 고른다.
- 처음 연결한 앱(기준이 없음)은 본사전에 없는 말만 올리고, 값이 다른 말은 충돌로 보여 준다.
- 다운받기는 아직 올리지 않은 변경이 있으면 멈춘다(덮어써서 잃지 않게). 받기 전 파일은
  config/dict_base/backup/ 에 남긴다.
- 앱 사전 파일은 원래 모양 그대로 쓴다: `rules:` 아래에 두는 모양 / 맨 위에 늘어놓는 모양,
  맨 위 주석도 보존.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import settings as settings_module
from .pronunciation import parse_rules_text

DEFAULT_HEADER = """# OmniVoice TTS 발음 본사전
#
# 합성 직전에 약자·외래어·숫자를 한국어 소리로 바꿉니다. 자막(SRT)에는 적용하지 않습니다.
#   - 긴 키부터 맞춥니다. 영문 키는 앞뒤가 영문자가 아닐 때만 맞습니다("CERN의" 는 맞음)
#   - 사전에 없는 대문자 약어는 한 글자씩 읽습니다(ABC → 에이비씨)
#   - 고치면 바로 반영됩니다(서버 재시작 불필요)
#   - 다른 영상 앱의 사전과는 웹 「발음 사전」 탭의 [업데이트]/[다운받기] 로 오갑니다
"""


# ---------------------------------------------------------------- 파일 읽기·쓰기

@dataclass
class DictFile:
    header: str
    rules: dict[str, str]
    shape: str = "rules"            # "rules" | "flat"
    bad_lines: list[str] = field(default_factory=list)   # 문법이 깨져 건너뛴 줄


def _clean(raw) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            key, val = str(k).strip(), ("" if v is None else str(v).strip())
            if key and val:
                out[key] = val
    return out


def read_dict(path: Path) -> DictFile:
    path = Path(path)
    if not path.is_file():
        return DictFile(DEFAULT_HEADER, {}, "rules")
    raw = path.read_text(encoding="utf-8-sig")
    rules, shape, bad = parse_rules_text(raw)
    lines = raw.splitlines()
    head: list[str] = []
    for ln in lines:                      # 첫 데이터 줄 앞의 주석·빈 줄이 머리말
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            head.append(ln)
        else:
            break
    header = "\n".join(head).strip("\n")
    header = (header + "\n") if header.strip() else DEFAULT_HEADER
    return DictFile(header, rules, shape, bad)


def _q(s: str, force: bool = False) -> str:
    """YAML 로 다시 읽었을 때 같은 문자열이 나오게. 필요할 때만 따옴표."""
    plain_ok = not force and s == s.strip() and s and not any(c in s for c in ":#'\"\n\t{}[],&*!|>%@`")
    if plain_ok:
        try:
            if yaml.safe_load(f"k: {s}") == {"k": s}:
                return s
        except yaml.YAMLError:
            pass
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_dict(path: Path, df: DictFile) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = df.shape == "flat"
    parts = [df.header.rstrip("\n") + "\n\n"]
    if not flat:
        parts.append("rules:\n")
    for k in sorted(df.rules):
        if flat:
            parts.append(f"{_q(k, True)}: {_q(df.rules[k], True)}\n")
        else:
            parts.append(f"  {_q(k)}: {_q(df.rules[k])}\n")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(parts), encoding="utf-8")
    os.replace(tmp, path)


def master_path() -> Path:
    return settings_module.load().pronunciation_map_path


def read_master() -> DictFile:
    return read_dict(master_path())


def write_master(df: DictFile) -> None:
    write_dict(master_path(), df)


# ---------------------------------------------------------------- 연결

_ID_RE = re.compile(r"[^0-9A-Za-z가-힣_-]+")


def _links_file() -> Path:
    return settings_module.load().dict_links_path


def _base_file(link_id: str) -> Path:
    return settings_module.load().dict_base_dir / f"{link_id}.yaml"


def load_links() -> dict[str, dict]:
    p = _links_file()
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k): dict(v) for k, v in (data.get("links") or {}).items()}


def _save_links(links: dict[str, dict]) -> None:
    p = _links_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = ("# 발음 본사전과 [업데이트]/[다운받기] 로 오가는 앱 사전 목록\n"
            + yaml.safe_dump({"links": links}, allow_unicode=True, sort_keys=False))
    p.write_text(body, encoding="utf-8")


def _load_base(link_id: str) -> dict[str, str] | None:
    p = _base_file(link_id)
    if not p.is_file():
        return None
    return _clean((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("rules"))


def _save_base(link_id: str, rules: dict[str, str]) -> None:
    p = _base_file(link_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"synced_at": time.strftime("%Y-%m-%d %H:%M:%S"), "rules": rules},
                                allow_unicode=True, sort_keys=True), encoding="utf-8")


def add_link(name: str, path: str | Path, link_id: str | None = None, *, mark_synced: bool = False) -> str:
    """앱 사전을 연결한다. mark_synced=True 면 지금 모습을 기준으로 적는다(이미 본사전에 합친 경우)."""
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"사전 파일이 없습니다: {p}")
    read_dict(p)  # 읽히는지 확인
    links = load_links()
    lid = _ID_RE.sub("-", (link_id or name or p.parent.name)).strip("-").lower() or "app"
    base_id, n = lid, 2
    while lid in links and Path(links[lid]["path"]) != p:
        lid, n = f"{base_id}-{n}", n + 1
    links[lid] = {"name": name or lid, "path": str(p)}
    _save_links(links)
    if mark_synced:
        _save_base(lid, read_dict(p).rules)
    return lid


def remove_link(link_id: str) -> None:
    links = load_links()
    links.pop(link_id, None)
    _save_links(links)
    _base_file(link_id).unlink(missing_ok=True)


# ---------------------------------------------------------------- 비교

@dataclass
class Status:
    link_id: str
    name: str
    path: str
    exists: bool
    first_time: bool                                   # 기준(지난 동기화)이 없음
    to_push: dict[str, str] = field(default_factory=dict)        # 올릴 것 (새로·바뀜)
    to_delete: list[str] = field(default_factory=list)           # 앱에서 지운 것
    conflicts: dict[str, dict] = field(default_factory=dict)     # key → {app, master, base}
    to_pull: int = 0                                   # 다운받으면 앱에서 새로 생기거나 바뀔 개수
    app_count: int = 0
    master_count: int = 0
    bad_lines: list[str] = field(default_factory=list)  # 앱 사전에서 문법이 깨져 못 읽은 줄

    @property
    def pending(self) -> bool:
        return bool(self.to_push or self.to_delete or self.conflicts)

    def to_dict(self) -> dict:
        return {
            "id": self.link_id, "name": self.name, "path": self.path, "exists": self.exists,
            "first_time": self.first_time, "to_push": self.to_push, "to_delete": self.to_delete,
            "conflicts": self.conflicts, "to_pull": self.to_pull, "pending": self.pending,
            "app_count": self.app_count, "master_count": self.master_count,
            "bad_lines": self.bad_lines,
        }


def status(link_id: str) -> Status:
    links = load_links()
    if link_id not in links:
        raise KeyError(f"연결되지 않은 사전: {link_id}")
    ln = links[link_id]
    p = Path(ln["path"])
    st = Status(link_id, ln.get("name", link_id), str(p), p.is_file(), False)
    if not st.exists:
        return st
    adf = read_dict(p)
    app = adf.rules
    st.bad_lines = adf.bad_lines
    master = read_master().rules
    base = _load_base(link_id)
    st.first_time = base is None
    st.app_count, st.master_count = len(app), len(master)

    if base is None:
        for k, v in app.items():
            if k not in master:
                st.to_push[k] = v
            elif master[k] != v:
                st.conflicts[k] = {"app": v, "master": master[k], "base": None}
    else:
        for k, v in app.items():
            if base.get(k) == v:
                continue                                  # 앱에서 안 바뀜
            if k in master and master[k] != v and master[k] != base.get(k):
                st.conflicts[k] = {"app": v, "master": master[k], "base": base.get(k)}
            elif master.get(k) != v:
                st.to_push[k] = v
        for k in base:
            if k not in app and k in master:
                if master[k] == base[k]:
                    st.to_delete.append(k)
                else:
                    st.conflicts[k] = {"app": None, "master": master[k], "base": base[k]}
    st.to_pull = sum(1 for k, v in master.items() if app.get(k) != v)
    return st


def push(link_id: str, choices: dict[str, str] | None = None) -> dict:
    """[업데이트] 앱 → 본사전. choices: 충돌 key → "app" | "master". 고르지 않은 충돌은 그대로 둔다."""
    choices = choices or {}
    st = status(link_id)
    if not st.exists:
        raise FileNotFoundError(f"사전 파일이 없습니다: {st.path}")
    mdf = read_master()
    added = changed = deleted = 0
    for k, v in st.to_push.items():
        if k in mdf.rules:
            changed += 1
        else:
            added += 1
        mdf.rules[k] = v
    for k in st.to_delete:
        if mdf.rules.pop(k, None) is not None:
            deleted += 1
    unresolved = []
    for k, c in st.conflicts.items():
        pick = choices.get(k)
        if pick == "app":
            if c["app"] is None:
                mdf.rules.pop(k, None)
                deleted += 1
            else:
                mdf.rules[k] = c["app"]
                changed += 1
        elif pick != "master":
            unresolved.append(k)
    write_master(mdf)
    app_rules = read_dict(Path(st.path)).rules
    if unresolved:
        # 아직 안 고른 충돌은 기준을 옛값으로 남겨 다음에도 충돌로 보이게 한다
        base = _load_base(link_id) or {}
        for k in unresolved:
            if k in base:
                app_rules[k] = base[k]
            else:
                app_rules.pop(k, None)
    _save_base(link_id, app_rules)
    return {"added": added, "changed": changed, "deleted": deleted,
            "unresolved": unresolved, "master_count": len(mdf.rules)}


def pull(link_id: str, force: bool = False) -> dict:
    """[다운받기] 본사전 → 앱 사전 파일 (앱의 머리말·모양은 그대로)."""
    st = status(link_id)
    if not st.exists:
        raise FileNotFoundError(f"사전 파일이 없습니다: {st.path}")
    if st.pending and not force:
        raise RuntimeError(
            f"이 앱 사전에 아직 올리지 않은 변경이 있습니다(올릴 것 {len(st.to_push)}, "
            f"지운 것 {len(st.to_delete)}, 충돌 {len(st.conflicts)}). 먼저 [업데이트] 하세요.")
    p = Path(st.path)
    backup_dir = settings_module.load().dict_base_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{link_id}-{time.strftime('%Y%m%d-%H%M%S')}.yaml"
    backup.write_bytes(p.read_bytes())
    adf = read_dict(p)
    master = read_master().rules
    write_dict(p, DictFile(adf.header, dict(master), adf.shape))
    _save_base(link_id, master)
    return {"written": len(master), "changed": st.to_pull, "backup": str(backup)}


def all_status() -> list[dict]:
    out = []
    for lid in load_links():
        try:
            out.append(status(lid).to_dict())
        except Exception as exc:  # noqa: BLE001
            out.append({"id": lid, "error": str(exc)})
    return out


# ---------------------------------------------------------------- 후보 찾기

_SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "site-packages",
              ".pytest_cache", "dist", "build", ".worktrees"}
_NAME_RE = re.compile(r"(pronunciation.*|.*발음사전.*)\.ya?ml$", re.IGNORECASE)


def find_candidates(root: Path | None = None, max_depth: int = 6) -> list[str]:
    """root(기본: 이 폴더의 부모) 아래 발음 사전처럼 보이는 yaml 들."""
    s = settings_module.load()
    root = Path(root) if root else s.home.parent
    linked = {str(Path(v["path"])).lower() for v in load_links().values()}
    mine = str(s.pronunciation_map_path).lower()
    found: list[str] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.endswith(".worktrees") and not d.startswith(".")
                       and depth < max_depth]
        for fn in filenames:
            if _NAME_RE.match(fn) and not fn.endswith((".bak", ".tmp")):
                full = str(Path(dirpath) / fn)
                if full.lower() not in linked and full.lower() != mine and "dict_base" not in full:
                    found.append(full)
    return sorted(found)

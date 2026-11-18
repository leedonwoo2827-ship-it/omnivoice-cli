import pytest
import yaml

from omnivoice_tts import dictsync
from omnivoice_tts.dictsync import DictFile, read_dict, write_dict


def test_roundtrip_keeps_shape_header_and_tricky_keys(tmp_path):
    p = tmp_path / "d.yaml"
    rules = {"NO": "노", "ON": "온", "::": "더블콜론", "#edchat": "샵에드챗", "1위": "일위", "A: B": "에이 비",
             "yes": "예스", "x": '따옴표 "안"'}
    write_dict(p, DictFile("# 머리말\n", rules, "rules"))
    back = read_dict(p)
    assert back.rules == rules and back.shape == "rules" and back.header.startswith("# 머리말")
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["rules"] == rules

    q = tmp_path / "flat.yaml"
    write_dict(q, DictFile("# 평평\n", rules, "flat"))
    fb = read_dict(q)
    assert fb.rules == rules and fb.shape == "flat"


def _app(tmp_path, rules, shape="rules"):
    p = tmp_path / "app_dict.yaml"
    write_dict(p, DictFile("# 앱 사전\n", rules, shape))
    return p


def test_first_link_pushes_only_new_and_reports_conflicts(home, tmp_path):
    app = _app(tmp_path, {"MOOC": "무크", "ChatGPT": "챗쥐피티", "LMS": "엘엠에스"})
    lid = dictsync.add_link("앱", app)
    st = dictsync.status(lid)
    assert st.first_time and st.to_push == {"LMS": "엘엠에스"}
    assert set(st.conflicts) == {"ChatGPT"}

    r = dictsync.push(lid)                     # 충돌은 고르지 않음 → 그대로
    assert r["added"] == 1 and r["unresolved"] == ["ChatGPT"]
    assert dictsync.read_master().rules["ChatGPT"] == "챗지피티"
    assert set(dictsync.status(lid).conflicts) == {"ChatGPT"}    # 다음에도 충돌로 보인다

    dictsync.push(lid, {"ChatGPT": "app"})
    assert dictsync.read_master().rules["ChatGPT"] == "챗쥐피티"
    assert not dictsync.status(lid).pending


def test_update_sends_only_changes_since_last_sync(home, tmp_path):
    app = _app(tmp_path, {"MOOC": "무크"})
    lid = dictsync.add_link("앱", app, mark_synced=True)
    master = dictsync.read_master()
    master.rules["API"] = "에이피아이"           # 다른 쪽에서 본사전에 추가
    dictsync.write_master(master)

    df = read_dict(app)
    df.rules["TTS"] = "티티에스"                # 이 앱에서 이번에 추가
    del df.rules["MOOC"]                        # 이 앱에서 지움
    write_dict(app, df)

    st = dictsync.status(lid)
    assert st.to_push == {"TTS": "티티에스"} and st.to_delete == ["MOOC"] and not st.conflicts
    dictsync.push(lid)
    m = dictsync.read_master().rules
    assert m["TTS"] == "티티에스" and "MOOC" not in m and m["API"] == "에이피아이"


def test_both_sides_changed_is_conflict(home, tmp_path):
    app = _app(tmp_path, {"MOOC": "무크"})
    lid = dictsync.add_link("앱", app, mark_synced=True)
    m = dictsync.read_master()
    m.rules["MOOC"] = "무욱"
    dictsync.write_master(m)
    df = read_dict(app)
    df.rules["MOOC"] = "묵"
    write_dict(app, df)
    st = dictsync.status(lid)
    assert st.conflicts == {"MOOC": {"app": "묵", "master": "무욱", "base": "무크"}}


def test_pull_refuses_when_unpushed_then_writes_master_with_backup(home, tmp_path):
    app = _app(tmp_path, {"MOOC": "무크", "NEW": "뉴"}, shape="flat")
    lid = dictsync.add_link("앱", app)
    with pytest.raises(RuntimeError):
        dictsync.pull(lid)
    dictsync.push(lid)
    r = dictsync.pull(lid)
    after = read_dict(app)
    assert after.shape == "flat" and after.header.startswith("# 앱 사전")
    assert after.rules == dictsync.read_master().rules
    assert "NEW" in after.rules and "ChatGPT" in after.rules
    from pathlib import Path
    assert Path(r["backup"]).is_file()
    st = dictsync.status(lid)
    assert not st.pending and st.to_pull == 0


def test_pull_fixes_broken_app_file(home, tmp_path):
    app = tmp_path / "broken.yaml"
    app.write_text('rules:\n  """: ":": 더블콜론"\n  MOOC: 무크\n', encoding="utf-8")
    lid = dictsync.add_link("깨진 앱", app, mark_synced=True)
    assert len(dictsync.status(lid).bad_lines) == 1
    dictsync.pull(lid)
    yaml.safe_load(app.read_text(encoding="utf-8"))           # 이제 YAML 로 읽힌다
    assert dictsync.status(lid).bad_lines == []

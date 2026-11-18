import io
import json
from pathlib import Path

import soundfile as sf

FIXTURE = Path(__file__).parent / "fixtures" / "ch99_script.json"


def test_health_and_voices(client):
    h = client.get("/api/health").json()
    assert h["engine_loaded"] and h["voices"] == ["W1"] and h["sample_rate"] == 24000
    v = client.get("/api/voices").json()
    assert v["default"] == "W1" and v["voices"][0]["name"] == "테스트 W1"


def test_synthesize_returns_wav_with_metrics(client, fake_engine):
    r = client.post("/api/synthesize", json={"text": "MOOC 수업입니다.", "voice": "W1", "steps": 16})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content))
    assert sr == 24000 and len(data) > 0
    assert r.headers["X-Voice"] == "W1" and r.headers["X-Steps"] == "16" and r.headers["X-Speed"] == "1.0"
    assert fake_engine.backend.texts[-1] == "무크 수업입니다."


def test_synthesize_rejects_unknown_voice(client):
    r = client.post("/api/synthesize", json={"text": "안녕", "voice": "NOPE"})
    assert r.status_code == 422 and "W1" in r.json()["detail"]


def test_dictionary_edit_is_reflected_immediately(client):
    assert client.post("/api/dict/preview", json={"text": "LMS"}).json()["text"] == "엘엠에스"
    r = client.post("/api/dict", json={"key": "LMS", "value": "엘엠에스 시스템"})
    assert r.status_code == 200 and r.json()["count"] == 3
    assert client.post("/api/dict/preview", json={"text": "LMS"}).json()["text"] == "엘엠에스 시스템"
    assert client.delete("/api/dict/LMS").json()["count"] == 2


def test_prepare_and_tags(client):
    j = client.post("/api/prepare", json={"text": "좋아요 <laugh>"}).json()
    assert j["warnings"]
    assert len(client.get("/api/tags").json()["tags"]) == 13


def test_add_voice_appears_in_list(client, make_wav):
    wav = make_wav("w2.wav", 5).read_bytes()
    r = client.post("/api/voices", data={"code": "w2", "name": "둘째", "ref_text": "안녕하세요"},
                    files={"wav": ("w2.wav", wav, "audio/wav")})
    assert r.status_code == 200, r.text
    assert r.json()["voice"]["code"] == "W2"
    codes = [v["code"] for v in client.get("/api/voices").json()["voices"]]
    assert codes == ["W1", "W2"]
    again = client.post("/api/voices", data={"code": "W2"}, files={"wav": ("w2.wav", wav, "audio/wav")})
    assert again.status_code == 409
    r = client.post("/api/synthesize", json={"text": "둘째 목소리", "voice": "W2"})
    assert r.status_code == 200 and r.headers["X-Voice"] == "W2"


def test_batch_writes_wav_and_srt(client, home):
    raw = FIXTURE.read_bytes()
    r = client.post("/api/batch", files={"script": ("ch99_script.json", raw, "application/json")})
    assert r.status_code == 200, r.text
    job = client.get(r.json()["status_url"]).json()
    assert job["status"] == "done", job
    n = len(json.loads(raw)["scenes"])
    audio = home / "workspace" / "ch99" / "audio"
    subs = home / "workspace" / "ch99" / "subtitles"
    assert len(list(audio.glob("*.wav"))) == n
    assert len(list(subs.glob("ch99_*_narration.srt"))) == n
    assert (subs / "ch99.srt").read_text(encoding="utf-8").startswith("1\n")
    assert any("calm_female" in w for w in job["warnings"])      # 모르는 voice_style 경고
    z = client.get(f"/api/jobs/{job['job_id']}/zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_dict_links_push_pull_over_http(client, tmp_path):
    from omnivoice_tts.dictsync import DictFile, write_dict

    app = tmp_path / "app.yaml"
    write_dict(app, DictFile("# 앱\n", {"MOOC": "무크", "XR": "엑스알"}, "rules"))
    st = client.post("/api/dict/links", json={"name": "필기", "path": str(app)}).json()
    assert st["to_push"] == {"XR": "엑스알"}
    assert client.post(f"/api/dict/links/{st['id']}/pull", json={}).status_code == 409
    r = client.post(f"/api/dict/links/{st['id']}/push", json={"choices": {}}).json()
    assert r["added"] == 1
    r = client.post(f"/api/dict/links/{st['id']}/pull", json={}).json()
    assert r["written"] == 3
    assert client.get("/api/dict/links").json()["links"][0]["pending"] is False


def test_token_guard_blocks_other_hosts(client, monkeypatch):
    monkeypatch.setenv("OMNIVOICE_TTS_TOKEN", "secret")
    # TestClient 는 testclient 호스트라 통과, 다른 호스트는 막힌다
    assert client.get("/api/health").status_code == 200
    from fastapi.testclient import TestClient

    from omnivoice_tts.server.app import create_app

    with TestClient(create_app(), client=("10.0.0.5", 5000)) as other:
        assert other.get("/api/health").status_code == 401
        assert other.get("/api/health", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert other.get("/").status_code == 401                         # 화면도 막힌다
        assert other.get("/?token=wrong").status_code == 401
        assert other.get("/static/app.js").status_code == 200

    # 브라우저: /?token= 으로 한 번 열면 쿠키를 받고, 주소에서 비밀번호가 빠진다
    with TestClient(create_app(), client=("10.0.0.5", 5000)) as browser:
        r = browser.get("/?token=secret", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert "omnivoice_token" in r.cookies or "omnivoice_token" in browser.cookies
        assert browser.get("/").status_code == 200
        assert browser.get("/api/health").status_code == 200
        assert browser.post("/api/to_pronunciation", json={"text": "MOOC"}).json()["text"] == "무크"


def test_web_pages(client):
    assert "OmniVoice TTS" in client.get("/").text
    assert "다른 앱 사전과 오가기" in client.get("/dict").text

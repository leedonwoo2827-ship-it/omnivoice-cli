"""원격 백엔드 — GPU 없는 PC 에서 코랩 T4 의 `omnivoice_server.py` 에 합성을 맡긴다.

    set OMNIVOICE_TTS_SERVER=https://….trycloudflare.com
    set OMNIVOICE_TTS_SERVER_TOKEN=<코랩 셀이 출력한 비밀번호>

프로토콜은 기존 서버 그대로(POST /tts {text, speed, steps, ref_name, ref_b64, ref_text}).
발음 사전·문장 나누기는 이 PC 에서 먼저 하고 보낸다. 이 PC 에는 torch 가 필요 없다.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from .voices import Voice


class RemoteBackend:
    def __init__(self, server: str, token: str = ""):
        self.url = server.rstrip("/")
        self.token = token
        info = self._call("/health", None)
        self.device = f"remote-{info.get('device', '?')}"
        self.device_name = f"원격 {info.get('device', '?')} ({self.url})"

    def _call(self, path: str, payload: dict | None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method="GET" if data is None else "POST",
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json",
                                              "User-Agent": "omnivoice-tts"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                body = r.read()
                return json.loads(body) if r.headers.get_content_type() == "application/json" else body
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"원격 서버 오류 {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"원격 서버에 연결하지 못했습니다: {self.url} ({e.reason})") from e

    def prompt(self, voice: Voice, cache_dir: Path):
        return {"ref_name": voice.ref_audio.name,
                "ref_b64": base64.b64encode(voice.ref_audio.read_bytes()).decode(),
                "ref_text": voice.ref_text}

    def generate(self, text, prompt, *, speed, steps, lang):
        import soundfile as sf

        body = self._call("/tts", {"text": text, "speed": speed, "steps": steps, **prompt})
        wav, _ = sf.read(io.BytesIO(body), dtype="float32")
        return np.asarray(wav, dtype=np.float32).reshape(-1)

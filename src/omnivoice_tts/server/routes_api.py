"""HTTP API — 화면(web/)과 다른 앱·에이전트가 같이 쓴다. 전체 목록은 /docs."""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import dictsync
from .. import settings as settings_module
from .. import tags as tags_module
from ..audio_io import to_wav_bytes
from ..batch import parse_script, run_batch
from ..engine import Engine
from ..paths import (
    chapter_audio_dir,
    chapter_srt_path,
    chapter_subtitles_dir,
    narration_path,
    normalize_chapter_id,
    resolve_chapter_id,
    srt_path,
)
from ..pronunciation import load_pronunciation_map
from ..schemas import BatchSubmitResponse, JobStatus, SynthesizeRequest, VoiceInfoOut, VoiceListResponse
from ..srt import Cue, auto_time_cues, make_multi_srt, merge_scene_cues, parse_srt_cues, split_into_cues
from ..voices import add_voice, list_voices, load_voice_map
from .jobs import JobRecord, get_registry

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------- 목소리

def _pick_voice(voice: str | None, voice_style: str | None = None) -> str:
    s = settings_module.load()
    codes = {v.code for v in list_voices(s.voices_dir)}
    if voice:
        code = voice.strip().upper()
        if code not in codes:
            raise HTTPException(status_code=422,
                                detail=f"모르는 목소리: {voice} (등록된 목소리: {', '.join(sorted(codes))})")
        return code
    code, _ = load_voice_map(s.voice_map_path, s.voices_dir, s.default_voice).resolve(voice_style)
    return code


@router.get("/voices", response_model=VoiceListResponse)
async def get_voices() -> VoiceListResponse:
    s = settings_module.load()
    vmap = load_voice_map(s.voice_map_path, s.voices_dir, s.default_voice)
    voices = [
        VoiceInfoOut(code=v.code, name=v.name, gender=v.gender, speed=v.speed, steps=v.steps,
                     language=v.language, memo=v.memo, ref_ok=v.ok,
                     default_for_unknown=(v.code == vmap.default))
        for v in list_voices(s.voices_dir)
    ]
    return VoiceListResponse(voices=voices, voice_map=dict(vmap.styles), default=vmap.default)


@router.post("/voices")
async def create_voice(
    code: str = Form(...),
    wav: UploadFile = File(...),
    name: str = Form(""),
    gender: str = Form(""),
    ref_text: str = Form(""),
    speed: float | None = Form(None),
    steps: int | None = Form(None),
    memo: str = Form(""),
) -> dict:
    """새 목소리 등록 — voices/<코드>/ 에 ref.wav · ref.txt · voice.yaml 을 만든다."""
    data = await wav.read()
    if not data:
        raise HTTPException(status_code=422, detail="wav 파일이 비어 있습니다")
    try:
        info = sf.info(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"읽을 수 없는 음성 파일입니다(wav 로 올려 주세요): {exc}") from exc
    s = settings_module.load()
    try:
        v = add_voice(s.voices_dir, code, data, name=name, gender=gender, ref_text=ref_text,
                      speed=speed, steps=steps, memo=memo)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sec = info.frames / float(info.samplerate)
    note = None
    if sec < 3 or sec > 20:
        note = f"녹음 길이 {sec:.1f}초 — 3~10초가 가장 좋습니다 (20초가 넘으면 앞부분만 씁니다)"
    return {"voice": v.to_dict(), "seconds": round(sec, 2), "note": note}


@router.get("/voices/{code}/preview")
async def voice_preview(code: str, text: str | None = None) -> Response:
    """목소리 카드의 ▶ — 짧은 문장 하나를 그 목소리로."""
    voice_code = _pick_voice(code)
    engine = await Engine.get()
    sample = (text or "안녕하세요. 이 목소리로 읽어 드립니다.").strip()[:200]
    wav, _ = await engine.synth_timed(sample, voice_code=voice_code)
    return Response(content=to_wav_bytes(wav, engine.sample_rate), media_type="audio/wav")


# ---------------------------------------------------------------- 합성

@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    """글 → wav (24kHz 16bit mono). 메트릭은 X-* 헤더로."""
    voice_code = _pick_voice(req.voice, req.voice_style)
    engine = await Engine.get()
    try:
        wav, m = await engine.synth_timed(req.text, voice_code=voice_code, lang=req.lang,
                                          steps=req.steps, speed=req.speed)
    except Exception as exc:
        logger.exception("synthesize 실패")
        raise HTTPException(status_code=500, detail=f"합성 실패: {exc}") from exc
    ts = int(time.time())
    return Response(
        content=to_wav_bytes(wav, engine.sample_rate),
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="synth_{voice_code}_{ts}.wav"',
            "Access-Control-Expose-Headers": (
                "X-Synth-Seconds, X-Audio-Seconds, X-Rtf, X-Voice, X-Speed, X-Steps, X-Lang, X-Tags, X-Sample-Rate"),
            "X-Synth-Seconds": str(m["synth_seconds"]),
            "X-Audio-Seconds": str(m["duration_seconds"]),
            "X-Rtf": str(m["rtf"]),
            "X-Voice": voice_code,
            "X-Speed": str(m["speed"]),
            "X-Steps": str(m["steps"]),
            "X-Lang": str(m["lang"]),
            "X-Tags": ",".join(m["tags"]),
            "X-Sample-Rate": str(engine.sample_rate),
        },
    )


async def _run_batch_job(rec: JobRecord, *, raw: bytes, filename: str | None, chapter_explicit: str | None,
                         output_root: str | None, voice_override: str | None, speed: float | None,
                         steps: int | None) -> None:
    try:
        rec.status = "running"
        engine = await Engine.get()
        script = parse_script(raw)

        async def cb(completed: int, total: int, current: int | None):
            rec.completed = completed
            rec.current_scene = current

        result = await run_batch(engine=engine, script=script, chapter_id_explicit=chapter_explicit,
                                 filename_hint=filename, output_root=Path(output_root) if output_root else None,
                                 voice_override=voice_override, speed=speed, steps=steps, on_progress=cb)
        rec.files = result.files
        rec.warnings = result.warnings
        rec.output_dir = result.output_dir
        rec.status = "done"
    except Exception as exc:
        logger.exception("batch job 실패: %s", rec.job_id)
        rec.status = "error"
        rec.error = str(exc)
    finally:
        rec.finished_at = datetime.now(timezone.utc)


@router.post("/batch", response_model=BatchSubmitResponse)
async def submit_batch(
    background: BackgroundTasks,
    script: UploadFile = File(...),
    chapter: str | None = Form(None),
    output_root: str | None = Form(None),
    voice_override: str | None = Form(None),
    speed: float | None = Form(None),
    steps: int | None = Form(None),
    total_step: int | None = Form(None),
) -> BatchSubmitResponse:
    """대본 JSON → 장면마다 wav + SRT, 장 전체 SRT. 진행은 status_url 로."""
    raw = await script.read()
    if not raw:
        raise HTTPException(status_code=422, detail="대본 파일이 비어 있습니다")
    try:
        parsed = parse_script(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"대본 JSON 오류: {exc}") from exc
    try:
        chapter_id = resolve_chapter_id(explicit=chapter, script_field=parsed.chapter, filename_hint=script.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if voice_override:
        voice_override = _pick_voice(voice_override)

    s = settings_module.load()
    out_root = Path(output_root) if output_root else s.workspace_root
    rec = await get_registry().create(chapter=chapter_id, scene_count=len(parsed.scenes),
                                      output_dir=out_root / f"ch{chapter_id}" / "audio")
    background.add_task(_run_batch_job, rec, raw=raw, filename=script.filename, chapter_explicit=chapter,
                        output_root=output_root, voice_override=voice_override, speed=speed,
                        steps=steps if steps is not None else total_step)
    return BatchSubmitResponse(job_id=rec.job_id, scene_count=len(parsed.scenes), chapter=chapter_id,
                               status_url=f"/api/jobs/{rec.job_id}")


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> JobStatus:
    rec = await get_registry().get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="job not found")
    return rec.to_status()


@router.get("/jobs/{job_id}/zip")
async def get_job_zip(job_id: str) -> StreamingResponse:
    rec = await get_registry().get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status != "done":
        raise HTTPException(status_code=409, detail=f"아직 끝나지 않았습니다 (status={rec.status})")
    audio_dir = Path(rec.output_dir)
    sub_dir = audio_dir.parent / "subtitles"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in (sorted(audio_dir.glob("*.wav")) if audio_dir.exists() else []):
            zf.write(p, arcname=f"audio/{p.name}")
        for p in (sorted(sub_dir.glob("*.srt")) if sub_dir.exists() else []):
            zf.write(p, arcname=f"subtitles/{p.name}")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="ch{rec.chapter}_bundle.zip"'})


# ---------------------------------------------------------------------------
# 장면 단위 화면: 대본 읽기 → 장면 하나씩 합성 → 파일 보기
# ---------------------------------------------------------------------------

@router.post("/parse_script")
async def parse_script_endpoint(
    script: UploadFile = File(...),
    chapter: str | None = Form(None),
) -> dict:
    raw = await script.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty script file")
    try:
        parsed = parse_script(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid script JSON: {exc}") from exc
    try:
        chapter_id = resolve_chapter_id(
            explicit=chapter,
            script_field=parsed.chapter,
            filename_hint=script.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    s = settings_module.load()
    vmap = load_voice_map(s.voice_map_path, s.voices_dir, s.default_voice)
    scenes_out = []
    for sc in parsed.scenes:
        code, _ = vmap.resolve(sc.voice_style)
        scenes_out.append({
            "scene": sc.scene,
            "narration_text": sc.narration_text,
            "srt_text": sc.srt_text,
            "narration_seconds": sc.narration_seconds,
            "voice_style": sc.voice_style,
            "voice_resolved": code,
            "image_filename": sc.image_filename,
        })
    return {"chapter": chapter_id, "scenes": scenes_out}


@router.post("/synthesize_scene")
async def synthesize_scene(
    chapter: str = Form(...),
    scene: int = Form(...),
    text: str = Form(...),
    srt_text: str | None = Form(None),       # SRT 자막에 들어갈 원본 텍스트 (없으면 text 사용)
    voice: str | None = Form(None),
    voice_style: str | None = Form(None),
    speed: float | None = Form(None),
    steps: int | None = Form(None),
    total_step: int | None = Form(None),
    lang: str | None = Form(None),
    narration_seconds: float | None = Form(None),   # 참고용 — 타이밍은 실측 오디오 길이를 쓴다
    output_root: str | None = Form(None),
) -> dict:
    if not text.strip():
        raise HTTPException(status_code=422, detail="empty narration_text")
    # 챕터 ID 정규화. 예전엔 여기만 날것으로 썼던 탓에 `5` 를 넘기면 ch05 가
    # 아니라 ch5 디렉터리가 조용히 생겨서, 나중에 SRT 병합이 짝을 못 찾았다.
    chapter = normalize_chapter_id(chapter) or ""
    if not chapter:
        raise HTTPException(status_code=422, detail="invalid chapter id")

    s = settings_module.load()
    voice_code = _pick_voice(voice, voice_style)
    engine = await Engine.get()

    out_root = Path(output_root) if output_root else s.workspace_root

    try:
        wav, metrics = await engine.synth_timed(
            text, voice_code=voice_code, lang=lang,
            steps=steps if steps is not None else total_step, speed=speed,
        )
    except Exception as exc:
        logger.exception("synthesize_scene 실패: ch%s scene %s", chapter, scene)
        raise HTTPException(status_code=500, detail=f"synthesis failed: {exc}") from exc

    from ..audio_io import write_wav as _write_wav
    wav_path = narration_path(out_root, chapter, int(scene))
    _write_wav(wav_path, wav, engine.sample_rate)

    actual_duration = float(len(wav)) / float(engine.sample_rate)
    body_for_srt = (srt_text or text).strip()  # 자막엔 항상 원본 텍스트가 들어감
    # ~30자 구간으로 쪼개고 실측 오디오 길이에 맞춰 자동 타임코드 부여 (사용자가 이후 조정)
    cues = auto_time_cues(split_into_cues(body_for_srt), actual_duration)
    srt_body_str = make_multi_srt(cues)
    srt_p = srt_path(out_root, chapter, int(scene))
    srt_p.parent.mkdir(parents=True, exist_ok=True)
    srt_p.write_text(srt_body_str, encoding="utf-8")

    return {
        "chapter": chapter,
        "scene": int(scene),
        "voice": voice_code,
        "duration_seconds": actual_duration,
        "wav_url": f"/api/files/ch{chapter}/audio/{wav_path.name}",
        "srt_url": f"/api/files/ch{chapter}/subtitles/{srt_p.name}",
        "cues": [{"text": c.text, "start": c.start, "end": c.end} for c in cues],
        "synth_seconds": metrics["synth_seconds"],
        "rtf": metrics["rtf"],
        "lang": metrics["lang"],
        "tags": metrics["tags"],
    }


def _read_root(output_root: str | None) -> Path:
    """읽기 경로 루트. 쓰기 쪽 out_root 계산과 반드시 같은 규칙이어야 한다.

    예전에는 쓰기만 output_root 를 존중하고 읽기는 항상 workspace_root 를 봐서,
    커스텀 루트에 쓴 파일이 UI에서 영영 안 보였다.
    """
    return Path(output_root) if output_root else settings_module.load().workspace_root


@router.get("/files/ch{chapter_id}/{kind}/{filename}")
async def serve_workspace_file(
    chapter_id: str, kind: str, filename: str, output_root: str | None = None
) -> FileResponse:
    if kind not in ("audio", "subtitles"):
        raise HTTPException(status_code=404, detail="unknown kind")
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    s = settings_module.load()
    base = _read_root(output_root) / f"ch{chapter_id}" / kind
    p = base / filename
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    media = "audio/wav" if kind == "audio" else "text/plain; charset=utf-8"
    return FileResponse(str(p), media_type=media, filename=filename)


@router.get("/files/ch{chapter_id}/subtitles_full")
async def serve_chapter_srt(chapter_id: str, output_root: str | None = None) -> FileResponse:
    s = settings_module.load()
    p = chapter_srt_path(_read_root(output_root), chapter_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="chapter SRT not generated yet")
    return FileResponse(str(p), media_type="text/plain; charset=utf-8", filename=f"ch{chapter_id}.srt")


_PER_SCENE_SRT_RE = re.compile(r"^ch[^_]+_(\d+)_narration\.srt$")


def _wav_duration(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / float(info.samplerate)


def _cues_from_payload(raw: str) -> list[Cue]:
    """프런트가 보낸 cues JSON([{start,end,text}, ...])을 검증해 Cue 목록으로."""
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid cues JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="cues must be a list")
    cues: list[Cue] = []
    prev_end = -1.0
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"cue {i} must be an object")
        text = str(item.get("text", "")).strip()
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", 0.0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"cue {i} has non-numeric time")
        if start < 0 or end < start:
            raise HTTPException(status_code=422, detail=f"cue {i} time invalid (start={start}, end={end})")
        if start < prev_end - 1e-3:
            raise HTTPException(status_code=422, detail=f"cue {i} overlaps previous (start < prev end)")
        prev_end = end
        if text:
            cues.append(Cue(text=text, start=round(start, 3), end=round(end, 3)))
    return cues


@router.post("/save_scene_srt")
async def save_scene_srt(
    chapter: str = Form(...),
    scene: int = Form(...),
    cues: str = Form(...),
    output_root: str | None = Form(None),
) -> dict:
    """사용자가 UI에서 조정한 큐 타임코드를 per-scene SRT로 덮어쓴다."""
    chap = normalize_chapter_id(chapter)
    if chap is None:
        raise HTTPException(status_code=422, detail=f"invalid chapter: {chapter}")
    parsed = _cues_from_payload(cues)
    if not parsed:
        raise HTTPException(status_code=422, detail="no cues to save")

    s = settings_module.load()
    out_root = Path(output_root) if output_root else s.workspace_root
    srt_p = srt_path(out_root, chap, int(scene))
    srt_p.parent.mkdir(parents=True, exist_ok=True)
    srt_p.write_text(make_multi_srt(parsed), encoding="utf-8")
    return {
        "chapter": chap,
        "scene": int(scene),
        "cue_count": len(parsed),
        "srt_url": f"/api/files/ch{chap}/subtitles/{srt_p.name}",
    }


@router.post("/regenerate_chapter_srt")
async def regenerate_chapter_srt(chapter: str = Form(...)) -> dict:
    """workspace의 per-scene SRT + WAV을 다시 모아 챕터 통합 SRT를 새로 만든다.

    카드별 재생성으로 일부 scene이 갱신된 뒤, 챕터 자막의 타임코드를 현재
    오디오와 동기화하기 위함. 멀티큐 per-scene SRT를 누적 offset으로 병합한다.
    """
    chap = normalize_chapter_id(chapter)
    if chap is None:
        raise HTTPException(status_code=422, detail=f"invalid chapter: {chapter}")

    s = settings_module.load()
    sub_dir = chapter_subtitles_dir(s.workspace_root, chap)
    if not sub_dir.exists():
        raise HTTPException(status_code=404, detail=f"no subtitles dir for ch{chap}")

    scene_data: list[tuple[int, list[Cue], float]] = []
    for srt_p in sorted(sub_dir.glob("*_narration.srt")):
        m = _PER_SCENE_SRT_RE.match(srt_p.name)
        if not m:
            continue
        scene_num = int(m.group(1))
        wav_p = narration_path(s.workspace_root, chap, scene_num)
        if not wav_p.exists():
            # SRT만 있고 WAV가 없으면 스킵 (오디오 없는 scene은 챕터 SRT에 포함 못함)
            continue
        cues = parse_srt_cues(srt_p.read_text(encoding="utf-8"))
        dur = _wav_duration(wav_p)
        scene_data.append((scene_num, cues, dur))

    if not scene_data:
        raise HTTPException(status_code=404, detail="no per-scene SRT/WAV pairs found")

    scene_data.sort(key=lambda t: t[0])
    chapter_text = merge_scene_cues([(cues, dur) for _, cues, dur in scene_data])
    cp = chapter_srt_path(s.workspace_root, chap)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(chapter_text, encoding="utf-8")
    return {
        "chapter": chap,
        "scene_count": len(scene_data),
        "url": f"/api/files/ch{chap}/subtitles_full",
    }


# ---------------------------------------------------------------- 발음 변환

class TextIn(BaseModel):
    text: str = Field(..., max_length=20000)


class TextOut(BaseModel):
    text: str


def _convert(text: str) -> str:
    if not text.strip():
        return ""
    pmap = load_pronunciation_map(settings_module.load().pronunciation_map_path)
    return pmap.apply(text, spell_unknown_acronyms=True, convert_years=True)


@router.post("/to_pronunciation", response_model=TextOut)
async def to_pronunciation(req: TextIn) -> TextOut:
    """발음 사전 + 대문자 약어 음역 + 연도·숫자+단위 — 합성 직전과 같은 변환."""
    return TextOut(text=_convert(req.text))


@router.post("/dict/preview", response_model=TextOut)
async def dict_preview(req: TextIn) -> TextOut:
    return TextOut(text=_convert(req.text))


@router.post("/prepare")
async def prepare(req: TextIn) -> dict:
    """모델에 실제로 들어갈 글 + 태그 + 경고."""
    return {"text": _convert(req.text), "tags": tags_module.find(req.text),
            "warnings": tags_module.validate(req.text)}


@router.get("/tags")
async def list_tags() -> dict:
    return {"tags": tags_module.as_dicts(), "format": "[laughter]"}


# ---------------------------------------------------------------- 발음 본사전

class DictRule(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    value: str = Field(..., min_length=1, max_length=128)


class DictResponse(BaseModel):
    rules: dict[str, str]
    count: int
    path: str = ""


def _dict_resp(df: dictsync.DictFile) -> DictResponse:
    return DictResponse(rules=df.rules, count=len(df.rules), path=str(dictsync.master_path()))


@router.get("/dict", response_model=DictResponse)
async def dict_get() -> DictResponse:
    """본사전 전체 — 다른 앱은 이것을 받아 쓰면 된다."""
    return _dict_resp(dictsync.read_master())


@router.post("/dict", response_model=DictResponse)
async def dict_upsert(rule: DictRule) -> DictResponse:
    key, val = rule.key.strip(), rule.value.strip()
    if not key or not val:
        raise HTTPException(status_code=400, detail="key/value 가 비었습니다")
    df = dictsync.read_master()
    df.rules[key] = val
    dictsync.write_master(df)
    return _dict_resp(df)


# ---------------------------------------------------------------- 앱 사전 연결 ([업데이트]/[다운받기])

class LinkIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    path: str = Field(..., min_length=3)


class PushIn(BaseModel):
    choices: dict[str, str] = Field(default_factory=dict)   # 충돌 key → "app" | "master"


class PullIn(BaseModel):
    force: bool = False


@router.get("/dict/links")
async def links_list() -> dict:
    return {"links": dictsync.all_status(), "master_path": str(dictsync.master_path())}


@router.post("/dict/links")
async def links_add(body: LinkIn) -> dict:
    try:
        lid = dictsync.add_link(body.name, body.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"사전 파일을 읽지 못했습니다: {exc}") from exc
    return dictsync.status(lid).to_dict()


@router.get("/dict/candidates")
async def links_candidates() -> dict:
    """이 폴더 옆(상위 폴더 아래)에서 발음 사전처럼 보이는 파일 — 연결 후보."""
    import asyncio
    return {"candidates": await asyncio.to_thread(dictsync.find_candidates)}


@router.delete("/dict/links/{link_id}")
async def links_remove(link_id: str) -> dict:
    dictsync.remove_link(link_id)
    return {"ok": True}


@router.get("/dict/links/{link_id}")
async def links_status(link_id: str) -> dict:
    try:
        return dictsync.status(link_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/dict/links/{link_id}/push")
async def links_push(link_id: str, body: PushIn | None = None) -> dict:
    """[업데이트] 그 앱에서 바뀐 것만 본사전에 올린다."""
    try:
        res = dictsync.push(link_id, (body.choices if body else {}))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**res, "status": dictsync.status(link_id).to_dict()}


@router.post("/dict/links/{link_id}/pull")
async def links_pull(link_id: str, body: PullIn | None = None) -> dict:
    """[다운받기] 본사전을 그 앱 사전 파일로 받는다 (받기 전 파일은 백업)."""
    try:
        res = dictsync.pull(link_id, force=bool(body and body.force))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**res, "status": dictsync.status(link_id).to_dict()}


# 키에 '/' 가 들어갈 수 있어(:path) 연결 경로들보다 뒤에 둔다
@router.delete("/dict/{key:path}", response_model=DictResponse)
async def dict_delete(key: str) -> DictResponse:
    df = dictsync.read_master()
    if key.strip() not in df.rules:
        raise HTTPException(status_code=404, detail=f"'{key}' 가 사전에 없습니다")
    del df.rules[key.strip()]
    dictsync.write_master(df)
    return _dict_resp(df)


# ---------------------------------------------------------------- 상태

@router.get("/health")
async def health() -> dict:
    s = settings_module.load()
    info: dict = {
        "status": "ok",
        "engine_loaded": Engine.loaded(),
        "default_voice": s.default_voice,
        "voices": [v.code for v in list_voices(s.voices_dir)],
        "sample_rate": settings_module.SAMPLE_RATE,
        "device_setting": s.device,
        "remote_server": s.remote_server or None,
    }
    if Engine.loaded():
        e = Engine.get_sync()
        info.update(device=e.device, device_name=e.device_name, gpu=e.use_gpu_active)
    return info

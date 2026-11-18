/* ---------------------------------------------------------------------------
   앱 셸 — 사이드바(목소리/스텝/속도), 목소리 추가, 표현 태그 칩, 결과 메트릭,
   발음 사전 탭 임베드.

   app.js 는 window.__s3 로만 붙는다. app.js 가 /api/voices 로 #voice <select>
   를 채운 뒤 window.__s3.onVoices() 를 부른다.
--------------------------------------------------------------------------- */
(() => {
  const $ = (id) => document.getElementById(id);
  window.__s3 = window.__s3 || {};

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ------------------------------------------------------------------ 목소리 카드
  const voiceSel = $('voice');
  const grid = $('voiceGrid');
  let previewAudio = null;

  function voiceInfo(code) {
    const d = window.__s3.voicesData;
    return d ? d.voices.find((v) => v.code === code) : null;
  }

  function buildVoiceGrid() {
    const d = window.__s3.voicesData;
    if (!grid || !d) return;
    grid.innerHTML = '';
    if (!d.voices.length) {
      grid.innerHTML = '<p class="side-help">등록된 목소리가 없습니다. 「+ 목소리 추가」로 등록하세요.</p>';
      return;
    }
    d.voices.forEach((v) => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'voice-cell' + (v.ref_ok ? '' : ' broken');
      cell.dataset.code = v.code;
      cell.title = `${v.code} · ${v.name}` +
        (v.gender ? ` (${v.gender})` : '') +
        `\nspeed ${v.speed ?? '기본'} · steps ${v.steps ?? '기본'}` +
        (v.memo ? `\n${v.memo}` : '') +
        (v.ref_ok ? '' : '\n⚠ 기준 녹음 파일이 없습니다');
      cell.innerHTML = `<span class="voice-code">${escapeHtml(v.code)}</span>` +
        `<span class="voice-name">${escapeHtml(v.name)}</span>`;
      if (v.default_for_unknown) {
        const star = document.createElement('span');
        star.className = 'voice-default';
        star.textContent = '★';
        star.title = '기본 목소리';
        cell.appendChild(star);
      }
      const play = document.createElement('button');
      play.type = 'button';
      play.className = 'voice-play';
      play.textContent = '▶';
      play.title = `${v.code} 미리 듣기 (실제 합성이라 처음엔 모델을 올리느라 오래 걸립니다)`;
      play.addEventListener('click', (ev) => { ev.stopPropagation(); previewVoice(v.code, play); });
      cell.appendChild(play);
      cell.addEventListener('click', () => selectVoice(v.code, true));
      grid.appendChild(cell);
    });
    selectVoice(voiceSel.value || d.default, true);
  }

  // 목소리를 고르면 사이드바 스텝·속도를 그 목소리 설정값으로 맞춘다
  function selectVoice(code, applyDefaults) {
    if (!code) return;
    voiceSel.value = code;
    grid.querySelectorAll('.voice-cell').forEach((c) =>
      c.classList.toggle('selected', c.dataset.code === code));
    const v = voiceInfo(code);
    if (applyDefaults && v) {
      setSlider('totalStep', v.steps ?? 32);
      setSlider('speed', v.speed ?? 1.0);
    }
  }

  async function previewVoice(code, btn) {
    if (btn.disabled) return;
    btn.disabled = true; btn.classList.add('busy'); btn.textContent = '…';
    try {
      const res = await fetch(`/api/voices/${encodeURIComponent(code)}/preview`);
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch {}
        throw new Error(detail);
      }
      if (previewAudio) previewAudio.pause();
      previewAudio = new Audio(URL.createObjectURL(await res.blob()));
      previewAudio.play();
      refreshBadges();
    } catch (e) {
      alert(`미리 듣기 실패: ${e.message}`);
    } finally {
      btn.disabled = false; btn.classList.remove('busy'); btn.textContent = '▶';
    }
  }

  window.__s3.onVoices = buildVoiceGrid;
  if (window.__s3.voicesData) buildVoiceGrid();

  // ------------------------------------------------------------------ 목소리 추가
  const dlg = $('addVoiceDialog');
  const form = $('addVoiceForm');
  const msg = $('addVoiceMsg');
  $('addVoiceBtn').addEventListener('click', () => { msg.textContent = ''; form.reset(); dlg.showModal(); });
  $('addVoiceCancel').addEventListener('click', () => dlg.close());
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    ['speed', 'steps'].forEach((k) => { if (!fd.get(k)) fd.delete(k); });
    const btn = $('addVoiceSubmit');
    btn.disabled = true; msg.textContent = '등록 중…';
    try {
      const res = await fetch('/api/voices', { method: 'POST', body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || res.statusText);
      await window.__s3.reloadVoices();
      selectVoice(j.voice.code, true);
      msg.textContent = `등록했습니다: ${j.voice.code} (${j.seconds}초)` + (j.note ? ` — ${j.note}` : '') +
        ' · ▶ 로 들어 보세요. 첫 합성 때 목소리를 등록(받아쓰기)하느라 조금 더 걸립니다.';
    } catch (e) {
      msg.textContent = `실패: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  // ------------------------------------------------------------------ 배지
  async function refreshBadges() {
    try {
      const j = await (await fetch('/api/health')).json();
      const eng = $('badgeEngine');
      const prov = $('badgeProvider');
      if (j.engine_loaded) {
        eng.textContent = '엔진 준비됨';
        eng.className = 'badge ok';
        prov.textContent = j.device_name || j.device;
        prov.className = 'badge' + (j.gpu ? ' ok' : ' wait');
      } else {
        eng.textContent = '엔진 대기 중 — 첫 생성 때 로드 (수십 초)';
        eng.className = 'badge wait';
        prov.textContent = j.remote_server ? `원격 ${j.remote_server}` : `장치 ${j.device_setting}`;
      }
    } catch {
      const eng = $('badgeEngine');
      eng.textContent = '서버 연결 실패';
      eng.className = 'badge err';
    }
  }

  // ------------------------------------------------------------------ 표현 태그 칩
  const tagBar = $('tagBar');
  const pronTa = $('text');
  const warnBox = $('tagWarnings');
  const FIRST = 4;           // 처음엔 자주 쓰는 몇 개만
  let allTags = [];
  let showAll = false;

  function renderTagChips() {
    if (!tagBar) return;
    tagBar.querySelectorAll('.tag-chip, .tagbar-more').forEach((n) => n.remove());
    (showAll ? allTags : allTags.slice(0, FIRST)).forEach((t) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'tag-chip';
      chip.innerHTML = `${escapeHtml(t.name)} <code>${escapeHtml(t.tag)}</code>`;
      chip.title = `${t.tag} — ${t.effect}\n클릭하면 커서 자리에 넣습니다.`;
      chip.addEventListener('click', () => insertAtCursor(t.tag));
      tagBar.appendChild(chip);
    });
    if (allTags.length > FIRST) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'tagbar-more';
      more.textContent = showAll ? '접기' : `+${allTags.length - FIRST}종 더`;
      more.addEventListener('click', () => { showAll = !showAll; renderTagChips(); });
      tagBar.appendChild(more);
    }
  }

  function insertAtCursor(tag) {
    if (!pronTa) return;
    const start = pronTa.selectionStart ?? pronTa.value.length;
    const end = pronTa.selectionEnd ?? start;
    const before = pronTa.value.slice(0, start);
    const after = pronTa.value.slice(end);
    const lead = before && !/\s$/.test(before) ? ' ' : '';
    const trail = after && !/^\s/.test(after) ? ' ' : '';
    pronTa.value = before + lead + tag + trail + after;
    const pos = (before + lead + tag + trail).length;
    pronTa.setSelectionRange(pos, pos);
    pronTa.focus();
    pronTa.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function loadTags() {
    try {
      allTags = (await (await fetch('/api/tags')).json()).tags || [];
      renderTagChips();
    } catch (e) { console.error('tag list failed', e); }
  }

  // ------------------------------------------------------------------ 글자수 + 태그 경고
  const charCount = $('charCount');
  let warnTimer = null;

  function updateCharCount() {
    if (!charCount || !pronTa) return;
    const n = pronTa.value.length;
    charCount.textContent = `${n.toLocaleString()}글자`;
    charCount.classList.toggle('over', n > 5000);
    if (n > 5000) charCount.textContent += ' — 5,000자를 넘었습니다 (대본 일괄을 쓰세요)';
  }

  async function refreshWarnings() {
    if (!warnBox || !pronTa) return;
    const text = pronTa.value;
    if (!text.trim()) { warnBox.classList.add('hidden'); return; }
    try {
      const res = await fetch('/api/prepare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.slice(0, 5000) }),
      });
      if (!res.ok) return;
      const j = await res.json();
      if (!j.warnings || !j.warnings.length) { warnBox.classList.add('hidden'); return; }
      warnBox.innerHTML = j.warnings.map((w) => `<p>⚠ ${escapeHtml(w)}</p>`).join('');
      warnBox.classList.remove('hidden');
    } catch { /* 경고는 부가 기능 */ }
  }

  if (pronTa) {
    pronTa.addEventListener('input', () => {
      updateCharCount();
      clearTimeout(warnTimer);
      warnTimer = setTimeout(refreshWarnings, 500);
    });
    updateCharCount();
  }

  // ------------------------------------------------------------------ 생성 결과 메트릭
  window.__s3.showMetrics = (headers) => {
    const box = $('metrics');
    if (!box || !headers) return;
    const dur = parseFloat(headers.get('X-Audio-Seconds'));
    const syn = parseFloat(headers.get('X-Synth-Seconds'));
    const rtf = parseFloat(headers.get('X-Rtf'));
    if (!Number.isFinite(dur)) { box.classList.add('hidden'); return; }
    $('mDuration').innerHTML = `${dur.toFixed(2)}<small>초</small>`;
    $('mSynth').innerHTML = `${syn.toFixed(2)}<small>초</small>`;
    $('mRtf').innerHTML = `${rtf.toFixed(2)}<small>배</small>`;
    $('mRtf').parentElement.title =
      `${headers.get('X-Voice')} · speed ${headers.get('X-Speed')} · steps ${headers.get('X-Steps')}\n` +
      `오디오 ${dur.toFixed(2)}초를 ${syn.toFixed(2)}초 만에 만들었습니다. 1보다 크면 실시간보다 빠릅니다.`;
    box.classList.remove('hidden');
    refreshBadges();
  };

  // ------------------------------------------------------------------ 발음 사전 탭 (독립 페이지 /dict 를 그대로)
  let dictLoaded = false;
  function mountDict() {
    if (dictLoaded) return;
    const root = $('dictRoot');
    if (!root) return;
    const f = document.createElement('iframe');
    f.src = '/dict?embed=1';
    f.title = '발음 사전';
    f.style.cssText = 'width:100%;height:calc(100vh - 240px);min-height:620px;border:1px solid var(--border);border-radius:6px;background:#fff';
    root.appendChild(f);
    dictLoaded = true;
  }

  async function refreshDictCount() {
    try {
      const j = await (await fetch('/api/dict')).json();
      const el = $('dictCountTab');
      if (el) el.textContent = j.count;
    } catch { /* 배지일 뿐 */ }
  }
  window.__s3.refreshDictCount = refreshDictCount;

  document.querySelectorAll('.tab').forEach((t) => {
    t.addEventListener('click', () => { if (t.dataset.tab === 'dict') mountDict(); });
  });

  // ------------------------------------------------------------------ 슬라이더
  function setSlider(id, value) {
    const el = $(id);
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event('input'));
  }
  function bindSideSlider(id, valId, digits) {
    const el = $(id), v = $(valId);
    if (!el || !v) return;
    const show = () => { v.textContent = Number(el.value).toFixed(digits); };
    el.addEventListener('input', show);
    show();
  }
  bindSideSlider('speed', 'speedValue', 2);
  bindSideSlider('totalStep', 'stepValue', 0);
  // 대본 일괄 슬라이더는 건드렸을 때만 보낸다 — 아니면 장면마다 그 목소리의 설정값
  [['batchSpeed', 'batchSpeedValue', 2], ['batchTotalStep', 'batchStepValue', 0]].forEach(([id, valId, d]) => {
    const el = $(id), v = $(valId);
    if (!el || !v) return;
    el.addEventListener('input', () => {
      el.dataset.touched = '1';
      v.textContent = Number(el.value).toFixed(d);
    });
  });

  loadTags();
  refreshBadges();
  refreshDictCount();
})();

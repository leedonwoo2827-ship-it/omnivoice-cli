/* 발음 사전 — 다른 앱 사전과 오가기 ([업데이트] / [다운받기]) */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const listEl = $('linkList');
  if (!listEl) return;

  async function api(url, opts = {}) {
    const res = await fetch(url, {
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined, ...opts,
    });
    let j = null;
    try { j = await res.json(); } catch {}
    if (!res.ok) throw new Error((j && j.detail) || res.statusText);
    return j;
  }

  function afterMasterChange() {
    if (window.__reloadDict) window.__reloadDict();
    try { window.parent.__s3 && window.parent.__s3.refreshDictCount && window.parent.__s3.refreshDictCount(); } catch {}
  }

  function stats(st) {
    if (st.error) return `<span class="err">${esc(st.error)}</span>`;
    if (!st.exists) return '<span class="err">파일이 없습니다</span>';
    const push = Object.keys(st.to_push).length + st.to_delete.length;
    const conf = Object.keys(st.conflicts).length;
    return [
      `<span>앱 ${st.app_count}개 · 본사전 ${st.master_count}개</span>`,
      `<span class="${push ? 'warn' : ''}">올릴 것 ${push}</span>`,
      `<span class="${conf ? 'warn' : ''}">충돌 ${conf}</span>`,
      `<span>받을 것 ${st.to_pull}</span>`,
      st.first_time ? '<span class="warn">처음 연결</span>' : '',
      st.bad_lines && st.bad_lines.length ? `<span class="err" title="${esc(st.bad_lines.join('\n'))}">깨진 줄 ${st.bad_lines.length} (다운받기로 고쳐짐)</span>` : '',
    ].join('');
  }

  function detail(st) {
    const rows = [];
    Object.entries(st.to_push).forEach(([k, v]) =>
      rows.push(`<tr><td>올림</td><td><code>${esc(k)}</code></td><td>${esc(v)}</td><td></td></tr>`));
    st.to_delete.forEach((k) =>
      rows.push(`<tr><td>지움</td><td><code>${esc(k)}</code></td><td colspan="2">앱에서 지웠습니다 → 본사전에서도 지움</td></tr>`));
    Object.entries(st.conflicts).forEach(([k, c]) => {
      const name = `c_${st.id}_${btoa(unescape(encodeURIComponent(k))).replace(/=/g, '')}`;
      rows.push(`<tr data-key="${esc(k)}"><td>충돌</td><td><code>${esc(k)}</code></td>
        <td class="choice">
          <label><input type="radio" name="${name}" value="app"> 앱: ${c.app === null ? '<em>지움</em>' : esc(c.app)}</label>
          <label><input type="radio" name="${name}" value="master"> 본사전: ${esc(c.master)}</label>
        </td><td></td></tr>`);
    });
    if (!rows.length) return '';
    return `<details class="link-detail" ${Object.keys(st.conflicts).length ? 'open' : ''}>
      <summary>올릴 내용 보기 (${rows.length})</summary>
      <table><tbody>${rows.join('')}</tbody></table></details>`;
  }

  function card(st) {
    const div = document.createElement('div');
    const pending = !st.error && st.exists && (Object.keys(st.to_push).length || st.to_delete.length || Object.keys(st.conflicts).length);
    div.className = 'link-card' + (pending ? ' pending' : '') + (st.error || !st.exists ? ' missing' : '');
    div.innerHTML = `
      <div class="link-head">
        <span class="link-name">${esc(st.name || st.id)}</span>
        <span class="link-stats">${stats(st)}</span>
        <span class="link-actions">
          <button type="button" class="act-push primary" title="그 앱에서 고친 것을 본사전에 올립니다">↑ 업데이트</button>
          <button type="button" class="act-pull" title="본사전 전체를 그 앱 사전 파일로 받습니다 (받기 전 파일은 config/dict_base/backup/ 에 백업)">↓ 다운받기</button>
          <button type="button" class="act-remove" title="연결만 끊습니다 (파일은 그대로)">✕</button>
        </span>
        <span class="link-path">${esc(st.path || '')}</span>
      </div>
      ${st.error ? '' : detail(st)}
      <div class="link-msg"></div>`;
    const msg = div.querySelector('.link-msg');
    const say = (t, ok) => { msg.textContent = t; msg.className = 'link-msg ' + (ok ? 'ok' : 'err'); };

    div.querySelector('.act-push').addEventListener('click', async (ev) => {
      const choices = {};
      div.querySelectorAll('tr[data-key]').forEach((tr) => {
        const r = tr.querySelector('input:checked');
        if (r) choices[tr.dataset.key] = r.value;
      });
      ev.target.disabled = true;
      try {
        const r = await api(`/api/dict/links/${encodeURIComponent(st.id)}/push`, {
          method: 'POST', body: JSON.stringify({ choices }),
        });
        afterMasterChange();
        await load();
        const left = r.unresolved.length ? ` · 고르지 않은 충돌 ${r.unresolved.length}개는 그대로 뒀습니다` : '';
        flash(st.id, `업데이트: 새로 ${r.added} · 바뀜 ${r.changed} · 지움 ${r.deleted} → 본사전 ${r.master_count}개${left}`, true);
      } catch (e) { say(`업데이트 실패: ${e.message}`, false); ev.target.disabled = false; }
    });

    div.querySelector('.act-pull').addEventListener('click', async (ev) => {
      if (!confirm(`${st.name} 사전 파일을 본사전(${st.master_count}개)으로 바꿉니다.\n${st.path}\n\n받기 전 파일은 백업해 둡니다. 계속할까요?`)) return;
      ev.target.disabled = true;
      try {
        const r = await api(`/api/dict/links/${encodeURIComponent(st.id)}/pull`, { method: 'POST', body: JSON.stringify({}) });
        await load();
        flash(st.id, `다운받기: ${r.written}개 (바뀐 것 ${r.changed}) · 백업 ${r.backup}`, true);
      } catch (e) { say(e.message, false); ev.target.disabled = false; }
    });

    div.querySelector('.act-remove').addEventListener('click', async () => {
      if (!confirm(`${st.name} 연결을 끊을까요? (사전 파일은 그대로 둡니다)`)) return;
      await api(`/api/dict/links/${encodeURIComponent(st.id)}`, { method: 'DELETE' });
      load();
    });
    div.dataset.id = st.id;
    return div;
  }

  function flash(id, text, ok) {
    const c = listEl.querySelector(`.link-card[data-id="${CSS.escape(id)}"] .link-msg`);
    if (c) { c.textContent = text; c.className = 'link-msg ' + (ok ? 'ok' : 'err'); }
  }

  async function load() {
    try {
      const j = await api('/api/dict/links');
      listEl.innerHTML = '';
      if (!j.links.length) {
        listEl.innerHTML = '<p class="empty">연결된 앱 사전이 없습니다. 아래 「+ 앱 사전 연결」로 추가하세요.</p>';
        return;
      }
      j.links.forEach((st) => listEl.appendChild(card(st)));
    } catch (e) {
      listEl.innerHTML = `<p class="empty">불러오기 실패: ${esc(e.message)}</p>`;
    }
  }

  $('linkForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api('/api/dict/links', {
        method: 'POST', body: JSON.stringify({ name: $('linkName').value.trim(), path: $('linkPath').value.trim() }),
      });
      $('linkName').value = ''; $('linkPath').value = '';
      load();
    } catch (e) { alert(`연결 실패: ${e.message}`); }
  });

  $('findCandidates').addEventListener('click', async (ev) => {
    ev.target.disabled = true;
    $('candidateMsg').textContent = '찾는 중… (폴더가 많으면 수십 초)';
    try {
      const j = await api('/api/dict/candidates');
      const ul = $('candidateList'), dl = $('linkCandidates');
      ul.innerHTML = ''; dl.innerHTML = '';
      j.candidates.forEach((p) => {
        const li = document.createElement('li');
        li.textContent = p;
        li.title = '눌러서 경로 칸에 넣기';
        li.addEventListener('click', () => {
          $('linkPath').value = p;
          if (!$('linkName').value) {
            const parts = p.split(/[\\/]/);
            $('linkName').value = parts.length > 3 ? parts[2] : parts[0];
          }
          $('linkName').focus();
        });
        ul.appendChild(li);
        const o = document.createElement('option'); o.value = p; dl.appendChild(o);
      });
      $('candidateMsg').textContent = `${j.candidates.length}개`;
    } catch (e) { $('candidateMsg').textContent = `실패: ${e.message}`; }
    ev.target.disabled = false;
  });

  load();
})();

/* 3dflowhub 사이트 검색 — search.json(글·기초 가이드·도구별 정리)을 브라우저에서 검색.
   - 여러 단어: 모든 단어가 들어간 항목만, 제목 일치가 먼저
   - 한/영 자판 오타 자동 변환: 'ㅠㅣ둗ㅇㄷㄱ' → blender, 'qmffpsej' → 블렌더 (결과가 없을 때)
   - 키보드: Enter = 첫 결과 열기, Esc = 닫기, ↑↓ = 결과 이동 */
(function () {
  const q = document.getElementById('q');
  const box = document.getElementById('results');
  if (!q) return;
  let idx = null, ALIAS = {};
  const HOVER = matchMedia('(hover: hover)').matches;  // 키보드 안내는 마우스 환경에서만
  const esc = s => String(s).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');

  // ── 한글 → 영문 자판 (한글 모드로 영어를 친 경우) ─────────────────────────
  const CHO = 'r R s e E f a q Q t T d w W c z x v g'.split(' ');
  const JUNG = 'k o i O j p u P h hk ho hl y n nj np nl b m ml l'.split(' ');
  const JONG = ' r R rt s sw sg e f fr fa fq ft fx fv fg a q qt t T d w c z x v g'.split(' ');
  const COMPAT = 'ㄱㄲㄳㄴㄵㄶㄷㄸㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅃㅄㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ';
  const COMPAT_KEYS = 'r R rt s sw sg e E f fr fa fq ft fx fv fg a q Q qt t T d w W c z x v g k o i O j p u P h hk ho hl y n nj np nl b m ml l'.split(' ');
  function ko2en(s) {
    let out = '';
    for (const ch of s) {
      const c = ch.charCodeAt(0);
      if (c >= 0xAC00 && c <= 0xD7A3) {
        const n = c - 0xAC00;
        out += CHO[Math.floor(n / 588)] + JUNG[Math.floor((n % 588) / 28)] + JONG[n % 28];
      } else {
        const i = COMPAT.indexOf(ch);
        out += i >= 0 ? COMPAT_KEYS[i] : ch;
      }
    }
    return out.toLowerCase();
  }

  // ── 영문 자판 → 한글 (영문 모드로 한글을 친 경우) ─────────────────────────
  const KEY2JAMO = {r:'ㄱ',R:'ㄲ',s:'ㄴ',e:'ㄷ',E:'ㄸ',f:'ㄹ',a:'ㅁ',q:'ㅂ',Q:'ㅃ',t:'ㅅ',T:'ㅆ',d:'ㅇ',w:'ㅈ',W:'ㅉ',
    c:'ㅊ',z:'ㅋ',x:'ㅌ',v:'ㅍ',g:'ㅎ',k:'ㅏ',o:'ㅐ',i:'ㅑ',O:'ㅒ',j:'ㅓ',p:'ㅔ',u:'ㅕ',P:'ㅖ',h:'ㅗ',y:'ㅛ',
    n:'ㅜ',b:'ㅠ',m:'ㅡ',l:'ㅣ'};
  const CHO_J = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  const JUNG_J = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ';
  const JONG_J = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ';
  const VV = {'ㅗㅏ':'ㅘ','ㅗㅐ':'ㅙ','ㅗㅣ':'ㅚ','ㅜㅓ':'ㅝ','ㅜㅔ':'ㅞ','ㅜㅣ':'ㅟ','ㅡㅣ':'ㅢ'};
  const CC = {'ㄱㅅ':'ㄳ','ㄴㅈ':'ㄵ','ㄴㅎ':'ㄶ','ㄹㄱ':'ㄺ','ㄹㅁ':'ㄻ','ㄹㅂ':'ㄼ','ㄹㅅ':'ㄽ','ㄹㅌ':'ㄾ','ㄹㅍ':'ㄿ','ㄹㅎ':'ㅀ','ㅂㅅ':'ㅄ'};
  const SPLIT = Object.fromEntries(Object.entries(CC).map(([k, v]) => [v, k]));
  const isV = j => JUNG_J.includes(j);
  function en2ko(s) {
    let out = '', cho = '', jung = '', jong = '';
    const flush = () => {
      if (cho && jung) out += String.fromCharCode(0xAC00 + (CHO_J.indexOf(cho) * 21 + JUNG_J.indexOf(jung)) * 28 + Math.max(0, JONG_J.indexOf(jong)));
      else out += cho + jung + jong;
      cho = jung = jong = '';
    };
    for (const ch of s) {
      const j = KEY2JAMO[ch] || KEY2JAMO[ch.toLowerCase()];
      if (!j) { flush(); out += ch; continue; }
      if (isV(j)) {
        if (jong) {  // 받침이 다음 글자의 초성으로 이동
          const parts = SPLIT[jong];
          const move = parts ? parts[1] : jong;
          jong = parts ? parts[0] : '';
          flush(); cho = move; jung = j;
        } else if (jung && VV[jung + j]) jung = VV[jung + j];
        else if (cho && !jung) jung = j;
        else { flush(); jung = j; }
      } else {
        if (cho && jung && !jong && JONG_J.includes(j)) jong = j;
        else if (jong && CC[jong + j]) jong = CC[jong + j];
        else { flush(); cho = j; }
      }
    }
    flush();
    return out;
  }

  const norm = s => String(s || '').toLowerCase().replace(/\s+/g, ' ');
  function search(v) {
    const words = norm(v).split(' ').filter(Boolean);
    if (!words.length) return [];
    const scored = [];
    for (const p of idx) {
      const t = norm(p.t), o = norm(p.o), rest = norm(p.c + ' ' + p.g);
      let score = 0, ok = true;
      for (const w of words) {
        const forms = ALIAS[w] ? [w, ALIAS[w]] : [w];  // 블렌더 ↔ blender
        const has = s => forms.some(f => s.includes(f));
        if (has(t)) score += 3;
        else if (has(o)) score += 2;
        else if (has(rest)) score += 1;
        else { ok = false; break; }
      }
      if (ok) scored.push([score + (p.k === 'g' ? 0.5 : 0), p]);
    }
    return scored.sort((a, b) => b[0] - a[0]).map(x => x[1]);
  }

  async function load() {
    if (!idx) { const d = await (await fetch(ROOT + 'search.json')).json(); idx = d.i || d; ALIAS = d.a || {}; }
  }
  // 오타 보정까지 한 검색: [결과, 실제로 쓴 검색어]
  function find(v) {
    let h = search(v), used = '';
    if (!h.length) {
      const alt = /[ㄱ-ㅣ가-힣]/.test(v) ? ko2en(v) : (/^[a-zA-Z\s]+$/.test(v) ? en2ko(v) : '');
      if (alt && alt !== v) { const h2 = search(alt); if (h2.length) { h = h2; used = alt; } }
    }
    return [h, used];
  }
  function mark(text, v) {  // 검색어 강조
    let out = esc(text);
    norm(v).split(' ').filter(w => w.length > 0).forEach(w => {
      const forms = ALIAS[w] ? [w, ALIAS[w]] : [w];
      forms.forEach(f => { out = out.replace(new RegExp('(' + f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>'); });
    });
    return out;
  }
  const srpUrl = v => ROOT + 'search/?q=' + encodeURIComponent(v);
  const KIND = {p: '', g: '📚 기초 가이드', r: '🧭 도구별 정리'};
  let hits = [], sel = -1;
  function render(v, used) {
    box.hidden = false;
    const note = used ? `<div class="row s">‘${esc(v)}’ 결과가 없어 <b>‘${esc(used)}’</b>(으)로 검색했어요 (한/영 자판 전환)</div>` : '';
    box.innerHTML = `<a class="row all" href="${srpUrl(v)}">‘${esc(v)}’ 검색 결과 전체 보기 (${hits.length}건) →</a>` + note + (hits.length
      ? `<div class="row s">${hits.length}건${hits.length > 30 ? ' · 상위 30건' : ''}${HOVER ? ' · Enter 전체 결과 · ↑↓ 고르기 · Esc 닫기' : ''}</div>` +
        hits.slice(0, 30).map((p, i) => `<a class="row${i === sel ? ' on' : ''}" href="${ROOT}${p.u}"><span>` +
          `<span class="t">${mark(p.t, v)}</span><br><span class="s">${KIND[p.k] ? KIND[p.k] + ' · ' : ''}${esc(p.c)}</span></span></a>`).join('')
      : '<div class="row">검색 결과 없음 — 도구 이름(예: Blender, 3ds Max)이나 기능 이름(예: Bend, Geometry Nodes)으로 찾아보세요</div>');
  }

  let timer = null;
  if (box) q.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const v = q.value.trim();
      if (!v) { box.innerHTML = ''; box.hidden = true; return; }
      await load();
      let used; [hits, used] = find(v); sel = -1;
      render(v, used);
    }, 120);
  });
  q.addEventListener('keydown', e => {
    const links = box ? box.querySelectorAll('a.row:not(.all)') : [];
    if (e.key === 'Escape') { q.value = ''; if (box) { box.innerHTML = ''; box.hidden = true; } return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!links.length) return;
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length;
      links.forEach((a, i) => a.classList.toggle('on', i === sel));
      links[sel].scrollIntoView({block: 'nearest'});
    }
    if (e.key === 'Enter' && !e.isComposing && q.value.trim()) {
      e.preventDefault();
      const items = box ? box.querySelectorAll('a.row:not(.all)') : [];
      location.href = sel >= 0 && items[sel] ? items[sel].href : srpUrl(q.value.trim());
    }
  });
  // 결과 창 바깥을 누르면 닫기 (모바일에서 결과 창이 화면을 덮으므로)
  if (box) document.addEventListener('click', e => {
    if (!box.hidden && !box.contains(e.target) && e.target !== q) box.hidden = true;
  });
  if (box) q.addEventListener('focus', () => { if (q.value.trim() && box.innerHTML) box.hidden = false; });
  // ── 검색 결과 페이지 (/search/?q=) ─────────────────────────────────────
  (async function () {
    const list = document.getElementById('srp-list');
    if (!list) return;
    const v = (new URLSearchParams(location.search).get('q') || '').trim();
    const sq = document.getElementById('srp-q'), meta = document.getElementById('srp-meta');
    const tabs = document.getElementById('srp-tabs'), more = document.getElementById('srp-more');
    sq.value = v; q.value = v;
    if (!v) { sq.focus(); meta.textContent = '찾고 싶은 도구·기능·오류 메시지를 입력하세요.'; return; }
    document.title = `‘${v}’ 검색 결과 - 3dflowhub`;
    document.getElementById('srp-title').textContent = `‘${v}’ 검색 결과`;
    meta.textContent = '찾는 중…';
    await load();
    const [all, used] = find(v);
    const term = used || v;
    const GROUPS = [['all', '전체', () => true], ['g', '기초 가이드', p => p.k === 'g'], ['p', '소식·글', p => p.k === 'p'], ['r', '정리·레시피', p => p.k === 'r']];
    let cur = 'all', shown = 20;
    function draw() {
      const f = GROUPS.find(g => g[0] === cur)[2], hits = all.filter(f);
      tabs.innerHTML = GROUPS.map(([k, name, fn]) => { const n = all.filter(fn).length;
        return n || k === 'all' ? `<button type="button" role="tab" data-k="${k}" aria-selected="${k === cur}">${name}<span>${n}</span></button>` : ''; }).join('');
      meta.innerHTML = (used ? `‘${esc(v)}’ 결과가 없어 <b>‘${esc(used)}’</b>(으)로 찾았어요 (한/영 자판 전환) · ` : '')
        + `${hits.length.toLocaleString('ko-KR')}건` + (hits.length > 1 ? ' · 제목에 검색어가 들어간 것부터' : '');
      list.innerHTML = hits.length ? hits.slice(0, shown).map(p => `<li><div class="p"><b>${p.k === 'g' ? '기초 가이드' : p.k === 'r' ? '정리' : '소식'}</b>${esc(p.c)}</div>`
        + `<a class="t" href="${ROOT}${p.u}">${mark(p.t, term)}</a>`
        + `<p class="s">${p.d ? `<span class="d">${esc(p.d)}</span>` : ''}${p.s ? mark(p.s, term) : (p.o ? mark(p.o, term) : '')}</p></li>`).join('')
        : `<li class="srp-empty"><b>‘${esc(v)}’에 맞는 결과가 없어요.</b><ul><li>단어 수를 줄여 보세요 (예: “Blender 모디파이어 미러” → “미러”)</li>`
          + `<li>도구 이름을 영어·한글로 바꿔 보세요 (Blender ↔ 블렌더)</li><li>오류는 메시지의 핵심 단어로 찾아보세요</li></ul></li>`;
      more.innerHTML = hits.length > shown ? `<a href="#" class="pg-nav" id="srp-next">결과 더 보기 (${hits.length - shown}건 남음)</a>` : '';
      const nx = document.getElementById('srp-next');
      if (nx) nx.onclick = e => { e.preventDefault(); shown += 20; draw(); };
    }
    tabs.addEventListener('click', e => { const b = e.target.closest('button[data-k]'); if (b) { cur = b.dataset.k; shown = 20; draw(); } });
    draw();
  })();

  window.__3dflowhub_search = {ko2en, en2ko, search: v => { return idx ? search(v) : []; }};  // 테스트용
})();

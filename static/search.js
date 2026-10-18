/* 3dflowhub 사이트 검색 — search.json(글·기초 가이드·도구별 정리)을 브라우저에서 검색.
   - 여러 단어: 모든 단어가 들어간 항목만, 제목 일치가 먼저
   - 한/영 자판 오타 자동 변환: 'ㅠㅣ둗ㅇㄷㄱ' → blender, 'qmffpsej' → 블렌더 (결과가 없을 때)
   - 키보드: Enter = 첫 결과 열기, Esc = 닫기, ↑↓ = 결과 이동 */
(function () {
  const q = document.getElementById('q');
  const box = document.getElementById('results');
  if (!q || !box) return;
  let idx = null, ALIAS = {};
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

  const KIND = {p: '', g: '📚 기초 가이드', r: '🧭 도구별 정리'};
  let hits = [], sel = -1;
  function render(v, used) {
    box.hidden = false;
    const note = used ? `<div class="row s">‘${esc(v)}’ 결과가 없어 <b>‘${esc(used)}’</b>(으)로 검색했어요 (한/영 자판 전환)</div>` : '';
    box.innerHTML = note + (hits.length
      ? `<div class="row s">${hits.length}건${hits.length > 30 ? ' · 상위 30건' : ''} · Enter 첫 결과 열기 · Esc 닫기</div>` +
        hits.slice(0, 30).map((p, i) => `<a class="row${i === sel ? ' on' : ''}" href="${ROOT}${p.u}"><span class="ph"></span><span>` +
          `<span class="t">${esc(p.t)}</span><br><span class="s">${KIND[p.k] ? KIND[p.k] + ' · ' : ''}${esc(p.c)}</span></span><span></span></a>`).join('')
      : '<div class="row">검색 결과 없음 — 도구 이름(예: Blender, 3ds Max)이나 기능 이름(예: Bend, Geometry Nodes)으로 찾아보세요</div>');
  }

  let timer = null;
  q.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const v = q.value.trim();
      if (!v) { box.innerHTML = ''; box.hidden = true; return; }
      if (!idx) { const d = await (await fetch(ROOT + 'search.json')).json(); idx = d.i || d; ALIAS = d.a || {}; }
      hits = search(v); sel = -1;
      let used = '';
      if (!hits.length) {  // 한/영 자판 오타 보정
        const alt = /[ㄱ-ㅣ가-힣]/.test(v) ? ko2en(v) : (/^[a-zA-Z\s]+$/.test(v) ? en2ko(v) : '');
        if (alt && alt !== v) { const h2 = search(alt); if (h2.length) { hits = h2; used = alt; } }
      }
      render(v, used);
    }, 120);
  });
  q.addEventListener('keydown', e => {
    const links = box.querySelectorAll('a.row');
    if (e.key === 'Escape') { q.value = ''; box.innerHTML = ''; box.hidden = true; return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!links.length) return;
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length;
      links.forEach((a, i) => a.classList.toggle('on', i === sel));
      links[sel].scrollIntoView({block: 'nearest'});
    }
    if (e.key === 'Enter' && links.length && !e.isComposing) { e.preventDefault(); location.href = links[Math.max(sel, 0)].href; }
  });
  window.__3dflowhub_search = {ko2en, en2ko, search: v => { return idx ? search(v) : []; }};  // 테스트용
})();

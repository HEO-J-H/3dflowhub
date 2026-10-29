/* 3dflowhub 개인 기능 — 로그인 없이 이 브라우저에만 저장 (localStorage).
   - ☆ 저장: 글·기초 가이드를 저장해 두고 /saved/ 에서 모아 보기
   - 읽은 글 표시: 한 번 연 글은 목록에서 흐리게 + '읽음' 표시
   저장소를 못 쓰는 환경(사생활 보호 모드 등)에서는 조용히 기능만 꺼짐 */
(function () {
  const KEY_SAVED = '3dfh_saved', KEY_READ = '3dfh_read';
  const load = k => { try { return JSON.parse(localStorage.getItem(k) || '[]'); } catch (e) { return []; } };
  const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장 불가 */ } };
  const path = location.pathname;
  const isItem = /\/p\/[^/]+\.html$/.test(path) || /\/learn\/[^/]+\/$/.test(path);
  const key = p => p.replace(/^.*?(\/(p|learn)\/)/, '$1');  // 사이트 주소가 달라도 같은 키

  // 1) 읽음 기록
  if (isItem) {
    const read = load(KEY_READ).filter(x => x !== key(path));
    read.unshift(key(path));
    store(KEY_READ, read.slice(0, 500));
  }

  // 2) ☆ 저장 버튼 (글·가이드 페이지 제목 옆)
  const h1 = document.querySelector('main h1');
  if (isItem && h1) {
    const btn = document.createElement('button');
    btn.className = 'savebtn';
    btn.type = 'button';
    const isSaved = () => load(KEY_SAVED).some(x => x.k === key(path));
    const paint = () => { const on = isSaved(); btn.textContent = on ? '★ 저장됨' : '☆ 저장'; btn.setAttribute('aria-pressed', on); };
    btn.addEventListener('click', () => {
      let list = load(KEY_SAVED);
      if (isSaved()) list = list.filter(x => x.k !== key(path));
      else list.unshift({k: key(path), t: h1.textContent.trim(), at: new Date().toISOString().slice(0, 10)});
      store(KEY_SAVED, list.slice(0, 300));
      paint();
    });
    paint();
    h1.insertAdjacentElement('afterend', btn);
  }

  // 3) 목록에서 읽은 글 표시
  const readSet = new Set(load(KEY_READ));
  if (readSet.size) {
    document.querySelectorAll('a.row, a.card, a.gcard, .rank a').forEach(a => {
      const href = a.getAttribute('href') || '';
      if (readSet.has(key(new URL(href, location.href).pathname))) a.classList.add('read');
    });
  }

  // 4) /saved/ 페이지 그리기
  const box = document.getElementById('saved-list');
  if (box) {
    const root = typeof ROOT === 'string' ? ROOT : '../';
    const list = load(KEY_SAVED);
    const esc = s => String(s).replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
    box.innerHTML = list.length
      ? list.map((x, i) => `<div class="row"><span><a class="t" href="${root}${x.k.replace(/^\//, '')}">${esc(x.t)}</a><br>` +
          `<span class="s">${x.k.startsWith('/learn/') ? '📚 기초 가이드' : '📰 소식'} · ${esc(x.at)} 저장</span></span>` +
          `<button class="savebtn" data-i="${i}" type="button">삭제</button></div>`).join('')
      : '<div class="row">아직 저장한 글이 없어요. 글이나 기초 가이드 제목 아래 <b>☆ 저장</b>을 눌러 보세요.</div>';
    box.addEventListener('click', e => {
      const i = e.target.dataset && e.target.dataset.i;
      if (i === undefined) return;
      const l = load(KEY_SAVED); l.splice(+i, 1); store(KEY_SAVED, l); location.reload();
    });
  }
})();


// 3) 오류 제보 — 종류 선택 + 메모 → 방문 통계(GoatCounter) 이벤트로 접수 (개인정보 없음) → '접수됨' 안내
//    AI 관리자가 매일 제보를 모아 현황판 '할 일'로 올린다. 자세한 설명은 창 안의 '메일로 자세히' 로.
(function () {
  const TYPES = ['내용이 틀려요', '오래된 정보예요', '링크·영상이 안 열려요', '문장·번역이 어색해요', '기타'];
  let dlg;
  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'repdlg';
    dlg.setAttribute('aria-labelledby', 'rep-h');
    dlg.innerHTML = '<form method="dialog"><h2 id="rep-h">이 페이지 오류 제보</h2>' +
      '<p>무엇이 문제인지 알려 주세요. 확인 후 고치거나 내립니다.</p>' +
      '<label for="rep-type">종류</label><select id="rep-type">' + TYPES.map(t => '<option>' + t + '</option>').join('') + '</select>' +
      '<label for="rep-note">어디가 어떻게 틀렸나요? (선택, 120자)</label>' +
      '<textarea id="rep-note" maxlength="120" placeholder="예: 3번 단계의 메뉴 이름이 실제와 달라요"></textarea>' +
      '<div class="row"><a class="mail" href="#">메일로 자세히</a><button value="cancel">취소</button>' +
      '<button class="go" value="send">보내기</button></div></form>';
    document.body.appendChild(dlg);
  }
  function toast(msg) {
    const t = document.createElement('div');
    t.className = 'reptoast'; t.setAttribute('role', 'status'); t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button.rep');
    if (!btn) return;
    if (!dlg) build();
    const mail = dlg.querySelector('a.mail');
    const subject = btn.dataset.subject || '[3dflowhub] 오류 제보';
    const holder = document.createElement('textarea'); holder.innerHTML = btn.dataset.mail || '';
    const addr = holder.value;
    mail.href = 'mailto:' + addr + '?subject=' + encodeURIComponent(subject) +
      '&body=' + encodeURIComponent('페이지: ' + location.href + '\n\n');
    dlg.querySelector('#rep-note').value = '';
    dlg.onclose = () => {
      if (dlg.returnValue !== 'send') return;
      const type = dlg.querySelector('#rep-type').value;
      const note = dlg.querySelector('#rep-note').value.trim().slice(0, 120);
      const sent = !!(window.goatcounter && window.goatcounter.count);
      if (sent) {
        window.goatcounter.count({ path: 'report/' + TYPES.indexOf(type) + location.pathname,
                                   title: (type + (note ? ' — ' + note : '')).slice(0, 200), event: true });
        toast('✅ 제보가 접수됐어요. 확인 후 고치겠습니다. 고맙습니다!');
      } else {
        toast('⚠️ 광고·추적 차단기 때문에 바로 접수되지 않아 메일 쓰기 창을 엽니다.');
        location.href = mail.href + encodeURIComponent('종류: ' + type + '\n내용: ' + note);
      }
    };
    dlg.showModal();
  });
})();

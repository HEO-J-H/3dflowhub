"""현황판 HQ 화면 — 🏢 전체 요약, 그리고 3dflowhub 외 사이트(life-after-60)의 전용 화면.
app.py 가 사이드바의 '사이트' 선택에 따라 호출한다. (3dflowhub 는 기존 탭 화면을 그대로 사용)"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

import core
import manager
import sites
import staff


def _site_of(x: dict) -> str:
    return x.get("site") or sites.DEFAULT_SITE


def _sync(paths: list[str], msg: str) -> None:
    err = core.git_sync(paths, f"chore(hq): {msg} [skip ci]")
    if err:
        st.error(f"이 PC에는 저장됐지만 GitHub 반영 실패: {err}")


def _kst(ts: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(ts).astimezone(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def proposals_block(site: str, key: str) -> None:
    pend = [x for x in manager.board()["proposals"] if x["status"] == "new" and _site_of(x) == site]
    if not pend:
        st.success("결정할 제안이 없습니다")
    for x in pend[:8]:
        with st.container(border=True):
            st.caption(f"{x.get('category')} · 제안: {x.get('by') or '🧭 AI 관리자'} · {_kst(x['at'])}")
            st.markdown(f"**{x['title']}**")
            st.markdown(f"**근거** — {x.get('evidence', '')}")
            st.markdown(f"**제안** — {x.get('proposal', '')}")
            if x.get("source"):
                st.markdown(f"[🔗 근거 자료 열기]({x['source']})")
            st.caption("수락하면: " + manager.describe(x.get("action")))
            note = st.text_input("사유·메모 (선택)", key=f"{key}_n_{x['id']}", label_visibility="collapsed",
                                 placeholder="예: 공식 고시 확인함 / 아직 확정 아님")
            c1, c2, c3, _ = st.columns([1, 1, 1, 3])
            for col, v, label in ((c1, "accepted", "✅ 수락"), (c2, "held", "⏸ 보류"), (c3, "rejected", "✕ 거절")):
                if col.button(label, key=f"{key}_{v}_{x['id']}", type="primary" if v == "accepted" else "secondary",
                              width="stretch"):
                    manager.decide(x["id"], v, note)
                    _sync(["memory/proposals.json"], f"제안 {label}")
                    st.rerun()


def outbox_block(site: str, key: str) -> None:
    waiting = [x for x in staff.outbox() if x["status"] == "new" and _site_of(x) == site]
    st.caption("복사해서 채널에 올린 뒤 '게시함'을 눌러 주세요. 자동 게시는 하지 않습니다.")
    if not waiting:
        st.info("대기 중인 홍보 글이 없습니다")
    for x in waiting[:6]:
        with st.container(border=True):
            st.caption(f"{x.get('channel')} · {_kst(x['at'])}")
            if x.get("title"):
                st.markdown(f"**{x['title']}**")
            img = core.ROOT / x["image"] if x.get("image") else None
            if img and img.exists():
                a, b = st.columns([1, 2])
                a.image(str(img), width="stretch")
                a.download_button("⬇ 이미지 받기", img.read_bytes(), file_name=img.name, mime="image/png", key=f"{key}_dl_{x['id']}")
                b.code(f"{x['body']}\n\n{x['url']}", language=None, wrap_lines=True)
            else:
                st.code(f"{x['body']}\n\n{x['url']}", language=None, wrap_lines=True)
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("✅ 게시함", key=f"{key}_p_{x['id']}", type="primary", width="stretch"):
                staff.set_outbox(x["id"], "posted")
                _sync(["memory/outbox.json"], "홍보 게시")
                st.rerun()
            if c2.button("건너뛰기", key=f"{key}_s_{x['id']}", width="stretch"):
                staff.set_outbox(x["id"], "skipped")
                _sync(["memory/outbox.json"], "홍보 건너뜀")
                st.rerun()


def team_block(site: str, key: str) -> None:
    for r in [r for r in staff.roles().values() if r.get("site", sites.DEFAULT_SITE) == site]:
        with st.container(border=True):
            a, b = st.columns([4, 1.4])
            a.markdown(f"**{r['name']}** · {'🟢 근무 중' if r['status'] == 'active' else '⏸ 휴식'} · {r.get('every_hours')}시간마다")
            a.caption(r.get("mission", "")[:240])
            a.caption(f"마지막 업무: {_kst(r['last_run']) if r.get('last_run') else '아직 없음'}"
                      + (f" — {r['last_summary']}" if r.get("last_summary") else ""))
            if b.button("▶ 지금 일 시키기", key=f"{key}_run_{r['id']}", width="stretch", disabled=r["status"] != "active"):
                with st.spinner(f"{r['name']} 업무 중…"):
                    try:
                        res = staff.run_role(r)
                        _sync(["memory/outbox.json", "memory/roles.json", "memory/proposals.json",
                               f"memory/sites/{site}/health.json"], f"{r['name']} 업무")
                        st.toast(f"완료 — {res.get('note', '')[:60]}")
                    except Exception as e:
                        st.error(f"업무 실패: {e}")
                st.rerun()
            if b.button("⏸ 쉬게 하기" if r["status"] == "active" else "▶ 다시 일하게", key=f"{key}_ps_{r['id']}", width="stretch"):
                staff.set_status(r["id"], r["status"] != "active")
                _sync(["memory/roles.json"], "직원 상태 변경")
                st.rerun()


def render_site(site_id: str) -> None:
    """3dflowhub 외 사이트 전용 화면 (예: 💰 life-after-60)."""
    s = sites.SITES[site_id]
    st.title(s["name"])
    st.caption(f"{s['about']} · [사이트 열기]({s['url']}) · [저장소](https://github.com/{s['repo']})")
    if s.get("rules"):
        st.info("🛡 운영 원칙: " + s["rules"])
    h = sites.last_health(site_id)
    t_today, t_reg, t_promo, t_team = st.tabs(["🏠 오늘", "⚖️ 규정 점검", "📣 홍보", "👥 팀"])
    with t_today:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("사이트 상태", "정상" if h.get("status") == 200 else ("확인 필요" if h else "점검 전"))
        m2.metric("규정 검토일", h.get("review_stamp") or "-",
                  f"{h['review_age_days']}일 경과" if h.get("review_age_days") is not None else None, delta_color="off")
        m3.metric("깨진 참고 링크", sum(1 for b in h.get("broken_links", []) if b.get("sure")))
        m4.metric("결정 대기", sum(1 for x in manager.board()["proposals"] if x["status"] == "new" and _site_of(x) == site_id))
        for p in h.get("problems") or []:
            st.warning(p)
        if h:
            st.caption(f"마지막 점검 {_kst(h['at'])} · 🔗 상태 점검 직원이 매일 확인")
        st.subheader("✅ 결정할 일")
        proposals_block(site_id, "today")
    with t_reg:
        st.caption("⚖️ 규정 감시 직원이 공식 발표·보도를 사이트의 현재 기준과 비교해 [확정]/[논의] 로 올립니다. "
                   "확정 항목은 law.go.kr·국세청·국민연금공단 등 공식 출처 대조 후 regulatory-reference.js 를 직접 수정하고 "
                   "REVIEW_STAMP 를 갱신해 주세요 (자동 수정 없음).")
        regs = [x for x in manager.board()["proposals"] if _site_of(x) == site_id and "규정" in (x.get("by") or "")]
        for x in regs[:15]:
            st.markdown(f"- **{x['title']}** · {manager.STATUS_KO[x['status']]} · {_kst(x['at'])}"
                        + (f" · [근거]({x['source']})" if x.get("source") else ""))
        if not regs:
            st.caption("아직 규정 감시 기록이 없습니다")
        bl = h.get("broken_links") or []
        if bl:
            st.markdown("**참고 링크 점검 결과**")
            st.dataframe([{"상태": "❌ 깨짐" if b.get("sure") else "❔ 확인 필요(해외 접속 차단 가능)", "주소": b["url"],
                           "응답": str(b["status"])} for b in bl], hide_index=True, width="stretch")
    with t_promo:
        outbox_block(site_id, "promo")
        chans = core.load_config().get(f"promo_channels_{site_id}") or []
        with st.expander("📣 홍보 채널 설정"):
            txt = st.text_area("채널 (한 줄에 하나)", "\n".join(chans) or "네이버 블로그\n네이버 카페 (재테크·은퇴 준비)\n카카오톡 오픈채팅\n페이스북",
                               key=f"ch_{site_id}")
            if st.button("채널 저장", key=f"chs_{site_id}"):
                core.save_config({f"promo_channels_{site_id}": [c.strip() for c in txt.splitlines() if c.strip()][:10]})
                _sync(["config.json"], "홍보 채널")
                st.toast("저장했습니다")
    with t_team:
        team_block(site_id, "team")


def render_hq() -> None:
    """🏢 전체 요약: 모든 사이트의 상태·결정 대기·홍보 대기·팀을 한 화면에."""
    st.title("🏢 본사 — 전체 요약")
    board = manager.board()["proposals"]
    box = staff.outbox()
    team = staff.roles().values()
    cols = st.columns(len(sites.SITES))
    for col, (sid, s) in zip(cols, sites.SITES.items()):
        with col, st.container(border=True):
            st.markdown(f"### {s['name']}")
            st.caption(s["about"])
            if sid == "3dflowhub":
                import manager as _m
                dn = _m.done_today()
                st.markdown(f"오늘 소식 **{dn['news']}** · 가이드 **{dn['guides']}** · 정리 **{dn['roundups']}**")
            else:
                h = sites.last_health(sid)
                st.markdown(f"상태 **{'정상' if h.get('status') == 200 else '확인 필요' if h else '점검 전'}** · "
                            f"규정 검토 {h.get('review_age_days', '-')}일 전 · 문제 {len(h.get('problems') or [])}건")
            st.metric("결정 대기", sum(1 for x in board if x["status"] == "new" and _site_of(x) == sid))
            st.metric("홍보 대기", sum(1 for x in box if x["status"] == "new" and _site_of(x) == sid))
            members = [r["name"] for r in team if r.get("site", sites.DEFAULT_SITE) == sid and r["status"] == "active"]
            st.caption("근무 중: " + (", ".join(members) or "없음"))
            st.link_button("사이트 열기", s["url"], width="stretch")
    st.caption(f"AI 여력 {core.llm_capacity_left()}회 남음 (모든 사이트 공유) · 리셋 {core.llm_reset_kst()} (한국 시간)")

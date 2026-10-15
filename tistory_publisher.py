"""
티스토리 브라우저 자동 발행 (Open API 종료 대안)
================================================
이 PC 전용입니다. 로그인 정보는 저장하지 않고, 직접 로그인한 브라우저 프로필(.tistory_profile/)을 재사용합니다.

  1) 최초 1회 로그인:      python tistory_publisher.py --login
     → 크롬 창에서 카카오 계정으로 직접 로그인 후 창을 닫으세요.
  2) 테스트(발행 안 함):   python tistory_publisher.py --dry-run
     → 가장 최근 초안을 에디터에 채우고 스크린샷만 저장 (output/tistory_shots/)
  3) 초안 일괄 발행:       python tistory_publisher.py --publish [--public]
     → output/tistory_drafts/*.html 을 발행. 기본은 비공개, --public 시 공개 발행.

주의: 티스토리 에디터 화면이 바뀌면 선택자(SELECTORS) 수정이 필요할 수 있습니다.
     자동화 발행은 티스토리 운영정책(과도한 자동 게시 제한)을 지키도록 글 사이에 간격을 둡니다.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

import core

ROOT = Path(__file__).parent
PROFILE = ROOT / ".tistory_profile"
COOKIES = PROFILE / "session_cookies.json"  # 세션 쿠키는 브라우저 재시작 시 사라지므로 별도 저장
SHOTS = ROOT / "output" / "tistory_shots"
DONE_DIR = core.DRAFT_DIR / "published"
BLOG = core.TISTORY_BLOG_NAME
NEWPOST = f"https://{BLOG}.tistory.com/manage/newpost/?type=post"
GAP_SECONDS = 60  # 연속 발행 간격 (스팸 판정 방지)

SELECTORS = {
    "title": "#post-title-inp",
    "mode_btn": "#editor-mode-layer-btn-open",
    "mode_html": "#editor-mode-html",
    "tag": "#tagText",
    "category_btn": "#category-btn",
    "complete": "#publish-layer-btn",
    "private": "#open0",
    "public": "#open20",
    "publish": "#publish-btn",
}


def _launch(p, headless: bool):
    """설치된 크롬 → 엣지 → Playwright 내장 크로미움 순으로 시도."""
    last = None
    for channel in ("chrome", "msedge", None):
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), channel=channel, headless=headless,
                viewport={"width": 1400, "height": 1000}, locale="ko-KR")
            break
        except Exception as e:
            last = e
    else:
        raise last
    if COOKIES.exists():
        ctx.add_cookies(json.loads(COOKIES.read_text(encoding="utf-8")))
    return ctx


def login() -> None:
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tistory.com/auth/login?redirectUrl=" + NEWPOST, wait_until="domcontentloaded")
        print("브라우저에서 직접 로그인하세요. 로그인이 확인되면 창이 자동으로 닫힙니다(최대 10분).", flush=True)
        # 창을 직접 닫으면 쿠키가 디스크에 기록되기 전에 종료될 수 있어, 로그인 감지 후 정상 종료
        deadline = time.time() + 600
        ok = False
        while time.time() < deadline and ctx.pages:  # 창을 모두 닫으면 종료
            urls = [pg.url for pg in ctx.pages]
            # 로그인 후 블로그/관리 화면 등 tistory 페이지로 돌아오면 성공 (카카오 화면·로그인 화면 제외)
            if any("tistory.com" in u and "auth/login" not in u and "kakao" not in u for u in urls):
                ok = True
                break
            ctx.pages[0].wait_for_timeout(2000)  # time.sleep 은 Playwright 이벤트 처리를 막아 URL 이 갱신되지 않음
        if ok:
            page = ctx.pages[-1]
            page.goto(NEWPOST, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            ok = "/manage/" in page.url and "login" not in page.url
            print("현재 화면:", page.url, flush=True)
            if ok:
                COOKIES.write_text(json.dumps(ctx.cookies(), ensure_ascii=False), encoding="utf-8")
        ctx.close()
    print("로그인 세션 저장 완료" if ok else "로그인이 확인되지 않았습니다", flush=True)


def is_logged_in(page: Page) -> bool:
    page.goto(NEWPOST, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    return "/manage/" in page.url and "login" not in page.url


def parse_draft(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"<!-- TITLE: (.*?) \| TAGS: (.*?) -->\n", raw)
    title, tags = (m.group(1), [t for t in m.group(2).split(",") if t]) if m else (path.stem, [])
    return {"title": title, "tags": tags, "html": raw[m.end():] if m else raw, "path": path}


def fill_post(page: Page, post: dict) -> None:
    page.on("dialog", lambda d: d.accept())  # 'HTML 모드로 전환' 확인창 등 자동 수락
    page.goto(NEWPOST, wait_until="domcontentloaded")
    page.wait_for_selector(SELECTORS["title"], timeout=20000)
    # 이전 임시저장 글 이어쓰기 팝업이 뜨면 '취소'
    try:
        page.get_by_role("button", name="취소").click(timeout=2000)
    except PWTimeout:
        pass

    # HTML 모드로 전환 후 CodeMirror 에 본문 주입
    page.click(SELECTORS["mode_btn"])
    page.click(SELECTORS["mode_html"])
    page.wait_for_selector(".CodeMirror", timeout=10000)
    page.evaluate("html => document.querySelector('.CodeMirror').CodeMirror.setValue(html)", post["html"])

    page.fill(SELECTORS["title"], post["title"])
    for t in post["tags"][:10]:
        page.fill(SELECTORS["tag"], t)
        page.keyboard.press("Enter")


def publish(page: Page, public: bool) -> str:
    page.click(SELECTORS["complete"])
    page.wait_for_selector(SELECTORS["publish"], timeout=10000)
    page.click(SELECTORS["public"] if public else SELECTORS["private"])
    page.click(SELECTORS["publish"])
    page.wait_for_url(re.compile(r"/manage/posts"), timeout=30000)
    return page.url


def shot(page: Page, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def run(dry_run: bool, public: bool, limit: int, headless: bool) -> list[dict]:
    drafts = sorted(core.DRAFT_DIR.glob("*.html"))[:limit] if core.DRAFT_DIR.exists() else []
    if not drafts:
        print("발행할 초안이 없습니다:", core.DRAFT_DIR)
        return []
    results = []
    with sync_playwright() as p:
        ctx = _launch(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not is_logged_in(page):
            ctx.close()
            raise SystemExit("로그인이 필요합니다: python tistory_publisher.py --login")
        for i, path in enumerate(drafts[:1] if dry_run else drafts):
            post = parse_draft(path)
            try:
                fill_post(page, post)
                if dry_run:
                    results.append({"title": post["title"], "status": "dry_run", "shot": shot(page, "dry_run")})
                    continue
                url = publish(page, public)
                DONE_DIR.mkdir(parents=True, exist_ok=True)
                path.rename(DONE_DIR / path.name)
                results.append({"title": post["title"], "status": "published", "url": url})
            except Exception as e:  # 한 글 실패가 전체를 멈추지 않도록
                results.append({"title": post["title"], "status": "error", "error": str(e)[:300],
                                "shot": shot(page, "error")})
            print(json.dumps(results[-1], ensure_ascii=False))
            if not dry_run and i < len(drafts) - 1:
                time.sleep(GAP_SECONDS)
        ctx.close()
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="에디터에 채우고 스크린샷만 (발행 안 함)")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--public", action="store_true", help="공개 발행 (기본 비공개)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--show", action="store_true", help="브라우저 창 보이기")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.dry_run or a.publish:
        run(a.dry_run, a.public, a.limit, headless=not a.show)
    else:
        ap.print_help()

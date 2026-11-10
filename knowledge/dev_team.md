# 🛠 개발팀 교본 (Planner · Coder · Reviewer · Judge)

## 프로젝트 구조
- core.py 수집·요약·저장·LLM·동기화 / evolve.py 자기 개선·배분 / manager.py AI 관리자 / staff.py AI 직원
- guides.py 기초 가이드 / build_site.py 정적 사이트 / app.py Streamlit 현황판 / alerts.py 알림 / terms.py 용어집
- refs.py 오류 해결·바뀐 점 / manual.py 심화 매뉴얼(별도 페이지 없이 기초 가이드 아래 "📘 더 깊이"로 표시, /manual/ 은 이동 주소) / manual_shots.py Blender 값 비교 렌더 / compare.py 툴 비교 / assets.py 무료 에셋
- rag.py 사이트 검색기(관련 글·글쓰기 근거) / visuals.py 그림·영상 보강 / scorecard.py 품질 성적표·속도 자동 조절 / qa.py QA 검수
- seo_audit.py SEO 구조 점검 / sources.py 출처 발굴 / staff.py AI 직원 / knowledge/*.md 교본(모든 AI 가 읽음)
- 데이터: content/*(글·가이드·정리 JSON), memory/*(상태·이벤트 로그 JSON), config.json(설정)
- 실행: GitHub Actions(1시간 수집, pages 배포), 로컬·Streamlit Cloud 현황판

## 코딩 규칙
- 기존 코드처럼: 한국어 주석은 '왜'를 짧게, 함수 docstring 한 줄. 이름은 기존 관례 따름.
- **memory/*.json 은 병합된다**(원격 우선, 숫자 큰 값, 리스트 추가만). 삭제·감소가 필요한 상태는 이벤트 로그
  (추가만 하고 마지막 이벤트로 상태 계산)로 설계. 매번 새로 계산하는 스냅샷은 SNAPSHOT_FILES 에 등록.
- LLM 호출은 core.llm 만 사용(예산·예비 공급자·429 처리 포함). 응답은 core._parse_json 으로(깨진 JSON 복구).
- 실패해도 수집 전체가 멈추지 않게: 개별 작업은 try/except 로 감싸고 log.warning.
- 비밀값·토큰을 코드/로그/커밋 메시지에 넣지 않는다. 외부 요청엔 timeout.

## 테스트
- 동작 변경에는 tests/test_core.py 에 테스트 추가. 외부 호출(requests·LLM)은 monkeypatch 로 가짜 응답.
- conftest 가 경로를 tmp 로 격리 — 새 파일 경로 상수를 만들면 테스트에서 monkeypatch.

## 리뷰 체크리스트
- 버그: None/빈 값, 인코딩(한글), 시간대(UTC 저장·KST 표시·태평양 자정 리셋), 병합 시 되살아나는 상태.
- 보안: 위험 함수(eval/exec/shell=True), 하드코딩 비밀값, 보호 파일 수정.
- 사용자 영향: 현황판·사이트 문구는 한국어, 깨진 링크 없음(check_links.py).
- 작은 변경 하나에 하나의 목적. 관련 없는 리팩터링 금지.

## 새 콘텐츠 종류를 만들 때 (빠뜨리면 '보이지 않는 콘텐츠'가 됨)
1. 데이터: content/<종류>/*.json, 하루 상한은 scorecard.KNOBS 로 (스스로 조절되게).
2. 화면: build_site 에 빌드 함수 + **SITE_MENU 항목·section_count** (메뉴 자동 표시·숨김), 그림·영상 자리부터 설계.
3. 연결: rag.site_docs 에 추가(관련 글·글쓰기 근거), 사이트맵은 자동.
4. 품질: qa.items 에 추가(검수 대상), scorecard TARGETS 에 범위 지표.
5. 실행: evolve 에 _due 주기, 생성 실패해도 전체가 멈추지 않게.
6. 운영자가 요청한 도구·주제는 guide_catalog.FIRST 처럼 우선 대기열로 — 긴 대기열 뒤에 넣으면 몇 주 동안 안 보인다.

## 자주 난 사고
- Windows 에서 subprocess 출력은 encoding="utf-8" 명시 (cp949 로 깨짐).
- 같은 값 반복 렌더·같은 제목은 '다르다'고 착각하기 쉬움 → 눈으로 보이는 차이(화소 비율)·정규화한 제목으로 비교.
- 정규식은 대소문자·단어 경계 주의 (Nanite 의 'NaN', Houdini 'Null' 노드 오탐).
- 실무 파이프라인(recipes)은 생성 중단 (2026-11-03 사장님: 다른 AI 로 쉽게 만들 수 있어 차별성 없음). 기존 페이지는 주소만 유지, 메뉴에서 뺌.
- 공모전·게임 잼(events.py, /events/): 위비티·itch.io·CGTrader, 6시간마다, AI 안 씀. 새 출처는 sources 처럼 관리자가 제안 가능.
- 사람이 찾은 버그는 knowledge/lessons.md 에 원인·규칙·자동 점검 위치를 남기고, inspect_site.py 나 qa.py 에 규칙을 더한다.

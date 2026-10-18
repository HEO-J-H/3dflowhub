# 🛠 개발팀 교본 (Planner · Coder · Reviewer · Judge)

## 프로젝트 구조
- core.py 수집·요약·저장·LLM·동기화 / evolve.py 자기 개선·배분 / manager.py AI 관리자 / staff.py AI 직원
- guides.py 기초 가이드 / build_site.py 정적 사이트 / app.py Streamlit 현황판 / alerts.py 알림 / terms.py 용어집
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

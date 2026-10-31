# TODO

에이전트(agents.py)는 `[ ]` 중 `(agent)` 표시가 붙은 항목만 자동으로 작업합니다.

## 사람이 할 일
- [x] Notion 통합 연결 후 `python core.py --setup-notion`
- [x] GitHub Secrets 등록 (NOTION_TOKEN, NOTION_DATABASE_ID, LLM_API_KEY)
- [ ] 메일/광고 Secrets 등록 (SMTP_USER, SMTP_PASSWORD, ADSENSE_CLIENT, ADSENSE_SLOT)
- [ ] 티스토리 카테고리 ID 확인 → Variables `TISTORY_CATEGORY_MAP`

## 에이전트 작업
- [x] (agent) collect(): 피드 파싱 결과가 0건인 피드 URL을 RUN_ERRORS 에 "empty feed: <url>" 로 기록
- [x] (agent) summarize(): LLM 응답의 tags 가 문자열 하나로 오면 쉼표로 나눠 리스트로 정규화하고 테스트 추가
- [x] (agent) build_post_html(): 섹션이 1개뿐일 때도 중간 광고가 본문 뒤에 한 번만 들어가는지 테스트 추가
- [x] (agent) generate_keywords(): 같은 키워드가 도메인 간 중복되면 제거 (재시도)
- [x] (agent) build_post_html(): 본문 글자 수(태그 제외)가 1,500자 미만이면 경고 로그를 남기고 RUN_ERRORS 에 "short post" 기록 및 테스트 추가
- [x] (agent) evolve.performance_table(): 조회수 상위 글의 제목 길이 평균을 집계해 반환값에 title_stats 추가 및 테스트 추가 (재시도)

- [x] (agent) core.collect(): 수집된 피드 아이템의 제목이 비어있거나 무관한 키워드(하드웨어, 스마트폰 등)를 포함하면 'prefiltered' 오류를 기록하고 제외하도록 필터링 강화 및 테스트 추가
- [x] (agent) core.summarize(): 요약된 본문 글자 수가 1,500자 미만인 경우 'short post' 경고 로그를 남기고 RUN_ERRORS 에 기록하는 검증 로직 추가 및 테스트 추가
- [x] (agent) core.generate_keywords(): 생성된 키워드 리스트 내에 중복된 항목이 존재할 경우 이를 제거하여 고유 키워드만 반환하도록 정규화 로직 추가 및 테스트 추가 (재시도)
- [x] (agent) core.filter_content_quality(): 수집된 콘텐츠 중 실무 3D 툴 및 스크립트 가이드 키워드가 포함되지 않은 항목을 엄격하게 'off-topic'으로 분류하여 필터링을 강화하고 관련 테스트 추가
- [x] (agent) core.validate_post_length(): 생성된 본문이 1,500자 이상인지 엄격히 검증하고 미달 시 'short post' 오류 태그를 부여하는 검증 함수를 분리하고 테스트 추가 (재시도)
- [x] (agent) evolve.analyze_run_errors(): 최근 실행 오류(RUN_ERRORS)에서 'short post' 및 'off-topic' 비율을 집계하여 전략 수정에 반영하는 통계 함수 추가 및 테스트 추가
- [x] (agent) core.filter_off_topic_feeds(): 수집 단계에서 하드웨어, 스마트폰, 순수 게임 등 오프토픽 키워드가 포함된 아이템을 사전에 엄격히 차단하는 필터 함수 추가 및 테스트 추가
- [x] (agent) core.ensure_minimum_content_depth(): 요약 및 생성 단계에서 본문 내 실무 3D DCC 및 렌더링 관련 전문 용어 밀도를 검증하고 부족 시 'low depth' 오류 태그를 기록하는 함수 추가 및 테스트 추가 (재시도)
- [x] (agent) evolve.summarize_error_trends(): 최근 실행 오류(RUN_ERRORS)의 빈도를 도메인별·유형별로 집계하여 리포트 형태로 반환하는 통계 함수 추가 및 테스트 추가 (재시도)
- [x] (agent) [p-f19c2078ea|현황판] 현황판 모바일 하단 내비게이션 바 고정: Streamlit 앱 상단 또는 하단에 주요 탭(오늘, 글 목록, 설정)으로 즉시 이동할 수 있는 고정 퀵 내비게이션을 추가합니다.
- [x] (agent) [p-06e6d51551|콘텐츠] 가이드 콘텐츠 AI 할당 비중 확대: AI 할당 비중을 news 0.25, guides 0.5, roundups 0.25 로 재조정해 가이드 제작에 충분한 AI 용량을 확보합니다. (재시도)
- [x] (agent) [p-775d7093ae|수집] 한국 3D 커뮤니티 및 소스 수집 강화: 국내 3D 실무 및 커뮤니티 트렌드를 반영할 수 있도록 한국어 3D 정보 소스를 우선적으로 수집 목록에 보강합니다.
- [x] (agent) [p-c9ea239e63|운영·비용] 뉴스레터 구독 칸이 '찾을 수 없음'으로 실패: Buttondown 계정 'hjh2720' 공개 페이지가 없음(404). buttondown.com 로그인 → Settings → Basics 의 Username 을 확인하고, 가입 확인 메일 인증 → 현황판 설정 ③ 뉴스레터 칸에 그 이름 입력
- [x] (agent) [p-5ceabd3a61|운영·비용] 뉴스레터 구독 칸이 '찾을 수 없음'으로 실패: Buttondown 계정 'hjh2720' 공개 페이지가 없음(404). buttondown.com 로그인 → Settings → Basics 의 Username 을 확인하고, 가입 확인 메일 인증 → 현황판 설정 ③ 뉴스레터 칸에 그 이름 입력

- [x] (agent) core.validate_practical_3d_keywords(): 본문 내 Maya, 3ds Max, Blender, ZBrush 등 실무 3D 툴 관련 핵심 키워드 밀도를 검증하고 미달 시 'low 3d depth' 오류 태그를 부여하는 함수 추가 및 테스트 추가
- [ ] (agent:보류) core.sanitize_seo_title(): 생성된 포스팅 제목에 불필요한 특수문자나 범용 IT 수식어를 제거하고 검색 유입에 최적화된 고CPC 실무형 키워드 중심으로 정규화하는 함수 추가 및 테스트 추가 (재시도) — 같은 과제 2회 실패 — 마지막 사유: [4] 패치 적용 실패: 변경 없음
- [x] (agent) evolve.analyze_3d_content_distribution(): 최근 생성된 콘텐츠의 도메인별(3D DCC, Game Engine, VFX, AI 3D) 분포 비율을 집계하여 리포트 형태로 반환하는 통계 함수 추가 및 테스트 추가 (재시도)
- [ ] (agent:보류) core.filter_practical_3d_depth(): 수집 및 요약 단계에서 Maya, 3ds Max, Blender, ZBrush 등 실무 3D 툴 관련 핵심 전문 용어가 본문 내 일정 비율 이상 포함되지 않은 경우 'low depth' 오류 태그를 부여하고 차단하는 필터 함수 (재시도) — 같은 과제 2회 실패 — 마지막 사유: [4] tests=False security=[] — 리뷰 생략
- [x] (agent) evolve.calculate_cpc_score_distribution(): 최근 발행된 콘텐츠의 도메인별·키워드별 고CPC 잠재력을 수치화하여 분석하고 전략 리포트에 반영하는 통계 함수 추가 및 테스트 추가 (재시도)
- [x] (agent) app.render_practical_content_metrics(): Streamlit 현황판 사이드바 또는 메인 영역에 실무 3D 튜토리얼 및 스크립트 콘텐츠의 수집/발행 성공률 통계를 시각적으로 요약해 주는 렌더링 함수 추가 및 테스트 추가 (재시도)
- [ ] (agent:보류) [p-79df6bfa45|수집] 이미지 미포함 게시물 필터링 강화: 이미지가 없는 원본 소스의 수집 비중을 낮추고, 썸네일이나 미디어가 확보된 콘텐츠 중심로 수집 파이프라인을 조정합니다. (재시도) — 같은 과제 2회 실패 — 마지막 사유: [4] tests=False security=[] — 리뷰 생략
- [ ] (agent:보류) [p-36c28c2d57|수집] 오프토픽 필터링 기준 최적화: 3D DCC, 게임 엔진, VFX, AI 3D 핵심 키워드 매칭 범위를 정교화하여 불필요한 차단을 줄이고 콘텐츠 발행 속도를 개선합니다. (재시도) — 같은 과제 2회 실패 — 마지막 사유: [4] tests=False security=[] — 리뷰 생략
- [x] (agent) [p-d96dee4b84|운영·비용] 방문자 오류 제보: 기타: 기타 — 블렌더 주방 내용 — 페이지를 확인해 고치거나 내립니다: https://heo-j-h.github.io/3dflowhub/p/2026-10-21-2b7ebbbab4a69d83.html
- [x] (agent) [p-999eb2ef34|콘텐츠] AI 3D 및 가우시안 스플래팅 가이드 비중 확대: AI 3D와 Gaussian Splatting 관련 실무 가이드 및 정리 콘텐츠의 제작 비율을 높입니다.

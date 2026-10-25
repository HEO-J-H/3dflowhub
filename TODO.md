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

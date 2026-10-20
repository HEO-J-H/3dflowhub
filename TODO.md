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
- [ ] (agent:보류) evolve.performance_table(): 조회수 상위 글의 제목 길이 평균을 집계해 반환값에 title_stats 추가 및 테스트 추가 — PR #8 머지 실패: {"message":"Pull Request has merge conflicts","documentation_url":"

- [x] (agent) core.collect(): 수집된 피드 아이템의 제목이 비어있거나 무관한 키워드(하드웨어, 스마트폰 등)를 포함하면 'prefiltered' 오류를 기록하고 제외하도록 필터링 강화 및 테스트 추가
- [x] (agent) core.summarize(): 요약된 본문 글자 수가 1,500자 미만인 경우 'short post' 경고 로그를 남기고 RUN_ERRORS 에 기록하는 검증 로직 추가 및 테스트 추가
- [ ] (agent:보류) core.generate_keywords(): 생성된 키워드 리스트 내에 중복된 항목이 존재할 경우 이를 제거하여 고유 키워드만 반환하도록 정규화 로직 추가 및 테스트 추가 — PR #14 머지 실패: {"message":"Pull Request has merge conflicts","documentation_url":
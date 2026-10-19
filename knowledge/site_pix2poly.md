# 🧱 Pix2Poly 교본 (이 사이트 소속 직원·코딩 에이전트 공통)

## 무엇인가
- 이미지·URL·영상으로 3D 메시(OBJ/GLB/FBX)와 PBR 텍스처(Albedo·Normal·Roughness·Metallic·AO)를 만드는 툴.
  - **웹 버전** `web/` (https://heo-j-h.github.io/Pix2Poly/): 높이맵 메시·PBR 을 브라우저에서 처리, 이미지 서버 전송 없음. `backend/app/services` 알고리즘을 JS 로 옮긴 것 — 한쪽을 고치면 다른 쪽도 맞춘다.
  - **로컬 버전** (FastAPI + `/ui/`): TripoSR(GPU)·COLMAP(영상) 같은 고급 기능.
- 파이프라인: 단일 이미지 → 높이맵 메시(기본, CPU) / TripoSR(선택, GPU) · 영상 → COLMAP 재구성 · PBR 맵 생성 · Blender 로 FBX 내보내기.
- 사용자는 3D 아티스트. 무거운 모델은 GPU(VRAM) 요구가 크므로 **CPU 기본 경로가 항상 동작**해야 한다.

## 바꿔도 되는 것 / 안 되는 것
- 자동 머지 가능(위험 낮음): `backend/tests/` 테스트 추가, `docs/` 문서, `backend/static/` 화면 문구·스타일, 작은 버그 수정(테스트 포함).
- PR 로만(사람 승인): `backend/app/services/*`(파이프라인), `main.py` API 형태, `requirements.txt` 의존성, 외부 모델 도입, `web/`(공개 페이지).
- 금지: 테스트를 지우거나 약하게 바꾸기, 비밀값·개인 경로 하드코딩, 비상업 라이선스 코드 복사, 네트워크 필요한 테스트.

## 외부 기술 도입 체크리스트
1. 라이선스: MIT·Apache-2.0·BSD 우선. CC BY-NC·연구용 전용은 '선택 엔진·개인용'으로만, 기본값 금지.
2. 요구 사양: VRAM·설치 난이도(Windows) — README 에 정직하게 적기.
3. 인터페이스: 기존 `triposr_runner.py` 처럼 '없으면 건너뛰는' 선택 엔진으로 붙이기.
4. 근거 링크(저장소·논문)와 예상 효과를 제안에 반드시 포함.

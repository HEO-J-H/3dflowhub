"""기초 가이드 확장 주제 — 도구마다 100개 이상 (guides.CATALOG 에 더해짐, 이미 있는 영문 이름은 자동 제외).

한 줄 = "분류|영문 이름|한국어 제목". 문서 주소는 넣지 않음(확인 안 된 주소 대신 공식 문서 검색 링크 사용).
"""
from __future__ import annotations

RAW = {
"3ds Max": """
모디파이어|Edit Mesh modifier|Edit Mesh — 삼각면 기반 편집
모디파이어|Mesh Smooth modifier|MeshSmooth — 부드럽게 만들기(구버전 방식)
모디파이어|OpenSubdiv modifier|OpenSubdiv — 크리스 지원 서브디비전
모디파이어|Relax modifier|Relax — 메시 고르게 풀기
모디파이어|Push modifier|Push — 표면을 노멀 방향으로 부풀리기
모디파이어|Displace modifier|Displace — 이미지로 표면 높낮이
모디파이어|Slice modifier|Slice — 평면으로 자르기
모디파이어|Cap Holes modifier|Cap Holes — 구멍 막기
모디파이어|Optimize modifier|Optimize — 평면 부분 폴리곤 줄이기
모디파이어|MultiRes modifier|MultiRes — 단계별 폴리곤 감소
모디파이어|Smooth modifier|Smooth — 스무딩 그룹 자동 지정
모디파이어|Normal modifier|Normal — 면 방향 뒤집기
모디파이어|Edit Normals modifier|Edit Normals — 노멀 직접 다듬기
모디파이어|Weighted Normals modifier|Weighted Normals — 하드서피스 노멀 정리
모디파이어|Path Deform modifier|Path Deform — 경로 따라 휘기
모디파이어|Spline IK Control modifier|Spline IK Control — 스플라인 정점에 헬퍼 달기
모디파이어|Wave modifier|Wave — 물결 변형
모디파이어|Ripple modifier|Ripple — 동심원 물결
모디파이어|Melt modifier|Melt — 녹아내리는 효과
모디파이어|Stretch modifier|Stretch — 늘이며 가운데 오므리기
모디파이어|Squeeze modifier|Squeeze — 눌러 찌그러뜨리기
모디파이어|Spherify modifier|Spherify — 구 모양으로
모디파이어|Skew modifier|Skew — 한쪽으로 기울이기
모디파이어|Mirror modifier|Mirror — 뒤집어 복제
모디파이어|XForm modifier|XForm — 스택 안에서 변형 기록
모디파이어|Material modifier|Material — 재질 ID 지정
모디파이어|MultiMaterial and Material ID|Material ID — 한 오브젝트에 재질 여러 개
모디파이어|Vol. Select modifier|Vol. Select — 영역으로 부분 선택
모디파이어|Poly Select modifier|Poly Select — 선택만 스택에 남기기
모디파이어|Skin Wrap modifier|Skin Wrap — 저폴리로 고폴리 움직이기
모디파이어|Cloth modifier|Cloth — 천 시뮬레이션
모디파이어|Hair and Fur modifier|Hair and Fur — 털·잔디
모디파이어|Retopology modifier|Retopology — 자동 리토폴로지
모디파이어|Quadify Mesh modifier|Quadify Mesh — 사각면으로 정리
모디파이어|Data Channel modifier|Data Channel — 정점 데이터로 절차적 효과
모디파이어|Conform modifier|Conform — 다른 표면에 맞붙이기
모디파이어|Smart Extrude|Smart Extrude — 돌출하며 자동 정리
모델링|Editable Poly sub-object levels|Editable Poly — 점·선·면 편집 단계
모델링|Connect edges|Connect — 엣지 사이 잇기
모델링|Bridge in Editable Poly|Bridge — 두 면·엣지 잇기
모델링|Cut tool|Cut — 원하는 곳 자르기
모델링|QuickSlice|QuickSlice — 한 번에 가로지르기
모델링|Swift Loop|Swift Loop — 엣지 루프 넣기
모델링|Target Weld|Target Weld — 점 끌어 붙이기
모델링|Bevel and Inset in Editable Poly|Bevel·Inset — 면 안쪽 넣고 돌출
모델링|Shift-drag clone edges|Shift 드래그 — 엣지 늘려 면 만들기
모델링|Boolean compound object|Boolean — 합치기·빼기(복합 오브젝트)
모델링|ProBoolean|ProBoolean — 깔끔한 불리언
모델링|Loft compound object|Loft — 경로 따라 단면 잇기
모델링|ShapeMerge|ShapeMerge — 표면에 스플라인 새기기
모델링|Scatter compound object|Scatter — 표면에 오브젝트 뿌리기
모델링|Spline editing (Editable Spline)|Editable Spline — 점·선 편집
모델링|Spline Boolean and Outline|스플라인 Outline·Boolean
모델링|Text spline|Text — 글자 스플라인
모델링|Freeform PolyDraw|PolyDraw — 표면 위에 그리며 모델링
모델링|Paint Deform|Paint Deform — 브러시로 밀고 당기기
모델링|Graphite Swift Loop and Flow|Flow Connect — 곡률 따라 루프
모델링|Polygon count and Statistics|폴리곤 수 보기(Statistics)
UV|UV Editor Peel tools|Peel — UV 펼치기 도구
UV|UV seams and Pelt|Seam — UV 자를 곳 정하기
UV|UV packing|Pack UVs — UV 배치
UV|Checker map for UV|체커 맵으로 UV 늘어짐 확인
재질|Physical Material|Physical Material — 기본 PBR 재질
재질|Bitmap texture map|Bitmap — 이미지 텍스처 넣기
재질|Normal Bump map|Normal Bump — 노멀 맵 연결
재질|OSL maps|OSL 맵 — 절차적 텍스처
재질|Multi/Sub-Object material|Multi/Sub-Object — 재질 ID별 재질
재질|Arnold Standard Surface|Standard Surface — Arnold 재질
렌더링|Arnold lights|Arnold 조명 설정
렌더링|Physical Camera|Physical Camera — 실사 카메라
렌더링|Exposure Control|노출 조절(Exposure Control)
렌더링|Render Elements|Render Elements — 패스 나눠 렌더
렌더링|ActiveShade|ActiveShade — 실시간 렌더 미리보기
렌더링|Batch Render|Batch Render — 여러 카메라 한 번에
렌더링|Environment and HDRI|HDRI 환경 조명
렌더링|Safe Frame and output size|Safe Frame — 출력 화면 비율
애니메이션|Auto Key and Set Key|Auto Key·Set Key — 키 만들기
애니메이션|Dope Sheet|Dope Sheet — 키 시간 조절
애니메이션|Path Constraint|Path Constraint — 경로 따라 이동
애니메이션|Look At Constraint|LookAt — 바라보게 하기
애니메이션|Link and Hierarchy|Link — 부모·자식 연결
애니메이션|Pivot (Affect Pivot Only)|피벗 옮기기(Affect Pivot Only)
애니메이션|Wire Parameters|Wire Parameters — 값 연결
애니메이션|Bones and IK solvers|Bone·IK — 기본 리깅
애니메이션|CAT character rig|CAT — 캐릭터 리그
애니메이션|Biped basics|Biped — 바이페드 기초
애니메이션|Motion paths (Trajectories)|궤적 보기(Trajectories)
메뉴·패널|Viewport layouts and shading|뷰포트 배치·셰이딩
메뉴·패널|Customize User Interface (hotkeys)|단축키 바꾸기
메뉴·패널|Units Setup|Units Setup — 단위 설정
메뉴·패널|Grid and Snaps settings|스냅 설정
메뉴·패널|Align tool|Align — 오브젝트 정렬
메뉴·패널|Selection sets and Isolate|선택 세트·Isolate
메뉴·패널|Asset Tracking and missing maps|Asset Tracking — 깨진 텍스처 경로
메뉴·패널|Merge and XRef|Merge·XRef — 다른 파일 불러오기
메뉴·패널|FBX export settings|FBX 내보내기 설정
메뉴·패널|Archive scene|Archive — 파일 모으기
메뉴·패널|Scene States|Scene States — 장면 상태 저장
메뉴·패널|Containers|Container — 묶어 관리
스크립트|MAXScript selection and loops|MAXScript — 선택·반복
스크립트|MAXScript modifiers via script|MAXScript — 모디파이어 일괄 추가
스크립트|Macroscript toolbar button|Macroscript — 툴바 버튼 만들기
스크립트|Python in 3ds Max (pymxs)|pymxs — 파이썬으로 Max 제어
""",
"Blender": """
모델링|Spin tool|Spin — 회전시켜 면 만들기
모델링|Extrude along normals|Extrude Along Normals — 노멀 방향 돌출
모델링|Poke Faces|Poke — 면 가운데 점 넣기
모델링|Grid Fill|Grid Fill — 구멍 격자로 막기
모델링|Fill (F)|Fill — 면 만들기
모델링|Dissolve edges and vertices|Dissolve — 지우되 면 유지
모델링|Delete vs Dissolve|Delete와 Dissolve 차이
모델링|Rip vertices (V)|Rip — 점 찢기
모델링|Offset Edge Slide|Offset Edge Slide — 양쪽 엣지 추가
모델링|Subdivide|Subdivide — 면 잘게 나누기
모델링|Mesh Symmetry options|Mesh Symmetry — 편집 대칭
모델링|Shear|Shear — 기울이기
모델링|Randomize vertices|Randomize — 점 흐트러뜨리기
모델링|Smooth Vertices|Smooth Vertices — 점 고르게
모델링|Edge Crease|Edge Crease — 서브디비전 모서리 세우기
모델링|Mark Sharp and Auto Smooth|Mark Sharp — 날카로운 모서리 표시
모델링|Convert curve to mesh|커브를 메시로 변환
모델링|Text object|Text — 3D 글자
모델링|Metaball basics|Metaball — 말랑한 덩어리
모디파이어|Wireframe modifier|Wireframe — 엣지를 기둥으로
모디파이어|Skin modifier|Skin — 선으로 몸체 만들기
모디파이어|Remesh modifier|Remesh — 고른 면으로 재구성
모디파이어|Displace modifier|Displace — 텍스처로 높낮이
모디파이어|Curve modifier|Curve — 커브 따라 휘기
모디파이어|Smooth Corrective modifier|Corrective Smooth — 변형 후 매끄럽게
모디파이어|Triangulate modifier|Triangulate — 삼각면으로
모디파이어|Weighted Normal modifier|Weighted Normal — 하드서피스 노멀
모디파이어|Data Transfer modifier|Data Transfer — 노멀·UV 옮기기
모디파이어|Cast modifier|Cast — 구·원통 모양으로
모디파이어|Wave modifier|Wave — 물결
모디파이어|Build modifier|Build — 면이 하나씩 생기는 애니메이션
스컬프트|Sculpt Mode basics|Sculpt Mode — 조각 시작하기
스컬프트|Dyntopo|Dyntopo — 동적 토폴로지
스컬프트|Multiresolution modifier|Multires — 단계별 조각
스컬프트|Sculpt brushes (Draw, Clay Strips, Grab)|주요 스컬프트 브러시
스컬프트|Voxel Remesh|Voxel Remesh — 조각용 재구성
재질|Principled BSDF|Principled BSDF — 기본 PBR 재질
재질|Image Texture node|Image Texture — 이미지 텍스처 연결
재질|Normal Map node|Normal Map — 노멀 맵 연결
재질|Texture Coordinate and Mapping|Mapping — 텍스처 위치·크기
재질|Noise Texture node|Noise Texture — 절차적 노이즈
재질|Color Ramp node|Color Ramp — 값을 색으로
재질|Mix Shader and Mix Color|Mix — 재질·색 섞기
재질|Emission shader|Emission — 빛나는 재질
재질|Glass and Transmission|유리 재질
재질|Node Wrangler add-on|Node Wrangler — 노드 작업 빠르게
렌더링|Cycles vs EEVEE|Cycles와 EEVEE 차이
렌더링|Cycles samples and denoising|Cycles 샘플·디노이즈
렌더링|World HDRI lighting|HDRI 월드 조명
렌더링|Light types|조명 종류(Point·Sun·Spot·Area)
렌더링|Camera and Depth of Field|카메라·피사계 심도
렌더링|Color Management (AgX)|색 관리(View Transform)
렌더링|Render output settings|렌더 출력 설정(해상도·포맷)
렌더링|View Layers and passes|View Layer·렌더 패스
렌더링|Compositor basics|컴포지터 기초
애니메이션|Keyframes basics|키프레임 넣기(I)
애니메이션|Graph Editor|그래프 에디터 — 곡선 다듬기
애니메이션|Dope Sheet and Action Editor|Dope Sheet — 키 시간 조절
애니메이션|NLA Editor|NLA — 동작 이어 붙이기
애니메이션|Follow Path constraint|Follow Path — 경로 따라 이동
애니메이션|Track To constraint|Track To — 바라보게 하기
애니메이션|Shape Keys|Shape Keys — 모양 변형 애니메이션
애니메이션|Drivers|Drivers — 값 연결
리깅|Armature basics|Armature — 뼈대 만들기
리깅|Automatic Weights parenting|자동 웨이트로 본 연결
리깅|Inverse Kinematics constraint|IK — 역운동학
리깅|Rigify|Rigify — 자동 캐릭터 리그
시뮬레이션|Rigid Body|Rigid Body — 물체 충돌
시뮬레이션|Cloth simulation|Cloth — 천 시뮬레이션
시뮬레이션|Particle system hair|파티클 헤어
시뮬레이션|Mantaflow smoke and fire|연기·불 시뮬레이션
지오메트리 노드|Distribute Points on Faces|Distribute Points — 표면에 점 뿌리기
지오메트리 노드|Instance on Points|Instance on Points — 점마다 복제
지오메트리 노드|Realize Instances|Realize Instances — 실제 메시로
지오메트리 노드|Set Position node|Set Position — 점 위치 바꾸기
지오메트리 노드|Curve to Mesh node|Curve to Mesh — 커브에 단면
기본 조작|Collections|Collection — 오브젝트 묶기
기본 조작|Append and Link|Append·Link — 다른 파일에서 가져오기
기본 조작|Asset Browser|Asset Browser — 자산 재사용
기본 조작|FBX and glTF export|FBX·glTF 내보내기
기본 조작|Pack and unpack resources|텍스처 파일 묶기(Pack)
기본 조작|Unit scale and measurement|단위·치수 재기(Measure)
UV|Smart UV Project|Smart UV Project — 자동 UV
UV|Mark Seam and Unwrap|Seam 표시 후 펼치기
UV|UDIM basics|UDIM — 여러 장 텍스처
텍스처|Baking normal maps in Cycles|Cycles 노멀 맵 굽기
스크립트|Python Console basics|파이썬 콘솔 — 첫 스크립트
스크립트|Running scripts in Text Editor|텍스트 에디터에서 스크립트 실행
""",
"Houdini": """
노드|Box SOP|Box — 상자 만들기
노드|Grid SOP|Grid — 평면 격자
노드|Sphere SOP|Sphere — 구 만들기
노드|Tube SOP|Tube — 원통
노드|Line SOP|Line — 직선
노드|Circle SOP|Circle — 원
노드|Curve SOP|Curve — 커브 그리기
노드|Transform SOP|Transform — 이동·회전·크기
노드|Merge SOP|Merge — 여러 입력 합치기
노드|Blast SOP|Blast — 선택 부분 지우기
노드|Delete SOP|Delete — 조건으로 지우기
노드|Group Create SOP|Group Create — 그룹 만들기
노드|Group Expression SOP|Group Expression — 식으로 그룹
노드|Fuse SOP|Fuse — 가까운 점 합치기
노드|Clean SOP|Clean — 메시 정리
노드|Subdivide SOP|Subdivide — 부드럽게 나누기
노드|PolyBevel SOP|PolyBevel — 모서리 깎기
노드|PolyBridge SOP|PolyBridge — 면 잇기
노드|PolyFill SOP|PolyFill — 구멍 막기
노드|PolyReduce SOP|PolyReduce — 폴리곤 줄이기
노드|PolyWire SOP|PolyWire — 선을 튜브로
노드|PolySplit SOP|PolySplit — 면 자르기
노드|Divide SOP|Divide — 면 나누기·보로노이 선
노드|Clip SOP|Clip — 평면으로 자르기
노드|Resample SOP|Resample — 커브 점 고르게
노드|Carve SOP|Carve — 커브 일부만
노드|Revolve SOP|Revolve — 회전체
노드|Skin SOP|Skin — 커브 사이 면
노드|Extrude Volume SOP|Extrude Volume — 두께 주기
노드|Mirror SOP|Mirror — 대칭 복제
노드|Copy and Transform SOP|Copy and Transform — 반복 복제
노드|Normal SOP|Normal — 노멀 계산
노드|Reverse SOP|Reverse — 면 방향 뒤집기
노드|Facet SOP|Facet — 면 정리·분리
노드|UV Unwrap SOP|UV Unwrap — 자동 UV
노드|UV Flatten SOP|UV Flatten — UV 펼치기
노드|UV Layout SOP|UV Layout — UV 배치
노드|UV Project SOP|UV Project — 투영 UV
노드|Attribute Create SOP|Attribute Create — 속성 만들기
노드|Attribute Promote SOP|Attribute Promote — 속성 단계 옮기기
노드|Attribute Transfer SOP|Attribute Transfer — 가까운 곳에서 속성 가져오기
노드|Attribute Randomize SOP|Attribute Randomize — 무작위 값
노드|Attribute Noise SOP|Attribute Noise — 노이즈 값
노드|Attribute Blur SOP|Attribute Blur — 값 부드럽게
노드|Color SOP|Color — 색 지정
노드|Measure SOP|Measure — 면적·곡률 재기
노드|Point Wrangle examples|Wrangle 예제 — 점 다루기
노드|For-Each Loop|For-Each — 조각마다 반복
노드|Switch SOP|Switch — 입력 고르기
노드|Null SOP and OUT nodes|Null — 출력 표시 노드
노드|Object Merge SOP|Object Merge — 다른 노드 가져오기
노드|File SOP|File — 파일 불러오기
노드|ROP Geometry Output|Geometry ROP — 지오메트리 저장
노드|File Cache SOP|File Cache — 캐시 저장
노드|Connectivity SOP|Connectivity — 덩어리 번호
노드|Pack SOP and packed primitives|Pack — 가볍게 묶기
노드|Unpack SOP|Unpack — 묶음 풀기
노드|Assemble SOP|Assemble — 조각 정리
노드|Voronoi Fracture SOP|Voronoi Fracture — 조각내기
노드|RBD Material Fracture SOP|RBD Material Fracture — 재질별 파괴
노드|Edge Fracture|Edge Fracture — 모서리 따라 깨기
노드|Points from Volume SOP|Points from Volume — 부피 안 점
노드|VDB Smooth SDF|VDB Smooth — 볼륨 매끄럽게
노드|Convert VDB SOP|Convert VDB — 볼륨↔폴리곤
노드|VDB Combine|VDB Combine — 볼륨 합치기
노드|Heightfield SOP|Heightfield — 지형 시작
노드|Heightfield Noise|Heightfield Noise — 지형 굴곡
노드|Heightfield Erode|Heightfield Erode — 침식
노드|Heightfield Scatter|Heightfield Scatter — 지형에 뿌리기
노드|Labs tools overview|SideFX Labs 도구 소개
노드|Font SOP|Font — 글자
노드|Trace SOP|Trace — 이미지 윤곽 따기
노드|Ray SOP|Ray — 표면에 투영
노드|Smooth SOP|Smooth — 매끄럽게
노드|Peak SOP|Peak — 노멀 방향 밀기
노드|Bend SOP|Bend — 휘기
노드|Lattice SOP|Lattice — 격자 변형
노드|Point Deform SOP|Point Deform — 저폴리로 고폴리 변형
노드|Path Deform SOP|Path Deform — 커브 따라 변형
노드|Sort SOP|Sort — 점 순서 바꾸기
노드|Timeshift SOP|Timeshift — 프레임 고정
노드|Trail SOP|Trail — 궤적·속도
시뮬레이션|POP particles basics|POP — 파티클 기초
시뮬레이션|Pyro smoke and fire|Pyro — 연기·불
시뮬레이션|FLIP fluids basics|FLIP — 액체 기초
시뮬레이션|RBD Bullet Solver|RBD — 강체 파괴
시뮬레이션|Vellum cloth|Vellum Cloth — 천
시뮬레이션|Vellum hair and grains|Vellum — 머리카락·모래
렌더링|Karma renderer basics|Karma — 렌더 기초
렌더링|Solaris LOP basics|Solaris — USD 장면 구성
렌더링|Lights and environment light|조명·환경광
렌더링|MaterialX shaders in Karma|MaterialX 재질
기본 조작|Network editor navigation|네트워크 에디터 다루기
기본 조작|Parameters and channel references|파라미터·채널 참조(ch)
기본 조작|Geometry Spreadsheet|Geometry Spreadsheet — 속성 보기
기본 조작|Digital Assets (HDA) basics|HDA — 나만의 노드 만들기
기본 조작|Takes|Takes — 설정 바꿔 보기
""",
"Unreal Engine": """
에디터|Content Browser|Content Browser — 자산 관리
에디터|Viewport navigation|뷰포트 이동 방법
에디터|Outliner and Details panel|Outliner·Details 패널
에디터|Static Mesh import (FBX)|Static Mesh 가져오기(FBX)
에디터|Static Mesh Editor|Static Mesh 에디터
에디터|Collision setup|콜리전 설정
에디터|LOD settings|LOD — 거리별 단순화
에디터|Modeling Mode tools|Modeling Mode — 엔진 안에서 모델링
에디터|Quixel Bridge and Fab assets|Fab — 무료 자산 가져오기
에디터|Level and World Partition|World Partition — 큰 맵 나누기
에디터|Level Instances|Level Instance — 묶음 재사용
에디터|Foliage tool|Foliage — 나무·풀 칠하기
에디터|Procedural Content Generation (PCG) basics|PCG — 절차적 배치
에디터|Landscape materials (layer blend)|Landscape 재질 레이어
에디터|Water system|Water — 물 시스템
에디터|Project Settings and Plugins|프로젝트 설정·플러그인
에디터|Editor Preferences and hotkeys|에디터 단축키
에디터|Data Layers|Data Layers — 장면 상태 나누기
에디터|Editor Utility Widgets|Editor Utility Widget — 편집 도구 만들기
재질|Material Instances|Material Instance — 재질 변형 빨리
재질|Texture import settings|텍스처 가져오기 설정(sRGB·압축)
재질|Material parameters|재질 파라미터
재질|Material Functions|Material Function — 노드 재사용
재질|Texture Coordinate and tiling|UV 타일링
재질|World Aligned Texture|World Aligned — 월드 기준 텍스처
재질|Masked and Translucent blend modes|Masked·Translucent — 투명 재질
재질|Emissive materials|Emissive — 빛나는 재질
재질|Material Layers|Material Layers — 재질 겹치기
재질|Decals|Decal — 표면에 덧붙이기
재질|Runtime Virtual Texturing|RVT — 지형과 오브젝트 섞기
재질|Substrate materials|Substrate — 새 재질 시스템
조명|Directional Light and Sky Atmosphere|태양광·하늘
조명|Sky Light|Sky Light — 주변광
조명|Point, Spot and Rect Light|Point·Spot·Rect 조명
조명|Exponential Height Fog|Height Fog — 안개
조명|Volumetric Clouds|Volumetric Cloud — 구름
조명|Light Mobility (Static, Stationary, Movable)|조명 Mobility 차이
조명|Lightmass baked lighting|Lightmass — 라이트 굽기
조명|Virtual Shadow Maps|Virtual Shadow Maps — 그림자
조명|HDRI Backdrop|HDRI Backdrop — HDRI 배경
렌더링|Post Process Volume|Post Process Volume — 화면 효과
렌더링|Exposure and Auto Exposure|노출 설정
렌더링|Color grading|색 보정
렌더링|Depth of Field (Cine Camera)|Cine Camera — 피사계 심도
렌더링|Path Tracer|Path Tracer — 사실적 렌더
렌더링|Hardware Ray Tracing settings|하드웨어 레이 트레이싱
렌더링|Reflections (Lumen reflections)|반사 설정
렌더링|High Resolution Screenshot|고해상도 스크린샷
렌더링|Scalability settings|Scalability — 품질 단계
렌더링|Stat commands (FPS, GPU)|stat 명령 — 성능 확인
블루프린트|Blueprint Actor basics|Blueprint Actor 만들기
블루프린트|Variables and functions in Blueprint|블루프린트 변수·함수
블루프린트|Event Graph and Construction Script|Event Graph·Construction Script
블루프린트|Timeline node|Timeline — 시간에 따른 값
블루프린트|Trigger Box overlap events|Trigger — 들어가면 동작
블루프린트|Opening a door with Blueprint|블루프린트로 문 열기
블루프린트|Enhanced Input|Enhanced Input — 키 입력
블루프린트|Blueprint Interfaces|Blueprint Interface — 서로 호출
블루프린트|Spawn Actor|Spawn Actor — 실행 중 생성
블루프린트|UMG widgets basics|UMG — 화면 UI
블루프린트|Level Blueprint|Level Blueprint
블루프린트|Game Mode and Player Controller|Game Mode·Player Controller
애니메이션|Skeletal Mesh import|Skeletal Mesh 가져오기
애니메이션|Animation Blueprint basics|Animation Blueprint 기초
애니메이션|Blend Space|Blend Space — 걷기·뛰기 섞기
애니메이션|Retargeting (IK Retargeter)|IK Retargeter — 애니메이션 옮기기
애니메이션|Control Rig basics|Control Rig — 엔진 안 리깅
애니메이션|Animation Montage|Montage — 동작 재생
애니메이션|MetaHuman basics|MetaHuman — 디지털 휴먼
애니메이션|Live Link|Live Link — 외부 툴 연결
시퀀서|Camera cuts in Sequencer|시퀀서 카메라 컷
시퀀서|Keyframing actors in Sequencer|시퀀서 키프레임
시퀀서|Camera Rig Rail and Crane|Camera Rail·Crane
시퀀서|Movie Render Graph|Movie Render Graph — 렌더 설정 그래프
이펙트|Niagara emitters and modules|Niagara 이미터·모듈
이펙트|Niagara fire and smoke|Niagara 불·연기
이펙트|Niagara mesh particles|Niagara 메시 파티클
이펙트|Chaos Destruction (Geometry Collection)|Chaos — 부수기
이펙트|Chaos Cloth|Chaos Cloth — 천
물리|Physics simulation on actors|물리 시뮬레이션 켜기
물리|Physics Asset Editor|Physics Asset — 래그돌
최적화|Nanite settings and fallback|Nanite 설정·Fallback
최적화|Instanced Static Mesh|Instanced Mesh — 대량 복제
최적화|Texture streaming and mipmaps|텍스처 스트리밍
최적화|Unreal Insights profiling|Unreal Insights — 성능 분석
최적화|Shader compile and DDC|셰이더 컴파일·DDC
내보내기|Packaging a project|프로젝트 패키징
내보내기|Datasmith import (3ds Max, SketchUp)|Datasmith — 건축 파일 가져오기
내보내기|USD in Unreal|USD 가져오기
내보내기|Pixel Streaming basics|Pixel Streaming — 웹으로 보기
내보내기|Python scripting in Unreal Editor|에디터 파이썬 스크립트
에디터|Actor pivot and snapping|액터 피벗·스냅
에디터|Merge Actors tool|Merge Actors — 메시 합치기
에디터|Bookmarks and camera views|뷰 북마크
""",
"Maya": """
기본 조작|Viewport navigation and panels|뷰포트 이동·패널
기본 조작|Outliner|Outliner — 장면 정리
기본 조작|Hotbox and marking menus|Hotbox·마킹 메뉴
기본 조작|Shelves|Shelf — 자주 쓰는 도구
기본 조작|Project and workspace setup|프로젝트 설정
기본 조작|Pivot editing (D key)|피벗 옮기기(D)
기본 조작|Snapping (grid, point, curve)|스냅
기본 조작|Freeze Transformations|Freeze Transformations — 값 초기화
기본 조작|Delete History|Delete History — 기록 지우기
기본 조작|Center Pivot|Center Pivot
기본 조작|Grouping and parenting|그룹·부모 연결
기본 조작|Display layers|Display Layer
기본 조작|Node Editor|Node Editor
기본 조작|Preferences and units|설정·단위
모델링|Polygon primitives|기본 도형 만들기
모델링|Insert Edge Loop|Insert Edge Loop
모델링|Bridge|Bridge — 면 잇기
모델링|Append to Polygon|Append to Polygon — 구멍 메우기
모델링|Fill Hole|Fill Hole
모델링|Merge vertices|Merge — 점 합치기
모델링|Target Weld|Target Weld
모델링|Combine and Separate|Combine·Separate
모델링|Boolean|Boolean — 합치기·빼기
모델링|Mirror|Mirror — 대칭
모델링|Symmetry modeling|Symmetry — 대칭 편집
모델링|Smooth (Subdivision preview 3 key)|Smooth·3키 미리보기
모델링|Crease tool|Crease — 서브디비전 모서리
모델링|Quad Draw|Quad Draw — 리토폴로지
모델링|Retopologize|Retopologize — 자동 리토폴로지
모델링|Reduce|Reduce — 폴리곤 줄이기
모델링|Cleanup|Cleanup — 메시 정리
모델링|Soft Selection|Soft Selection — 부드럽게 함께 이동
모델링|Duplicate Special|Duplicate Special — 규칙 복제
모델링|Edge flow and Edit Edge Flow|Edit Edge Flow
모델링|Slide Edge|Slide Edge
모델링|Chamfer Vertex|Chamfer Vertex
모델링|Poke Face and Wedge|Poke·Wedge
모델링|Extrude along curve|커브 따라 Extrude
모델링|NURBS curves (CV Curve tool)|CV Curve — 커브 그리기
모델링|Revolve and Loft|Revolve·Loft
모델링|Type tool (3D text)|Type — 3D 글자
모델링|Sculpting tools|스컬프트 도구
모델링|Lattice deformer|Lattice — 격자 변형
모델링|Bend and nonlinear deformers|Bend 등 Nonlinear 디포머
모델링|Wrap deformer|Wrap 디포머
모델링|Blend Shape|Blend Shape — 표정
모델링|Mesh Display normals|노멀 표시·뒤집기
모델링|Soften/Harden Edge|Soften·Harden Edge
UV|UV Editor basics|UV Editor 기초
UV|Automatic and Planar mapping|Automatic·Planar 매핑
UV|Cut and Sew UVs|Cut·Sew UV
UV|Unfold and Layout|Unfold·Layout
UV|Texel Density|Texel Density
재질|Standard Surface (Arnold)|Standard Surface — Arnold 재질
재질|File texture node|File 텍스처 연결
재질|Bump and normal maps|Bump·노멀 맵
재질|aiImage and color spaces|색 공간 설정
재질|Assigning materials to faces|면별 재질 지정
재질|Layered shader|Layered Shader
재질|Ramp texture|Ramp — 그라데이션
렌더링|Arnold Render View|Arnold Render View
렌더링|Arnold lights (Area, SkyDome)|Arnold 조명
렌더링|Render Settings|Render Settings
렌더링|AOVs|AOV — 렌더 패스
렌더링|Render Setup (layers)|Render Setup — 렌더 레이어
렌더링|Camera and depth of field|카메라·피사계 심도
렌더링|Batch render|Batch Render
렌더링|Viewport 2.0 settings|Viewport 2.0 설정
렌더링|Playblast|Playblast — 미리보기 영상
애니메이션|Set Key and Auto Key|키 넣기(S)·Auto Key
애니메이션|Time Slider and Range Slider|타임 슬라이더
애니메이션|Graph Editor|Graph Editor
애니메이션|Dope Sheet|Dope Sheet
애니메이션|Motion Path|Motion Path — 경로 따라
애니메이션|Constraints (Parent, Aim, Point)|Constraint — 부모·조준
애니메이션|Ghosting and Motion Trail|Motion Trail
애니메이션|Time Editor|Time Editor
애니메이션|Animation Layers|Animation Layer
애니메이션|Set Driven Key|Set Driven Key
리깅|Joints basics|Joint — 뼈 만들기
리깅|Orient Joints|Orient Joint — 축 정리
리깅|IK Handle|IK Handle
리깅|Bind Skin|Bind Skin — 스키닝
리깅|Paint Skin Weights|Paint Skin Weights
리깅|Component Editor weights|Component Editor — 웨이트 숫자로
리깅|Controllers and offset groups|컨트롤러·오프셋 그룹
리깅|HumanIK|HumanIK — 캐릭터 리그
리깅|Quick Rig|Quick Rig — 빠른 리그
이펙트|nCloth basics|nCloth — 천
이펙트|nParticles basics|nParticles
이펙트|Bifrost Graph basics|Bifrost — 노드 이펙트
이펙트|MASH basics|MASH — 모션 그래픽 복제
이펙트|XGen basics|XGen — 털·머리카락
이펙트|Bullet and rigid bodies|강체 시뮬레이션
내보내기|FBX export for games|게임용 FBX 내보내기
내보내기|Reference files|Reference — 파일 참조
내보내기|Alembic cache|Alembic 캐시
내보내기|USD in Maya|USD 사용
스크립트|Script Editor and MEL|Script Editor·MEL
스크립트|Python (maya.cmds) basics|파이썬 maya.cmds 기초
스크립트|Custom shelf button from script|스크립트를 Shelf 버튼으로
""",
"ZBrush": """
기본 조작|ZBrush interface and LightBox|인터페이스·LightBox
기본 조작|Canvas navigation|캔버스 회전·이동
기본 조작|Edit mode and 2.5D|Edit 모드와 2.5D 차이
기본 조작|Tools vs Projects (ZTL and ZPR)|Tool·Project 저장 차이
기본 조작|Draw Size, Z Intensity, Focal Shift|브러시 크기·세기·Focal Shift
기본 조작|Symmetry (X key)|대칭(X)
기본 조작|Radial symmetry|방사 대칭
기본 조작|Custom UI and hotkeys|UI·단축키 바꾸기
기본 조작|Undo History|Undo History
기본 조작|QuickSave|QuickSave — 자동 저장
기본 조작|Floor grid and Perspective|바닥 그리드·원근
기본 조작|Transpose line|Transpose — 이동·회전·크기
기본 조작|Gizmo 3D|Gizmo 3D
SubTool|SubTool palette|SubTool — 부품 관리
SubTool|Append and Insert SubTool|Append·Insert
SubTool|Split and Merge SubTools|Split·Merge
SubTool|Folders in SubTool|SubTool 폴더
SubTool|Visibility and Solo mode|Solo 모드
SubTool|Polygroups|Polygroup — 면 그룹
SubTool|Auto Groups and Group by normals|자동 Polygroup
SubTool|Masking basics|마스크 기초(Ctrl)
SubTool|Mask by cavity|Cavity 마스크
SubTool|Hide and show (Ctrl+Shift)|숨기기·보이기
모델링|Subdivision levels (Divide)|Divide — 단계 올리기
모델링|Smooth brush|Smooth — 매끄럽게(Shift)
모델링|ZModeler brush|ZModeler — 폴리곤 모델링
모델링|Live Boolean|Live Boolean
모델링|ZSphere basics|ZSphere — 뼈대로 형태
모델링|Adaptive Skin|Adaptive Skin
모델링|Sculptris Pro|Sculptris Pro — 동적 폴리곤
모델링|Shadowbox|ShadowBox — 실루엣으로 형태
모델링|Extract (shell from mask)|Extract — 마스크로 껍질
모델링|Panel Loops|Panel Loops — 판 두께
모델링|Mirror and Weld|Mirror and Weld
모델링|Decimation Master|Decimation Master — 폴리곤 줄이기
모델링|Project All (detail transfer)|Project All — 디테일 옮기기
모델링|Reconstruct Subdiv|Reconstruct Subdiv
모델링|Crease and Crease PG|Crease — 날카로운 모서리
모델링|Bevel Pro|Bevel Pro — 하드서피스 베벨
모델링|Dynamic Subdivision|Dynamic Subdiv — 미리보기 서브디비전
모델링|Gizmo deformers (Bend, Twist, Taper)|Gizmo 디포머
모델링|Array Mesh|Array Mesh — 반복 복제
모델링|Nano Mesh|Nano Mesh — 면마다 배치
모델링|Curve brushes (CurveTube)|Curve 브러시
모델링|IMM brushes|IMM — 부품 넣기
모델링|Insert Mesh brushes|Insert Mesh
모델링|Thick Skin|Thick Skin — 두께
모델링|Close Holes|Close Holes — 구멍 막기
모델링|Remesh All|Remesh All
모델링|Topology brush|Topology 브러시 — 직접 리토폴로지
브러시|Standard brush|Standard 브러시
브러시|Move brush|Move 브러시
브러시|Clay Buildup|Clay Buildup
브러시|Dam Standard|Dam Standard — 주름 선
브러시|Inflate brush|Inflate — 부풀리기
브러시|Pinch brush|Pinch — 모서리 조이기
브러시|hPolish and Trim Dynamic|hPolish·Trim — 평평하게
브러시|Snakehook|Snakehook — 끌어당겨 뽑기
브러시|Move Topological|Move Topological
브러시|Clip brushes|Clip 브러시 — 잘라 평평하게
브러시|Slice brushes|Slice — Polygroup 나누기
브러시|Knife brushes|Knife — 잘라내기
브러시|Alphas and stroke types|Alpha·Stroke 종류
브러시|DragRect with alphas|DragRect — 무늬 찍기
브러시|Lazy Mouse|Lazy Mouse — 부드러운 선
브러시|Backface Masking|Backface Mask
브러시|Saving custom brushes|브러시 저장
브러시|Surface noise|Surface Noise — 표면 질감
브러시|Layers palette|Layer — 디테일 층
브러시|Morph Target|Morph Target — 되돌리기 붓
페인트|Polypaint basics|Polypaint — 정점 색칠
페인트|Spotlight projection|Spotlight — 사진 투영
페인트|Materials (MatCap)|MatCap 재질
페인트|Fill object with color|색 채우기
페인트|Polypaint from texture|텍스처에서 Polypaint
리토폴로지|ZRemesher guides|ZRemesher Guide — 흐름 지정
리토폴로지|ZRemesher Target Polygons and Adaptive|ZRemesher 옵션
리토폴로지|Freeze Subdivision Levels|Freeze Subdivision Levels
UV|UV Master|UV Master — 자동 UV
UV|UV Master Control Painting|UV Master 경계 지정
맵|Displacement map export|디스플레이스먼트 맵 내보내기
맵|Normal map export|노멀 맵 내보내기
맵|Multi Map Exporter|Multi Map Exporter
맵|Vector displacement|Vector Displacement
렌더링|BPR render|BPR 렌더
렌더링|Render passes for compositing|렌더 패스
렌더링|Turntable recording|Turntable 영상
렌더링|KeyShot bridge|KeyShot 연동
내보내기|GoZ to other apps|GoZ — 다른 툴로 보내기
내보내기|FBX Export Import|FBX 내보내기·가져오기
내보내기|3D Print Hub|3D Print Hub — 출력용
내보내기|Scale Master|Scale Master — 실제 크기
기타|Timeline and movie|Timeline — 애니메이션
기타|Poseable symmetry|Poseable Symmetry
기타|Transpose Master|Transpose Master — 포즈 잡기
기타|Dynamics (cloth simulation)|Dynamics — 천 시뮬레이션
기타|XMD and Fibermesh|FiberMesh — 털
기타|NoiseMaker|NoiseMaker
기타|Text 3D and Vector Shapes|Text 3D
기타|Scripting with ZScript basics|ZScript 기초
""",
"Substance 3D": """
페인터|Substance Painter project setup|Painter 새 프로젝트 설정
페인터|Painter interface and shelf|Painter 인터페이스·Shelf
페인터|Viewport navigation in Painter|Painter 뷰포트 이동
페인터|Texture Set settings|Texture Set 설정
페인터|Fill layers|Fill 레이어
페인터|Paint layers and brushes|Paint 레이어·브러시
페인터|Smart Materials|Smart Material
페인터|Smart Masks|Smart Mask
페인터|Generators (Dirt, Edge Wear)|Generator — 먼지·모서리 마모
페인터|Filters|Filter
페인터|Anchor points|Anchor Point — 레이어 참조
페인터|Height and normal painting|높이·노멀 칠하기
페인터|Stencils and projection|스텐실·투영
페인터|Polygon Fill tool|Polygon Fill — 면 단위 마스크
페인터|ID map masking (Color Selection)|ID 맵으로 마스크
페인터|Symmetry painting|대칭 칠하기
페인터|Particle brushes|Particle 브러시
페인터|Decals and alphas|데칼·알파
페인터|Text tool in Painter|Text — 글자 넣기
페인터|UV Tiles and UDIM|UDIM 작업
페인터|Baking ambient occlusion and curvature|AO·Curvature 굽기
페인터|Baking with cage|Cage로 베이킹
페인터|Fixing baking artifacts|베이킹 오류 고치기
페인터|Export textures presets|텍스처 내보내기 프리셋
페인터|Export for Unreal Engine|언리얼용 내보내기
페인터|Export for Unity|유니티용 내보내기
페인터|Export for Blender and Arnold|블렌더·Arnold용 내보내기
페인터|Iray rendering in Painter|Painter Iray 렌더
페인터|Environment map and lighting|환경 맵·조명
페인터|Display settings and color profile|Display Settings
페인터|Shaders (PBR Metal Rough vs Spec Gloss)|Metal Rough와 Spec Gloss
페인터|Opacity and alpha channel|불투명도 채널
페인터|Emissive channel|Emissive 채널
페인터|Layer blending modes|레이어 혼합 모드
페인터|Folders and instancing layers|레이어 폴더·인스턴스
페인터|Geometry mask|Geometry Mask
페인터|Paint brush presets|브러시 프리셋 저장
페인터|Material painting|Material 칠하기
페인터|Projection painting from photos|사진 투영 칠하기
페인터|Warp projection|Warp 투영
페인터|Auto UV unwrap in Painter|Painter 자동 UV
페인터|Reimport mesh|메시 다시 불러오기
페인터|Python scripting in Painter|Painter 파이썬
페인터|Substance Painter plugins|플러그인
페인터|Performance and memory settings|성능 설정
페인터|Mesh Maps resolution|메시 맵 해상도
페인터|Ambient occlusion in fill layers|AO 활용
페인터|Rust and dirt workflow|녹·먼지 표현
페인터|Hand-painted stylized texturing|손그림 스타일
페인터|Skin texturing basics|피부 텍스처 기초
페인터|Fabric and leather materials|천·가죽 재질
페인터|Wood material workflow|나무 재질
페인터|Metal edge wear workflow|금속 모서리 마모
페인터|Glass and transparent materials|유리 재질
페인터|Painter to Marmoset Toolbag|Marmoset으로 보내기
디자이너|Substance Designer interface|Designer 인터페이스
디자이너|Graphs and nodes basics|그래프·노드 기초
디자이너|Shape and Tile Generator|Tile Generator — 반복 무늬
디자이너|Noise nodes|노이즈 노드
디자이너|Height to Normal|높이 → 노멀
디자이너|Blend node|Blend 노드
디자이너|Levels and Histogram Scan|Levels·Histogram Scan
디자이너|Warp and Directional Warp|Warp — 일그러뜨리기
디자이너|Flood Fill|Flood Fill — 조각별 무작위
디자이너|Tile Sampler|Tile Sampler
디자이너|Exposed parameters|파라미터 노출
디자이너|Publishing SBSAR|SBSAR 내보내기
디자이너|Bricks material in Designer|벽돌 재질 만들기
디자이너|Ground and rocks material|땅·바위 재질
디자이너|Fabric pattern material|천 무늬 재질
디자이너|Function graphs basics|Function Graph 기초
디자이너|Pixel processor basics|Pixel Processor
디자이너|Bakers in Designer|Designer 베이킹
디자이너|Atlas Maker|Atlas — 아틀라스
디자이너|Make It Tile|Make It Tile — 이음새 없애기
샘플러|Substance Sampler image to material|Sampler — 사진으로 재질
샘플러|Sampler layers and filters|Sampler 레이어·필터
샘플러|AI-powered material generation|AI 재질 생성
샘플러|Tileable photos in Sampler|사진 타일링
샘플러|Atlas creator in Sampler|Sampler 아틀라스
샘플러|Export from Sampler|Sampler 내보내기
스테이저|Substance Stager scene setup|Stager 장면 구성
스테이저|Stager lighting and camera|Stager 조명·카메라
스테이저|Stager rendering|Stager 렌더
모델러|Substance Modeler basics|Modeler 기초
모델러|Modeler in VR|Modeler VR
공통|Substance 3D Assets library|Substance 에셋 라이브러리
공통|SBSAR in Blender|블렌더에서 SBSAR
공통|SBSAR in Unreal Engine|언리얼에서 SBSAR
공통|SBSAR in 3ds Max and Maya|Max·Maya에서 SBSAR
공통|Texel density and resolution planning|텍스처 해상도 계획
공통|Channel packing (ORM)|채널 패킹(ORM)
공통|Color space for textures|텍스처 색 공간
공통|PBR basics (albedo, roughness, metallic)|PBR 기초
공통|Low poly and high poly preparation|로우·하이폴리 준비
공통|Naming for bake matching|베이크 이름 맞추기
공통|Mesh map types explained|메시 맵 종류
공통|Material reference and color values|실제 재질 색 값
공통|Substance licensing basics|라이선스 기초
""",
}


def topics() -> list[tuple]:
    out = []
    for tool, block in RAW.items():
        for line in block.strip().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3 and parts[1] != "placeholder":
                out.append((tool, parts[0], parts[1], parts[2], None))
    return out

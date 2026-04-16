# 아키텍처 문서 (ARCHITECTURE.md)

## 1. 시스템 개요

CNC 시뮬레이터는 레이어드 아키텍처(Layered Architecture)를 따릅니다.
각 레이어는 명확한 책임을 가지며, 하위 레이어에만 의존합니다.

```
┌─────────────────────────────────────┐
│           UI Layer (PySide6)        │  사용자 인터페이스
├─────────────────────────────────────┤
│         Service Layer               │  비즈니스 로직 조율
├─────────────────────────────────────┤
│    Parser │ Simulation │ Geometry   │  도메인 로직
│           │ Verification│           │
├─────────────────────────────────────┤
│         Models Layer                │  데이터 구조
├─────────────────────────────────────┤
│         Utils Layer                 │  공통 유틸리티
└─────────────────────────────────────┘
```

## 2. 모듈 구조

### 2.1 Parser 패키지 (`app/parser/`)

G-코드 파싱의 핵심 로직을 담당합니다.

**nc_tokenizer.py**
- 역할: NC 코드 라인을 개별 토큰으로 분해
- 입력: NC 코드 문자열 라인
- 출력: `NCToken` 리스트 (어드레스-값 쌍)
- 처리: 괄호/세미콜론 주석 제거, N코드 필터링

**modal_state.py**
- 역할: G코드 모달 상태 추적 및 관리
- 상태: 이동 모드, 평면, 단위, 좌표계, 이송 속도 등
- 특징: 한 번 설정된 모달값은 변경 전까지 유지

**gcode_parser.py**
- 역할: 전체 파싱 프로세스 조율
- 입력: NC 파일 경로 또는 G-코드 문자열
- 출력: `Toolpath` 객체
- 처리: 라인별 토크나이징 → 모달 상태 업데이트 → 세그먼트 생성

### 2.2 Models 패키지 (`app/models/`)

데이터 구조를 정의합니다. 순수 데이터 클래스로 비즈니스 로직을 최소화합니다.

**toolpath.py**
- `MotionType`: 이동 유형 열거형 (RAPID/LINEAR/ARC_CW/ARC_CCW/DWELL)
- `MotionSegment`: 단일 이동 세그먼트 (시작/끝 위치, 이송 속도, 공구 번호 등)
- `Toolpath`: 전체 공구경로 컨테이너 (세그먼트 목록, 통계, 경고)

**tool.py**
- `ToolType`: 공구 종류 열거형
- `Tool`: 공구 사양 (번호, 이름, 직경, 길이 등)

**machine.py**
- `MachineAxis`: 단일 축 이동 범위
- `MachineDef`: 머신 전체 사양

**project.py**
- `ProjectConfig`: 프로젝트 설정 (NC 파일, 머신, 공구, 소재)

### 2.3 Simulation 패키지 (`app/simulation/`)

시뮬레이션 재생 로직을 담당합니다.

**machine_state.py**
- 역할: 재생 중 현재 상태 추적
- 기능: step_forward/backward, jump_to, get_progress
- 패턴: 상태 머신 (State Machine)

**motion_planner.py**
- 역할: 세그먼트 보간 및 경로 계산
- 기능: 직선/원호 보간, 미리보기 점 생성

**time_estimator.py**
- 역할: 가공 시간 추정
- 계산: 거리 / 이송 속도 기반

### 2.4 Geometry 패키지 (`app/geometry/`)

소재 모델과 공구 형상을 다룹니다.

**stock_model.py**
- 역할: Z-맵 방식 소재 표현
- 자료구조: 2D numpy 배열 (격자별 최대 Z 높이)
- 핵심 연산: `remove_material()` - 공구 경로 아래 Z 업데이트

**tool_geometry.py**
- 역할: 공구 형상 계산
- 기능: 절삭 원통, 스윕 볼륨 경계 박스, 3D 메시 생성

**material_removal.py**
- 역할: 전체 공구경로에 대한 재료 제거 시뮬레이션
- 처리: 절삭 이동마다 stock_model 업데이트

### 2.5 Verification 패키지 (`app/verification/`)

NC 코드 검증 규칙을 구현합니다.

**rules.py**
- 역할: 개별 검증 규칙 함수들
- 패턴: 각 함수는 독립적으로 `VerificationWarning` 리스트 반환
- 규칙: 충돌, 범위, 공구, 주축, 이송 속도 등 9가지

**checker.py**
- 역할: 모든 규칙을 일괄 실행하고 결과 집계
- 기능: 규칙별 ON/OFF, 결과를 라인 번호 순 정렬

### 2.6 Services 패키지 (`app/services/`)

애플리케이션 수준의 비즈니스 로직을 조율합니다.

**project_service.py**
- 역할: 프로젝트 파일 로드/저장 (YAML)
- 기능: 머신/공구/소재 설정 파싱, 기본 설정 로드

**report_service.py**
- 역할: 검증 보고서 생성
- 출력: 포맷된 텍스트 보고서 (헤더, 통계, 경고 목록)

### 2.7 UI 패키지 (`app/ui/`)

PySide6 기반 사용자 인터페이스입니다.

**main_window.py**
- 역할: 전체 UI 조율 및 이벤트 처리
- 구성: 메뉴, 툴바, 3D 뷰어, 제어 패널, 공구경로 목록

**viewer_3d.py**
- 역할: OpenGL 기반 3D 공구경로 시각화
- 기능: 궤도/팬/줌 카메라, 색상별 이동 유형 표시

**simulation_controls.py**
- 역할: 재생 제어 UI (버튼, 슬라이더)
- 신호: play/pause/step/jump/speed_changed

**tool_info_panel.py**
- 역할: 현재 공구 및 가공 상태 표시

**toolpath_widget.py**
- 역할: 세그먼트 목록 테이블 (경고 색상 표시)

**report_dialog.py**
- 역할: 검증 보고서 표시 및 저장 다이얼로그

## 3. 데이터 흐름

```
NC 파일
    │
    ▼
GCodeParser.parse_file()
    │  nc_tokenizer → NCToken 리스트
    │  modal_state → 모달 상태 추적
    │  MotionSegment 생성
    ▼
Toolpath 객체
    │
    ├──► MachineState.load_toolpath() → 시뮬레이션 재생
    │
    ├──► VerificationChecker.run_all_checks() → 경고 목록
    │        │
    │        └──► StockModel (소재 모델과 비교)
    │
    └──► TimeEstimator.estimate_total_time() → 예상 시간
```

## 4. 주요 설계 결정

### 4.1 Z-맵 소재 모델 선택

완전한 3D 볼륨 표현(복셀 등) 대신 Z-맵을 선택한 이유:
- 3축 가공에서 충분한 정확도 제공
- 메모리 효율적 (3D 배열 대신 2D 배열)
- 빠른 재료 제거 계산 O(n×m) vs O(n×m×k)

한계: 언더컷 형상 표현 불가, 5축 가공에 부적합

### 4.2 모달 상태 분리

ModalState를 GCodeParser에서 분리한 이유:
- 단위 테스트 용이
- 상태 변화 추적 명확
- 상태 복제 가능 (undo 지원 가능성)

### 4.3 검증 규칙 함수 형태

규칙을 클래스 대신 독립 함수로 구현한 이유:
- 규칙 추가/제거 용이
- 독립 테스트 가능
- VerificationChecker에서 선택적 실행 용이

## 5. 성능 고려사항

- Z-맵 해상도(resolution)는 성능과 정밀도의 트레이드오프
  - resolution=1.0mm: 높은 정밀도, 많은 메모리
  - resolution=5.0mm: 낮은 정밀도, 빠른 계산
- 원호 이동은 분할 수가 너무 많으면 재료 제거 속도 저하
- 대형 NC 파일(10만줄 이상)은 파싱에 시간이 걸릴 수 있음

## 6. 향후 개선 계획

- 서브프로그램 (M98/M99) 지원
- G54~G59 좌표계 오프셋 지원
- 완전한 3D 소재 모델 (복셀 기반)
- 공구 변형/파손 시뮬레이션
- CAM 연동 (STEP 파일 등)
- 멀티스레드 파싱으로 대형 파일 처리 개선

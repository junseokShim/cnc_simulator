# CNC 시뮬레이터 - NC 코드 검증 시스템

CNC 가공 시뮬레이션 및 NC 코드 검증을 위한 Python 기반 오픈소스 도구입니다.
G-코드 파싱, 3D 공구경로 시각화, 충돌 검사, 검증 보고서 생성 기능을 제공합니다.

## 주요 기능

- **G-코드 파싱**: G0/G1/G2/G3/G4 등 주요 G코드와 M코드 지원
- **3D 시각화**: OpenGL 기반 실시간 공구경로 시각화 (색상별 이동 유형 구분)
- **시뮬레이션**: 블록 단위 재생/일시정지/역재생/속도 조절
- **NC 코드 검증**: 충돌 검사, 범위 초과, 주축 오류 등 9가지 검증 규칙
- **보고서 생성**: 검증 결과를 텍스트 보고서로 저장
- **헤드리스 모드**: UI 없이 커맨드라인에서 검증만 실행

## 설치 방법

### 요구사항

- Python 3.9 이상
- 아래 패키지 필요 (requirements.txt 참조)

### 패키지 설치

```bash
pip install -r requirements.txt
```

### 개발용 설치

```bash
pip install -e .
```

## 사용 방법

### GUI 모드 실행

```bash
python -m app.main
```

### NC 파일과 함께 실행

```bash
python -m app.main --file examples/simple_pocket.nc
```

### 프로젝트 파일과 함께 실행

```bash
python -m app.main --project examples/example_project.yaml
```

### 헤드리스 모드 (검증만 실행)

```bash
python -m app.main --headless --file examples/simple_pocket.nc
python -m app.main --headless --file examples/simple_pocket.nc --output report.txt
```

## 프로젝트 구조

```
vericut/
├── app/
│   ├── main.py              # 애플리케이션 진입점
│   ├── ui/                  # UI 위젯 모듈
│   ├── parser/              # G-코드 파서
│   ├── simulation/          # 시뮬레이션 엔진
│   ├── geometry/            # 기하학 모듈
│   ├── verification/        # 검증 규칙
│   ├── models/              # 데이터 모델
│   ├── services/            # 서비스 레이어
│   └── utils/               # 유틸리티
├── configs/                 # 설정 파일
├── examples/                # 예제 NC 파일
├── tests/                   # 단위 테스트
└── docs/                    # 문서
```

## 지원하는 G-코드

| 코드 | 기능 |
|------|------|
| G0   | 급속 이동 |
| G1   | 직선 이송 |
| G2   | 시계방향 원호 이동 |
| G3   | 반시계방향 원호 이동 |
| G4   | 드웰 (일시 정지) |
| G17  | XY 평면 선택 |
| G20  | 인치 단위 |
| G21  | mm 단위 |
| G28  | 원점 복귀 |
| G90  | 절대 좌표 |
| G91  | 증분 좌표 |

## 지원하는 M-코드

| 코드 | 기능 |
|------|------|
| M3   | 주축 정회전 |
| M4   | 주축 역회전 |
| M5   | 주축 정지 |
| M6   | 공구 교환 |
| M8   | 냉각수 ON |
| M9   | 냉각수 OFF |
| M30  | 프로그램 종료 |

## 검증 규칙

1. **RAPID_INTO_STOCK**: 급속 이동이 소재 내부로 진입하는 경우
2. **OUT_OF_BOUNDS**: 이동 위치가 머신 이동 범위를 초과하는 경우
3. **MISSING_TOOL**: 참조된 공구 번호가 공구 라이브러리에 없는 경우
4. **SPINDLE_OFF_CUTTING**: 주축 정지 상태에서 절삭 이동하는 경우
5. **LARGE_Z_PLUNGE**: 단일 이동에서 Z 하강이 너무 큰 경우
6. **ZERO_FEEDRATE**: 절삭 이동의 이송 속도가 0인 경우
7. **ARC_RADIUS_TOO_SMALL**: 원호 반경이 너무 작은 경우
8. **EXCESSIVE_FEEDRATE**: 이송 속도가 머신 최대값을 초과하는 경우
9. **EXCESSIVE_SPINDLE_SPEED**: 주축 회전수가 머신 최대값을 초과하는 경우

## 테스트 실행

```bash
# 전체 테스트
pytest tests/

# 특정 테스트만
pytest tests/test_parser.py -v

# 커버리지 포함
pytest tests/ --cov=app
```

## 한계 사항

- G54~G59 좌표계 오프셋은 지원되지 않습니다
- 서브프로그램 (M98/M99)은 지원되지 않습니다
- 소재 모델은 Z-맵 방식으로 완전한 3D 충돌 검사와 차이가 있습니다
- 5축 가공은 지원되지 않습니다

## 라이선스

MIT License

## 기여 방법

버그 리포트와 기능 개선 제안을 환영합니다.
이슈 트래커를 통해 제보해 주세요.

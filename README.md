# CNC NC 코드 시뮬레이터

> 연구/개발/교육 목적의 Python 기반 3축 CNC 시뮬레이션 및 NC 코드 검증 도구입니다.
> 실제 산업용 채터 해석기나 상용 검증기의 완전한 대체는 아니며, 공학적 근사 모델을 사용합니다.

## 개요

이 프로젝트는 NC/G-code를 파싱하여 공구경로를 시각화하고,
스톡(소재) 상태를 바탕으로 세그먼트별 AE/AP를 추정한 뒤
다음 값을 수치적으로 계산합니다.

- 스핀들 부하 추정
- 절삭력 추정
- 채터/불안정 위험도
- X/Y/Z 축별 예상 진동
- 누적 가공 footprint(가공 흔적) 맵

이번 버전에서는 특히 다음 두 가지가 강화되었습니다.

1. AE/AP-aware 가공 해석
2. 지속적으로 남는 가공 흔적(footprint) 시각화

추가로, 소재의 크기와 원점을 UI에서 직접 설정할 수 있습니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| NC 코드 파싱 | G0/G1/G2/G3/G4 및 기본 모달 상태 추적 |
| 공구경로 시각화 | 3D 뷰 + 2D fallback 뷰에서 급속/절삭 경로 구분 |
| 누적 가공 흔적 | 절삭 스윕이 지나간 영역을 footprint 형태로 계속 남김 |
| AE/AP 기반 부하 해석 | 스톡 상태에서 맞물림을 다시 계산하여 부하와 위험도 추정 |
| X/Y/Z 축 진동 정보 | 축력 분해 + 축강성 기반 예상 진동(um) 표시 |
| 검증 규칙 | 급속 이동 소재 진입, 범위 초과, 공구 누락 등 검증 |
| 리포트 생성 | 검증 결과와 가공 해석 요약을 텍스트 리포트로 저장 |

## AE/AP-aware 해석 모델

### 1. 스톡 기반 맞물림 추정

세그먼트를 따라 여러 샘플 점을 잡고 현재 남아 있는 스톡과 공구 스윕을 교차시켜
`AE(반경방향 맞물림)`과 `AP(축방향 절입)`를 추정합니다.

- 같은 경로라도 이미 한 번 지나간 영역이면 AE가 작아질 수 있습니다.
- 더 깊게 파고들수록 AP가 커집니다.
- 따라서 AE/AP 변화가 실제로 부하와 채터 위험도에 반영됩니다.

### 2. 부하/절삭력 추정

모델은 다음 입력을 반영합니다.

- 공구 직경
- 회전수(RPM)
- 이송속도(mm/min)
- 날 수
- AE / AP
- 플런지 / 램프 여부
- 방향 전환 각도
- 공구 돌출 계수
- 기계 강성 계수
- 재료 계수

대표적인 내부 계산 흐름은 다음과 같습니다.

```text
Vc = pi * D * n / 1000
fz = F / (n * z)
chip_thickness = f(fz, ae/D)
cutting_force ~= Kc(hm) * ap * hm * z_eff * engagement_factor
spindle_load ~= mix(power_based_load, mrr_based_load) * AE/AP bonus
```

### 3. 채터/진동 위험도 추정

채터 위험도는 다음 요소를 복합적으로 합산합니다.

- AE/AP 기반 engagement 위험
- 절삭속도 구간
- 방향 전환
- 플런지/램프 진입
- 스핀들 부하
- 블록 간 부하 변화
- 칩로드
- 공구 돌출
- 기계 강성

### 4. X/Y/Z 축 진동 추정

절삭력을 공구 진행 방향 기준으로 X/Y/Z 축력으로 나눈 뒤,
축강성(N/um)과 동적 증폭 계수를 반영해 예상 진동을 계산합니다.

- X/Y 축: stepover, 방향 전환, 측면 힘 영향이 큼
- Z 축: AP, 플런지/램프 진입 영향이 큼

UI에서는 현재 세그먼트의 다음 값을 바로 확인할 수 있습니다.

- X축 예상 진동
- Y축 예상 진동
- Z축 예상 진동
- 합성 진동

## 가공 흔적(footprint) 시각화

시뮬레이션은 현재 공구만 움직여 보여주는 방식이 아니라,
이미 가공이 끝난 영역도 계속 남는 `누적 footprint` 오버레이를 사용합니다.

사용자는 화면에서 다음을 구분할 수 있습니다.

- 아직 untouched 상태인 소재
- 이미 지나간 가공 영역
- 현재 공구 위치
- 공구경로
- 급속 이동 vs 절삭 이동

필요하면 색상 모드를 `스핀들 부하` 또는 `채터 위험도` 기준으로 바꿔
footprint와 경로를 더 공학적으로 읽을 수 있습니다.

## 소재 크기 / 원점 설정

우측 제어 패널의 `소재 설정`에서 다음 항목을 조정할 수 있습니다.

- 원점 기준
  - 상면 중심
  - 상면 최소 코너
  - 바닥 중심
  - 바닥 최소 코너
  - 소재 중심
- 원점 X/Y/Z
- 소재 크기 X/Y/Z
- Z-map 격자 해상도

`소재 적용`을 누르면 다음이 즉시 다시 계산됩니다.

1. 스톡 경계
2. AE/AP 기반 해석
3. 검증 결과
4. 누적 footprint 시각화

## 설치

```bash
pip install -r requirements.txt
```

개발 모드 설치:

```bash
pip install -e .
```

## 실행

GUI 실행:

```bash
python -m app.main
```

NC 파일 직접 로드:

```bash
python -m app.main --file examples/simple_pocket.nc
```

프로젝트 파일 로드:

```bash
python -m app.main --project examples/example_project.yaml
```

헤드리스 검증:

```bash
python -m app.main --headless --file examples/simple_pocket.nc
```

## 주요 설정 파일

`configs/simulation_options.yaml`

중요 키:

- `stock.origin_mode`
- `stock.origin`
- `stock.size`
- `stock.resolution`
- `machining.machine_stiffness`
- `machining.tool_overhang_factor`
- `machining.x_axis_stiffness_n_per_um`
- `machining.y_axis_stiffness_n_per_um`
- `machining.z_axis_stiffness_n_per_um`
- `machining.xy_vibration_warning_um`
- `machining.z_vibration_warning_um`
- `machining.resultant_vibration_warning_um`

## 예제 프로젝트

`examples/example_project.yaml`은 다음 형식을 보여줍니다.

```yaml
stock:
  origin_mode: top_center
  origin: [0.0, 0.0, 0.0]
  size: [120.0, 120.0, 30.0]
  resolution: 2.0
```

## 테스트

```bash
pytest -q tests
```

현재 테스트는 다음을 포함합니다.

- AE 변화가 부하/위험도/진동에 반영되는지
- AP 변화가 부하/위험도/Z축 진동에 반영되는지
- 이송 방향에 따라 주 진동축이 달라지는지
- 플런지에서 Z축 진동이 커지는지
- footprint 맵이 누적되고 reset 시 초기화되는지
- 소재 원점/크기 설정이 올바르게 bounds로 변환되는지

## 한계

- 채터 안정성 로브선도(SLD) 완전 해석은 아직 구현되지 않았습니다.
- 스톡 모델은 Z-map 기반이므로 해상도에 따른 근사 오차가 있습니다.
- 5축 가공, 좌표계 오프셋(G54~G59), 서브프로그램(M98/M99)은 아직 제한적이거나 미구현입니다.
- 실제 가공 적용 전에는 반드시 현장 조건과 실측 데이터를 기준으로 재검토해야 합니다.

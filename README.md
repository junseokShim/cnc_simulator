# CNC NC 코드 시뮬레이터 (Python 오픈소스)

> **연구/개발/교육 목적의 독립적인 오픈소스 구현입니다.**
> 상용 CNC 검증 소프트웨어와 동일한 정확도를 보장하지 않습니다.

---

## 프로젝트 개요

Python 기반의 오픈소스 3축 CNC 가공 시뮬레이션 및 NC 코드 검증 도구입니다.
NC/G-코드를 로드하여 공구경로를 3D로 시각화하고,
공학적 근사 수치 모델을 통해 스핀들 부하와 채터/진동 위험도를 블록별로 추정합니다.

---

## 주요 기능

### 핵심 기능
| 기능 | 설명 |
|------|------|
| NC 코드 파싱 | G0/G1/G2/G3, 모달 상태 추적 |
| 3D 공구경로 시각화 | pyqtgraph.opengl 기반, 급속/절삭/원호 색상 구분 |
| 스핀들 부하 추정 | Kienzle 단순화 모델, 블록별 부하% 계산 및 차트 |
| 채터 위험도 추정 | 복합 위험 인자 가중 합산, 4단계 위험 수준 분류 |
| NC 코드 검증 | 급속절입/범위초과/공구누락 등 9가지 규칙 |
| 가공 해석 차트 | 블록별 스핀들 부하/채터 위험도 pyqtgraph 차트 |
| 블록별 시뮬레이션 | 재생/일시정지/단계이동, 현재 블록 공구 위치 표시 |
| 검증 보고서 | 가공 해석 결과 포함 종합 텍스트 보고서 |

---

## 가공 수치 모델

### 스핀들 부하 추정 (Kienzle 단순화 모델)

```
절삭 속도:    Vc = π × D × n / 1000            [m/min]
날당 이송량:  fz = F / (n × z)                  [mm/tooth]
단일날 절삭력: Fc_tooth = Kc1 × ap × fz^(1-mc) [N]
총 절삭력:    Fc = Fc_tooth × (ae/πD) × z      [N]
스핀들 전력:  P = Fc × Vc / 60000 / η           [kW]
스핀들 부하:  Load% = P / P_rated × 100         [%]
```

재료별 Kc1/mc 계수 (기본값 기준):
- 알루미늄 합금: Kc1=700 N/mm², mc=0.25
- 저탄소강: Kc1=1800 N/mm², mc=0.26
- 스테인리스강: Kc1=2200 N/mm², mc=0.27

### 채터/진동 위험도 추정

| 위험 인자 | 설명 | 기본 가중치 |
|-----------|------|------------|
| 맞물림 위험도 | ae/D, ap/D 비율 기반 | 0.35 |
| 절삭 속도 위험도 | Vc 범위별 불안정 구간 | 0.20 |
| 방향 전환 위험도 | 경로 방향 변화각 | 0.20 |
| 절입 위험도 | Z방향 플런지 감지 | 0.25 |

**위험 수준 분류:**
- 낮음: < 25%  |  중간: 25~50%  |  높음: 50~75%  |  위험: ≥ 75%

### 가정과 한계
- 반경방향 맞물림(ae): Z-맵 기반 실제 계산 미적용, 공구직경 비율로 근사
- 채터 안정성: 안정성 로브선도(SLD) 완전 해석 미구현
- 재료 계수: 교재/카탈로그 참고값, 실제 측정값과 다를 수 있음
- 공구/머신 동적 특성 미적용

---

## 설치 방법

```bash
pip install -r requirements.txt
```

## 실행 방법

```bash
# GUI 실행
python -m app.main

# NC 파일 직접 로드
python -m app.main --file examples/simple_pocket.nc

# 헤드리스 검증 모드
python -m app.main --headless --file examples/simple_pocket.nc
```

---

## 가공 파라미터 설정

`configs/simulation_options.yaml`의 `machining` 섹션:

```yaml
machining:
  material: "aluminum"          # 재료 종류
  machine_stiffness: 1.0        # 머신 강성 계수
  tool_overhang_factor: 1.0     # 공구 돌출 계수
  spindle_rated_power_w: 7500.0 # 스핀들 정격 출력 (W)
  default_ae_ratio: 0.5         # 반경방향 맞물림 비율
  default_ap_mm: 2.0            # 축방향 절입 깊이 (mm)
  chatter_sensitivity: 1.0      # 채터 민감도 배율
```

---

## 디렉토리 구조

```
vericut/
├─�� app/
│   ├── main.py
│   ├── parser/          # G코드 파서
│   ├── simulation/
│   │   ├── machining_model.py  ★ 3축 가공 수치 모델
│   │   └── machine_state.py    # 시뮬레이션 재생 상태
│   ├── geometry/        # Z-맵 소재 모델
│   ├── verification/    # 9가지 검증 규칙
│   ├── models/
│   │   └── machining_result.py ★ 가공 해석 결과 모델
│   ├── ui/
│   │   ├── viewer_3d.py        ★ 3D 공구경로 뷰어
│   │   └── analysis_panel.py   ★ 가공 해석 차트 패널
│   └── services/        # 보고서/프로젝트 서비스
├── configs/             # YAML 설정 파일
├── examples/            # 예제 NC/프로젝트 파일
├── tests/               # pytest 테스트 (48개)
└── docs/ARCHITECTURE.md # 아키텍처 문서
```

---

## 한계점

- 반경방향 맞물림(ae) 실제 계산 미적용 (비율 근사)
- 채터 안정성 로브선도(SLD) 완전 해석 미구현
- 서브프로��램(M98/M99)/좌표계 오프셋(G54~G59) 미지원
- 5축 이동 시뮬레이션 미지원
- **실제 가공 전 반드시 전문 기술자의 검토 필요**

## 향후 개선 방향

1. Z-맵 기반 ae 실제 계산
2. 안정성 로브선도 완전 해석
3. 실측 센서 데이터 연계
4. 재료 데이터베이스 확장
5. 5축 가공 모델 확장
6. 공구 마모 모델 (Taylor 방정식)

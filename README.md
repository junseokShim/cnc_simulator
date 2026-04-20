# CNC NC 코드 시뮬레이터

> 연구/개발/교육 목적의 Python 기반 3축 CNC 시뮬레이션 및 NC 코드 검증 도구입니다.
> 실제 산업용 채터 해석기나 상용 검증기의 완전한 대체는 아니며, 공학적 근사 모델을 사용합니다.

**기본 기계**: DN Solutions T4000 (BT30, 12,000 RPM)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| NC 코드 파싱 | G0/G1/G2/G3/G4 및 기본 모달 상태 추적 |
| 공구경로 시각화 | 3D 뷰 + 2D fallback에서 급속/절삭 경로 구분 |
| 누적 가공 흔적 | 절삭 스윕이 지나간 영역을 footprint 형태로 계속 남김 |
| 기계론적 절삭력 모델 | Altintas (2000) 기반 접선/반경/축방향 절삭력 수치 계산 |
| 스핀들 부하 추정 | 기저+이송+절삭 성분 분해 (공중이송≠절삭 부하) |
| 채터 위험도 추정 | 비선형 점수화로 포화 방지, 의미 있는 위험도 분포 |
| X/Y/Z 축 진동 | FRF 기반 동적 진동 진폭 추정 (μm) |
| 기계 프로파일 | DN Solutions T4000 기본, YAML로 다른 기계 추가 가능 |
| 검증 규칙 | 급속 이동 소재 진입, 범위 초과, 공구 누락 등 |
| 리포트 생성 | 검증 결과 + 가공 해석 요약 텍스트/CSV 저장 |

---

## 비현실 모델 수정 기록

### 이전 모델의 문제점

#### 문제 1: G1 공중이송에서 절삭급 스핀들 부하 발생
**원인**: `seg.is_cutting_move`는 G0이 아니면 무조건 True였습니다.
stock_model 접촉 검사에서 `engaged_samples == 0`이어도 `is_cutting=True`가 유지되었고,
`ae = D × 0.5`(기본값)가 절삭력 모델에 그대로 사용되어 공중이송에도 절삭급 부하가 발생했습니다.

**수정**: `engaged_samples == 0`이면 `is_cutting = False`로 강제 전환합니다.
`CuttingFeatures`에 `machining_state` 필드를 추가하여 RAPID/AIR_FEED/PLUNGE/CUTTING 상태를 명시적으로 관리합니다.

#### 문제 2: 채터 위험도가 거의 모든 블록에서 100%로 포화
**원인**: 선형 점수 공식 `base_score = 1 - SM/SM_safe`에 가산 보정값(최대 +0.37)을 더하면
일반 절삭 조건에서도 1.0+가 되어 하드 클리핑 후 항상 100%가 되었습니다.

예) 스틸 ap=2mm, ae=D/2: ap_lim≈1.2mm → SM=0.6 → base_score=0.76 → +보정 → >1.0 → 100%

**수정**: 비선형 시그모이드 유사 공식으로 교체합니다:
```
base_score = 1 / (1 + (SM / SM_ref)^power)   SM_ref=1.2, power=2.5
```
추가 보정도 가산→승산 방식으로 변경하여 포화를 원천 방지합니다.

#### 문제 3: 기계 특성값 하드코딩
**원인**: `spindle_rated_power_w = 7500.0` 같은 값이 하드코딩되어 있어
특정 기계의 특성을 반영하지 못했습니다.

**수정**: `MachineProfile` 객체와 YAML 파일로 기계 특성을 분리하고,
DN Solutions T4000을 기본 프로파일로 사용합니다.

---

## 스핀들 부하 분해 구조

스핀들 부하는 세 가지 물리적 성분의 합으로 계산됩니다:

```
total_load = baseline_component + axis_motion_component + cutting_component
```

| 성분 | 설명 | 비절삭 시 | 절삭 시 |
|------|------|-----------|---------|
| `baseline_load_pct` | 스핀들 무부하 회전 (베어링 마찰, 냉각팬 등) | ~7% | ~7% |
| `axis_motion_load_pct` | 이송 축 구동 (이송속도 비례) | ~1-3% | ~1-3% |
| `cutting_load_pct` | Altintas 절삭력 모델 (소재 접촉 시만 발생) | **0%** | 조건에 따라 |

**실제 결과 예시 (알루미늄, D=16mm, ap=2mm, ae=16mm, S=4500)**:
- 급속이동 (G0): 0%
- 공중이송 G1: ~8.4% (기저 7% + 이송 1%)
- 실제 절삭: ~19% (기저 7% + 이송 1% + 절삭 11%)

공중이송이 절삭보다 높은 부하를 보이는 현상이 완전히 해소되었습니다.

---

## 채터 위험도 점수화 방식 (비선형)

### 이전 (포화 문제)
```python
# 선형 + 가산 → 포화
base_score = 1 - SM / 2.5
score = (base_score + 0.15 + 0.12 + 0.10) * sensitivity  # → 1.0+ → clip → 100%
```

### 현재 (비선형, 포화 방지)
```python
# 비선형 시그모이드 유사 매핑
base_score = 1 / (1 + (SM / SM_ref)^power)    # SM_ref=1.2, power=2.5

# 승산적 보정 (포화 방지)
score = base_score * resonance_factor * plunge_factor * dir_factor * sensitivity
```

SM별 위험도 분포:

| SM | 의미 | 위험도 |
|----|------|--------|
| 0.5 | 심각하게 불안정 | ~84% |
| 1.0 | 불안정 경계 | ~60% |
| 1.2 | 50% 기준점 | 50% |
| 2.0 | 안정 | ~28% |
| 4.0 | 매우 안정 | ~10% |
| 8.0 | 극도로 안정 | ~3% |

---

## DN Solutions T4000 기계 프로파일

T4000은 이 시뮬레이터의 기본 기계 프로파일입니다.

### T4000 주요 사양

| 항목 | 값 |
|------|-----|
| 스핀들 최대 RPM | 12,000 (옵션: 18,000) |
| 스핀들 정격 출력 | 7.5 kW (연속) / 11 kW (순간) |
| 스핀들 테이퍼 | BT30 (ISO #30) |
| X/Y/Z 이동량 | 520 / 400 / 350 mm |
| 급속 이송 | 56 m/min |
| 공구 끝단 강성 | 22 N/μm (BT30 홀더 기준) |
| 고유주파수 | 900 Hz |
| 감쇠비 | 0.03 |

### 기계 프로파일 아키텍처

```
configs/machines/
└── t4000.yaml          ← T4000 특성값 (스핀들, 이동량, 동특성)

app/machines/
├── __init__.py
└── machine_profile.py  ← MachineProfile 데이터클래스 + MachineProfileRegistry
```

T4000 특성값은 `configs/machines/t4000.yaml`에 정의되어 있으며,
모델 코드에 하드코딩되지 않습니다.

---

## 다른 기계 프로파일 추가 방법

1. `configs/machines/{machine_id}.yaml` 파일을 생성합니다:

```yaml
machine_profile:
  name: "My Machine XYZ"
  manufacturer: "Brand"
  model_id: "xyz_model"
  spindle_max_rpm: 15000.0
  spindle_rated_power_w: 11000.0
  spindle_taper: "BT40"
  x_travel_mm: 800.0
  y_travel_mm: 500.0
  z_travel_mm: 450.0
  rapid_traverse_mm_min: 48000.0
  machine_stiffness_factor: 1.1
  damping_ratio: 0.03
  tool_tip_stiffness_n_per_um: 30.0
  natural_frequency_hz: 750.0
  chatter_sensitivity: 1.0
  baseline_power_ratio: 0.07
  axis_motion_power_ratio: 0.04
  machine_efficiency: 0.85
  tool_holder_rigidity: 1.0
  stability_lobe_correction: 1.0
```

2. `configs/simulation_options.yaml`에서 `machine_profile_id`를 변경합니다:

```yaml
machining:
  machine_profile_id: xyz_model    # 새 기계로 전환
```

3. 시뮬레이션 파이프라인 코드 수정은 불필요합니다.

---

## 수학적 모델링 개요

```
NC 세그먼트
    │
    ▼
CuttingConditionExtractor  →  CuttingFeatures (초기 추정)
    │
    ▼  (stock_model 있으면 실제 소재 접촉 검사)
[Stock Engagement Gate]    →  is_cutting 최종 결정, machining_state 확정
    │
    ├──▶ MechanisticCuttingForceModel  →  SpindleLoadPrediction
    │    (Altintas 2000)                   - Ft, Fr, Fa, Fx, Fy, Fz
    │                                      - 토크, 총전력
    │                                      - baseline/axis/cutting 부하 분해
    │
    └──▶ StabilityLobeChatterModel     →  ChatterRiskPrediction
         (Altintas & Budak 1995)           - SM (안정성 마진)
                                           - 채터 위험도 0~1 (비선형)
                                           - 진동 진폭 X/Y/Z μm
```

---

## 스핀들 부하 추정 방식

### 기반 이론

Altintas, Y. (2000). *Manufacturing Automation*. Cambridge University Press. Chapter 2.

**1회전 평균 접선 절삭력**:

```
Ft = z·ap/(2π) · [Ktc·fz·(cos(φ_st)−cos(φ_ex)) + Kte·(φ_ex−φ_st)]
```

**X/Y 방향 합력** (방향 계수 이용):

```
Fx = z·ap·fz/(4π) · (Ktc·a_xx + Krc·a_xy) + 날끝 기여
Fy = z·ap·fz/(4π) · (Ktc·a_yx + Krc·a_yy) + 날끝 기여
```

**토크 및 절삭 전력**:

```
T = Ft · D/2      [N·mm → N·m]
P_cutting = Ft · Vc / 60  [W]
```

**스핀들 총 전력 및 부하**:

```
P_total = P_baseline + P_axis + P_cutting / η
load%   = P_total / P_rated · 100
```

### 재료별 절삭력 계수 (기본값)

| 재료 | Ktc (N/mm²) | Krc (N/mm²) | 비고 |
|------|------------|------------|------|
| 알루미늄 | 700 | 210 | Al 6061/7075 기준 |
| 저탄소강 | 1800 | 630 | S45C 기준 |
| 경화강 | 2500 | 1000 | HRC 45+ |
| 스테인리스 | 2200 | 770 | SUS304 |
| 티타늄 | 2000 | 800 | Ti-6Al-4V |
| 주철 | 1100 | 330 | GC250 |

---

## 진동/채터 위험도 추정 방식

### 기반 이론

Altintas, Y., & Budak, E. (1995). Analytical Prediction of Stability Lobes in Milling. *CIRP Annals*, 44(1), 357–362.

### 핵심 공식

**단일 자유도 FRF**:

```
Re[G]_min = −1/(2kζ√(1−ζ²))
```

**임계 축방향 절입 깊이**:

```
ap_lim = −2π / (N·Ktc·a_d·Λ_R) · stability_lobe_correction
```

**안정성 마진**:

```
SM = ap_lim / ap_actual
```

**채터 위험도 (비선형)**:

```
base_score = 1 / (1 + (SM / 1.2)^2.5)
score = base_score × 공진보정 × 플런지보정 × 방향보정 × 민감도
```

---

## 한계점

1. **FRF 기반 한계**: 실제 공구-스핀들 시스템 FRF를 측정하지 않아 채터 경계 오차 가능
2. **공정 감쇠 미구현**: 저속 가공에서 나타나는 process damping 효과 미반영
3. **MDOF 미구현**: 다중 자유도 안정성 해석 미구현
4. **재료 계수**: 문헌 기준 평균값, 실제 재료에 따른 편차 존재
5. **열적 효과**: 절삭열에 의한 강성 변화 미반영

---

## 데이터 기반 모델로 교체하는 방법

다음 파일들을 수정하면 ML 모델을 주입할 수 있습니다:

### 교체 대상 파일

| 파일 | 교체할 내용 |
|------|------------|
| `app/models/cutting_force_model.py` | `SpindleLoadPredictor` 구현체 교체 |
| `app/models/chatter_model.py` | `ChatterRiskPredictor` 구현체 교체 |
| `app/models/model_interfaces.py` | 인터페이스 정의 (변경 최소화 권장) |
| `app/simulation/machining_model.py` | predictor 주입 위치 |

### 교체 방법

```python
# app/simulation/machining_model.py
model = MachiningModel(
    load_predictor=ML스핀들부하모델(),     # ← 교체 지점 A
    chatter_predictor=ML채터모델(),        # ← 교체 지점 B
    machine_profile=MachineProfileRegistry.get("t4000"),
)
```

인터페이스(`app/models/model_interfaces.py`)를 구현하면 UI, 보고서, 검증 모듈은 변경 없이 동작합니다.

> 상세 가이드: `docs/model_replacement_guide.md`

---

## 공구 라이브러리 입력

공구 정보는 더 이상 단순 라벨이 아니라, 스핀들 부하/절삭 진동/채터 위험 계산에 직접 반영됩니다.

앱 UI에서 직접 편집할 수 있습니다.

1. 우측 탭의 `공구 라이브러리`를 엽니다.
2. `T5`, `T6`, `T7` 같은 공구 번호별로 직경, 타입, 날 수, 오버행, 길이, 강성, KC, 비고를 수정합니다.
3. `적용`을 누르면 즉시 시뮬레이션에 반영됩니다.
4. `저장`을 누르면 프로젝트를 열어 둔 경우 프로젝트 파일의 `tools` 항목에 저장되고, 프로젝트가 없으면 `configs/default_tools.yaml`에 저장됩니다.

중요: 공구 입력값은 항상 직경(mm) 기준입니다.

- `12mm EM` = 직경 12mm 엔드밀
- 내부 계산 반경 = `직경 / 2`
- 예) 12mm -> 반경 6mm, 16mm -> 반경 8mm, 7.5mm -> 반경 3.75mm

- `tool_library_file`: 별도 YAML 공구 라이브러리 파일 경로
- `tool_library.definitions`: 현장식 shorthand 정의
- `tools`: 상세 YAML 정의

지원 필드 예시는 다음과 같습니다.

```yaml
tool_library:
  definitions:
    - "T5 = 12mm EM 4F OH55 L90 RIGID=1.05 KC=0.95"
    - "T6 = 10mm EM 4F OH48 L85"
    - "T7 = 7.5mm DR 2F OH70 L95"
```

각 필드는 아래처럼 모델에 반영됩니다.

- `diameter_mm`: 접촉 폭, 내부 반경 계산, MRR, 절삭력 스케일
- `tool_type` / `tool_category`: `REM`, `EM`, `DR`별 절삭/진동 가정
- `flute_count`: 이빨 통과 주파수와 `fz` 계산
- `overhang_mm`: 슬렌더니스와 채터 민감도
- `rigidity_factor`: 유효 강성 및 급속 충격 민감도
- `cutting_coefficient_factor`, `material_coefficient_overrides`: 절삭력 계수 보정

## 디버그 가시성

세그먼트 CSV와 리포트에는 아래 중간값이 함께 기록됩니다.

- `machining_state`
- `motion_vibration_um`, `cutting_vibration_um`
- `motion_risk_score`, `chatter_raw_score`, `chatter_risk_score`
- `baseline_load_pct`, `axis_motion_load_pct`, `cutting_load_pct`
- `stability_margin`, `ap_limit_mm`, `dynamic_magnification`
- `material_ktc`, `material_krc` 등 계수

## 설치 및 실행

```bash
pip install PySide6 PyOpenGL pyqtgraph pyyaml numpy scipy trimesh

python -m app.main
```

## 테스트

```bash
python -m pytest tests/ -v
```

---

## 프로젝트 구조

```
app/
├── main.py                         # 진입점
├── machines/
│   ├── __init__.py
│   └── machine_profile.py          # MachineProfile + MachineProfileRegistry
├── models/
│   ├── model_interfaces.py         # 추상 인터페이스 (ML 교체 지점)
│   ├── cutting_conditions.py       # 절삭 조건 추출, 절입각, 가공상태 상수
│   ├── cutting_force_model.py      # Altintas 기계론적 절삭력 + 부하 분해
│   ├── chatter_model.py            # 안정성 로브선도 채터 (비선형 점수화)
│   └── machining_result.py         # 결과 데이터 구조 (상태/분해 필드 포함)
├── simulation/
│   └── machining_model.py          # 파이프라인 오케스트레이터 + stock gate
├── ui/                             # PySide6 UI 컴포넌트
├── services/                       # 파싱, 리포트 서비스
└── geometry/                       # 스톡(소재) 모델
configs/
├── simulation_options.yaml         # 재료/경보 파라미터, machine_profile_id
└── machines/
    └── t4000.yaml                  # DN Solutions T4000 기계 프로파일 (기본)
docs/
└── model_replacement_guide.md      # ML 모델 교체 가이드
```

---

## 참고한 논문 / 문헌

### [1] Altintas, Y. (2000). Manufacturing Automation
Cambridge University Press.

**기여**: 기계론적 밀링 절삭력 모델의 핵심 이론.
- 1회전 평균 절삭력 공식 (Eq. 2.15–2.26) → `cutting_force_model.py`
- 절입각 φ_entry, φ_exit 정의 (Eq. 2.5–2.6) → `cutting_conditions.py`
- 방향 계수 a_xx, a_xy, a_yx, a_yy (Eq. 2.23–2.26) → `cutting_conditions.py`
- 스핀들 전력 계산 (Eq. 2.17) → `cutting_force_model.py`
- SDOF FRF 모델 (Ch. 4) → `chatter_model.py`

### [2] Altintas, Y., & Budak, E. (1995). Analytical Prediction of Stability Lobes in Milling
*CIRP Annals*, 44(1), 357–362.

**기여**: 안정성 로브선도 이론의 핵심 공식.
- 임계 절입 깊이 ap_lim = −2π / (N·Kt·a_d·Λ_R) → `chatter_model.py`
- 방향 계수를 이용한 안정성 행렬 → `cutting_conditions.py`

### [3] Schmitz, T.L., & Smith, K.S. (2009). Machining Dynamics
Springer US.

**기여**: 채터 메커니즘 및 주파수 분석.
- 날 통과 주파수 공식 f_tp = n·z/60 (Eq. 3.1) → `chatter_model.py`

### [4] Kao, Y.-C. et al. (2015). A prediction method of cutting force coefficients
*International Journal of Advanced Manufacturing Technology*, 77, 1–11.

**기여**: 재료별 절삭력 계수 참조 데이터베이스 → `cutting_force_model.py`

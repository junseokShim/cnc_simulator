# 데이터 기반 모델 교체 가이드

> 현재 수학적 모델을 ML/데이터 기반 모델로 교체할 때 참조하는 개발자 문서입니다.

---

## 1. 현재 수학 모델 파이프라인

```
NC 파일 (G-code)
    │
    ▼
app/services/gcode_parser.py       ← G-code → MotionSegment 리스트
    │
    ▼
app/simulation/machining_model.py  ← 파이프라인 오케스트레이터
    │
    ├── app/models/cutting_conditions.py
    │       CuttingConditionExtractor.extract(seg, tool)
    │       → CuttingFeatures  (표준화된 입력 피처)
    │
    ├── app/models/cutting_force_model.py   ← [교체 지점 A]
    │       MechanisticCuttingForceModel.predict(features, params)
    │       → SpindleLoadPrediction
    │
    └── app/models/chatter_model.py         ← [교체 지점 B]
            StabilityLobeChatterModel.predict(features, load_pred, params)
            → ChatterRiskPrediction
                │
                ▼
    app/models/machining_result.py
        SegmentMachiningResult  (UI/보고서에 전달)
```

---

## 2. 교체 지점 A — 스핀들 부하 모델

### 현재 구현
- 파일: `app/models/cutting_force_model.py`
- 클래스: `MechanisticCuttingForceModel`
- 기반: Altintas (2000) 기계론적 밀링 절삭력 모델
- 핵심 공식:
  ```
  Ft = z*ap/(2π) * [Ktc*fz*(cos(φ_st)-cos(φ_ex)) + Kte*(φ_ex-φ_st)]
  P  = Ft * Vc / 60  [W]
  load% = P_shaft / P_rated * 100
  ```

### 교체 방법

**1단계: 새 클래스 작성**

```python
# app/models/ml_spindle_load_model.py (예시)
from app.models.model_interfaces import SpindleLoadPredictor, CuttingFeatures, SpindleLoadPrediction
import pickle

class MLSpindleLoadPredictor(SpindleLoadPredictor):
    def __init__(self, model_path: str):
        with open(model_path, "rb") as f:
            self._model = pickle.load(f)

    def predict(self, features: CuttingFeatures, params: dict) -> SpindleLoadPrediction:
        X = self._build_feature_vector(features)
        y_pred = self._model.predict([X])[0]  # [Ft, Fx, Fy, Fz, power_w, load_pct]

        return SpindleLoadPrediction(
            spindle_load_pct=y_pred[5],
            cutting_force_ft=y_pred[0],
            force_x=y_pred[1],
            force_y=y_pred[2],
            force_z=y_pred[3],
            power_w=y_pred[4],
            mrr=features.mrr_mm3_per_min,
            aggressiveness=features.mrr_mm3_per_min / params.get("mrr_reference_mm3min", 50000.0),
        )

    def _build_feature_vector(self, features: CuttingFeatures) -> list:
        return [
            features.cutting_speed_vc,
            features.feed_per_tooth_fz,
            features.axial_depth_ap,
            features.radial_depth_ae,
            features.radial_ratio,
            features.flute_count,
            features.spindle_rpm,
            features.phi_entry_deg,
            features.phi_exit_deg,
            features.engagement_arc_deg,
        ]
```

**2단계: MachiningModel에 주입**

```python
# app/simulation/machining_model.py
from app.models.ml_spindle_load_model import MLSpindleLoadPredictor

ml_load_model = MLSpindleLoadPredictor("models/spindle_load_v1.pkl")
model = MachiningModel(load_predictor=ml_load_model)
```

**변경 불필요한 파일**:
- `app/models/cutting_conditions.py` (피처 추출)
- `app/models/chatter_model.py` (채터 모델)
- `app/ui/` 전체 (UI)
- `app/services/report_service.py` (보고서)

---

## 3. 교체 지점 B — 채터/진동 모델

### 현재 구현
- 파일: `app/models/chatter_model.py`
- 클래스: `StabilityLobeChatterModel`
- 기반: Altintas & Budak (1995) 안정성 로브선도 이론
- 핵심 공식:
  ```
  Λ_R = -1/(2kζ√(1-ζ²))                      # FRF 실수부 최솟값 (mm/N)
  ap_lim = -2π / (N·Ktc·a_d·Λ_R)              # 임계 절입 깊이 (mm)
  SM = ap_lim / ap_actual                       # 안정성 마진
  score = 1 - clip(SM / SM_safe, 0, 1)         # 채터 위험도 (0~1)
  ```

### 교체 방법

**1단계: 새 클래스 작성**

```python
# app/models/ml_chatter_model.py (예시)
from app.models.model_interfaces import (
    ChatterRiskPredictor, CuttingFeatures,
    SpindleLoadPrediction, ChatterRiskPrediction
)

class MLChatterRiskPredictor(ChatterRiskPredictor):
    def __init__(self, model_path: str):
        import torch
        self._model = torch.load(model_path)

    def predict(
        self,
        features: CuttingFeatures,
        load_pred: SpindleLoadPrediction,
        params: dict,
    ) -> ChatterRiskPrediction:
        X = self._build_feature_vector(features, load_pred)
        with torch.no_grad():
            y = self._model(torch.tensor(X, dtype=torch.float32))
        # y = [risk_score, stability_margin, vib_x, vib_y, vib_z]

        return ChatterRiskPrediction(
            chatter_risk_score=float(y[0]),
            stability_margin=float(y[1]),
            vibration_x_um=float(y[2]),
            vibration_y_um=float(y[3]),
            vibration_z_um=float(y[4]),
            resultant_vibration_um=float((y[2]**2 + y[3]**2 + y[4]**2)**0.5),
        )

    def _build_feature_vector(self, features, load_pred) -> list:
        return [
            features.cutting_speed_vc,
            features.feed_per_tooth_fz,
            features.axial_depth_ap,
            features.radial_depth_ae,
            features.spindle_rpm,
            features.flute_count,
            features.phi_entry_deg,
            features.phi_exit_deg,
            features.direction_change_deg,
            float(features.is_plunge),
            load_pred.cutting_force_ft,
            load_pred.force_x,
            load_pred.force_y,
            load_pred.force_z,
            load_pred.power_w,
            load_pred.spindle_load_pct,
        ]
```

**2단계: MachiningModel에 주입**

```python
from app.models.ml_chatter_model import MLChatterRiskPredictor

ml_chatter = MLChatterRiskPredictor("models/chatter_v1.pt")
model = MachiningModel(chatter_predictor=ml_chatter)
```

---

## 4. 입력 피처 스키마 (CuttingFeatures)

ML 모델 학습 시 아래 피처를 입력으로 사용하세요.

| 피처명 | 단위 | 설명 | 추출 방법 |
|--------|------|------|-----------|
| `cutting_speed_vc` | m/min | 절삭 속도 | π·D·n/1000 |
| `feed_per_tooth_fz` | mm/tooth | 날당 이송량 | F/(n·z) |
| `axial_depth_ap` | mm | 축방향 절입 깊이 | Z 이동 추적 또는 설정값 |
| `radial_depth_ae` | mm | 반경방향 맞물림 | D·ae_ratio |
| `radial_ratio` | - | ae/D 비율 | ae/D |
| `tool_diameter` | mm | 공구 직경 | 공구 정의 |
| `flute_count` | - | 날 수 | 공구 정의 |
| `spindle_rpm` | RPM | 주축 회전수 | NC 블록 S 값 |
| `feedrate` | mm/min | 이송 속도 | NC 블록 F 값 |
| `phi_entry_deg` | deg | 절입각 φ_st | arccos(1-2ae/D) |
| `phi_exit_deg` | deg | 이탈각 φ_ex | π (업밀링) |
| `engagement_arc_deg` | deg | 맞물림 호 각도 | φ_ex - φ_st |
| `direction_change_deg` | deg | 직전 세그먼트 대비 방향 전환각 | arccos(v1·v2) |
| `is_plunge` | bool | 플런지 이동 여부 | ΔZ<0 and ΔXY≈0 |
| `is_ramp` | bool | 경사 절입 여부 | ΔZ<0 and ΔXY>0 |
| `mrr_mm3_per_min` | mm³/min | 재료 제거율 | ae·ap·F |

> 정의: `app/models/model_interfaces.py` → `CuttingFeatures` 데이터클래스

---

## 5. 출력 스키마

### SpindleLoadPrediction (스핀들 부하 예측 결과)

| 필드 | 단위 | 설명 |
|------|------|------|
| `spindle_load_pct` | % | 스핀들 부하 백분율 |
| `cutting_force_ft` | N | 접선 절삭력 (평균) |
| `cutting_force_fr` | N | 반경 절삭력 (평균) |
| `cutting_force_fa` | N | 축방향 절삭력 (평균) |
| `force_x` | N | X방향 합력 |
| `force_y` | N | Y방향 합력 |
| `force_z` | N | Z방향 합력 |
| `torque_nm` | N·m | 스핀들 토크 |
| `power_w` | W | 스핀들 소비 전력 |
| `mrr` | mm³/min | 재료 제거율 |
| `aggressiveness` | 0~1 | 절삭 공격성 지수 |

### ChatterRiskPrediction (채터/진동 예측 결과)

| 필드 | 단위 | 설명 |
|------|------|------|
| `chatter_risk_score` | 0~1 | 채터 위험도 (0: 안전, 1: 위험) |
| `stability_margin` | - | SM=ap_lim/ap (>1: 안정) |
| `ap_limit` | mm | 임계 축방향 절입 깊이 |
| `tooth_passing_freq_hz` | Hz | 날 통과 주파수 |
| `dynamic_magnification` | - | 동적 배율 (FRF 기반) |
| `vibration_x_um` | μm | X축 예상 진동 진폭 |
| `vibration_y_um` | μm | Y축 예상 진동 진폭 |
| `vibration_z_um` | μm | Z축 예상 진동 진폭 |
| `resultant_vibration_um` | μm | 합성 진동 진폭 |
| `risk_factors` | dict | 상세 위험 인자 딕셔너리 |

---

## 6. 훈련 데이터 수집 전략

ML 모델로 교체하려면 다음 데이터 수집이 필요합니다:

1. **스핀들 부하 모델 훈련 데이터**:
   - 입력: CuttingFeatures (위 스키마)
   - 출력: 실측 스핀들 전류/전력, 실측 절삭력 (동력계)
   - 수집: 다양한 재료·공구·절삭 조건에서의 가공 실험

2. **채터 모델 훈련 데이터**:
   - 입력: CuttingFeatures + SpindleLoadPrediction
   - 출력: 실측 진동 가속도, 음향 방출 신호, 채터 발생 여부 라벨
   - 수집: 가속도계/마이크 부착 후 다양한 ap·ae 조합에서 실험

3. **핵심 가정**:
   - 현재 모델은 `ae`, `ap`를 NC 파일에서 근사 추출
   - 실제 ML 모델은 Z-맵 기반 정확한 engagement 계산을 권장

---

## 7. 인터페이스 파일

| 파일 | 역할 |
|------|------|
| `app/models/model_interfaces.py` | 추상 기저 클래스, 데이터 스키마 정의 |
| `app/models/cutting_conditions.py` | 피처 추출 (교체 불필요) |
| `app/simulation/machining_model.py` | 오케스트레이터 (교체 지점 주입부) |

---

## 8. 검증 체크리스트

ML 모델 교체 후 다음 항목을 검증하세요:

- [ ] `python -m app.main` 정상 실행
- [ ] `python -m pytest tests/` 기존 테스트 통과
- [ ] 알루미늄 테스트: 스핀들 부하 5~15% (n=3000, F=800, ae=50%, ap=5mm, 10mm 4날)
- [ ] 강재 테스트: 스핀들 부하 20~40% (동일 조건)
- [ ] 채터 SM > 1 (안전) / SM < 1 (위험) 구분 일치
- [ ] 진동 진폭이 절입 깊이에 비례하는 경향 확인

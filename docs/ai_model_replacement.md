# AI 기반 해석 모델 교체 가이드

이 문서는 현재의 수치적/공학적 가공 해석 모델을, 향후 데이터 기반 AI 모델로
교체할 때 어디를 수정하면 되는지 빠르게 파악할 수 있도록 정리한 문서입니다.

## 1. 교체의 중심 진입점

가장 먼저 볼 위치는 다음입니다.

- `app/simulation/machining_model.py`
- `app/ui/main_window.py`
- `app/services/report_service.py`
- `app/models/machining_result.py`

현재 구조에서 해석 실행의 실질적인 진입점은 아래 메서드입니다.

- `MachiningModel.analyze_toolpath(...)`

이 메서드는 전체 세그먼트를 순회하면서, 각 세그먼트에 대해 `_analyze_segment(...)`
를 호출하고, 결과를 `SegmentMachiningResult`로 정리한 뒤 `MachiningAnalysis`에
모아 반환합니다.

즉, AI 모델로 교체하더라도 UI와 저장 기능을 최대한 건드리지 않으려면
`analyze_toolpath(...)`의 반환 형식을 그대로 유지하는 것이 가장 안전합니다.

## 2. 가장 덜 깨지게 교체하는 방법

권장 방법은 `MachiningModel` 자체를 없애는 것이 아니라, 내부 예측기만
갈아끼울 수 있게 만드는 것입니다.

추천 순서:

1. `SegmentMachiningResult`를 AI 모델이 채울 수 있는 최소 공통 출력 형식으로 유지합니다.
2. `MachiningModel._analyze_segment(...)` 내부에서 공학식을 직접 계산하는 대신,
   AI 예측 함수나 별도 추론 클래스를 호출하도록 바꿉니다.
3. UI는 기존처럼 `MachiningAnalysis`만 받아서 표시하도록 유지합니다.

이 방식의 장점:

- `ToolInfoPanel`, `AnalysisPanel`, `ReportService`를 거의 그대로 재사용할 수 있습니다.
- CSV 저장 포맷이 유지됩니다.
- 수치 모델과 AI 모델을 설정으로 전환하기 쉬워집니다.

## 3. 실제 입력 피처를 만드는 위치

AI 모델 입력 피처를 만드는 데 가장 적합한 위치는 아래입니다.

- `app/simulation/machining_model.py`

특히 다음 정보는 이미 이 레이어에서 모두 모입니다.

- 공구 직경
- 날 수
- spindle speed
- feedrate
- AE / AP
- motion type
- plunge / ramp 여부
- 방향 전환각
- 소재 기반 engagement 정보
- 소재 계수 / 장비 강성 계수

따라서 AI 모델용 입력 벡터를 만들려면, `_analyze_segment(...)` 안에서
공학식을 계산하기 직전에 feature dict를 만들고, 그것을 AI 추론기로 넘기는 구조가 좋습니다.

예시 흐름:

1. 세그먼트에서 기하/공정 입력 추출
2. `feature_dict` 또는 `np.ndarray` 생성
3. AI 추론 호출
4. 반환값을 `SegmentMachiningResult`에 매핑

## 4. 교체 시 유지해야 하는 출력 계약

아래 필드는 UI와 CSV 저장에서 직접 사용하므로 유지하는 것이 좋습니다.

- `spindle_load_pct`
- `estimated_cutting_force`
- `radial_depth_ae`
- `axial_depth_ap`
- `chatter_risk_score`
- `estimated_force_x`
- `estimated_force_y`
- `estimated_force_z`
- `vibration_x_um`
- `vibration_y_um`
- `vibration_z_um`
- `resultant_vibration_um`
- `warning_messages`

이 필드들이 유지되면 아래 모듈은 큰 수정 없이 그대로 동작합니다.

- `app/ui/tool_info_panel.py`
- `app/ui/analysis_panel.py`
- `app/services/report_service.py`

## 5. UI에서 해석 모델을 고르는 위치

현재 해석 모델 생성은 아래에서 일어납니다.

- `app/ui/main_window.py`의 `_load_default_configs()`
- `create_machining_model_from_config(...)`

AI 모델을 붙일 때는 설정 파일에 예를 들어 아래처럼 추가하는 것이 좋습니다.

```yaml
machining:
  model_backend: physics
  ai_model_path: models/chatter_predictor.onnx
```

그 다음 `create_machining_model_from_config(...)`에서:

- `physics`면 현재 공학 모델 생성
- `ai`면 AI 추론기를 포함한 모델 생성

으로 분기하면 됩니다.

## 6. 추천하는 최소 리팩터링 구조

향후 교체를 쉽게 하려면 아래처럼 역할을 분리하는 것이 좋습니다.

- `SegmentFeatureBuilder`
  - 세그먼트와 소재 상태에서 입력 피처 생성
- `PhysicsMachiningPredictor`
  - 현재 공학식 기반 예측
- `AIMachiningPredictor`
  - 학습 모델 기반 예측
- `MachiningModel`
  - 위 예측기를 호출하고 결과를 `SegmentMachiningResult`로 정리

즉, 지금의 `MachiningModel`은 오케스트레이터 역할만 남기고,
실제 계산 엔진을 predictor 클래스로 분리하는 방향이 가장 좋습니다.

## 7. 학습 데이터 저장에 이미 활용할 수 있는 위치

이번에 추가된 CSV 저장 기능은 AI 학습 데이터셋 정리에 바로 활용할 수 있습니다.

관련 위치:

- `app/services/report_service.py`
  - `save_analysis_csv_bundle(...)`

특히 `*_segments.csv`에는 다음이 포함됩니다.

- 좌표 시작/끝점
- 공구 정보
- motion type
- spindle/feed
- AE/AP
- 부하/절삭력
- X/Y/Z 진동
- 채터 위험
- 경고 메시지

즉, 현재 수치 모델을 “라벨 생성기”처럼 사용해 초기 학습 데이터를 모으고,
나중에 실측 데이터로 라벨을 대체하는 흐름도 가능합니다.

## 8. 실제로 먼저 손대면 좋은 함수 순서

AI 전환 시 수정 우선순위는 아래 순서를 추천합니다.

1. `app/simulation/machining_model.py`
   - `_analyze_segment(...)`
   - `analyze_toolpath(...)`
2. `app/models/machining_result.py`
   - AI 출력 필드 추가가 필요할 때만 수정
3. `configs/simulation_options.yaml`
   - 모델 백엔드/모델 경로/정규화 파라미터 추가
4. `app/ui/main_window.py`
   - 설정 기반 모델 선택 연결
5. `app/services/report_service.py`
   - AI confidence, inference source 같은 메타데이터를 CSV에 추가

## 9. 요약

핵심은 아래 한 줄로 정리됩니다.

- `MachiningAnalysis` / `SegmentMachiningResult` 출력 형식을 유지한 채,
  `MachiningModel._analyze_segment(...)` 내부 계산 엔진만 AI 추론기로 교체하는 것이
  가장 안전하고 확장성이 좋습니다.

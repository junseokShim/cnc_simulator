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

## 빠른 시작

### 설치

```bash
pip install -r requirements.txt
```

### GUI 실행

```bash
python -m app.main
python -m app.main --file examples/simple_pocket.nc
```

### 헤드리스 검증

```bash
python -m app.main --headless --file examples/simple_pocket.nc
```

### 파이썬 코드에서 사용

```python
from app.parser.gcode_parser import GCodeParser
from app.verification.checker import VerificationChecker
from app.geometry.stock_model import StockModel
from app.models.machine import create_default_machine
import numpy as np

# NC 파일 파싱
parser = GCodeParser()
toolpath = parser.parse_file("examples/simple_pocket.nc")
print(f"파싱 완료: {len(toolpath.segments)}개 세그먼트")

# 검증 실행
machine = create_default_machine()
stock = StockModel(np.array([-60,-60,-30.]), np.array([60,60,0.]), 2.0)
checker = VerificationChecker()
warnings = checker.run_all_checks(toolpath, stock, machine, {})
print(f"경고: {len(warnings)}개")
```

## 테스트

```bash
pytest tests/ -v
```

## 문서

자세한 내용은 `docs/` 디렉토리를 참조하세요:
- [README.md](docs/README.md) - 상세 사용 설명서
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - 시스템 아키텍처

## 라이선스

MIT License

# Unreal Engine 5 연동

이 저장소의 `unreal/VericutViewer`는 NC 해석 결과를 Unreal Engine에서 표시하는
런타임 프로젝트입니다. 외부 상용 모델에 의존하지 않고 Engine 기본 메시로 3축
머시닝센터 외형, 테이블, 스톡, 공구와 경로를 절차적으로 구성합니다. 따라서 모델
코드는 이 프로젝트와 동일한 라이선스로 수정할 수 있습니다. 더 정밀한 외형은
오픈 하드웨어인 [ShapeOko CAD](https://github.com/shapeoko/ShapeOko)처럼 라이선스가
명시된 메시로 교체할 수 있지만, DN Solutions T4000의 제조사 CAD라고 오인해서는
안 됩니다.

## 실행

1. Python에서 UE 장면과 물리 결과를 생성합니다.

   ```bash
   ./venn/bin/python -m app.main \
     --file examples/simple_pocket.nc \
     --unreal-export Saved/vericut_scene.json
   ```

2. Unreal Engine 5.4에서 `unreal/VericutViewer/VericutViewer.uproject`를 엽니다.
   최초 실행 시 `VericutBridge` C++ 플러그인을 빌드합니다.
3. 빈 레벨에 `VericutMachiningActor`를 배치하고 `Scene File`에 생성된 JSON의 절대
   경로를 지정한 뒤 Details 패널의 **Load Scene**을 누릅니다.
4. Blueprint/Sequencer에서 `Set Playback Segment`를 호출하면 공구 위치, 절삭력,
   축 진동, 스핀들 부하와 채터 위험도가 해당 NC 블록 값으로 갱신됩니다.

## 배포 실행 파일

macOS에서는 다음 명령으로 Shipping 앱을 만듭니다.

```bash
./scripts/package_unreal_macos.sh
```

결과는 `dist/macos/VericutViewer-Mac-Shipping.app`과 Unreal 설치가 필요 없는
`VericutViewer-macOS-arm64-portable.zip`입니다. 앱 번들에는 엔진 런타임, Metal
셰이더, 플러그인, TBB 및 기본 장면 데이터가 포함됩니다.

Windows에서는 UE 5.4와 Visual Studio 2022가 설치된 Windows 머신에서 실행합니다.

```bat
scripts\package_unreal_windows.bat
```

결과는 `dist\windows\Windows\VericutViewer.exe`와 Unreal 설치가 필요 없는
`VericutViewer-Windows-portable.zip`입니다. `-prereqs` 옵션으로 필수 런타임도
스테이징됩니다. Unreal은 Mac 호스트에서
Win64 게임 바이너리를 교차 컴파일하지 않으므로 `.exe` 생성에는 Windows 빌드
호스트가 필요합니다.

macOS 패키지는 현재 ad-hoc 서명입니다. 다른 Mac에서 Gatekeeper가 차단하면 사용자가
Finder의 **우클릭 → 열기**를 최초 한 번 수행해야 합니다. 경고 없는 외부 배포에는
Apple Developer ID 서명과 `notarytool` 공증용 계정 정보가 필요합니다.

## 반영된 모델

Python이 소재 접촉을 먼저 판정한 뒤 각 세그먼트에 다음 값을 기록합니다.

- 기계론적 절삭력: Ft 및 Fx/Fy/Fz, 절삭 토크와 동력
- 스핀들 부하: 무부하 + 축 이송 + 절삭 부하
- 재료 제거율: `MRR = ap × ae × feed`
- 안정성 로브 기반 채터 위험과 X/Y/Z 진동 진폭
- 실제 소재 접촉 기반 ap/ae 및 RAPID/AIR_FEED/PLUNGE/CUTTING 상태

Unreal은 mm를 cm로 0.1배 변환합니다. Chaos 힘 단위 변환은 `1 N = 100 kg·cm/s²`를
사용하며, 공구가 Blueprint에서 `Simulate Physics`로 설정된 경우 `AddForce`에 전달합니다.
스톡과 머신 외형은 기본적으로 kinematic collision body입니다. `Force Visual Scale`은
시각적 과장을 위한 값이므로 계측 비교 시 1.0으로 설정하십시오.

## 재료 제거 표현과 정확도 한계

기본 플러그인은 절삭 구간을 계층형 인스턴스 메시로 누적 표시합니다. 이는 대형 NC
파일에서도 안정적이지만 실제 스톡 메시의 체적 불리언은 아닙니다. UE Geometry Script는
런타임 메시 구성과 불리언을 제공하지만 문서상 실험 기능이므로 생산 빌드의 기본 경로로
사용하지 않았습니다. 정확한 잔삭/언더컷 검증은 현재 Python Z-map(3축) 또는 향후 복셀/SDF
백엔드에서 수행해야 합니다.

Chaos는 충돌·마찰·감쇠·강체 제약을 담당합니다. 금속 절삭 계수, 공구 FRF, 안정성 로브를
Chaos가 자체 계산하지는 않으므로 해당 공학 모델은 Python에서 단일 진실 공급원으로
유지합니다. 이 구분은 같은 공식을 Python과 C++에서 중복 구현해 값이 갈라지는 문제를 막습니다.

참고: [Unreal Engine Physics](https://dev.epicgames.com/documentation/unreal-engine/physics-in-unreal-engine),
[Geometry Script Reference](https://dev.epicgames.com/documentation/unreal-engine/geometry-script-reference-in-unreal-engine?application_version=5.1).

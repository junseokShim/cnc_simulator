#include "VericutOrbitPawn.h"
#include "Camera/CameraComponent.h"
#include "Components/InputComponent.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"

AVericutOrbitPawn::AVericutOrbitPawn()
{
    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera")); SetRootComponent(Camera);
    AutoPossessPlayer = EAutoReceiveInput::Player0; UpdateCamera();
}
void AVericutOrbitPawn::SetupPlayerInputComponent(UInputComponent* I)
{
    I->BindAxisKey(EKeys::MouseX, this, &AVericutOrbitPawn::OrbitX);
    I->BindAxisKey(EKeys::MouseY, this, &AVericutOrbitPawn::OrbitY);
    I->BindAxisKey(EKeys::MouseWheelAxis, this, &AVericutOrbitPawn::Zoom);
}
void AVericutOrbitPawn::OrbitX(float V){ if (V && GetController<APlayerController>()->IsInputKeyDown(EKeys::RightMouseButton)){ Yaw += V*.35f; UpdateCamera(); } }
void AVericutOrbitPawn::OrbitY(float V){ if (V && GetController<APlayerController>()->IsInputKeyDown(EKeys::RightMouseButton)){ Pitch=FMath::Clamp(Pitch+V*.35f,-89.f,15.f); UpdateCamera(); } }
void AVericutOrbitPawn::Zoom(float V){ if(V){ Distance=FMath::Clamp(Distance-V*2.f,8.f,120.f); UpdateCamera(); } }
void AVericutOrbitPawn::SetPreset(int32 P){ if(P==0){Yaw=-90;Pitch=-89;} else if(P==1){Yaw=-52;Pitch=-28;} else {Yaw=-90;Pitch=0;} UpdateCamera(); }
void AVericutOrbitPawn::UpdateCamera(){ const FRotator R(Pitch,Yaw,0); SetActorLocation(-R.Vector()*Distance); SetActorRotation(R); }

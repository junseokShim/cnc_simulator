#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "VericutOrbitPawn.generated.h"
class UCameraComponent;
UCLASS()
class VERICUTBRIDGE_API AVericutOrbitPawn : public APawn
{
    GENERATED_BODY()
public:
    AVericutOrbitPawn();
    virtual void SetupPlayerInputComponent(UInputComponent* Input) override;
    void SetPreset(int32 Preset);
private:
    UPROPERTY() TObjectPtr<UCameraComponent> Camera;
    float Yaw = -52.f, Pitch = -28.f, Distance = 32.f;
    void OrbitX(float V); void OrbitY(float V); void Zoom(float V); void UpdateCamera();
};

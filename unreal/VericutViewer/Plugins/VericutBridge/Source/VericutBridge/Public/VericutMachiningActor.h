#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "VericutMachiningActor.generated.h"

class UHierarchicalInstancedStaticMeshComponent;
class UStaticMeshComponent;
class FJsonObject;
class FJsonValue;

UCLASS(BlueprintType)
class VERICUTBRIDGE_API AVericutMachiningActor : public AActor
{
    GENERATED_BODY()

public:
    AVericutMachiningActor();
    virtual void Tick(float DeltaSeconds) override;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Vericut") FFilePath SceneFile;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Vericut") float PathRadiusCm = 0.18f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Vericut") bool bBuildProceduralMachine = false;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Vericut|Physics") float ForceVisualScale = 0.01f;
    UPROPERTY(BlueprintReadOnly, Category="Vericut|Physics") FVector CurrentCuttingForceN = FVector::ZeroVector;
    UPROPERTY(BlueprintReadOnly, Category="Vericut|Physics") FVector CurrentVibrationUm = FVector::ZeroVector;
    UPROPERTY(BlueprintReadOnly, Category="Vericut|Physics") float CurrentSpindleLoadPct = 0.0f;
    UPROPERTY(BlueprintReadOnly, Category="Vericut|Physics") float CurrentChatterRisk = 0.0f;

    UFUNCTION(CallInEditor, BlueprintCallable, Category="Vericut") bool LoadScene();
    UFUNCTION(BlueprintCallable, Category="Vericut") bool LoadNCFile(const FString& FilePath);
    UFUNCTION(BlueprintCallable, Category="Vericut") bool LoadNCText(const FString& NCText);
    UFUNCTION(BlueprintCallable, Category="Vericut") bool SetPlaybackSegment(int32 SegmentIndex);
    void Play() { bPlaying = true; }
    void Pause() { bPlaying = false; }
    void Stop();
    void Step(int32 Delta);
    void SetPlaybackSpeed(float Value) { PlaybackSpeed = FMath::Clamp(Value, 0.1f, 10.0f); }
    int32 GetCurrentSegment() const { return CurrentSegment; }
    int32 GetSegmentCount() const { return Segments.Num(); }
    bool IsPlaying() const { return bPlaying; }
    FString GetStatusText() const;
    FString GetForceText() const;
    FString GetVibrationText() const;

protected:
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<USceneComponent> Root;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UHierarchicalInstancedStaticMeshComponent> RapidPath;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UHierarchicalInstancedStaticMeshComponent> CuttingPath;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UHierarchicalInstancedStaticMeshComponent> RemovedMaterial;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UStaticMeshComponent> Stock;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UStaticMeshComponent> Tool;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UStaticMeshComponent> ToolShank;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UStaticMeshComponent> ToolTip;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UHierarchicalInstancedStaticMeshComponent> ToolFlutes;
    UPROPERTY(VisibleAnywhere, Category="Vericut|Components") TObjectPtr<UHierarchicalInstancedStaticMeshComponent> VoxelStock;

private:
    TArray<TSharedPtr<FJsonObject>> Segments;
    int32 CurrentSegment = 0;
    bool bPlaying = false;
    float PlaybackSpeed = 1.0f;
    float PlaybackAccumulator = 0.0f;
    float SegmentProgress = 0.0f;
    float StockTopCm = 0.0f;
    FVector StockMinCm = FVector::ZeroVector;
    FVector StockMaxCm = FVector::ZeroVector;
    float ActiveToolRadiusCm = 0.5f;
    float ActiveToolLengthCm = 7.5f;
    float ActiveFluteLengthCm = 2.5f;
    int32 ActiveToolNumber = INDEX_NONE;
    float ActiveTipOffsetCm = 0.0f;
    UPROPERTY(Transient) TArray<TObjectPtr<UStaticMeshComponent>> MachineParts;
    bool LoadSceneJson(const FString& Text);
    void AddCylinder(UHierarchicalInstancedStaticMeshComponent* Component, const FVector& A, const FVector& B, float RadiusCm);
    void BuildMachineEnvelope();
    void RebuildVoxelStock(int32 ThroughSegment);
    void ConfigureTool(int32 ToolNumber);
    void UpdateToolPosition(const FVector& Tip);
    static FVector JsonVector(const TArray<TSharedPtr<FJsonValue>>& Values, float Scale = 0.1f);
};

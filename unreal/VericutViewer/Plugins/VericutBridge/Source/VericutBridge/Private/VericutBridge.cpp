#include "VericutMachiningActor.h"
#include "VericutOrbitPawn.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PointLight.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "Engine/GameViewportClient.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SMultiLineEditableTextBox.h"
#include "TimerManager.h"

class FVericutBridgeModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        WorldHandle = FWorldDelegates::OnPostWorldInitialization.AddRaw(
            this, &FVericutBridgeModule::OnWorldInitialized);
    }

    virtual void ShutdownModule() override
    {
        FWorldDelegates::OnPostWorldInitialization.Remove(WorldHandle);
    }

private:
    FDelegateHandle WorldHandle;
    TWeakObjectPtr<AVericutMachiningActor> ActiveSimulation;
    TWeakObjectPtr<AVericutOrbitPawn> OrbitCamera;
    TSharedPtr<SEditableTextBox> FilePathInput;
    TSharedPtr<SMultiLineEditableTextBox> NCInput;

    FText StatusText() const
    {
        return FText::FromString(ActiveSimulation.IsValid() ? ActiveSimulation->GetStatusText() : TEXT("No simulation"));
    }
    FText ForceText() const { return FText::FromString(ActiveSimulation.IsValid()?ActiveSimulation->GetForceText():TEXT("Cutting force -")); }
    FText VibrationText() const { return FText::FromString(ActiveSimulation.IsValid()?ActiveSimulation->GetVibrationText():TEXT("Spindle vibration -")); }

    void AddRuntimeUI(UWorld* World, AVericutMachiningActor* Simulation)
    {
        if (!World || !World->GetGameViewport()) return;
        ActiveSimulation = Simulation;
        const FString Sample = TEXT("G21\nG90\nT1 M6\nS6000 M3\nG0 X-35 Y-35 Z10\nG0 Z2\nG1 Z-2 F200\nG1 X35 Y-35 F800\nG1 X35 Y35\nG1 X-35 Y35\nG1 X-35 Y-35\nG0 Z10");
        TSharedRef<SWidget> Panel =
            SNew(SBorder).Padding(12).BorderBackgroundColor(FLinearColor(0.015f, 0.02f, 0.025f, 0.94f))
            [ SNew(SBox).WidthOverride(390).HeightOverride(620)
              [ SNew(SVerticalBox)
                + SVerticalBox::Slot().AutoHeight().Padding(0,0,0,8)[SNew(STextBlock).Text(FText::FromString(TEXT("VERICUT CNC CONTROL"))).Font(FCoreStyle::GetDefaultFontStyle("Bold", 18)).ColorAndOpacity(FLinearColor(0.1f,0.85f,0.7f))]
                + SVerticalBox::Slot().AutoHeight().Padding(0,2)[SAssignNew(FilePathInput, SEditableTextBox).HintText(FText::FromString(TEXT("NC file path (.nc/.tap/.cnc)")))]
                + SVerticalBox::Slot().AutoHeight().Padding(0,4)
                  [ SNew(SButton).Text(FText::FromString(TEXT("LOAD NC FILE"))).OnClicked_Lambda([this]() { const bool Ok = ActiveSimulation.IsValid() && ActiveSimulation->LoadNCFile(FilePathInput->GetText().ToString()); return FReply::Handled(); }) ]
                + SVerticalBox::Slot().AutoHeight().Padding(0,10,0,3)[SNew(STextBlock).Text(FText::FromString(TEXT("NC CODE INPUT")))]
                + SVerticalBox::Slot().FillHeight(1.0f)[SAssignNew(NCInput, SMultiLineEditableTextBox).Text(FText::FromString(Sample)).AutoWrapText(false)]
                + SVerticalBox::Slot().AutoHeight().Padding(0,6)
                  [ SNew(SButton).Text(FText::FromString(TEXT("PARSE / APPLY"))).OnClicked_Lambda([this]() { if (ActiveSimulation.IsValid()) ActiveSimulation->LoadNCText(NCInput->GetText().ToString()); return FReply::Handled(); }) ]
                + SVerticalBox::Slot().AutoHeight().Padding(0,5)
                  [ SNew(SHorizontalBox)
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("|<"))).OnClicked_Lambda([this](){ if (ActiveSimulation.IsValid()) ActiveSimulation->Stop(); return FReply::Handled(); })]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("<"))).OnClicked_Lambda([this](){ if (ActiveSimulation.IsValid()) ActiveSimulation->Step(-1); return FReply::Handled(); })]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("PLAY"))).OnClicked_Lambda([this](){ if (ActiveSimulation.IsValid()) ActiveSimulation->Play(); return FReply::Handled(); })]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("PAUSE"))).OnClicked_Lambda([this](){ if (ActiveSimulation.IsValid()) ActiveSimulation->Pause(); return FReply::Handled(); })]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT(">"))).OnClicked_Lambda([this](){ if (ActiveSimulation.IsValid()) ActiveSimulation->Step(1); return FReply::Handled(); })]
                  ]
                + SVerticalBox::Slot().AutoHeight().Padding(0,3)
                  [ SNew(SHorizontalBox)
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("TOP"))).OnClicked_Lambda([this](){if(OrbitCamera.IsValid())OrbitCamera->SetPreset(0);return FReply::Handled();})]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("ISO"))).OnClicked_Lambda([this](){if(OrbitCamera.IsValid())OrbitCamera->SetPreset(1);return FReply::Handled();})]
                    + SHorizontalBox::Slot().FillWidth(1)[SNew(SButton).Text(FText::FromString(TEXT("FRONT"))).OnClicked_Lambda([this](){if(OrbitCamera.IsValid())OrbitCamera->SetPreset(2);return FReply::Handled();})]
                  ]
                + SVerticalBox::Slot().AutoHeight().Padding(0,8)[SNew(STextBlock).Text_Lambda([this](){ return StatusText(); }).ColorAndOpacity(FLinearColor(0.5f,0.85f,1.0f))]
                + SVerticalBox::Slot().AutoHeight().Padding(0,2)[SNew(STextBlock).Text_Lambda([this](){ return ForceText(); }).ColorAndOpacity(FLinearColor(1.0f,0.72f,0.25f))]
                + SVerticalBox::Slot().AutoHeight().Padding(0,2)[SNew(STextBlock).Text_Lambda([this](){ return VibrationText(); }).ColorAndOpacity(FLinearColor(0.75f,0.55f,1.0f))]
              ]
            ];
        World->GetGameViewport()->AddViewportWidgetContent(SNew(SOverlay) + SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Fill).Padding(12)[Panel], 100);
    }

    void OnWorldInitialized(UWorld* World, const UWorld::InitializationValues)
    {
        if (!World || (World->WorldType != EWorldType::Game && World->WorldType != EWorldType::PIE)) return;
        World->GetTimerManager().SetTimerForNextTick([this, WeakWorld = TWeakObjectPtr<UWorld>(World)]()
        {
            UWorld* RuntimeWorld = WeakWorld.Get();
            if (!RuntimeWorld) return;
            AVericutMachiningActor* Simulation = RuntimeWorld->SpawnActor<AVericutMachiningActor>();
            FString ScenePath;
            if (!FParse::Value(FCommandLine::Get(), TEXT("VericutScene="), ScenePath))
                ScenePath = FPaths::ProjectContentDir() / TEXT("Data/vericut_scene.json");
            Simulation->SceneFile.FilePath = FPaths::ConvertRelativePathToFull(ScenePath);
            Simulation->LoadScene();
            FString NCPath;
            if (FParse::Value(FCommandLine::Get(), TEXT("VericutNC="), NCPath))
                Simulation->LoadNCFile(NCPath);
            if (FParse::Param(FCommandLine::Get(), TEXT("VericutAutoPlay")))
                Simulation->Play();
            AddRuntimeUI(RuntimeWorld, Simulation);

            AVericutOrbitPawn* Camera = RuntimeWorld->SpawnActor<AVericutOrbitPawn>(); OrbitCamera = Camera;
            if (APlayerController* Controller = RuntimeWorld->GetFirstPlayerController()) { Controller->Possess(Camera); Controller->bShowMouseCursor=true; Controller->SetInputMode(FInputModeGameAndUI()); }
            FTimerHandle CameraActivationTimer;
            RuntimeWorld->GetTimerManager().SetTimer(
                CameraActivationTimer,
                FTimerDelegate::CreateLambda([
                    WeakRuntimeWorld = TWeakObjectPtr<UWorld>(RuntimeWorld),
                    WeakCamera = TWeakObjectPtr<AVericutOrbitPawn>(Camera)]()
                {
                    if (UWorld* ActiveWorld = WeakRuntimeWorld.Get())
                        if (APlayerController* Controller = ActiveWorld->GetFirstPlayerController())
                            { Controller->Possess(WeakCamera.Get()); Controller->bShowMouseCursor=true; Controller->SetInputMode(FInputModeGameAndUI()); }
                }),
                0.5f, false);

            ADirectionalLight* Light = RuntimeWorld->SpawnActor<ADirectionalLight>(
                FVector::ZeroVector, FRotator(-45.0, -35.0, 0.0));
            Light->SetBrightness(5.0f);

            APointLight* FillLight = RuntimeWorld->SpawnActor<APointLight>(
                FVector(0.0, -80.0, 120.0), FRotator::ZeroRotator);
            FillLight->SetBrightness(18000.0f);
            FillLight->SetRadius(600.0f);
        });
    }
};

IMPLEMENT_MODULE(FVericutBridgeModule, VericutBridge)

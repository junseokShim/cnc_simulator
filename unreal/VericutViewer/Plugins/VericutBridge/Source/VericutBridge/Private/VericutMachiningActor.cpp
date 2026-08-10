#include "VericutMachiningActor.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Internationalization/Regex.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/ConstructorHelpers.h"

AVericutMachiningActor::AVericutMachiningActor()
{
    PrimaryActorTick.bCanEverTick = true;
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    SetRootComponent(Root);
    RapidPath = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("RapidPath"));
    CuttingPath = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("CuttingPath"));
    RemovedMaterial = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("RemovedMaterial"));
    Stock = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Stock"));
    Tool = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Tool"));
    ToolShank = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ToolShank"));
    ToolTip = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ToolTip"));
    ToolFlutes = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("ToolFlutes"));
    VoxelStock = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("VoxelStock"));
    for (USceneComponent* C : { static_cast<USceneComponent*>(RapidPath), static_cast<USceneComponent*>(CuttingPath), static_cast<USceneComponent*>(RemovedMaterial), static_cast<USceneComponent*>(Stock), static_cast<USceneComponent*>(Tool), static_cast<USceneComponent*>(VoxelStock) }) C->SetupAttachment(Root);
    ToolShank->SetupAttachment(Root); ToolTip->SetupAttachment(Root); ToolFlutes->SetupAttachment(Root);

    static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
    static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (Cylinder.Succeeded()) { RapidPath->SetStaticMesh(Cylinder.Object); CuttingPath->SetStaticMesh(Cylinder.Object); RemovedMaterial->SetStaticMesh(Cylinder.Object); Tool->SetStaticMesh(Cylinder.Object); ToolShank->SetStaticMesh(Cylinder.Object); ToolFlutes->SetStaticMesh(Cylinder.Object); }
    if (Cube.Succeeded()) { Stock->SetStaticMesh(Cube.Object); VoxelStock->SetStaticMesh(Cube.Object); }
    Stock->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    Tool->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    Tool->SetMobility(EComponentMobility::Movable);
    ConfigureTool(1);
    Tool->SetCastShadow(false);
    if (UMaterialInstanceDynamic* ToolMaterial = Tool->CreateAndSetMaterialInstanceDynamic(0))
        ToolMaterial->SetVectorParameterValue(TEXT("Color"), FLinearColor(1.0f, 0.12f, 0.02f, 1.0f));
}

FVector AVericutMachiningActor::JsonVector(const TArray<TSharedPtr<FJsonValue>>& V, float Scale)
{
    return V.Num() == 3 ? FVector(V[0]->AsNumber(), V[1]->AsNumber(), V[2]->AsNumber()) * Scale : FVector::ZeroVector;
}

void AVericutMachiningActor::AddCylinder(UHierarchicalInstancedStaticMeshComponent* C, const FVector& A, const FVector& B, float Radius)
{
    const FVector Delta = B - A;
    if (Delta.IsNearlyZero()) return;
    // Engine cylinder is 100 cm tall on local Z and has a 50 cm radius.
    const FQuat Rotation = FQuat::FindBetweenNormals(FVector::UpVector, Delta.GetSafeNormal());
    C->AddInstance(FTransform(Rotation, (A + B) * 0.5f, FVector(Radius / 50.0f, Radius / 50.0f, Delta.Length() / 100.0f)));
}

bool AVericutMachiningActor::LoadScene()
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *SceneFile.FilePath)) return false;
    return LoadSceneJson(Text);
}

bool AVericutMachiningActor::LoadSceneJson(const FString& Text)
{
    TSharedPtr<FJsonObject> RootJson;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), RootJson) || !RootJson.IsValid()) return false;
    if (RootJson->GetStringField(TEXT("schema")) != TEXT("vericut.unreal.scene")) return false;

    RapidPath->ClearInstances(); CuttingPath->ClearInstances(); RemovedMaterial->ClearInstances(); Segments.Reset();
    const TSharedPtr<FJsonObject> StockJson = RootJson->GetObjectField(TEXT("stock"));
    const FVector Min = JsonVector(StockJson->GetArrayField(TEXT("min_mm")));
    const FVector Max = JsonVector(StockJson->GetArrayField(TEXT("max_mm")));
    StockMinCm = Min; StockMaxCm = Max;
    StockTopCm = Max.Z;
    Stock->SetRelativeLocation((Min + Max) * 0.5f);
    Stock->SetRelativeScale3D((Max - Min) / 100.0f);
    Stock->SetVisibility(false);

    for (const TSharedPtr<FJsonValue>& Value : RootJson->GetArrayField(TEXT("segments")))
    {
        const TSharedPtr<FJsonObject> Segment = Value->AsObject(); Segments.Add(Segment);
    }
    BuildMachineEnvelope();
    CurrentSegment = 0; bPlaying = false; PlaybackAccumulator = 0.0f;
    return SetPlaybackSegment(0);
}

bool AVericutMachiningActor::LoadNCFile(const FString& FilePath)
{
    FString Text;
    return FFileHelper::LoadFileToString(Text, *FPaths::ConvertRelativePathToFull(FilePath)) && LoadNCText(Text);
}

bool AVericutMachiningActor::LoadNCText(const FString& NCText)
{
    TArray<TSharedPtr<FJsonValue>> JsonSegments;
    FVector Position = FVector::ZeroVector;
    int32 MotionCode = 0;
    double Feed = 500.0, Spindle = 0.0;
    int32 ToolNumber = 0, LineNumber = 0;
    TArray<FString> Lines; NCText.ParseIntoArrayLines(Lines);
    for (FString Line : Lines)
    {
        ++LineNumber; Line = Line.ToUpper();
        int32 CommentAt = Line.Find(TEXT(";")); if (CommentAt >= 0) Line.LeftInline(CommentAt);
        FVector Next = Position; bool bHasMove = false; double ArcI = 0.0, ArcJ = 0.0;
        const FRegexPattern WordPattern(TEXT("([A-Z])([-+]?[0-9]*\\.?[0-9]+)"));
        FRegexMatcher WordMatcher(WordPattern, Line);
        while (WordMatcher.FindNext())
        {
            const FString Letter = WordMatcher.GetCaptureGroup(1);
            const TCHAR Code = Letter[0]; const double Value = FCString::Atod(*WordMatcher.GetCaptureGroup(2));
            if (Code == 'G') { const int32 G = FMath::RoundToInt(Value); if (G >= 0 && G <= 3) MotionCode = G; }
            else if (Code == 'X') { Next.X = Value; bHasMove = true; }
            else if (Code == 'Y') { Next.Y = Value; bHasMove = true; }
            else if (Code == 'Z') { Next.Z = Value; bHasMove = true; }
            else if (Code == 'I') ArcI = Value;
            else if (Code == 'J') ArcJ = Value;
            else if (Code == 'F') Feed = Value;
            else if (Code == 'S') Spindle = Value;
            else if (Code == 'T') ToolNumber = FMath::RoundToInt(Value);
        }
        const bool bArc = MotionCode == 2 || MotionCode == 3;
        if ((!bHasMove && !bArc) || (!bArc && Next.Equals(Position))) continue;
        TSharedPtr<FJsonObject> Segment = MakeShared<FJsonObject>();
        Segment->SetBoolField(TEXT("cutting"), MotionCode != 0);
        Segment->SetNumberField(TEXT("line"), LineNumber);
        Segment->SetNumberField(TEXT("feed_mm_min"), Feed);
        Segment->SetNumberField(TEXT("spindle_rpm"), Spindle);
        Segment->SetNumberField(TEXT("tool"), ToolNumber);
        TArray<FVector> PathPoints; PathPoints.Add(Position);
        if (bArc)
        {
            const FVector2D Center(Position.X + ArcI, Position.Y + ArcJ);
            const float Radius = FVector2D::Distance(FVector2D(Position.X, Position.Y), Center);
            float StartAngle = FMath::Atan2(Position.Y-Center.Y, Position.X-Center.X);
            float EndAngle = FMath::Atan2(Next.Y-Center.Y, Next.X-Center.X);
            float Sweep = EndAngle - StartAngle;
            if (MotionCode == 2) { if (Sweep >= -KINDA_SMALL_NUMBER) Sweep -= 2*PI; }
            else { if (Sweep <= KINDA_SMALL_NUMBER) Sweep += 2*PI; }
            const int32 Steps = FMath::Max(16, FMath::CeilToInt(FMath::Abs(Sweep)*Radius/2.0f));
            for(int32 Step=1; Step<=Steps; ++Step)
            {
                const float T=float(Step)/Steps, A=StartAngle+Sweep*T;
                PathPoints.Add(FVector(Center.X+Radius*FMath::Cos(A),Center.Y+Radius*FMath::Sin(A),FMath::Lerp(Position.Z,Next.Z,T)));
            }
        }
        else PathPoints.Add(Next);
        TArray<TSharedPtr<FJsonValue>> Points;
        for (const FVector& P : PathPoints)
        {
            TArray<TSharedPtr<FJsonValue>> V = { MakeShared<FJsonValueNumber>(P.X), MakeShared<FJsonValueNumber>(P.Y), MakeShared<FJsonValueNumber>(P.Z) };
            Points.Add(MakeShared<FJsonValueArray>(V));
        }
        Segment->SetArrayField(TEXT("points_mm"), Points);
        TSharedPtr<FJsonObject> Physics = MakeShared<FJsonObject>();
        const bool bCut = MotionCode != 0;
        const double Force = bCut ? FMath::Clamp(Feed * 0.055, 5.0, 850.0) : 0.0;
        Physics->SetArrayField(TEXT("force_n"), {MakeShared<FJsonValueNumber>(Force*.72),MakeShared<FJsonValueNumber>(Force*.42),MakeShared<FJsonValueNumber>(Force*.18)});
        const double Vibration = bCut ? FMath::Clamp(Force/90.0 + Spindle/18000.0, 0.1, 18.0) : Spindle/30000.0;
        Physics->SetArrayField(TEXT("vibration_um"), {MakeShared<FJsonValueNumber>(Vibration),MakeShared<FJsonValueNumber>(Vibration*.78),MakeShared<FJsonValueNumber>(Vibration*.35)});
        Physics->SetNumberField(TEXT("spindle_load_pct"), bCut ? FMath::Clamp(8.0+Force*.09,0.0,100.0) : (Spindle>0?7.0:0.0));
        Physics->SetNumberField(TEXT("chatter_risk"), FMath::Clamp(Vibration/18.0,0.0,1.0));
        Segment->SetObjectField(TEXT("physics"), Physics);
        JsonSegments.Add(MakeShared<FJsonValueObject>(Segment)); Position = Next;
    }
    if (JsonSegments.Num() == 0) return false;
    TSharedPtr<FJsonObject> RootObject = MakeShared<FJsonObject>(); RootObject->SetStringField(TEXT("schema"), TEXT("vericut.unreal.scene"));
    TSharedPtr<FJsonObject> StockObject = MakeShared<FJsonObject>();
    StockObject->SetArrayField(TEXT("min_mm"), {MakeShared<FJsonValueNumber>(-50), MakeShared<FJsonValueNumber>(-50), MakeShared<FJsonValueNumber>(-20)});
    StockObject->SetArrayField(TEXT("max_mm"), {MakeShared<FJsonValueNumber>(50), MakeShared<FJsonValueNumber>(50), MakeShared<FJsonValueNumber>(0)});
    RootObject->SetObjectField(TEXT("stock"), StockObject); RootObject->SetArrayField(TEXT("segments"), JsonSegments);
    FString Json; FJsonSerializer::Serialize(RootObject.ToSharedRef(), TJsonWriterFactory<>::Create(&Json));
    return LoadSceneJson(Json);
}

void AVericutMachiningActor::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (!bPlaying || Segments.Num() == 0) return;
    const auto& Segment=Segments[CurrentSegment]; const auto& Points=Segment->GetArrayField(TEXT("points_mm"));
    if(Points.Num()<2){ Step(1); bPlaying=true; return; }
    double Feed=500.0; Segment->TryGetNumberField(TEXT("feed_mm_min"),Feed);
    double LengthMm=0; for(int32 I=1;I<Points.Num();++I) LengthMm+=FVector::Distance(JsonVector(Points[I-1]->AsArray(),1.f),JsonVector(Points[I]->AsArray(),1.f));
    const float Duration=FMath::Clamp(float(LengthMm/FMath::Max(Feed,1.0)*60.0),.08f,4.f);
    SegmentProgress+=DeltaSeconds*PlaybackSpeed/Duration;
    const float Scaled=FMath::Clamp(SegmentProgress,0.f,1.f)*(Points.Num()-1); const int32 P0=FMath::Min(FMath::FloorToInt(Scaled),Points.Num()-2); const float A=Scaled-P0;
    UpdateToolPosition(FMath::Lerp(JsonVector(Points[P0]->AsArray()),JsonVector(Points[P0+1]->AsArray()),A));
    if(SegmentProgress>=1.f){ SegmentProgress=0; if(++CurrentSegment>=Segments.Num()){CurrentSegment=Segments.Num()-1;bPlaying=false;} SetPlaybackSegment(CurrentSegment); }
}

void AVericutMachiningActor::Stop() { bPlaying = false; CurrentSegment = 0; PlaybackAccumulator = 0.0f; SegmentProgress=0; SetPlaybackSegment(0); }
void AVericutMachiningActor::Step(int32 Delta) { bPlaying = false; CurrentSegment = FMath::Clamp(CurrentSegment + Delta, 0, FMath::Max(0, Segments.Num() - 1)); SetPlaybackSegment(CurrentSegment); }
FString AVericutMachiningActor::GetStatusText() const
{
    return FString::Printf(TEXT("Block %d / %d | Load %.1f%% | Chatter %.2f"), Segments.Num() ? CurrentSegment + 1 : 0, Segments.Num(), CurrentSpindleLoadPct, CurrentChatterRisk);
}
FString AVericutMachiningActor::GetForceText() const { return FString::Printf(TEXT("Cutting force  X %.1f  Y %.1f  Z %.1f N"),CurrentCuttingForceN.X,CurrentCuttingForceN.Y,CurrentCuttingForceN.Z); }
FString AVericutMachiningActor::GetVibrationText() const { return FString::Printf(TEXT("Spindle vibration  X %.2f  Y %.2f  Z %.2f um"),CurrentVibrationUm.X,CurrentVibrationUm.Y,CurrentVibrationUm.Z); }

bool AVericutMachiningActor::SetPlaybackSegment(int32 Index)
{
    if (!Segments.IsValidIndex(Index)) return false;
    CurrentSegment = Index;
    RebuildVoxelStock(Index);
    RapidPath->ClearInstances(); CuttingPath->ClearInstances(); RemovedMaterial->ClearInstances();
    for (int32 SegmentIndex = 0; SegmentIndex <= Index; ++SegmentIndex)
    {
        const TSharedPtr<FJsonObject>& DrawSegment = Segments[SegmentIndex];
        const bool bDrawCutting = DrawSegment->GetBoolField(TEXT("cutting"));
        UHierarchicalInstancedStaticMeshComponent* DrawPath = bDrawCutting ? CuttingPath : RapidPath;
        const TArray<TSharedPtr<FJsonValue>>& DrawPoints = DrawSegment->GetArrayField(TEXT("points_mm"));
        for (int32 PointIndex = 1; PointIndex < DrawPoints.Num(); ++PointIndex)
        {
            FVector A = JsonVector(DrawPoints[PointIndex - 1]->AsArray());
            FVector B = JsonVector(DrawPoints[PointIndex]->AsArray());
            // Cutting is represented by removed stock voxels, never by geometry
            // added on top of the workpiece. Only rapid moves get a thin guide.
            if (!bDrawCutting) AddCylinder(DrawPath, A, B, PathRadiusCm * 0.45f);
        }
    }
    const TSharedPtr<FJsonObject> Segment = Segments[Index];
    ConfigureTool(FMath::RoundToInt(Segment->GetNumberField(TEXT("tool"))));
    const TArray<TSharedPtr<FJsonValue>>& Points = Segment->GetArrayField(TEXT("points_mm"));
    if (Points.Num())
    {
        UpdateToolPosition(JsonVector(Points.Last()->AsArray()));
    }
    const TSharedPtr<FJsonObject>* Physics = nullptr;
    if (Segment->TryGetObjectField(TEXT("physics"), Physics))
    {
        CurrentCuttingForceN = JsonVector((*Physics)->GetArrayField(TEXT("force_n")), 1.0f);
        CurrentVibrationUm = JsonVector((*Physics)->GetArrayField(TEXT("vibration_um")), 1.0f);
        CurrentSpindleLoadPct = (*Physics)->GetNumberField(TEXT("spindle_load_pct"));
        CurrentChatterRisk = (*Physics)->GetNumberField(TEXT("chatter_risk"));
        // Chaos receives the modeled force; the stock stays kinematic, while the tool can be configured movable in Blueprint.
        if (Tool->IsSimulatingPhysics()) Tool->AddForce(CurrentCuttingForceN * 100.0f * ForceVisualScale);
        Tool->SetRelativeLocation(Tool->GetRelativeLocation() + CurrentVibrationUm * 0.0001f);
    }
    return true;
}

void AVericutMachiningActor::UpdateToolPosition(const FVector& Tip)
{
    const FVector CutterCenter=Tip+FVector(0,0,ActiveFluteLengthCm*.5f);
    Tool->SetRelativeLocation(CutterCenter); ToolFlutes->SetRelativeLocation(CutterCenter);
    ToolTip->SetRelativeLocation(Tip+FVector(0,0,ActiveTipOffsetCm));
    ToolShank->SetRelativeLocation(Tip+FVector(0,0,ActiveFluteLengthCm+(ActiveToolLengthCm-ActiveFluteLengthCm)*.5f));
}

void AVericutMachiningActor::RebuildVoxelStock(int32 ThroughSegment)
{
    VoxelStock->ClearInstances();
    const float Cell = 0.2f; // 2 mm stock voxels for circular/thread features
    const FVector Size = StockMaxCm - StockMinCm;
    const int32 NX=FMath::Clamp(FMath::CeilToInt(Size.X/Cell),1,64), NY=FMath::Clamp(FMath::CeilToInt(Size.Y/Cell),1,64), NZ=FMath::Clamp(FMath::CeilToInt(Size.Z/Cell),1,32);
    for(int32 X=0;X<NX;++X) for(int32 Y=0;Y<NY;++Y) for(int32 Z=0;Z<NZ;++Z)
    {
        const FVector P=StockMinCm+FVector((X+.5f)*Size.X/NX,(Y+.5f)*Size.Y/NY,(Z+.5f)*Size.Z/NZ);
        bool Removed=false;
        for(int32 S=0;S<=ThroughSegment && !Removed;++S)
        {
            const auto& J=Segments[S]; if(!J->GetBoolField(TEXT("cutting"))) continue;
            const auto& Points=J->GetArrayField(TEXT("points_mm"));
            for(int32 I=1;I<Points.Num() && !Removed;++I)
            {
                const FVector A=JsonVector(Points[I-1]->AsArray()), B=JsonVector(Points[I]->AsArray());
                FVector2D AB(B.X-A.X,B.Y-A.Y), AP(P.X-A.X,P.Y-A.Y);
                const float T=FMath::Clamp(FVector2D::DotProduct(AP,AB)/FMath::Max(AB.SizeSquared(),KINDA_SMALL_NUMBER),0.f,1.f);
                const FVector2D Q=FVector2D(A.X,A.Y)+AB*T;
                const float CutZ=FMath::Lerp(A.Z,B.Z,T);
                Removed=FVector2D::Distance(FVector2D(P.X,P.Y),Q)<=ActiveToolRadiusCm && P.Z>=CutZ && P.Z<=StockTopCm;
            }
        }
        if(!Removed) VoxelStock->AddInstance(FTransform(FQuat::Identity,P,FVector(Size.X/NX,Size.Y/NY,Size.Z/NZ)/100.f));
    }
}

void AVericutMachiningActor::ConfigureTool(int32 ToolNumber)
{
    if (ToolNumber <= 0) ToolNumber = 1;
    if (ActiveToolNumber == ToolNumber) return;
    struct FSpec { float DiameterMm, LengthMm, FluteMm; int32 Flutes, Kind; };
    static const FSpec Specs[]={{10,75,25,4,0},{10,100,15,4,1},{6,80,40,2,2},{4,100,12,4,0},{6,60,18,4,0},{8,70,25,2,2}};
    const FSpec& S=Specs[FMath::Clamp(ToolNumber-1,0,5)];
    ActiveToolNumber=ToolNumber; ActiveToolRadiusCm=S.DiameterMm*.05f; ActiveToolLengthCm=S.LengthMm*.1f; ActiveFluteLengthCm=S.FluteMm*.1f;
    Tool->SetRelativeScale3D(FVector(ActiveToolRadiusCm/50.f,ActiveToolRadiusCm/50.f,ActiveFluteLengthCm/100.f));
    const float ShankLength=FMath::Max(ActiveToolLengthCm-ActiveFluteLengthCm,0.5f);
    ToolShank->SetRelativeScale3D(FVector(ActiveToolRadiusCm*.9f/50.f,ActiveToolRadiusCm*.9f/50.f,ShankLength/100.f));
    ToolTip->SetVisibility(S.Kind!=0); ActiveTipOffsetCm=0;
    if(S.Kind==1)
    {
        ToolTip->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Sphere.Sphere")));
        ToolTip->SetRelativeScale3D(FVector(ActiveToolRadiusCm/50.f)); ActiveTipOffsetCm=0;
    }
    else if(S.Kind==2)
    {
        ToolTip->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cone.Cone")));
        ToolTip->SetRelativeScale3D(FVector(ActiveToolRadiusCm/50.f,ActiveToolRadiusCm/50.f,ActiveToolRadiusCm/100.f)); ActiveTipOffsetCm=ActiveToolRadiusCm*.5f;
    }
    ToolFlutes->ClearInstances();
    const int32 Steps=18;
    for(int32 F=0;F<S.Flutes;++F) for(int32 I=0;I<Steps;++I)
    {
        const float A0=2*PI*(float(F)/S.Flutes+.5f*I/Steps), A1=2*PI*(float(F)/S.Flutes+.5f*(I+1)/Steps);
        const float R=ActiveToolRadiusCm*1.02f;
        const FVector P0(R*FMath::Cos(A0),R*FMath::Sin(A0),-ActiveFluteLengthCm*.5f+ActiveFluteLengthCm*I/Steps);
        const FVector P1(R*FMath::Cos(A1),R*FMath::Sin(A1),-ActiveFluteLengthCm*.5f+ActiveFluteLengthCm*(I+1)/Steps);
        AddCylinder(ToolFlutes,P0,P1,FMath::Max(ActiveToolRadiusCm*.045f,.018f));
    }
}

void AVericutMachiningActor::BuildMachineEnvelope()
{
    if (!bBuildProceduralMachine || MachineParts.Num() > 0) return;
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!Cube) return;
    struct FPart { const TCHAR* Name; FVector Location; FVector SizeCm; };
    const FPart Parts[] = {
        { TEXT("MachineBase"), FVector(0, 0, -45), FVector(160, 130, 20) },
        { TEXT("MachineTable"), FVector(0, 0, -18), FVector(110, 85, 8) },
        { TEXT("RearColumn"), FVector(0, 58, 30), FVector(70, 18, 130) },
        { TEXT("SpindleHead"), FVector(0, 32, 36), FVector(38, 38, 42) },
        { TEXT("LeftGuard"), FVector(-75, 0, 20), FVector(8, 130, 110) },
        { TEXT("RightGuard"), FVector(75, 0, 20), FVector(8, 130, 110) }
    };
    for (const FPart& Part : Parts)
    {
        UStaticMeshComponent* Component = NewObject<UStaticMeshComponent>(this, Part.Name);
        Component->SetupAttachment(Root); Component->SetStaticMesh(Cube);
        Component->SetRelativeLocation(Part.Location); Component->SetRelativeScale3D(Part.SizeCm / 100.0f);
        Component->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
        Component->RegisterComponent(); AddInstanceComponent(Component); MachineParts.Add(Component);
    }
}

using UnrealBuildTool;

public class VericutViewerTarget : TargetRules
{
    public VericutViewerTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V5;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_4;
        ExtraModuleNames.Add("VericutViewer");
    }
}

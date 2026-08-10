using UnrealBuildTool;

public class VericutViewerEditorTarget : TargetRules
{
    public VericutViewerEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V5;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_4;
        ExtraModuleNames.Add("VericutViewer");
    }
}

using UnrealBuildTool;

public class VericutViewer : ModuleRules
{
    public VericutViewer(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "VericutBridge" });
    }
}

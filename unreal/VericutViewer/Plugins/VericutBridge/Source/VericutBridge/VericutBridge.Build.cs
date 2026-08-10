using UnrealBuildTool;

public class VericutBridge : ModuleRules
{
    public VericutBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "Json", "JsonUtilities", "PhysicsCore", "Slate", "SlateCore", "UMG" });
    }
}

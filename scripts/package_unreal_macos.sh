#!/bin/zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
engine_dir="${UE_ENGINE_DIR:-/Users/Shared/Epic Games/UE_5.4}"
project="$repo_dir/unreal/VericutViewer/VericutViewer.uproject"
output="$repo_dir/dist/macos"

"$repo_dir/venn/bin/python" -B -m app.main \
  --file "$repo_dir/examples/simple_pocket.nc" \
  --unreal-export "$repo_dir/unreal/VericutViewer/Content/Data/vericut_scene.json"

"$engine_dir/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun \
  -project="$project" -noP4 -platform=Mac -clientconfig=Shipping \
  -build -cook -stage -pak -archive -archivedirectory="$output" -prereqs

stage_app="$repo_dir/unreal/VericutViewer/Saved/StagedBuilds/Mac/VericutViewer-Mac-Shipping.app"
final_app="$output/VericutViewer-Mac-Shipping.app"
ditto "$stage_app" "$final_app"
tbb_dir="$final_app/Contents/UE/Engine/Binaries/ThirdParty/Intel/TBB/Mac"
mkdir -p "$tbb_dir"
ditto "$engine_dir/Engine/Binaries/ThirdParty/Intel/TBB/Mac/libtbb.dylib" "$tbb_dir/libtbb.dylib"
ditto "$engine_dir/Engine/Binaries/ThirdParty/Intel/TBB/Mac/libtbbmalloc.dylib" "$tbb_dir/libtbbmalloc.dylib"
codesign --force --deep --sign - "$final_app"
codesign --verify --deep --strict "$final_app"
portable_zip="$output/VericutViewer-macOS-arm64-portable.zip"
ditto -c -k --sequesterRsrc --keepParent "$final_app" "$portable_zip"

print "macOS package: $final_app"
print "Portable ZIP: $portable_zip"

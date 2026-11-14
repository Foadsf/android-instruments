# Builds halprobe (arm64 and armv7) and the camera shim (armv7 and arm64) with the NDK.
# Output: build/android-native/<abi>/. Usage: pwsh android/camshim/build.ps1
$ErrorActionPreference = 'Stop'
$repo = Resolve-Path "$PSScriptRoot/../.."
$ndk = Get-ChildItem "$env:ANDROID_HOME/ndk" -Directory | Sort-Object Name | Select-Object -Last 1
$bin = "$($ndk.FullName)/toolchains/llvm/prebuilt/windows-x86_64/bin"
$flags = @('-O2', '-Wall', '-Wextra', '-Werror', '-std=c11', "-I$repo/android/hal_common", "-I$repo/core/camera_idmap/include")
$targets = @{ 'arm64-v8a' = 'aarch64-linux-android29-clang.cmd'; 'armeabi-v7a' = 'armv7a-linux-androideabi29-clang.cmd' }
foreach ($abi in $targets.Keys) {
    $out = "$repo/build/android-native/$abi"
    New-Item -ItemType Directory -Force $out | Out-Null
    $cc = "$bin/$($targets[$abi])"
    & $cc @flags -o "$out/halprobe" "$repo/android/halprobe/halprobe.c" -ldl
    if ($LASTEXITCODE) { throw "halprobe ($abi) failed" }
    & $cc @flags "-I$repo/core/camera_params/include" -o "$out/hal1probe" "$repo/android/hal1probe/hal1probe.c" `
        "$repo/android/hal1probe/probe_window.c" "$repo/core/camera_params/camera_params.c" -ldl -lnativewindow
    if ($LASTEXITCODE) { throw "hal1probe ($abi) failed" }
    & $cc @flags -shared -fPIC -fvisibility=hidden "-I$repo/core/camera_params/include" `
        "-I$repo/core/camera_bridge_queue/include" -o "$out/camera.instruments_shim.so" `
        "$repo/android/camshim/camera_tele_shim.c" "$repo/core/camera_idmap/camera_idmap.c" `
        "$repo/android/camshim/bridge.c" "$repo/android/camshim/bridge_meta.c" "$repo/android/camshim/bridge_hal1.c" `
        "$repo/android/camshim/bridge_pool.c" "$repo/android/camshim/bridge_gralloc1.c" `
        "$repo/android/camshim/bridge_window.c" "$repo/android/camshim/bridge_tele.c" `
        "-I$repo/core/yuv_copy/include" "$repo/core/yuv_copy/yuv_copy.c" `
        "$repo/core/camera_bridge_queue/bridge_queue.c" "$repo/core/camera_params/camera_params.c" `
        -llog -ldl -lnativewindow
    if ($LASTEXITCODE) { throw "camera shim ($abi) failed" }
    Write-Output "built $abi"
}

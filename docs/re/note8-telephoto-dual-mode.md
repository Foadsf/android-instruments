# Note8 telephoto: why it cannot stream through two Camera2 sessions (static analysis)

Libraries studied, pulled from the Note8 (SM-N950F, LineageOS 20.0-20250628-UNOFFICIAL-greatlte), arm64 builds:

| File on the phone | SHA-256 |
|---|---|
| `/system/lib64/libexynoscamera3.so` | `7bf826cf19e11a21bc65ed5a6ccb25f3b6ebe9d6b8cf1ea0ed2f7d950c26d141` |
| `/system/lib64/hw/camera.vendor.universal8895.so` | `d04f5d998cd848197a5a0dde23fe4628d285f74c9faadcdc8f6a896eb206e0b5` |

The phone's camera provider is 32-bit and loads the `/system/lib` copies; the arm64 copies were analysed because they are easier to read. Any patch must be re-located in the 32-bit (Thumb-2) library. Tools: NDK `llvm-objdump`, `llvm-nm`, `llvm-readelf`, and `tools/re/xref.py` / `tools/re/elfstr.py` (string cross-references, function extraction). Addresses below are arm64 virtual addresses.

## Findings (read in the disassembly)

1. **Dual mode starts by itself.** When camera 3 (telephoto) is initialised while camera 0 is open, the vendor module logs `camera(3) set dual mode` (seen on the phone in run 082507-895d) and `ExynosCamera3::setDualMode(bool)` (0xca240) is the entry point.
2. **Binning is off in dual mode.** `ExynosCamera3Parameters::getBinningMode()` (0xdbfb0), with its virtual calls resolved through the vtable at 0x14e400:
   ```
   if sensor has no binning table                 -> false
   if getCameraId() == 1 && getUseCompanion()     -> false
   if getDualMode()                               -> false
   if mode field (+0x8d9c) in {1, 2, 4}           -> true
   return field +0x9180 == 1                      // set in the constructor from
                                                  // sys.cameramode.cam_binning == "1"
   ```
   `checkBinningProperty()` (0xba878) reads `sys.cameramode.cam_binning`, default `"0"`. The property cannot help the telephoto, which only runs in dual mode.
3. **Raw (FLITE) buffers are 16-bit, by a hard-wired choice.** `ExynosCamera3::m_setBuffers()` (0xd6488) sizes raw buffers with `getBayerFormat(getUsePureBayerReprocessing() ? 0 : 6)`; pipe 0 is `BYR2` (16 bit), pipe 6 is `BG10` (packed 10 bit). `getUsePureBayerReprocessing()` (0xe2c68) evaluates three checks, discards them, stores 1 and returns true. Hence 4032 x 2 x 3024 = 24,385,536 bytes per raw buffer, exactly the size in the out-of-memory log.
4. **Buffer counts are fixed per camera.** `m_setBuffers` allocates 7 raw buffers, all from the reserved camera pool (`setContigBufCount(7)`, 0xd66a8), then the 3AA/ISP buffers with 2 reserved (7 when the camera ID field `+0xc8` is 1). Counts come from the active config table (`[this+0x290]`, fields `+0x394`/`+0x398`). There is no dual-mode branch.
5. **The pool holds about 15 such buffers.** The kernel's ION dump at the failure listed 15 allocations of 24,387,584 bytes in the `camera` heap (id 10) when the telephoto's 7th raw buffer failed. Two back cameras as Camera2 opens them need at least 16.

## Inference (not proven)

Samsung's own 2x mode (Android 8, stock firmware) went through the HAL1 dual entry points in the vendor module (`HAL_camera_device_dual_*`), which this ROM's HAL3 path never calls. Whether Android 13's camera service still accepts HAL1 devices was not checked.

## What would make two cameras fit (each needs a patched 32-bit `libexynoscamera3.so`, bind-mounted like the shim, gone at reboot)

| Option | Change | Memory, two cameras | Risk |
|---|---|---|---|
| A | Fewer raw buffers per camera (7 -> 5) in the config table or the allocation call | 5 + 5 + 2 + 2 = 14 buffers <= 15 | Shallower pipeline; drops frames under load; location of the table value not yet found |
| B | `getUsePureBayerReprocessing()` returns false | raw buffers 15.2 MB instead of 24.4 MB | Switches every camera to the dirty-bayer reprocessing path, which this build may never exercise |

Every wrong guess can panic the kernel, as both device attempts on 2026-11-14 did.

## Option A tried (2026-11-14, run 084854-f68b)

32-bit patch sites (file offset = vaddr - 0x4000): `0x8e192` `movs r0,#7` in `m_setConfigInform` (stores to the config field read back at `+0x388`) and `0x9e52c` `movs r1,#7` before `setContigBufCount` in `m_setBuffers`, both set to 5. Result on the phone: both cameras' buffers allocated (memory problem solved), then `SetMasterInformation wrong camera type(0)` from the ISP firmware wrapper and a kernel panic from `fimc_is_gw0`.

## Next wall: master/follower setup for the ISP firmware (studied 2026-11-14)

1. **The firmware's field.** Per-frame control metadata carries `camera2_uctl.masterCam`, of type `enum aa_cameratype { AA_CAMERATYPE_SINGLE = 1, AA_CAMERATYPE_WIDE, AA_CAMERATYPE_TELE }` (GPL kernel header `fimc-is-metadata.h`, read from LineageOS `android_kernel_samsung_universal9810`, the same `fimc-is2` driver family; the Note8's own kernel source was not read). There is no value 0, so `SetMasterInformation wrong camera type(0)` means the field was never set.
2. **The HAL3 library never sets it.** `setMetaCtlMasterCam(camera2_shot_ext*, aa_cameratype)` (0x5f878) stores at `shot_ext + 0x4e6c`; it has no caller in `libexynoscamera3.so`, the vendor module, or the HAL1 library, and nothing else writes that offset.
3. **Samsung's dual camera lives in the HAL1 library.** `/system/lib64/libexynoscamera.so` contains `ExynosCamera1DualParameters` (master fallback by lux and distance), `ExynosCamera1Parameters::setZoomLevel` ("wake up masterCamera/slaveCamera"), the `PIPE_SYNC_SWITCHING` and `PIPE_SYNC_REPROCESSING` frame-sync pipes, `ExynosCameraDualFrameSelector` and `ExynosCameraFusionWrapper`. The HAL3 library has only the `setDualMode` flag: no sync pipes, no master selection.
4. **Android 13 does not use HAL1 here.** During the first installed run the camera service logged `Camera provider legacy/0 says an unknown camera device@1.0/legacy/2 now has torch status 0`: the provider offers the HAL1 (`device@1.0`) interface, the camera service registered only the HAL3 one. (Observed message; the camera service source was not read.)

## Conclusion

Streaming the Note8 telephoto on this ROM is not a matter of a patch or a setting. Samsung implemented wide + tele only in the HAL1 path, which this camera service does not use, and the HAL3 path lacks the frame-sync pipes and master selection the firmware requires once both sensors run. What would work is a HAL1-to-HAL3 adapter inside the camera shim: open the vendor HAL1 dual device (`open_legacy`, `dual_camera_mode` parameters, preview callbacks) and present its frames as a HAL3 camera. That is a camera-HAL implementation project, weeks rather than days, with every bring-up step able to panic the phone.

The earlier chats (`chats/`) do not cover the HAL1 dual path or `masterCam`; their `libexynoscamera3.so` analysis was of a different, S6-era library.

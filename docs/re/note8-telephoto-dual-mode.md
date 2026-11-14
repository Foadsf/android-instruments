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

## Next wall: master/follower setup for the ISP firmware

The firmware wants to be told which camera is the master and which the follower. Samsung's code path that does this is not reached by two independent HAL3 sessions. Static next step (no device risk): find where `libexynoscamera3.so` and the vendor module set the dual master/slave information (search for the camera-type field passed to the firmware, the `dual` V4L2 controls, and what `setDualMode(true)` changes beyond the flag), and whether camera 0 must also be switched into dual mode as master.

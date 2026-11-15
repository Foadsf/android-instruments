# Unit: align (first revision: homography, for hand-held bursts)

- **Stage:** 3.4 of the plan, pulled forward for Stage 8 fusion
- **Path:** `core/align/` (C), host CLI `core/align/cli/`, evaluator `tools/fusion/align_eval.py`
- **Ported from:** android-microscope `imaging/Align.kt` (`coarseSearch`, `refine`: pyramid, integer search at the top level, inverse-compositional Lucas-Kanade with a Huber weight and a brightness term). It is extended from four similarity parameters to the eight of a homography, one function at a time. microtopos `registration.py` is the reference for conventions only.

## Why this shape

`burst-merge.md` run 3 showed what fusion needs from alignment. In a bright, sharp scene, a 0.07 px shift between the two halves of a burst was half of the noise left after merging 16 frames. So a 16-frame merge of camera 0 needs the frames' relative positions known to a few hundredths of a pixel.

The first draft assumed a phone on a stand, so a global translation. Foad holds the phone by hand for every capture (since 2026-11-15). The six hand-held 16-frame bursts of the scale runs (`190102-7738`, `192124-73b2`: camera 0, OIS off, the screen board at 10 to 20 cm) measure what the motion really is. The board's 63 corners are fitted from each frame to frame 0 (pixel RMS of the fit residual; median over the frames of a burst):

| Bursts | Shift within the burst | After translation | After similarity | After homography |
|---|---|---|---|---|
| 2 held steady | 3 to 8 px (max 14) | 0.33 to 0.42 px (max 0.88) | 0.18 to 0.21 px | 0.12 px (max 0.15) |
| 4 drifting | 9 to 45 px (max 53) | 1.7 to 17.6 px | 0.25 to 0.72 px | 0.11 to 0.21 px |

- Translation leaves at least 15x the fusion budget even on the steadiest bursts. Rolls reach 0.36°, and scale changes reach 18 % when the hand moves along the axis.
- A homography brings the residual to 0.12 px on still and moving bursts alike. That is about the corner-detection noise on this screen at 10 to 20 cm, so motion not explained by a homography (rolling shutter, depth) is not visible above 0.1 px here. Whether it matters at 0.02 px is for this unit's own residuals to show.
- So the first revision is a **homography**, with a capture range of at least ±64 px. The scene is near-planar (a specimen at 10 to 20 cm, a screen, a page), which is where a homography is exact. Rolling-shutter and lens-distortion terms are a later revision if the device residuals show structure along the rows.

This unit only **estimates** the shift. Moving the pixels is a separate unit, `warp`, because resampling changes the noise the merge is judged on. Bilinear interpolation at a half-pixel shift keeps only 25 % of white-noise variance, and bicubic about 41 %. That would show up as a "fusion gain" that is really just smoothing. `warp` therefore needs its own contract with a noise-preserving resampler (see "Next" below).

## Contract

- **Input:**
  - two 8-bit luma planes of the same size (any row stride ≥ width, at least 64x64): the reference R and the moving image M;
  - an optional starting homography (default identity), for example from the gyroscope: H0 = K R K⁻¹, with R integrated from `imu.csv` between the two frame stamps. That is the later `motion_prior` unit; this unit only accepts the guess.
- **Output:**
  - a homography `H` (3x3, h33 = 1) in pixels, such that `M(H·x) ≈ g · R(x) + o` over the overlap;
  - g and o are a photometric gain and offset estimated alongside (`burst-merge.md` run 2 showed the per-frame gain wandering by ±4 % on camera 0). With H a pure translation by (dx, dy), positive dx means the content moved right in M.
  - Also returned:
    - the RMS residual;
    - the number of sample pixels used;
    - whether the fit converged;
    - the displacement H·x − x and its standard error at five control points: the image centre and the four points at a quarter of the width and height in from the corners. The standard error comes from the final fit's covariance, so a caller can tell a precise warp from a guess.
- **Method:**
  - Gaussian pyramid down to about 48 px on the short side.
  - At the top level, an exhaustive integer translation search of ±6 px around the starting guess, about ±130 px at full resolution on the 1440x1080 frames.
  - Inverse-compositional Lucas-Kanade from the top down: translation (2 parameters) on the coarse levels, similarity (4) on the middle levels and homography (8) on the two finest, each with gain and offset, a Huber weight and bicubic sampling of M. The model is raised only once the coarser one has converged.
  - Stops when the largest control-point update falls below 0.001 px, or after 30 iterations at the top level and 10 below.
- **Refusals (error codes, no warp returned):**
  - size mismatch, too small, NULL plane or short stride;
  - an untextured overlap: a control-point standard error above 0.05 px, or fewer than 500 textured samples. A featureless scene gives a code, never a number (the dark-scene NCC lesson from `microscope-live.md`);
  - an overlap below 50 % of the frame.
- **Host CLI** `align_cli --size WxH <ref> <moving> [--init h11,...,h32]`: the inputs are raw 8-bit luma or I420 files (only the first w·h bytes are read). It prints one JSON line. Exit codes: 0 done, 2 usage, 3 file error, 4 refused.
- **Evaluator** `tools/fusion/align_eval.py <burst_dir>`: aligns every frame to frame 0, runs the device checks below, and writes `results/<model>/align_<date>_<run>_cam<id>.json`. No image goes into the repository.

## Oracle

- **Synthetic, independent of the code's interpolator:**
  - The texture is analytic: a sum of about 200 sinusoids of random direction, phase and amplitude, band-limited below 0.35 cycles per pixel.
  - It is evaluated in closed form at exactly warped coordinates, R(x) = T(x) and M(x) = T(H⁻¹·x), pixel-integrated by 4x4 supersampling, so no interpolator touches the truth.
  - Independent Gaussian noise is added, and the result is quantised to 8 bits.
  - Truth is the requested H. The error is the displacement error at the five control points.
- **Device, exact truth on real frames: the decimation pair.**
  - Take one real frame and blur it with a Gaussian (σ = 1 px, to limit aliasing). The blur is the same everywhere, so it does not move anything.
  - Keep its even columns as R and its odd columns as M. Since M(x) = full(2x + 1) and R(x) = full(2x), the true warp in decimated pixels is exactly a translation by (−0.5, 0) by this unit's convention, from the sampling geometry alone.
  - The same with rows gives (0, −0.5), and with both gives (−0.5, −0.5).
  - The full homography is fitted, so the six non-translation parameters must come out zero.
  - The texture and the ISP's noise are real; R and M share no pixel. Run on frame 0 of every judged burst.
- **Device, independent implementation:** OpenCV `findTransformECC` (MOTION_HOMOGRAPHY, Gaussian filter 3, started from a corner-free ORB + RANSAC homography), on the same frame pairs as this unit (each burst frame against frame 0), compared at the five control points. OpenCV shares no code with this unit.
- **Device, independent measurement (recorded, not judged):** on the screen-board bursts, the homography fitted to the 63 detected ChArUco corners, compared at the control points. The corners' own noise is about 0.12 px, so this checks agreement to that floor only.
- **Device, consistency:** closure H(0→k)⁻¹ · H(j→k) · H(0→j) ≈ I over frame triples, as control-point displacement. This only checks that the unit is consistent with itself, so it never stands as proof of accuracy.

## Thresholds (declared before the first run)

| Check | Threshold | Source of the number |
|---|---|---|
| synthetic, 512x512, noise σ = 2 LSB, 50 hand-held-like homographies: shift uniform in ±20 px, roll ±0.4°, scale ±2 %, perspective terms giving ±1 px at the corners | control-point RMS error ≤ 0.01 px per axis, max ≤ 0.03 px | 0.07 px between halves broke a 16-frame merge (`burst-merge.md` run 3); 0.01 px keeps the motion share far below its 5 % gate. The plan's 0.05 px (3.4) is too loose for fusion. The ranges cover the steady and most drifting hand-held bursts measured above |
| synthetic, noise σ = 8 LSB | RMS ≤ 0.03 px | 4× the noise, about 4× the error (the error scales with noise over gradient) |
| synthetic capture range | shifts up to ±64 px, and scale ±10 %, recovered to the same accuracy | the largest hand-held drift measured was 53 px and 18 % in scale; beyond ±10 % the burst is not fusion material, and a refusal or non-convergence is an acceptable outcome there |
| synthetic, gain 1.04 and offset +5 on M | accuracy unchanged (RMS ≤ 0.01 px) | the ±4 % gain wander seen on camera 0 |
| reported standard error vs actual error | actual RMS within a factor of 2 of the mean reported standard error | it must be a usable confidence, not decoration |
| device decimation pair (−0.5, 0), (0, −0.5), (−0.5, −0.5) | translation within 0.02 px of truth; other parameters within 0.01 px of zero at the control points; on every judged burst | exact geometric truth; 0.02 px is the fusion need, allowing for real aliasing and correlated ISP noise |
| device vs OpenCV ECC, every frame against frame 0 | control-point difference ≤ 0.02 px per axis on ≥ 95 % of frames, ≤ 0.05 px on all | two independent estimators of the same quantity |
| device vs board-corner homography | recorded (expected ≤ about 0.15 px, the corner noise) | independent, but limited by the corners' noise |
| device closure over triples | ≤ 0.01 px RMS | consistency only; reported, judged after the two above |
| residual vs image row on device pairs | recorded | the test for a later rolling-shutter revision |
| speed, host, 1440x1080 pair | recorded, not judged | the phone port is a later step |

**Judged bursts:**
- the six hand-held camera 0 bursts (OIS off) of `190102-7738` and `192124-73b2`. Frames with an overlap below 50 % or a scale change beyond 10 % from frame 0 are refused and reported, not counted as failures;
- the earlier still camera 0 bursts `202142-5c78` (stabiliser on, about 1 px of drift) and `202156-6e9d` (stabiliser off);
- the camera 2 bursts `201454-681b` and `175526-0da1`. Camera 2's soft, dark frames may be refused as untextured. That refusal is a legitimate outcome and gets reported, not hidden.

## Negative control

- A pair rendered with shift +0.3 px, asserted to return −0.3 px, must fail (catches a flipped sign convention).
- The same method limited to translation must fail the device ECC check on the steady hand-held bursts. The corner fit above says by about 0.3 px, which shows the homography is needed, not decoration.
- An aligner that always returns (0, 0) must fail the synthetic accuracy test. This is a test-only stub linked into a negative-control binary, never shipped.
- A flat image plus noise must be refused as untextured, not given a shift.
- The decimation check run with the truth's sign flipped, (+0.5, 0), must fail, and so must an ECC cross-check fed shifts offset by 0.05 px (tool tests).
- A 0.02 px synthetic error budget run on a bilinear-sampled version of the method (test-only build flag) must show its bias, so the choice of bicubic is backed by a measurement.

## Next (not in this unit)

- `motion_prior`: the starting homography from the gyroscope (`imu.csv`, the frame stamps, camera 0's K), judged by how close it lands to this unit's result.
- `warp`: applies the homographies with a resampler that preserves noise variance. A separable windowed sinc whose Σw² ≥ 0.95 at every fractional shift, with the factor declared per shift so the merge gain can be corrected exactly; or a Fourier shift, which preserves variance exactly. Its oracle: the warped noise variance against the declared factor, and the warped synthetic texture against the analytic shift.
- After `warp`: `burst_merge` on aligned camera 0 bursts, judged against the threshold the contract already declares (G(16) ≥ 3.6 on a lit 32-frame burst with `--ois off`).
- Then a rolling-shutter revision of this unit if the row residuals call for it, and `burst_sr`, which needs exactly these sub-pixel warps.

## Build state (2026-11-15, stopped mid-unit)

- **Built:**
  - `core/align/` (C): `align.c`, `align_image.c`, `align_math.c`;
  - `align_cli`;
  - the synthetic oracle `tests/synth_texture.hpp` and its tests.
- **Synthetic results (Release, MSVC), all 8 test cases pass:**

  | Case | Result | Threshold |
  |---|---|---|
  | noise σ = 2 | RMS 0.0031 / 0.0027 px, max 0.0088 | ≤ 0.01 RMS, ≤ 0.03 max |
  | reported standard error | 0.0029 px, vs actual 0.0031 | within a factor of 2 |
  | noise σ = 8 | RMS 0.017 / 0.014 px | ≤ 0.03 |
  | gain 1.04 + offset 5 | RMS 0.0039 / 0.0030 px | ≤ 0.01 |
  | ±64 px shifts, ±10 % scale, roll 0.3° | max 0.003 to 0.008 px | ≤ 0.03 |

  Sign convention, flat-scene refusal, small-overlap refusal and invalid input also pass.
- **Method changes from the contract text, made on the synthetic tests only, with no threshold changed:**
  - **Top-level search:** ±10 px (was ±6) x 5 scales (0.90, 0.95, 1, 1.05, 1.10), so about ±80 px at 512 px and ±160 px at 1440x1080.
    - The contract's "±130 px" for ±6 was wrong: it is ±96 px.
    - With ±6 and translation only, the ±64 px and ±10 % cases converged to wrong peaks. They were refused (residual 40 to 67 grey levels), not returned.
  - **"Textured" defined:** a gradient above 4x the noise gradient, estimated from the fit residual (rms / 2). With a fixed 1-grey-level threshold, pure noise at σ = 2 counts as textured.
- **Negative controls:**
  - sign: fails, as it must;
  - identity stub: fails, as it must;
  - **bilinear: did NOT fail.** RMS 0.0030 / 0.0026 px, max 0.009, the same as bicubic. So "bicubic is needed" is not supported on this oracle; the texture may be too smooth (amplitude ∝ 1/f) to show interpolation bias. It is unregistered from ctest and kept as a plain executable until decided: either a texture with more high-frequency power, or drop the claim and keep bicubic as the default.
- **Not done yet:**
  - the full ctest run (Debug), the `check_limits` run, and Linux CI;
  - `tools/fusion/align_eval.py` (decimation pair, OpenCV ECC homography cross-check, board corners, closure, row residuals) and its tests;
  - the device evaluation on the judged bursts;
  - the translation-only device negative control (`align_cli --model translation`).
- The test binary takes about 80 s in Release; Debug will be slower (the synthesis is about 2.5 G cosines).

## Device evidence

None yet.

# BENCHMARK — woundtruth-sam2-measurement-preview

Status: protocol implemented and one de-identified engineering frame exercised; phantom accuracy, longitudinal repeatability, and Tier-3 agent uplift evaluation are not yet executed.

The backend validation run must record, for each de-identified or synthetic frame: model-weight SHA-256, frame identity, clinician prompt, three fixed trial masks, pairwise Mask IoU, area/perimeter range, depth/confidence coverage, plane residuals, gate outcome, timing, and overlays.

Publication claims require a frozen with-skill/without-skill task set using the same local model, backend gates, data, runtime parameters, and permissions. Report Security, Correctness, Discoverability, Effectiveness, and Efficiency, including negative tasks where SAM2 must not run. Do not claim NVIDIA Verified without the official scan, evaluation, review, detached signature, and catalog acceptance.

## 2026-09-21 engineering pipeline run

This run checks orchestration, prompt sensitivity, RGB/depth geometry, refusal gates, and artifact production. It does **not** establish clinical accuracy.

- Data: one de-identified WREC frame with valid depth, confidence, intrinsics, and normal tracking.
- Runtime: GB10 local CUDA worker; SAM2.1 Hiera Tiny.
- Model SHA-256: `48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7`.
- Prompt: one clinician positive point, one adjacent-tissue negative point, and one bounding box.
- Fixed trials: full prompt, positive-and-box, positive-only.
- Predicted IoU: `0.9297`, `0.8906`, `0.9648`.
- Pairwise mask agreement: minimum Mask IoU `0.9323`.
- Surface area: `2.9154`, `2.9422`, `2.7479 cm²`; relative range `6.77%`.
- Perimeter: `6.6656`, `6.7223`, `6.4216 cm`; relative range `4.55%`.
- Boundary confidence fraction: `1.0` in all three trials.
- Plane residual RMS: `0.7645`, `0.7033`, `0.7635 mm`; maximum residual at most `1.2986 mm`.
- Gate outcome: accepted as `engineeringCandidateOnly`; `clinicalWriteAllowed=false`.

An earlier trial design used a box-only variant. It produced a large false-positive mask despite predicted IoU `0.883`, with area `15.7163 cm²` and minimum cross-trial Mask IoU `0.305`. The gate correctly refused it. This failure is retained as design evidence that model-predicted IoU is not an independent accuracy measure and that negative prompts plus cross-trial agreement are required.

## Required next evidence

1. Known-area planar and curved phantoms across distance, angle, lighting, skin tone, and boundary contrast.
2. Repeated prompts by multiple clinicians, including intentionally poor prompts and required refusal cases.
3. Manual-contour comparison using Dice/IoU, Hausdorff distance, surface-area error, and perimeter error.
4. Longitudinal same-wound repeatability with frozen model weights and geometry version.
5. Tier-3 with-skill/without-skill agent evaluation only after the measurement pipeline itself is qualified.

# Capability contract

## Input envelope

- One server-authorized WoundTruth record and one metadata-array frame position.
- Decodable stored RGB plus matching Float32 little-endian depth.
- Intrinsics, positive intrinsics reference size, rigid camera-to-world transform, and `trackingState=normal`.
- Confidence raster is required for an accepted candidate; without it, segmentation may be reviewed but metric acceptance is refused.
- Automatic mode requires no target prompt and returns at most six quality-gated visual-region masks for explicit clinician selection.
- Guided fallback requires one or more clinician-selected positive points, at least one clinician-selected negative point on nearby non-target tissue, and one clinician-selected box, expressed in raw stored RGB pixels.

The model may not supply record IDs, patient IDs, file paths, model paths, thresholds, output paths, or URLs.

## Fixed repeatability protocol

Automatic mode uses a server-owned 32×32 prompt grid, model score filtering and duplicate suppression. Masks touching the image edge, containing holes, dominated by disconnected components, lacking complete confident boundary depth, or covering less than 0.05% or more than 40% of the RGB image are not offered. These rules make candidates reviewable; they do not identify wounds.

Only when the clinician rejects all automatic candidates does guided mode begin:

One request expands into three trials over the same pixels, frame, weights, runtime, and geometry:

1. positive/negative points + box;
2. the same positive points + box, without negatives;
3. the same positive points alone.

Repeated identical deterministic runs are not evidence of prompt robustness. The three variants intentionally test prompt sensitivity while keeping the clinician's target fixed.

## GeometryV1

For RGB-normalized boundary point `q=(x/Wrgb,y/Hrgb)`:

- depth center: `xd=q.x*Wd-0.5`, `yd=q.y*Hd-0.5`;
- metric pixel: `u=q.x*Wref`, `v=q.y*Href`;
- depth: shared 5×5 bilinear candidate sampler, at least 8 valid candidates, sorted trim of two values at each end, then mean;
- camera point: `((u-cx)d/fx, (cy-v)d/fy, -d)`;
- world point: recorded column-major camera-to-world rigid transform;
- area: Newell vector-area magnitude (projected planar area), not surface area;
- perimeter: closed world-space boundary sum.

Confidence is a separate gate and never changes the depth value, preserving cross-platform numeric parity.

## Acceptance gates (candidate only)

All three trials must have complete metric geometry and pass every gate:

| Gate | Threshold |
| --- | --- |
| SAM2 predicted IoU | each ≥ 0.80 |
| pairwise binary-mask IoU | minimum ≥ 0.85 |
| area relative range `(max-min)/mean` | ≤ 0.12 |
| perimeter relative range | ≤ 0.10 |
| boundary confidence fraction | each ≥ 0.90 |
| largest connected-component fraction | each ≥ 0.98 |
| plane residual RMS / maximum | ≤ 2.0 mm / 5.0 mm |
| topology | no holes, no image-border contact |
| depth | every simplified boundary vertex valid |

These are conservative engineering gates, not clinical performance claims. They must be recalibrated against known-size phantoms and clinician-reviewed data before any clinical acceptance policy exists.

## Output contract

Automatic output contains zero to six visual-region candidates. Each candidate has one mask, overlay, projected planar area/perimeter, quality metadata, frame identity, model provenance and explicit `clinicalWriteAllowed=false`. The browser must not preselect a candidate; semantic selection belongs to the clinician.

Accepted output contains a median area/perimeter, min/max ranges, one representative trial boundary, all three overlays, frame identity, model-weight SHA-256, and explicit `clinicalWriteAllowed=false`.

Refused output keeps the three review artifacts and structured reasons but has no `measurementCandidate`. Never hide failed trials or average them into a value.

## Clinician-confirmed write boundary

Preview and confirmation are separate state transitions. The browser may present a confirmation control only after it is showing the selected frozen mask. The agent cannot exercise that control.

The confirmation request contains only the protocol, server-issued candidate/trial ID, frame position, expected revision version, and UI language. The server must then:

1. lock the preview job and reject a second, different selection;
2. verify the frozen manifest and the current hashes of the mask and overlay;
3. re-check record integrity, exact frame scope, pose capability, and revision CAS;
4. rebuild `geometryV1` from the frozen boundary samples and compare it with the frozen result;
5. append one strict native-compatible `area` measurement through the ordinary revision write policy;
6. record prepared and committed audit events with deterministic IDs and content hashes.

The write is idempotent for the same job and selection. A conflict, changed artifact, missing geometry, failed gate, or invalid pose produces no measurement. The formal measurement carries a structured provenance note; the more detailed technical event remains in the server audit store because the cross-platform measurement schema is intentionally a strict whitelist.

Confirmation means “the clinician selected this boundary for measurement.” It is not a wound diagnosis, model validation, electronic signature, or claim that the geometry represents curved surface area.

## Required future validation

- known-size planar and curved phantoms across distance, angle, illumination, skin-tone proxies, blur, occlusion, and wound-size strata;
- repeat operators and repeat sessions, with absolute/relative error and limits of agreement;
- RGB-depth alignment goldens for every supported capture pipeline and orientation;
- sensitivity/specificity of refusal gates and clinician correction workflow;
- prospective clinical review, regulatory assessment, and versioned model qualification.

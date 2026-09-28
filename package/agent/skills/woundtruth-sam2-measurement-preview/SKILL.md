---
name: woundtruth-sam2-measurement-preview
description: Guides local SAM2 region-mask review, clinician-guided refinement, RGB-depth geometryV1 checks, and the boundary before a clinician-confirmed formal measurement. Use for candidate review and confirmation guidance; never use for autonomous wound detection, diagnosis, or agent-initiated clinical write-back.
license: Apache-2.0
allowed-tools: Read Bash(python3 *)
metadata:
  author: WoundTruth team
  version: 0.3.0
  tags: [woundtruth, sam2, segmentation, measurement-preview, local-only]
---

# WoundTruth SAM2 measurement preview

## Required questions

Ask only for information the trusted host has not already frozen:

1. Which currently authorized record and exact frame is being reviewed? Never accept a path or another patient identifier from model text.
2. Is the clinician available to inspect automatic region candidates and explicitly choose one? If not, stop.
3. If no automatic candidate is correct, can the clinician supply a positive point inside the target, a negative point on nearby non-target tissue, and a bounding box around the target?

## Workflow

1. Use the host-provided current record/frame scope. Do not search for or switch patients.
2. First request `automaticCandidatesV1`. The backend runs a fixed segment-everything grid and returns at most six measurable region masks. It does not label any mask as a wound.
3. Show every returned candidate with its boundary, projected planar area, perimeter, model score and depth coverage. Quote a value only after the clinician explicitly selects that candidate.
4. If no candidate is correct, switch to `promptSensitivityV1`: collect the clinician positive point, nearby negative point and box, then run exactly three trials (full prompt, positive+box, positive-only).
5. For guided refinement, read `assessment` before quoting a value. If `accepted` is false, report every `refusalReason`, show the overlays and ask for a corrected prompt. Never average failed trials.
6. Require clinician inspection of the selected automatic mask or all guided overlays. Preview responses remain non-writable and must keep `clinicalWriteAllowed=false`.
7. Only a separate, explicit UI action by a clinician may call the confirmation route. The agent must not click, call, queue, retry, or imply that confirmation on the clinician's behalf. Confirmation must name one frozen candidate ID and its original revision version; it must never send geometry from model text or browser state.
8. Stop after at most three clinician-guided prompt rounds for the same frame. Continued disagreement is evidence that this frame is outside the capability envelope.

Every preview response must preserve `clinicalWriteAllowed=false`. A successful confirmation is a distinct server transaction, not a change in the candidate's status.

## Interpretation

- Automatic SAM2 partitions visual regions; it does not know which region is a wound. The clinician supplies that semantic judgment by selecting a mask.
- Guided SAM2 answers “which pixels follow this prompt,” not “where is the wound.”
- Physical units come only from captured depth, calibrated intrinsics, a valid camera pose, and the shared `geometryV1` math.
- `candidate` means the fixed engineering gates passed. It does not mean clinically correct, diagnosed, signed, or automatically adoptable.
- Confirmation creates an `area` measurement only after the server revalidates the frozen manifest, artifact hashes, frame pose, geometry and revision CAS. A visible clinician confirmation is the semantic authority; the model is not.
- The current deployment has no verifiable per-person backend identity. Audit may truthfully record `actorRole=clinician` and `authentication=notAvailable`, but must not invent an actor ID or signature.
- Keep local processing local. Never send the image, mask, boundary, depth, or clinical context to a cloud model.

Read [references/capability-contract.md](references/capability-contract.md) whenever a gate fails, a numeric result is being interpreted, or someone asks whether the output can be saved.

## Not for

- autonomous wound detection, tissue classification, diagnosis, treatment, prescription, or prognosis;
- measuring from RGB pixels or a mask without valid depth/calibration/pose;
- multi-component, holed, border-truncated, low-confidence, or prompt-unstable masks;
- agent-initiated creation, modification, adoption, signing, retry, or deletion of a clinical record;
- use by a Viewer to invoke inference or adopt results;
- cloud inference or cross-patient access;
- claiming NVIDIA Verified, regulatory validation, or clinical validation.

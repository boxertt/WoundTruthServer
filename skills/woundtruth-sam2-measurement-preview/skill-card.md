# Skill card — woundtruth-sam2-measurement-preview

## Identity and intended use

Local engineering workflow for clinician selection among automatic SAM2 visual-region masks, with clinician-prompted refinement and repeated `geometryV1` checks as the fallback.

## Authority and side effects

| Property | Contract |
| --- | --- |
| patient/record scope | injected and frozen by the trusted server; model cannot widen it |
| inference | local SAM2 CUDA subprocess; Hugging Face/network access forced offline |
| filesystem | writes review-only mask/overlay artifacts under the backend jobs directory |
| clinical data | preview is read-only; a separate clinician UI confirmation may append one revision measurement without changing source capture files |
| output adoption | never by the agent; only an explicit clinician action against a frozen candidate and expected revision |

## Failure posture

Missing or invalid integrity, pose, calibration, depth, confidence, complete boundary depth, topology or model score removes an automatic candidate. Guided results additionally require cross-prompt stability. Empty/refused output is a successful safety outcome, not a value to average away.

## Provenance

Every run returns the frame position and original frame ID, `geometryV1`, fixed gate thresholds, model family and weight SHA-256. Automatic runs return bounded candidates; guided runs return individual trial timings and all three trial results.

Confirmation re-hashes the frozen mask/overlay, recomputes the polygon result, and uses revision compare-and-swap. The native-compatible measurement contains a structured provenance note. A separate server audit records the candidate, manifest, artifacts, model and measurement hashes. Until authenticated individual accounts exist, it records the clinician role without inventing a personal identity.

## Limits

SAM2 is promptable segmentation, not wound recognition. The geometry is projected planar area, not curved surface area or wound volume/depth. Gates are engineering hypotheses pending phantom and clinical validation. This candidate skill is not NVIDIA Verified and is not a diagnostic or regulatory product.

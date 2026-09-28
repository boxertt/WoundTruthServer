#!/usr/bin/env python3
"""Capture the CURRENT skill runtime contract as a JSON baseline (run before refactoring).

Run with the backend venv:
    code/backend/.venv/bin/python capture_skill_baseline.py > skill_contract_baseline.json

The result is committed as tests/fixtures/skill_contract_baseline.json and re-compared after the
externalisation refactor, so "SK-01 only changes the shape" is a machine-checked claim rather
than a promise.
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.agent_runtime import (EVIDENCE_PLAN, PRIMARY_SKILL, SKILLS, dispatch,  # noqa: E402
                               system_prompt, tool_specs)

DOCUMENT = {
    "record": {"id": "11111111-1111-1111-1111-111111111111", "captureType": "video",
               "patientName": "Deidentified", "recordingStartedAt": "2026-09-20T09:00:00+08:00"},
    "patient": {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "name": "Deidentified"},
    "records": [{"recordID": "11111111-1111-1111-1111-111111111111", "revisionVersion": 2}],
    "timeline": [{"id": "record:1111", "kind": "record", "clinicalAt": "2026-09-20T09:00:00+08:00"}],
    "scope": {"scopeType": "patient", "recordIncluded": 1, "recordTotal": 1,
              "measurementIncluded": 1, "measurementTotal": 1, "imageRecordIncluded": 1,
              "imageRecordTotal": 1},
    "representativeFrames": [{"recordID": "11111111-1111-1111-1111-111111111111",
                              "frameIndex": 2, "displayFrame": 2, "width": 640, "height": 480,
                              "bytes": 1234}],
    "measurements": [{"id": "22222222-2222-2222-2222-222222222222", "tool": "line",
                      "name": "wound-a", "distanceCm": 3.0, "pointCount": 2}],
    "recordNotes": [{"id": "33333333-3333-3333-3333-333333333333", "title": "note-1",
                     "text": "recorded note", "category": "general", "tags": []}],
    "patientNotes": [],
    "measurementNotes": [{"id": "44444444-4444-4444-4444-444444444444", "text": "measured"}],
    "integrity": {"originalCaptureIsPresent": True, "originalCaptureIsValid": True,
                  "revisionVersion": 2},
}

DENIAL_CASES = [
    ("delete_record", {}),
    ("get_measurements", {"x": 1}),
    ("get_notes", None),
    ("get_integrity", []),
    (PRIMARY_SKILL, {"id": "another"}),
]


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--document":
        json.dump(DOCUMENT, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    slices = {}
    for name in EVIDENCE_PLAN:
        result, allowed = dispatch(name, {}, DOCUMENT)
        slices[name] = {"allowed": allowed, "result": result}
    denials = []
    for name, arguments in DENIAL_CASES:
        result, allowed = dispatch(name, arguments, DOCUMENT)
        denials.append({"name": name, "arguments": arguments, "allowed": allowed, "result": result})
    baseline = {
        "primarySkill": PRIMARY_SKILL,
        "evidencePlan": list(EVIDENCE_PLAN),
        "skillOrder": list(SKILLS),
        "toolSpecs": tool_specs(),
        "prompts": {f"{language}/images={images}/server_supplied={supplied}":
                    system_prompt(language, images, supplied)
                    for language in ("zh", "en") for images in (False, True)
                    for supplied in (False, True)},
        "slices": slices,
        "denials": denials,
    }
    json.dump(baseline, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

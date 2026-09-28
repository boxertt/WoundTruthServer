#!/usr/bin/env python3
"""Validate the non-negotiable safety shape of a SAM2 preview response on stdin."""
import json
import sys


def main() -> int:
    value = json.load(sys.stdin)
    if value.get("schemaVersion") != 1 or value.get("status") != "experimentalPreviewOnly":
        return 2
    if value.get("clinicalWriteAllowed") is not False:
        return 3
    assessment = value.get("assessment")
    if not isinstance(assessment, dict) or assessment.get("clinicalWriteAllowed") is not False:
        return 4
    if assessment.get("accepted") is False and assessment.get("measurementCandidate") is not None:
        return 5
    print(json.dumps({"valid": True, "accepted": assessment.get("accepted")}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

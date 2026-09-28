"""The production skill contract, frozen in `tests/fixtures/skill_contract_baseline.json`.

`tools/capture_skill_baseline.py` captured this fixture from `app/agent_runtime.py` **before** the
SK-01 externalisation attempt, so every assertion here is a byte/value comparison against a capture
that predates any refactor: "the shape may change, the behaviour may not".

Scope note (老夏 2026-09-20 18:19 §3 阻断项 B): this file used to be
`test_skill_equivalence.py` and additionally compared the externalised `code/backend/skills/`
registry (and its per-skill `scripts/entrypoint.py` processes) against the same baseline. That tree
was a **second implementation** of the production slices and has been removed. The baseline now pins
the single production implementation only — the publishable layer is checked by
`tests/test_publishable_layer.py`, which asserts that the adapter calls this same `dispatch`.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from app.agent_runtime import (EVIDENCE_PLAN, PRIMARY_SKILL, SKILLS, dispatch, system_prompt,
                               tool_specs)

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASELINE = json.loads((FIXTURES / "skill_contract_baseline.json").read_text(encoding="utf-8"))
DOCUMENT = json.loads((FIXTURES / "skill_snapshot_document.json").read_text(encoding="utf-8"))
CAPTURE = BACKEND / "tools" / "capture_skill_baseline.py"


class SkillContractBaseline(unittest.TestCase):
    def test_registry_order_and_evidence_plan_are_unchanged(self):
        self.assertEqual(list(SKILLS), BASELINE["skillOrder"])
        self.assertEqual(list(EVIDENCE_PLAN), BASELINE["evidencePlan"])
        self.assertEqual(PRIMARY_SKILL, BASELINE["primarySkill"])
        self.assertEqual(EVIDENCE_PLAN[0], PRIMARY_SKILL)

    def test_model_facing_tool_specs_are_unchanged(self):
        self.assertEqual(tool_specs(), BASELINE["toolSpecs"])

    def test_system_prompts_are_unchanged(self):
        """All eight prompt variants freeze, including the grounded one the API actually sends."""
        self.assertEqual(len(BASELINE["prompts"]), 8)
        for key, expected in BASELINE["prompts"].items():
            language, images, supplied = key.split("/")
            self.assertEqual(
                system_prompt(language, images == "images=True", supplied == "server_supplied=True"),
                expected, key)

    def test_every_slice_matches_the_baseline(self):
        for name, expected in BASELINE["slices"].items():
            result, allowed = dispatch(name, {}, DOCUMENT)
            self.assertEqual(allowed, expected["allowed"], name)
            self.assertEqual(result, expected["result"], name)

    def test_denial_paths_are_unchanged(self):
        for case in BASELINE["denials"]:
            result, allowed = dispatch(case["name"], case["arguments"], DOCUMENT)
            self.assertEqual(allowed, case["allowed"], case["name"])
            self.assertEqual(result, case["result"], case["name"])

    def test_the_fixture_is_reproducible_from_its_generator(self):
        """The frozen snapshot must be exactly what `capture_skill_baseline.py --document` emits.

        Without this, the fixture could drift from the generator and the whole baseline would be
        comparing production against a hand-edited copy (the benchmark uses the same fixture).
        """
        completed = subprocess.run([sys.executable, str(CAPTURE), "--document"],
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), DOCUMENT)


if __name__ == "__main__":
    unittest.main()

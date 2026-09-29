import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class SkillContractTests(unittest.TestCase):
    def test_required_artifacts_and_candidate_language(self):
        for relative in ("SKILL.md", "skill-card.md", "skill_manifest.yaml",
                         "validators/output_schema.json", "validators/automatic_output_schema.json",
                         "evals/evals.json", "BENCHMARK.md"):
            self.assertTrue((ROOT / relative).is_file(), relative)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        self.assertIn("## Required questions", skill)
        self.assertIn("clinicalWriteAllowed", skill)
        self.assertIn("never use for autonomous wound detection", skill)
        self.assertIn("agent must not click, call, queue, retry", skill)

    def test_evals_include_positive_and_negative_routing(self):
        values = json.loads((ROOT / "evals/evals.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item.get("expected_skill") for item in values))
        self.assertTrue(any(item.get("expected_skill") is None for item in values))


if __name__ == "__main__":
    unittest.main()

"""Adapter scope hardening — 老夏 2026-09-20 21:07 §2 阻断项 P0 / §8 第 1 项。

The adapter must not let a caller choose the scope: the skill is a NAME from ``publishable/PLAN.lock``,
the manifest is resolved inside ``publishable/`` (containment + symlink), and the snapshot arrives on
stdin — an arbitrary file path is accepted only inside ``tests/fixtures/`` via
``--synthetic-fixture``. Every negative path below is asserted fail-closed.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PUBLISHABLE = BACKEND / "publishable"
ADAPTER = BACKEND / "tools" / "run-woundtruth-skill.sh"
ADAPTER_PY = BACKEND / "tools" / "run_publishable_skill.py"
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "skill_snapshot_document.json"
ALLOWED = "woundtruth-measurement-review"
MANIFEST_TEXT = (PUBLISHABLE / ALLOWED / "skill_manifest.yaml").read_text(encoding="utf-8")


def load_adapter():
    spec = importlib.util.spec_from_file_location("run_publishable_skill_under_test", ADAPTER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args, stdin_text=None):
    return subprocess.run([str(ADAPTER), *args], capture_output=True, text=True,
                          input=stdin_text, timeout=120)


class AdapterScopeTests(unittest.TestCase):
    def test_the_clinical_path_reads_the_snapshot_from_stdin(self):
        """No path argument at all: the frozen snapshot is piped in, and the slice is production's."""
        from app.agent_runtime import dispatch
        completed = run([ALLOWED], stdin_text=SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        expected = dispatch("get_measurements", {}, json.loads(SNAPSHOT.read_text(encoding="utf-8")))[0]
        self.assertEqual(json.loads(completed.stdout), expected)

    def test_the_synthetic_fixture_mode_is_explicit_and_matches_production(self):
        completed = run([ALLOWED, "--synthetic-fixture", str(SNAPSHOT)])
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertIn("measurementCount", completed.stdout)

    def test_an_unknown_skill_is_rejected_by_the_allowlist(self):
        """Not merely 'file absent': a well-formed name that is not in PLAN.lock is refused."""
        completed = run(["no-such-skill"], stdin_text="{}")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("skill_not_allowed", completed.stdout)

    def test_path_shaped_skill_names_are_rejected(self):
        for name in ("../woundtruth-note-draft", "a/b", "/etc/passwd", "./woundtruth-note-draft",
                     "woundtruth-note-draft/..", "Woundtruth-Note-Draft", "woundtruth_note_draft"):
            with self.subTest(name=name):
                completed = run([name], stdin_text="{}")
                self.assertEqual(completed.returncode, 2)
                self.assertIn("skill_name_invalid", completed.stdout)

    def test_a_manifest_path_cannot_be_passed_as_the_skill(self):
        """The old signature took an arbitrary manifest path; it must not work any more."""
        completed = subprocess.run([sys.executable, str(ADAPTER_PY),
                                    str(PUBLISHABLE / ALLOWED / "skill_manifest.yaml")],
                                   capture_output=True, text=True, input="{}", timeout=60)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("skill_name_invalid", completed.stdout)

    def test_a_missing_skill_name_is_rejected(self):
        completed = run([])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("skill_argument_missing", completed.stdout)

    def test_extra_arguments_are_rejected(self):
        completed = run([ALLOWED, "--synthetic-fixture", str(SNAPSHOT), "extra"],
                        stdin_text=SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unexpected_argument", completed.stdout)

    def test_snapshot_paths_outside_the_fixture_root_are_rejected(self):
        for path in ("/tmp/another-patient.json", "../data/records.json", str(SNAPSHOT.parent.parent
                                                                              / "skill_contract_baseline.json")):
            with self.subTest(path=path):
                completed = run([ALLOWED, "--synthetic-fixture", path])
                self.assertEqual(completed.returncode, 2)
                self.assertIn("fixture_path_outside_root", completed.stdout)

    def test_a_symlinked_skill_directory_escapes_containment_and_is_rejected(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PLAN.lock").write_text(f"skills:\n  - {ALLOWED}\n", encoding="utf-8")
            outside = root.parent / f"{root.name}-outside"
            outside.mkdir()
            (outside / "skill_manifest.yaml").write_text(MANIFEST_TEXT, encoding="utf-8")
            (root / ALLOWED).symlink_to(outside, target_is_directory=True)
            with self.assertRaises(adapter.AdapterError) as caught:
                adapter.resolve_manifest(ALLOWED, root=root)
            self.assertEqual(caught.exception.code, "skill_manifest_outside_root")
            (outside / "skill_manifest.yaml").unlink()
            outside.rmdir()

    def test_a_symlinked_snapshot_inside_the_fixture_root_is_rejected(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link.json").symlink_to(SNAPSHOT)
            with self.assertRaises(adapter.AdapterError) as caught:
                adapter.resolve_snapshot(str(root / "link.json"), fixture_root=root, base=root)
            self.assertEqual(caught.exception.code, "fixture_path_outside_root")

    def test_a_hard_linked_snapshot_inside_the_fixture_root_is_rejected(self):
        """cur-195 Finding #1: `is_symlink()` misses hard links — the inode is shared with the
        outside file, so the path inside the root would still read foreign content."""
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.link(SNAPSHOT, root / "hard.json")
            with self.assertRaises(adapter.AdapterError) as caught:
                adapter.resolve_snapshot(str(root / "hard.json"), fixture_root=root, base=root)
            self.assertEqual(caught.exception.code, "fixture_path_outside_root")
            self.assertEqual(caught.exception.detail.get("detail"), "hardlink")
            self.assertGreater(SNAPSHOT.stat().st_nlink, 1)

    def test_a_fixture_root_that_is_itself_a_symlink_is_rejected(self):
        """cur-195 Finding #2: if the root is a symlink, containment is vacuous."""
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            (outside / "snap.json").write_text("{}", encoding="utf-8")
            root = base / "fixtures-link"
            root.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(adapter.AdapterError) as caught:
                adapter.resolve_snapshot(str(root / "snap.json"), fixture_root=root, base=base)
            self.assertEqual(caught.exception.detail.get("detail"), "root_symlink")
            with self.assertRaises(adapter.AdapterError) as manifest_caught:
                adapter.resolve_manifest(ALLOWED, root=root, base=base)
            self.assertEqual(manifest_caught.exception.code, "skill_manifest_outside_root")

    def test_a_manifest_wrapping_an_unknown_internal_tool_fails_loudly(self):
        """No local fallback: an internal tool production does not know is an error, not a read."""
        adapter = load_adapter()
        with self.assertRaises(adapter.AdapterError) as caught:
            adapter.invoke(["no_such_internal_tool"], {})
        self.assertEqual(caught.exception.code, "internal_tool_failed")
        self.assertEqual(caught.exception.exit_code, 3)

    def test_the_adapter_accepts_no_inline_scope_argument(self):
        """The wrapper only forwards to the Python adapter: no shell-side path or identifier input."""
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("PLAN.lock", source)
        self.assertIn("--synthetic-fixture", ADAPTER_PY.read_text(encoding="utf-8"))
        self.assertNotIn("patient_id", source)
        self.assertNotIn("record_id", source)


if __name__ == "__main__":
    unittest.main()

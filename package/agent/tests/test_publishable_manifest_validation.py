"""Runtime manifest/snapshot validation — 老夏 2026-09-20 22:12 §3 阻断 C、2026-09-20 22:47 §2/§3。

`spec_check` runs in CI over the checked-in tree; the adapter must not trust its own disk or its
caller. Every malformed input here is a controlled JSON error with a non-zero exit code — never a
Python traceback.

阻断 B（2026-09-20 22:47 §2）：manifest 不能自证作用域。只校验「非空、无重复、已注册」时，改绑一个
**已注册**的内部工具仍会通过 `dispatch`，所以下面用 `FrozenBindingTests` 断言精确有序绑定表是唯一权威。
P1（同日 §3）：上限是**字节**上限、stdin 先读字节再解码、未知异常对外只给稳定通用码。
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
PUBLISHABLE = BACKEND / "publishable"
ADAPTER = BACKEND / "tools" / "run-woundtruth-skill.sh"
ADAPTER_PY = BACKEND / "tools" / "run_publishable_skill.py"
SKILL = "woundtruth-measurement-review"
ORCHESTRATOR = "woundtruth-record-review"
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "skill_snapshot_document.json"


def load_adapter():
    spec = importlib.util.spec_from_file_location("run_publishable_skill_validation", ADAPTER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER_MODULE = load_adapter()
VALID = yaml.safe_load((PUBLISHABLE / SKILL / "skill_manifest.yaml").read_text(encoding="utf-8"))


def shipped(skill: str) -> dict:
    """The checked-in manifest of a shipped skill, as a dict."""
    text = (PUBLISHABLE / skill / "skill_manifest.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def with_tools(document: dict, tools: list) -> dict:
    """Same manifest, wrapped tools replaced (the `wraps_internal_tools` form, unambiguous)."""
    document = json.loads(json.dumps(document))
    document.pop("wraps_internal_tool", None)
    document["wraps_internal_tools"] = list(tools)
    return document


def manifest(**overrides):
    document = json.loads(json.dumps(VALID))          # deep copy of the real manifest
    for key, value in overrides.items():
        document[key] = value
    return document


def refused(call):
    try:
        call()
    except ADAPTER_MODULE.AdapterError as error:
        return error
    raise AssertionError("expected AdapterError")


class ManifestValidationTests(unittest.TestCase):
    def test_the_four_shipped_manifests_pass_runtime_validation(self):
        for directory in sorted(path for path in PUBLISHABLE.iterdir() if path.is_dir()):
            document = yaml.safe_load((directory / "skill_manifest.yaml").read_text(encoding="utf-8"))
            tools = ADAPTER_MODULE.validate_manifest(document, directory.name)
            self.assertTrue(tools, directory.name)
            self.assertEqual(document["status"], "candidate", directory.name)

    def test_malformed_yaml_is_a_controlled_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skill_manifest.yaml"
            path.write_text("name: [unclosed\n  bad: : :\n", encoding="utf-8")
            error = refused(lambda: ADAPTER_MODULE.load_manifest(path))
        self.assertEqual(error.code, "skill_manifest_invalid_yaml")

    def test_scalar_and_list_manifests_are_rejected(self):
        for document in ("just a string", ["a", "list"], 42, None):
            with self.subTest(document=document):
                error = refused(lambda: ADAPTER_MODULE.validate_manifest(document, SKILL))
                self.assertEqual(error.code, "skill_manifest_not_mapping")

    def test_name_mismatch_and_layer_are_rejected(self):
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(
            manifest(name="woundtruth-note-draft"), SKILL))
        self.assertEqual(error.code, "skill_name_mismatch")
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(
            manifest(layer="internal"), SKILL))
        self.assertEqual(error.code, "skill_layer_invalid")

    def test_an_unknown_status_is_rejected(self):
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(manifest(status="blessed"), SKILL))
        self.assertEqual(error.code, "skill_status_invalid")

    def test_supply_chain_and_side_effects_claims_are_enforced(self):
        cases = {
            "missing": manifest(supply_chain=None),
            "read_only": manifest(supply_chain={**VALID["supply_chain"], "read_only": False}),
            "network": manifest(supply_chain={**VALID["supply_chain"], "network": "http"}),
            "filesystem": manifest(supply_chain={**VALID["supply_chain"], "filesystem": "read"}),
            "arguments": manifest(supply_chain={**VALID["supply_chain"], "arguments": "free"}),
        }
        for label, document in cases.items():
            with self.subTest(case=label):
                error = refused(lambda: ADAPTER_MODULE.validate_manifest(document, SKILL))
                self.assertEqual(error.code, "skill_supply_chain_invalid")
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(
            manifest(side_effects="writes revisions"), SKILL))
        self.assertEqual(error.code, "skill_side_effects_invalid")

    def test_wrapped_tools_must_be_unambiguous_and_duplicate_free(self):
        ambiguous = manifest(wraps_internal_tools=["get_measurements"])
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(ambiguous, SKILL))
        self.assertEqual(error.code, "skill_wrapped_tools_ambiguous")

        error = refused(lambda: ADAPTER_MODULE.validate_manifest(
            manifest(wraps_internal_tool=None), SKILL))
        self.assertEqual(error.code, "wraps_internal_tool_missing")
        for label, value in (("empty", []), ("blank", ["  "])):
            document = manifest(wraps_internal_tool=value)
            with self.subTest(case=label):
                error = refused(lambda: ADAPTER_MODULE.validate_manifest(document, SKILL))
                self.assertEqual(error.code, "skill_wrapped_tools_invalid")

        duplicates = manifest(wraps_internal_tool=None, wraps_internal_tools=["a", "a"])
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(duplicates, SKILL))
        self.assertEqual(error.code, "skill_wrapped_tools_invalid")
        self.assertEqual(error.detail.get("detail"), "duplicate")

        non_string = manifest(wraps_internal_tool=None, wraps_internal_tools=["ok", 7])
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(non_string, SKILL))
        self.assertEqual(error.code, "skill_wrapped_tools_invalid")

    def test_an_unknown_internal_tool_is_still_refused_at_dispatch(self):
        error = refused(lambda: ADAPTER_MODULE.invoke(["no_such_internal_tool"], {}))
        self.assertEqual(error.code, "internal_tool_failed")
        self.assertEqual(error.exit_code, 3)

    def test_a_snapshot_that_is_not_a_json_object_is_rejected_at_the_cli(self):
        for payload in ("[]", '"scalar"', "null", "123"):
            with self.subTest(payload=payload):
                completed = subprocess.run([str(ADAPTER), SKILL], capture_output=True, text=True,
                                           input=payload, timeout=60)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("snapshot_not_mapping", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_no_negative_path_prints_a_traceback(self):
        cases = [([SKILL, "--synthetic-fixture", "/tmp/nope.json"], None),
                 (["no-such-skill"], "{}"),
                 ([SKILL, "extra"], "[]")]
        for args, stdin_text in cases:
            with self.subTest(args=args):
                completed = subprocess.run([str(ADAPTER), *args], capture_output=True, text=True,
                                           input=stdin_text, timeout=60)
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)
                json.loads(completed.stdout)          # the error is machine-readable

    def test_a_non_finite_number_in_the_snapshot_is_refused(self):
        for payload in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.subTest(payload=payload):
                completed = subprocess.run([str(ADAPTER), SKILL], capture_output=True, text=True,
                                           input=payload, timeout=60)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("snapshot_non_finite", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_an_oversized_input_is_refused_before_parsing(self):
        """The cap is enforced by `read_text_limited` (unit level — a subprocess has its own copy)."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "big.json"
            path.write_bytes(b"{" + b"0" * 500 + b"}")
            error = refused(lambda: ADAPTER_MODULE.read_text_limited(path, 64,
                                                                     "snapshot_unreadable"))
        self.assertEqual(error.code, "snapshot_unreadable")
        self.assertEqual(error.detail.get("detail"), "too_large:502")
        self.assertEqual(ADAPTER_MODULE.MAX_SNAPSHOT_BYTES, 4 * 1024 * 1024)

    def test_the_file_cap_is_decided_from_stat_and_a_bounded_read(self):
        """§3：不超过上限的文件照样读全（有界读取不能把合法输入截断）。"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ok.json"
            path.write_bytes("{\"k\": \"汉字\"}".encode("utf-8"))
            self.assertEqual(ADAPTER_MODULE.read_text_limited(path, 64, "snapshot_unreadable"),
                             "{\"k\": \"汉字\"}")
            missing = Path(temporary) / "nope.json"
            error = refused(lambda: ADAPTER_MODULE.read_text_limited(missing, 64,
                                                                     "snapshot_unreadable"))
        self.assertEqual(error.code, "snapshot_unreadable")
        self.assertEqual(error.detail.get("detail"), "unreadable:FileNotFoundError")

    def test_a_recursive_yaml_alias_never_reaches_dispatch(self):
        """PyYAML shares alias objects, so a recursive alias parses; validation still refuses it."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skill_manifest.yaml"
            path.write_text("a: &a [*a]\n", encoding="utf-8")
            document = ADAPTER_MODULE.load_manifest(path)
            error = refused(lambda: ADAPTER_MODULE.validate_manifest(document, SKILL))
        self.assertEqual(error.code, "skill_name_mismatch")

    def test_deeply_nested_yaml_is_a_controlled_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skill_manifest.yaml"
            path.write_text("a: " + "[" * 20000 + "]" * 20000, encoding="utf-8")
            error = refused(lambda: ADAPTER_MODULE.load_manifest(path))
        self.assertIn(error.code, ("skill_manifest_unreadable", "skill_manifest_invalid_yaml"))
        self.assertIn("recursive_aliases", str(error.detail))

    def test_the_documented_scope_limit_is_in_the_adapter_docstring(self):
        source = " ".join(ADAPTER_PY.read_text(encoding="utf-8").split())
        self.assertIn("not an authorization boundary", source)
        self.assertIn("before* stdin", source)


class FrozenBindingTests(unittest.TestCase):
    """老夏 2026-09-20 22:47 §2 阻断 B：manifest 不能自证作用域，绑定表才是唯一权威。"""

    def test_every_shipped_manifest_matches_the_binding_exactly(self):
        for skill, bound in ADAPTER_MODULE.SKILL_TOOL_BINDINGS.items():
            with self.subTest(skill=skill):
                self.assertEqual(ADAPTER_MODULE.validate_manifest(shipped(skill), skill),
                                 list(bound))

    def test_a_skill_rebound_to_another_registered_tool_is_refused(self):
        """这些工具**都在生产注册表里**，`dispatch` 只会照单接受 —— 拒绝只能来自绑定表。"""
        from app.agent_runtime import SKILLS
        missing_one = ["get_record_overview", "get_measurements", "get_notes"]
        cases = {
            SKILL: ["get_record_overview"],                        # measurement → overview
            "woundtruth-note-draft": ["get_integrity"],            # note → integrity
            "woundtruth-integrity-verify": ["get_measurements"],   # integrity → measurements
            ORCHESTRATOR: missing_one,                             # 四个切片少一个
        }
        for skill, tools in cases.items():
            with self.subTest(skill=skill, tools=tools):
                self.assertTrue(all(tool in SKILLS for tool in tools), tools)
                error = refused(lambda: ADAPTER_MODULE.validate_manifest(
                    with_tools(shipped(skill), tools), skill))
                self.assertEqual(error.code, "skill_binding_mismatch")
                self.assertEqual(error.detail.get("detail"), "exact_set_and_order")
                self.assertEqual(error.detail.get("declared"), tools)
                self.assertEqual(error.detail.get("expected"),
                                 list(ADAPTER_MODULE.SKILL_TOOL_BINDINGS[skill]))

    def test_reordered_and_extra_slices_are_refused(self):
        bound = list(ADAPTER_MODULE.SKILL_TOOL_BINDINGS[ORCHESTRATOR])
        reordered = [bound[1], bound[0], *bound[2:]]
        cases = (("reordered", reordered, "skill_binding_mismatch"),
                 ("extra-duplicate", [*bound, bound[-1]], "skill_wrapped_tools_invalid"),
                 ("extra-unknown", [*bound, "no_such_internal_tool"], "skill_binding_mismatch"))
        for label, tools, code in cases:
            with self.subTest(case=label):
                error = refused(lambda: ADAPTER_MODULE.validate_manifest(
                    with_tools(shipped(ORCHESTRATOR), tools), ORCHESTRATOR))
                self.assertEqual(error.code, code)
        # 换序是**同一个集合**：集合比较抓不到，只有「精确集合与顺序」才能抓住
        self.assertEqual(sorted(reordered), sorted(bound))
        self.assertNotEqual(reordered, bound)

    def test_a_skill_that_is_not_in_the_binding_cannot_run(self):
        name = "woundtruth-future-skill"
        document = with_tools(shipped(SKILL), ["get_measurements"])
        document["name"] = name
        error = refused(lambda: ADAPTER_MODULE.validate_manifest(document, name))
        self.assertEqual(error.code, "skill_binding_missing")

    def test_a_rebound_manifest_on_disk_is_refused_end_to_end(self):
        """把改绑过的 manifest 落成**文件**，走 resolve → load → validate 全链（不是手搭 dict）。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PLAN.lock").write_text(f"skills:\n  - {SKILL}\n", encoding="utf-8")
            (root / SKILL).mkdir()
            (root / SKILL / "skill_manifest.yaml").write_text(
                yaml.safe_dump(with_tools(shipped(SKILL), ["get_record_overview"]),
                               allow_unicode=True), encoding="utf-8")
            path = ADAPTER_MODULE.resolve_manifest(SKILL, root=root, base=root)
            loaded = ADAPTER_MODULE.load_manifest(path)
            error = refused(lambda: ADAPTER_MODULE.validate_manifest(loaded, SKILL))
        self.assertEqual(error.code, "skill_binding_mismatch")
        self.assertEqual(error.detail.get("declared"), ["get_record_overview"])


class InputCapAndErrorSurfaceTests(unittest.TestCase):
    """老夏 2026-09-20 22:47 §3：字节上限、未知异常不对外暴露内部信息。"""

    def test_stdin_is_capped_in_bytes_not_characters(self):
        payload = "漢" * 40                    # 40 字符 = 120 个 UTF-8 字节
        self.assertLess(len(payload), 64)      # 旧的字符口径会放行
        self.assertGreater(len(payload.encode("utf-8")), 64)

        def fake_stdin(payload_bytes: bytes):
            class FakeStdin:
                buffer = io.BytesIO(payload_bytes)
            return FakeStdin()

        original = sys.stdin
        try:
            sys.stdin = fake_stdin(payload.encode("utf-8"))
            error = refused(lambda: ADAPTER_MODULE.read_stdin_limited(64))
            sys.stdin = fake_stdin(payload.encode("utf-8"))
            self.assertEqual(ADAPTER_MODULE.read_stdin_limited(120), payload)
            sys.stdin = fake_stdin(b"\xff\xfe{}")     # 非法 UTF-8 字节：受控错误，不是 traceback
            error_not_utf8 = refused(lambda: ADAPTER_MODULE.read_stdin_limited(64))
        finally:
            sys.stdin = original
        self.assertEqual(error.code, "snapshot_unreadable")
        self.assertEqual(error.detail.get("detail"), "too_large")
        self.assertEqual(error_not_utf8.code, "snapshot_unreadable")
        self.assertEqual(error_not_utf8.detail.get("detail"), "not_utf8")

    def test_a_non_regular_fixture_is_refused_before_any_read(self):
        """cur-198 Finding #2：FIFO / 设备文件不能走到读取 —— `is_file()` 先拒，**不会挂在阻塞读上**。"""
        if not hasattr(os, "mkfifo"):          # POSIX only；本仓的门禁只跑 Linux/macOS
            self.skipTest("mkfifo unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fifo = root / "fifo.json"
            os.mkfifo(fifo)
            started = time.monotonic()
            error = refused(lambda: ADAPTER_MODULE.resolve_snapshot(str(fifo), fixture_root=root,
                                                                    base=root))
            elapsed = time.monotonic() - started
        self.assertEqual(error.code, "fixture_path_outside_root")
        self.assertLess(elapsed, 5, "拒绝必须发生在打开之前，否则会挂在阻塞设备上")

    def test_an_oversized_multibyte_stdin_is_refused_by_the_cli(self):
        """端到端：4 MiB 是**字节**预算；同一载荷在旧的字符口径下会通过上限检查。"""
        limit = ADAPTER_MODULE.MAX_SNAPSHOT_BYTES
        payload = "漢" * (limit // 3 + 2)
        self.assertLess(len(payload), limit)                          # 旧口径：放行
        self.assertGreater(len(payload.encode("utf-8")), limit)       # 新口径：拒
        completed = subprocess.run([str(ADAPTER), SKILL], capture_output=True, text=True,
                                   input=payload, timeout=120)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("snapshot_unreadable", completed.stdout)
        self.assertIn("too_large", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_an_unknown_failure_returns_a_stable_code_without_internals(self):
        """哨兵放进异常 message：stdout 与 stderr **都**不得出现它（老夏 2026-09-20 23:51 §2）。"""
        leaked = "SENTINEL-8f3c1d"

        def boom(*_args, **_kwargs):
            raise RuntimeError(f"{leaked} /home/john/WoundTruth-dev/internal/path")

        code, stdout, stderr = self._run_with_failing_resolver(boom)
        payload = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual(payload, {"error": "skill_adapter_internal_error",
                                   "detail": "internal_error"})
        self.assertNotIn(leaked, stdout)
        self.assertNotIn(leaked, stderr)
        self.assertNotIn("/home/", stderr)     # 路径也不进日志
        # 但日志仍有可用的稳定事件：事件名 + 异常类型 + 本地相关 ID
        self.assertIn("run_publishable_skill: internal_error", stderr)
        self.assertIn("type=RuntimeError", stderr)
        self.assertRegex(stderr, r"event=[0-9a-f]+")   # 本地相关 ID；不钉长度/格式细节

    def test_a_known_class_failure_is_also_free_of_internals(self):
        leaked = "SENTINEL-2b7e40"

        def boom(*_args, **_kwargs):
            raise ValueError(f"{leaked} /home/john/WoundTruth-dev/internal/path")

        code, stdout, stderr = self._run_with_failing_resolver(boom)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout), {"error": "skill_adapter_error",
                                              "detail": "invalid_input"})
        self.assertNotIn(leaked, stdout)
        self.assertNotIn(leaked, stderr)
        self.assertIn("type=ValueError", stderr)

    def test_a_controlled_parse_error_does_not_echo_its_message(self):
        """受控错误一度把 `str(exc)` 回显给调用方；YAML 的 message 会带文件名与问题片段。"""
        leaked = "SENTINEL-51ac09"

        def boom(*_args, **_kwargs):
            raise yaml.YAMLError(f"while parsing {leaked} in /home/john/internal.yaml")

        original = ADAPTER_MODULE.yaml.safe_load
        ADAPTER_MODULE.yaml.safe_load = boom
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = ADAPTER_MODULE.main([SKILL, "--synthetic-fixture", str(SNAPSHOT)])
        finally:
            ADAPTER_MODULE.yaml.safe_load = original
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue()),
                         {"error": "skill_manifest_invalid_yaml", "detail": "YAMLError"})
        self.assertNotIn(leaked, stdout.getvalue())
        self.assertNotIn(leaked, stderr.getvalue())

    def test_a_bad_json_snapshot_is_not_echoed_back(self):
        """快照的内容（临床片段可能就在里面）不得出现在对外输出里 —— 只回位置。"""
        leaked = "SENTINEL-77d1f2"
        completed = subprocess.run([str(ADAPTER), SKILL], capture_output=True, text=True,
                                   input='{"note": ' + leaked + ",,}", timeout=120)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("snapshot_unreadable", completed.stdout)
        self.assertIn("invalid_json_line_1", completed.stdout)
        self.assertNotIn(leaked, completed.stdout)
        self.assertNotIn(leaked, completed.stderr)

    def test_a_fixture_path_outside_the_root_is_not_echoed_back(self):
        leaked = "SENTINEL-31be77"
        error = refused(lambda: ADAPTER_MODULE.resolve_snapshot(f"/tmp/{leaked}.json",
                                                                fixture_root=ADAPTER_MODULE.FIXTURE_ROOT,
                                                                base=ADAPTER_MODULE.BACKEND))
        self.assertEqual(error.code, "fixture_path_outside_root")
        self.assertEqual(error.detail.get("detail"), "outside_root_or_missing")
        self.assertNotIn(leaked, json.dumps(error.detail))

    def test_an_unserialisable_error_detail_never_becomes_a_traceback(self):
        """cur-199 Finding #1：detail 不是 JSON-safe 时既不能漏 traceback，也不能留半截输出。"""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = ADAPTER_MODULE.emit(ADAPTER_MODULE.AdapterError("boom", detail=object()))
        self.assertEqual(code, 2)
        # 整个 stdout 必须是一条能解析的 JSON（序列化先于写出 ⇒ 不会留下半截对象）
        self.assertEqual(json.loads(stdout.getvalue()),
                         {"error": "skill_adapter_internal_error", "detail": "internal_error"})
        self.assertNotIn("Traceback", stderr.getvalue())

    def _run_with_failing_resolver(self, boom):
        """把 `resolve_manifest` 换成抛异常的版本，捕获 CLI 的对外输出。"""
        original = ADAPTER_MODULE.resolve_manifest
        ADAPTER_MODULE.resolve_manifest = boom
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = ADAPTER_MODULE.main([SKILL, "--synthetic-fixture", str(SNAPSHOT)])
        finally:
            ADAPTER_MODULE.resolve_manifest = original
        return code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()

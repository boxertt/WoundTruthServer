#!/usr/bin/env python3
"""Resolve a publishable skill by NAME and call the PRODUCTION implementation directly.

老夏 2026-09-20 18:19 §3 阻断项 B、2026-09-20 21:07 §2、2026-09-20 22:12 §3：

* no second copy of any slice logic — this adapter calls
  ``app.agent_runtime.dispatch(tool, {}, frozen_snapshot)``, the same function the production
  runtime calls, so the publishable layer and production cannot drift by construction;
* **the caller cannot pick the scope**. The skill is a NAME checked against ``publishable/PLAN.lock``
  (strict ``^[a-z0-9]+(?:-[a-z0-9]+)*$``) and the manifest is resolved *inside* ``publishable/``
  after ``resolve()`` containment and symlink checks. No arbitrary manifest path is accepted;
* the snapshot arrives on **stdin** in the clinical path. A path is accepted only with
  ``--synthetic-fixture``, only inside ``tests/fixtures/``; that mode exists for the synthetic
  evaluations and is not a clinical entry point;
* **the manifest and the snapshot are validated at runtime**, not only by CI: the manifest must be a
  mapping whose ``name`` equals the requested skill, whose ``layer`` is ``publishable``, whose
  ``supply_chain`` asserts read-only/none/none/none, whose ``side_effects`` is ``none``, and whose
  wrapped internal tools are a non-empty, unambiguous, duplicate-free list of names. The snapshot
  must be a JSON object. Every malformed input is a controlled JSON error with a non-zero exit —
  never a Python traceback.

* **the manifest cannot certify its own scope.** 老夏 2026-09-20 22:47 §2: a runtime check that only
  requires the wrapped names to be known and duplicate-free still lets a manifest be edited to wrap a
  *different* registered tool (or to drop / reorder a slice), and `dispatch` would accept it — the
  evidence surface of the published Skill would silently change. The `SKILL_TOOL_BINDINGS` constant
  in this file is therefore the authority, the runtime compares the manifest against it on the exact
  set **and order**, and a difference is fail-closed. A skill absent from the table cannot run.
* the input caps are **byte** caps decided from `stat` + a bounded read, never by reading everything
  into memory first; stdin is read as a byte stream before UTF-8 decoding (老夏 2026-09-20 22:47 §3);
* an *unknown* exception returns a stable generic code with no internals in the caller-facing JSON;
  the diagnostic line on stderr carries only a stable event name, the exception **type** and a local
  correlation id (老夏 2026-09-20 23:51 §2). An exception *message* can carry internal paths, field
  values or clinical fragments, and stderr being captured by a trusted server is a deployment
  assumption, not a data-minimisation guarantee — so no message text, snapshot content, path or field
  value is written to stderr, to stdout or to any log file.

    tools/run_publishable_skill.py <skill-name> < snapshot.json
    tools/run_publishable_skill.py <skill-name> --synthetic-fixture <tests/fixtures/*.json>

Scope note (老夏 2026-09-20 22:12 §4): this CLI is a **development / evaluation adapter**. It is not
an authorization boundary: reading the snapshot from stdin says nothing about whether the caller is
trusted or whether the patient/record scope was authorized. In production the identity, role and
scope checks must happen *before* stdin, and this CLI must not be exposed as an end-user entry point.
"""
import argparse
import json
import re
import sys
import uuid
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
PUBLISHABLE = BACKEND / "publishable"
PLAN_LOCK = PUBLISHABLE / "PLAN.lock"
FIXTURE_ROOT = BACKEND / "tests" / "fixtures"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STATUS_VALUES = ("experimental", "candidate", "stable")
REQUIRED_SUPPLY_CHAIN = {"read_only": True, "network": "none", "filesystem": "none",
                         "arguments": "none"}
# 老夏 2026-09-20 22:47 §2 阻断 B: the frozen Skill → **exact ordered** internal tool list.
# This is reviewed code, not another mutable declaration: the runtime compares the manifest against
# it on the exact set *and* order and refuses any difference, so editing a manifest cannot widen,
# narrow or reorder what an already-published Skill reads. A skill missing from this table cannot run.
SKILL_TOOL_BINDINGS = {
    "woundtruth-record-review": ("get_record_overview", "get_measurements", "get_notes",
                                 "get_integrity"),
    "woundtruth-measurement-review": ("get_measurements",),
    "woundtruth-integrity-verify": ("get_integrity",),
    "woundtruth-note-draft": ("get_notes",),
}
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
CLINICAL_USAGE = ("usage: run_publishable_skill.py <skill-name> < snapshot.json | "
                  "--synthetic-fixture <tests/fixtures/*.json>")

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent_runtime import dispatch  # noqa: E402  (production's single implementation)


class AdapterError(Exception):
    """Fail-closed adapter error: a code, an exit status, and JSON-safe detail."""

    def __init__(self, code: str, exit_code: int = 2, **detail: object) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code
        self.detail = detail


def allowed_skills(plan_lock: Path = PLAN_LOCK) -> list[str]:
    """The publishable surface is exactly the `skills:` block of PLAN.lock — nothing else."""
    try:
        text = Path(plan_lock).read_text(encoding="utf-8")
    except OSError:
        return []
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("skills:"):
            continue
        if stripped.startswith("- "):
            names.append(stripped[2:].strip())
        elif names:                     # block over: anything after it is not an allowlist entry
            break
    return names


def _contained_root(root: Path, base: Path, code: str, **detail: object) -> Path:
    """A containment root that is not itself a symlink and stays inside `base`."""
    if Path(root).is_symlink():
        raise AdapterError(code, detail="root_symlink", **detail)
    resolved = Path(root).resolve()
    if not resolved.is_relative_to(Path(base).resolve()):
        raise AdapterError(code, detail="root_outside_base", **detail)
    return resolved


def resolve_manifest(skill: str, root: Path = PUBLISHABLE, base: Path = BACKEND) -> Path:
    """Resolve `<root>/<skill>/skill_manifest.yaml` for an allowlisted NAME only."""
    if not SKILL_NAME_RE.match(skill or ""):
        raise AdapterError("skill_name_invalid", skill=skill)
    resolved_root = _contained_root(root, base, "skill_manifest_outside_root", skill=skill)
    if skill not in allowed_skills(Path(resolved_root) / "PLAN.lock"):
        raise AdapterError("skill_not_allowed", skill=skill)
    directory = Path(root) / skill
    manifest = directory / "skill_manifest.yaml"
    if directory.is_symlink() or manifest.is_symlink():
        raise AdapterError("skill_manifest_outside_root", skill=skill, detail="symlink")
    resolved = manifest.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        # no path back to the caller: the resolved location is an internal detail, not input
        raise AdapterError("skill_manifest_outside_root", skill=skill, detail="path_mismatch")
    return resolved


def read_text_limited(path: Path, limit: int, code: str) -> str:
    """Read a file with a hard **byte** cap, without ever reading an oversized input whole.

    老夏 2026-09-20 22:47 §3: the previous version called `read_bytes()` first and only then compared
    the size — that is "refuse before parsing", not a read-time bound. Here the size is decided from
    `stat`, and the read itself stops at `limit + 1` bytes, so a file that grows between the two steps
    is still refused. Decoding is UTF-8 and a bad byte sequence is a controlled error, not a traceback.
    """
    try:
        size = Path(path).stat().st_size
        if size > limit:
            raise AdapterError(code, detail=f"too_large:{size}")
        with open(path, "rb") as stream:
            raw = stream.read(limit + 1)
    except AdapterError:
        raise
    except OSError as exc:                # no filesystem detail (paths) back to the caller
        raise AdapterError(code, detail=f"unreadable:{type(exc).__name__}") from exc
    if len(raw) > limit:
        raise AdapterError(code, detail=f"too_large:{len(raw)}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterError(code, detail="not_utf8") from exc


def read_stdin_limited(limit: int) -> str:
    """Read stdin with a **byte** cap before decoding (老夏 2026-09-20 22:47 §3).

    `sys.stdin.read(n)` counts *characters*, so multi-byte text could pass a 4 MiB byte budget. The
    byte stream is read instead, capped at `limit + 1` bytes, and only then decoded as UTF-8.
    """
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        raw = stream.read(limit + 1)
    except (OSError, UnicodeDecodeError) as exc:
        raise AdapterError("snapshot_unreadable", detail=type(exc).__name__) from exc
    if isinstance(raw, str):              # text-only stdin: judge the encoded bytes, not the characters
        raw = raw.encode("utf-8", errors="surrogatepass")
    if len(raw) > limit:
        raise AdapterError("snapshot_unreadable", detail="too_large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterError("snapshot_unreadable", detail="not_utf8") from exc


def parse_json(text: str, code: str) -> object:
    """Strict JSON: NaN/Infinity are not JSON and must not reach the snapshot."""
    def reject(value: str) -> None:
        raise AdapterError("snapshot_non_finite", detail=value)

    try:
        return json.loads(text, parse_constant=reject)
    except json.JSONDecodeError as exc:
        # position only, never the offending text (老夏 2026-09-20 23:51 §2)
        raise AdapterError(code, detail=f"invalid_json_line_{exc.lineno}") from exc


def load_manifest(path: Path) -> dict:
    """Parse a manifest as a YAML mapping; malformed YAML is a controlled error, not a traceback."""
    try:
        document = yaml.safe_load(read_text_limited(path, MAX_MANIFEST_BYTES,
                                                   "skill_manifest_unreadable"))
    except yaml.YAMLError as exc:
        # a YAML error message embeds the offending snippet and the file name → type only
        raise AdapterError("skill_manifest_invalid_yaml", detail=type(exc).__name__) from exc
    except AdapterError:
        raise
    except RecursionError as exc:          # recursive YAML aliases: refuse, never recurse
        raise AdapterError("skill_manifest_unreadable", detail="recursive_aliases") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise AdapterError("skill_manifest_unreadable", detail=type(exc).__name__) from exc
    return _mapping(document, "skill_manifest_not_mapping")


def _mapping(value: object, code: str, **detail: object) -> dict:
    if not isinstance(value, dict):
        raise AdapterError(code, got=type(value).__name__, **detail)
    return value


def resolve_snapshot(fixture: str | None, fixture_root: Path = FIXTURE_ROOT,
                     base: Path = BACKEND) -> dict:
    """Clinical path reads stdin; only `--synthetic-fixture` may name a file, inside the root."""
    if fixture in (None, "", "-"):
        return _mapping(parse_json(read_stdin_limited(MAX_SNAPSHOT_BYTES), "snapshot_unreadable"),
                        "snapshot_not_mapping")
    path = Path(fixture)
    if path.is_symlink():
        raise AdapterError("fixture_path_outside_root", detail="symlink")
    resolved = path.resolve()
    root = _contained_root(fixture_root, base, "fixture_path_outside_root")
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise AdapterError("fixture_path_outside_root", detail="outside_root_or_missing")
    if resolved.stat().st_nlink > 1:      # a hard link shares its inode with a file outside
        raise AdapterError("fixture_path_outside_root", detail="hardlink")
    try:
        text = read_text_limited(resolved, MAX_SNAPSHOT_BYTES, "snapshot_unreadable")
    except OSError as exc:
        raise AdapterError("snapshot_unreadable", detail=type(exc).__name__) from exc
    return _mapping(parse_json(text, "snapshot_unreadable"), "snapshot_not_mapping")


def raw_wrapped(document: dict) -> list:
    """The declared wrapped tools, before any coercion — ambiguity and junk must be visible."""
    single_declared = document.get("wraps_internal_tool") is not None
    many_declared = document.get("wraps_internal_tools") is not None
    if single_declared and many_declared:
        raise AdapterError("skill_wrapped_tools_ambiguous")
    many = document.get("wraps_internal_tools")
    if many_declared:
        return many if isinstance(many, list) else [many]
    single = document.get("wraps_internal_tool")
    return [] if single is None else [single]


def validate_manifest(document: dict, skill: str) -> list[str]:
    """Runtime structural validation — CI (`spec_check`) cannot stand in for this boundary."""
    document = _mapping(document, "skill_manifest_not_mapping", skill=skill)
    if document.get("name") != skill:
        raise AdapterError("skill_name_mismatch", skill=skill, declared=document.get("name"))
    if document.get("layer") != "publishable":
        raise AdapterError("skill_layer_invalid", skill=skill, layer=document.get("layer"))
    if document.get("status") not in STATUS_VALUES:
        raise AdapterError("skill_status_invalid", skill=skill, status=document.get("status"))
    supply = _mapping(document.get("supply_chain"), "skill_supply_chain_invalid", skill=skill)
    for key, expected in REQUIRED_SUPPLY_CHAIN.items():
        if supply.get(key) != expected:
            raise AdapterError("skill_supply_chain_invalid", skill=skill, key=key,
                               value=supply.get(key))
    if document.get("side_effects") != "none":
        raise AdapterError("skill_side_effects_invalid", skill=skill,
                           value=document.get("side_effects"))
    declared = raw_wrapped(document)
    if not declared:
        raise AdapterError("wraps_internal_tool_missing", skill=skill)
    if any(not isinstance(tool, str) or not tool.strip() for tool in declared):
        raise AdapterError("skill_wrapped_tools_invalid", skill=skill, tools=declared)
    tools = [tool.strip() for tool in declared]
    if len(set(tools)) != len(tools):
        raise AdapterError("skill_wrapped_tools_invalid", skill=skill, tools=tools,
                           detail="duplicate")
    # 阻断 B: the declaration is checked against the frozen binding on the exact set **and** order.
    # `dispatch` alone cannot catch this — every one of these tool names is registered in production,
    # so only the binding tells "this Skill reads exactly these slices, in this order" apart from
    # "this Skill was rebound to different evidence".
    bound = SKILL_TOOL_BINDINGS.get(skill)
    if bound is None:
        raise AdapterError("skill_binding_missing", skill=skill)
    if tools != list(bound):
        raise AdapterError("skill_binding_mismatch", skill=skill, expected=list(bound),
                           declared=tools, detail="exact_set_and_order")
    return list(bound)


def invoke(tools: list[str], snapshot: dict) -> object:
    """Call production `dispatch` for every wrapped tool; a partial read is an error, not a draft."""
    results: dict[str, object] = {}
    for tool in tools:
        result, allowed = dispatch(tool, {}, snapshot)
        if not allowed:
            # Unknown tool, or registry/plan drift: never fall back to a local implementation.
            raise AdapterError("internal_tool_failed", exit_code=3, internal=tool,
                               detail="dispatch_rejected")
        results[tool] = result
    return results[tools[0]] if len(tools) == 1 else {"evidence": results}


def log_internal(exc: BaseException) -> None:
    """Send a stable diagnostic for an unexpected failure to stderr only (老夏 2026-09-20 23:51 §2).

    Only three stable things are written: the event name, the exception **type** and a local
    correlation id — e.g. `run_publishable_skill: internal_error type=TypeError event=9f1c4a2b7d30`.
    The exception *message* is never written: an unexpected failure can be raised deep in a parser or
    dispatch path and its text may embed internal paths, field values or clinical fragments, while
    stderr being captured by a trusted server is a deployment assumption rather than a
    data-minimisation guarantee. The caller-facing JSON keeps its stable generic code; log retention
    and controlled diagnostic context belong to the production logging design, not to this adapter.
    A log *file* would be a filesystem side effect, which every manifest declares as `none`.
    """
    try:
        event = uuid.uuid4().hex[:12]
        sys.stderr.write(f"run_publishable_skill: internal_error "
                         f"type={type(exc).__name__} event={event}\n")
    except Exception:                     # noqa: BLE001 — diagnostics never change the exit path
        pass


def _stable_json(payload: dict) -> str:
    """Serialise a caller-facing payload **before** writing it, with a stable fallback.

    `json.dump` writes incrementally, so a detail that turns out not to be JSON-safe would leave a
    half-written object on stdout *and* raise past `main` — a Python traceback at the process
    boundary, which is exactly what this adapter promises never to do. Serialising first keeps the
    two failure modes apart, and the fallback is a stable generic code with no internals.
    """
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({"error": "skill_adapter_internal_error", "detail": "internal_error"},
                          ensure_ascii=False, sort_keys=True)


def emit(error: AdapterError) -> int:
    sys.stdout.write(_stable_json({"error": error.code, **error.detail}) + "\n")
    return error.exit_code


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="run_publishable_skill.py", add_help=False)
    parser.add_argument("skill")
    parser.add_argument("--synthetic-fixture", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return emit(AdapterError("unexpected_argument", detail=CLINICAL_USAGE))
    try:
        manifest_path = resolve_manifest(args.skill)
        document = load_manifest(manifest_path)
        snapshot = resolve_snapshot(args.synthetic_fixture)
        tools = validate_manifest(document, args.skill)
        payload = invoke(tools, snapshot)
    except AdapterError as error:
        return emit(error)
    except (OSError, yaml.YAMLError, ValueError, TypeError, KeyError) as exc:
        log_internal(exc)
        return emit(AdapterError("skill_adapter_error", detail="invalid_input"))
    except Exception as exc:  # noqa: BLE001 — the CLI boundary never leaks a traceback or internals
        log_internal(exc)
        return emit(AdapterError("skill_adapter_internal_error", detail="internal_error"))
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

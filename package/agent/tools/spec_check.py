#!/usr/bin/env python3
"""Bring the publishable skill layer up to the official Agent Skills directory shape (NVIDIA spec).

Checks the spec's structural rules that were missing from our generated artifacts:

  * `SKILL.md` body's FIRST section is `## Required questions` (官方心法第 2 条, 对照文档 §A2)
  * the official file set exists: SKILL.md / skill-card.md / skill_manifest.yaml /
    validators/output_schema.json / fixtures / evals / BENCHMARK.md / references
  * frontmatter carries only the official Agent Skills field set
    (`name / description / license / compatibility / metadata / allowed-tools`) and
    `metadata` carries `author / version / tags`
  * the manifest declares side effects explicitly (`side_effects: none`)

Scope note (老夏 2026-09-20 18:19 §3 阻断项 B): this checker used to also walk the
second slice implementation that lived under `code/backend/skills/`. That copy has been
removed. Later workflow skill packages in that directory are outside this checker; only the
publishable layer is checked here.

Run from anywhere; it only reads (and reports). Needs `pyyaml` from
`requirements-skills-dev.txt` (not a production dependency).
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OFFICIAL_FRONTMATTER_FIELDS = ("name", "description", "license", "compatibility",
                              "metadata", "allowed-tools")
SPEC_FILES_PUBLISHABLE = ("SKILL.md", "skill-card.md", "skill_manifest.yaml",
                          "validators/output_schema.json", "fixtures/README.md",
                          "evals/evals.json", "BENCHMARK.md", "references/README.md")


def first_section(text: str) -> str:
    body = text.split("---", 2)[2]
    for line in body.splitlines():
        if line.startswith("## "):
            return line.strip()
    return ""


def frontmatter(text: str) -> dict:
    block = text.split("---", 2)[1]
    keys = {}
    for line in block.splitlines():
        if line[:1].strip() and ":" in line:
            key, value = line.split(":", 1)
            keys[key.strip()] = value.strip()
    return keys


def report(name: str, directory: Path, spec_files: tuple) -> list:
    problems = []
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return [f"{name}: SKILL.md missing"]
    text = skill_md.read_text(encoding="utf-8")

    section = first_section(text)
    if section != "## Required questions":
        problems.append(f"{name}: first body section is {section!r}, spec requires '## Required questions'")

    front = frontmatter(text)
    for key in ("name", "description", "license"):
        if key not in front:
            problems.append(f"{name}: frontmatter missing {key}")
    for key in sorted(set(front) - set(OFFICIAL_FRONTMATTER_FIELDS)):
        problems.append(f"{name}: frontmatter field {key!r} is not part of the official "
                        f"Agent Skills set {OFFICIAL_FRONTMATTER_FIELDS}")
    block = text.split("---", 2)[1]
    if "author" not in block or "tags" not in block:
        problems.append(f"{name}: metadata.author / metadata.tags missing")
    if not re.search(r"^ {2}version:", block, re.M):
        problems.append(f"{name}: metadata.version missing (the official frontmatter has no top-level version)")

    for relative in spec_files:
        if not (directory / relative).is_file():
            problems.append(f"{name}: spec file missing {relative}")

    manifest = (directory / "skill_manifest.yaml").read_text(encoding="utf-8")
    if "side_effects:" not in manifest:
        problems.append(f"{name}: manifest does not declare side_effects")
    return problems


def main() -> int:
    problems = []
    publishable = BACKEND / "publishable"
    for directory in sorted(publishable.iterdir()):
        if (directory / "skill_manifest.yaml").is_file():
            problems += report(f"publishable/{directory.name}", directory, SPEC_FILES_PUBLISHABLE)

    if not problems:
        print("spec check: OK (Required questions first, official file set, frontmatter, side_effects)")
        return 0
    print(f"spec check: {len(problems)} problem(s)")
    for problem in problems:
        print(" -", problem)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

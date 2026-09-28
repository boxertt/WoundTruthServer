"""The publishable layer's own contract (老夏 §2 SK-01/§3/§5, §9 第 2/3 项; 2026-09-20 18:19 §2/§3).

What this file proves mechanically:

* declaration == behaviour: every publishable skill declares read-only / no network / no filesystem /
  no arguments, and keeps **no second implementation** of any slice logic;
* no drift from production: the adapter calls production's single implementation directly
  (`app.agent_runtime.dispatch`) and its output equals that slice output; a tool name that production
  does not know makes the adapter fail instead of falling back to a local copy;
* the Viewer boundary is a document-level invariant, not a table someone edits once: the permission
  matrix and its prose are scanned, and the judgement lives in two pure functions
  (`viewer_cell_violation` / `viewer_prose_violation`) that are themselves unit-tested against
  grant-smuggling fixtures — a cell that says 禁止 but also says 允许 does **not** pass (阻断项 A,
  cur-189 Finding #2/#3; cur-190 与 cur-191 两轮反例 —— 否定字夹空白/零宽、英文 not·never、
  裸「能/可/会」+风险动作 —— 都已并进夹具);
* production still runs on its own single implementation: `app.agent_runtime` imports without the
  removed tree, nothing in the backend imports it, and the delivery baseline never contained a
  second registry (cur-189 Finding #1);
* nothing leaks: no endpoint, port, credential, private path, patient identifier or model name
  appears anywhere in the publishable tree;
* no document promises results it has not produced (阻断项 C: pilot results stay flagged invalid).
"""
import json
import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from app.agent_runtime import SKILLS

BACKEND = Path(__file__).resolve().parents[1]
PUBLISHABLE = BACKEND / "publishable"
ADAPTER = BACKEND / "tools" / "run-woundtruth-skill.sh"
ADAPTER_PY = BACKEND / "tools" / "run_publishable_skill.py"
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "skill_snapshot_document.json"

LEAK_PATTERNS = (r"https?://", r":8000\b", r"11434\b", r"api[_-]?key", r"password", r"secret",
                 r"token", r"/home/[a-z]", r"\bqwen", r"192\.168\.", r"10\.\d+\.\d+\.\d+",
                 r"glm-5", r"minimax")
# The JSON Schema dialect identifier is a standard URI, not a leak of a deployment address.
ALLOWED_URLS = (r"https://json-schema\.org",)
REQUIRED_RED_LINES = ("诊断", "像素", "云端", "逐次确认", "范围之外", "匿名化", "签名等同", "文书辅助")

# 阻断项 A: a Viewer may read what is already saved, and nothing that needs a model round.
#
# cur-189 Finding #2/#3 与 cur-190 Finding #1/#2 之后，判定收成两个**纯函数**
# （guard 本身可被夹具单测，不必改文件来验假）：
#   * `viewer_cell_violation(cell)`  —— 表格：Viewer 那一格必须是「纯否决」；
#   * `viewer_prose_violation(line)` —— 散文：同一分句里 Viewer + 放行措辞 + 风险动作 = 违规。
# 三条口径（每条都踩过）：
#   1. **否决词与放行措辞同时出现时，否决不成立** ——「允许（只读推理）」「禁止（但允许提问）」
#      「不得发起；允许生成」都是在放行；
#   2. **被否定的否决词不算否决** ——「未禁止」「不禁止」「非严禁」含否决词却在放行（cur-190 #1）；
#   3. 表格格进一步要求**纯否决**：刨掉否决词后，剩下的文字里连**风险动作词**都不许有。
#      「禁止，可提问」「禁止，支持提问」「否（可提问）」「不得（仍可发起）」都在这一条上落地，
#      不必去穷举「可/支持/放行/开启/准许」这些放行同义词（那永远漏一个）。代价是
#      Viewer 列不许再复述动作名（「无权采纳、签名或写入」要写成「无权」）—— 动作名左边一列已经有了。
VIEWER_GRANT_RE = re.compile(r"允许|可以|能够|能做|可行|有权|可用|获准|开放|许可|支持|放行|开启|准许|"
                             r"\ballow(?:ed|s)?\b|\bpermit(?:ted|s)?\b|\bcan\b|\bmay\b|\bable to\b",
                             re.IGNORECASE)
VIEWER_RISKY_RE = re.compile(r"推理|起草|生成|创建|发起|采纳|写入|签名|修改|删除|提问|继续问|"
                             r"\b(?:infer|inference|create|generate|draft|adopt|write|sign|ask|question)\b",
                             re.IGNORECASE)
# 裸「能/可/会」**不进**上面那张词表（cur-191 #3）：`不可能` 刨掉 `不可` 之后会残留一个 `能`，
# 进球表就会把一句否决误判成放行。只有它**紧跟风险动作词**时才算放行（「Viewer 能生成草稿」）。
# 两个 lookbehind 是为了放行「不可能生成」「不能提问」这类真正的否决。
VIEWER_ABILITY_RE = re.compile(r"(?<!不)(?<!不可)(?:能|可|会)\s*(?:够|以|做)?\s*(?:"
                               r"推理|起草|生成|创建|发起|采纳|写入|签名|修改|删除|提问|继续问)",
                               re.IGNORECASE)
VIEWER_VETO = ("禁止", "不得", "无权", "不允许", "不能", "不可", "严禁", "越权", "做不了", "不提供",
               "只读", "forbidden", "denied", "not permitted", "permission denied")
# 表格格用的否决词表：**不含**「只读」。「只读」只有在同一格没提到风险动作时才算否决，
# 所以一格只写「只读」不算合规的否决（要求写清"禁止"）。
VIEWER_TABLE_VETO = ("禁止", "不得", "无权", "不允许", "不能", "不可", "严禁", "越权", "否",
                     "forbidden", "denied", "not permitted", "permission denied")
RISKY_ACTION = VIEWER_RISKY_RE
# 否定字：跟在否决词**前面**就把这个否决翻掉（「未禁止」= 放行）。
NEGATION_CHARS = "未不非无没"
# 否定前缀 = 中文否定字 / 英文 `not`·`never`，后面**可以**夹空白与零宽字符 ——
# 「未 禁止」「不\u200b禁止」「not forbidden」都是在放行（cur-191 #1/#2）。
# 英文这里不会误伤 `not permitted`：它本身就是否决词，前面没有第二个 not。
NEGATION_PREFIX = r"(?:[未不非无没]|\bnot\b|\bnever\b)[\s\u200b-\u200d\ufeff]*"
NEGATION_TAIL_RE = re.compile(NEGATION_PREFIX + r"$", re.IGNORECASE)
# 引号里的内容算**提及**不算主张：本文件自己那行「禁止再出现"Viewer 可推理/可起草"的表述」
# 属于引用违规写法，不该被自己抓。
QUOTED_SPAN_RE = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|`[^`]*`|\u300c[^\u300d]*\u300d")
NEGATED_VETO_RE = re.compile(NEGATION_PREFIX + "(?:" +
                             "|".join(re.escape(token) for token in sorted(VIEWER_VETO, key=len,
                                                                          reverse=True)) + ")",
                             re.IGNORECASE)
# 读一行（读取/查看/审阅…）不是「需要模型跑一次」的动作，哪怕它的宾语里带「采纳」二字
# （README 的「读取已保存的 AI 会话、草稿与采纳审计」就是这种，别当成风险行）。
READ_ONLY_ROW_RE = re.compile(r"^\s*[*_>\s]*(读取|查看|浏览|审阅|只读)")

# 阻断项 B: the removed second implementation must not survive as a dangling pointer.
REMOVED_TREE_MARKERS = ("skills/", "skill_registry")
REMOVAL_CONTEXT = ("移除", "不再有", "第二份", "gone", "removed")
# 阻断项 C: an unrun/protocol-frozen status, and pilot numbers that stay flagged invalid.
SK06_PROTOCOL_ID = "SK-06 contract 2"
SCORE_LIKE = re.compile(r"\b\d{1,3}\s*/\s*\d{1,3}\b")


def load_adapter():
    """The adapter module itself — its frozen binding table is part of the layer's contract."""
    spec = importlib.util.spec_from_file_location("run_publishable_skill_bindings", ADAPTER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def removed_slice_copies() -> list[Path]:
    """Paths that belong to the deleted second slice implementation.

    A later workflow skill package under ``code/backend/skills/`` is not a copy of
    the production evidence tools. The ban is the internal lock, the copied
    handlers, and the second registry — not the directory name.
    """
    found: list[Path] = []
    root = BACKEND / "skills"
    internal_lock = root / "PLAN.lock"
    if internal_lock.exists():
        found.append(internal_lock)
    if root.is_dir():
        for name in ("handler.py", "entrypoint.py"):
            found.extend(sorted(root.rglob(name)))
    for relative in ("app/skill_registry.py", "tests/test_skills_packaged.py"):
        path = BACKEND / relative
        if path.exists():
            found.append(path)
    return found


def skill_dirs() -> list[Path]:
    return sorted(path for path in PUBLISHABLE.iterdir()
                  if path.is_dir() and (path / "skill_manifest.yaml").is_file())


def manifest(directory: Path) -> dict:
    return yaml.safe_load((directory / "skill_manifest.yaml").read_text(encoding="utf-8"))


def wrapped_tools(document: dict) -> list[str]:
    many = document.get("wraps_internal_tools")
    if isinstance(many, list):
        return [str(item).strip() for item in many if str(item).strip()]
    single = document.get("wraps_internal_tool")
    return [str(single).strip()] if single else []


def documents() -> list[Path]:
    """Every text file in the layer — the scan targets, not just the obvious ones."""
    return sorted(path for path in PUBLISHABLE.rglob("*")
                  if path.is_file() and path.suffix in {".md", ".yaml", ".json", ".yml"})


def benchmark_files() -> list[Path]:
    return sorted(PUBLISHABLE.rglob("BENCHMARK.md"))


def markdown_tables(text: str) -> list[list[list[str]]]:
    """Group consecutive `| a | b |` lines into tables of cells (no markdown dependency)."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|"):
            current.append([cell.strip() for cell in stripped.strip("|").split("|")])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _strip_veto(text: str, tokens) -> str:
    """刨掉所有否决词之后剩下的文字（长的先刨，避免「不允许」被「允许」抢先）。

    被否定的否决词只刨掉**词**、留下那个否定字（「不可能」→「不能」，cur-191 #3）：
    否则残留的裸「能」会被当成放行，把一句真否决误判成放行。
    """
    pattern = re.compile("|".join(re.escape(token)
                                  for token in sorted(tokens, key=len, reverse=True)),
                          re.IGNORECASE)
    out: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        prefix = text[position:match.start()]
        out.append(prefix)
        if NEGATION_TAIL_RE.search(prefix):
            out.append("")
        elif match.group(0)[0] in NEGATION_CHARS:
            out.append(match.group(0)[0])
        else:
            out.append(" ")
        position = match.end()
    out.append(text[position:])
    return "".join(out)


def _valid_vetoes(text: str, tokens) -> bool:
    """有没有**真的在否决**的词？被否定的否决词不算（「未禁止」「不 禁止」「not forbidden」= 放行）。

    与散文那条用同一套否定口径（`NEGATION_TAIL_RE`）：否定字与否决词之间允许空白/零宽字符 ——
    只看紧邻前一字符会漏掉 `未 禁止`（cur-191 #1）。
    """
    for token in tokens:
        for match in re.finditer(re.escape(token), text, re.IGNORECASE):
            if NEGATION_TAIL_RE.search(text[:match.start()]):
                continue
            return True
    return False


def viewer_cell_violation(cell: str) -> str | None:
    """Viewer 那一格是不是在放行？返回原因；None = 合规的**纯否决**。

    先刨否决词再看残留：「禁止（但允许提问）」的「允许」会留在残留里 → 违规；
    残留里连风险动作词都不许有（「禁止，可提问」→ 违规），所以不必穷举放行同义词。
    """
    smuggled = VIEWER_GRANT_RE.search(_strip_veto(cell, VIEWER_TABLE_VETO))
    if smuggled:
        return f"否决词之外仍有放行措辞 {smuggled.group(0)!r}"
    risky = VIEWER_RISKY_RE.search(_strip_veto(cell, VIEWER_TABLE_VETO))
    if risky:
        return f"否决词之外仍在提风险动作 {risky.group(0)!r}（Viewer 列只写否决）"
    if not _valid_vetoes(cell, VIEWER_TABLE_VETO):
        return "这一格没有有效的否决词（未禁止/不禁止 这类不算否决）"
    return None


def viewer_prose_violation(line: str) -> str | None:
    """同一分句里 Viewer + 放行措辞 + 风险动作 = 声称 Viewer 可以推理/起草。

    按分句判定：否决词只对它所在的那一句负责，「Viewer 允许生成草稿，但不得发起会话」照样违规。
    引号里的内容算提及不算主张；被否定的否决词（「Viewer 不禁止生成草稿」）本身就算放行。
    """
    line = QUOTED_SPAN_RE.sub(" ", line)
    for clause in re.split(r"[。；;，,、]", line):
        if "viewer" not in clause.lower():
            continue
        risky = VIEWER_RISKY_RE.search(clause)
        if not risky:
            continue
        if NEGATED_VETO_RE.search(clause):
            return f"分句 {clause.strip()!r} 把否决词反过来用（视为放行）"
        residue = _strip_veto(clause, VIEWER_VETO)
        granted = VIEWER_GRANT_RE.search(residue) or VIEWER_ABILITY_RE.search(residue)
        if granted:
            return f"分句 {clause.strip()!r} 声称 Viewer 可以{granted.group(0)}…{risky.group(0)}"
    return None


class PublishableLayerTests(unittest.TestCase):
    def test_pilot_plan_lock_matches_the_directories(self):
        lock = yaml.safe_load((PUBLISHABLE / "PLAN.lock").read_text(encoding="utf-8"))["skills"]
        self.assertEqual(sorted(lock), sorted(path.name for path in skill_dirs()))

    def test_each_skill_declares_the_read_only_contract(self):
        for directory in skill_dirs():
            document = manifest(directory)
            supply = document["supply_chain"]
            self.assertEqual(document["layer"], "publishable")
            self.assertIs(supply["read_only"], True)
            self.assertEqual(supply["network"], "none")
            self.assertEqual(supply["filesystem"], "none")
            self.assertEqual(supply["arguments"], "none")
            self.assertEqual(supply["handler"], "adapter")
            self.assertEqual(document["side_effects"], "none", directory.name)

    def test_viewer_matrix_never_grants_inference_or_drafts(self):
        """阻断项 A, table half: parse the matrix and check the Viewer **column**.

        2026-09-20 的这个缺陷（「生成备注草稿：Viewer 允许（只读推理）」）是一行**表格**，
        它本身并不含 "Viewer" 字样 —— 所以必须按表头定位列，不能只搜行里的关键字。
        判据在 `viewer_cell_violation`（纯否决才算过）；读行（「读取…采纳审计」）不算风险行。
        """
        rows_checked = 0
        for path in documents():
            if path.suffix not in {".md", ".yml", ".yaml"}:
                continue
            for table in markdown_tables(path.read_text(encoding="utf-8")):
                header = table[0]
                if not any("Viewer" in cell for cell in header):
                    continue
                column = next(index for index, cell in enumerate(header) if "Viewer" in cell)
                for row in table[1:]:
                    if len(row) <= column:
                        continue
                    action = row[0]
                    if not RISKY_ACTION.search(action) or READ_ONLY_ROW_RE.search(action):
                        continue
                    rows_checked += 1
                    cell = row[column]
                    violation = viewer_cell_violation(cell)
                    self.assertIsNone(violation,
                                      f"{path.relative_to(PUBLISHABLE)}: 「{action}」的 Viewer 格"
                                      f"{violation} -> {cell!r}")
        self.assertGreaterEqual(rows_checked, 3, "没有扫到 Viewer 权限矩阵的正文行（表结构变了？）")

    def test_viewer_prose_never_grants_inference_or_drafts(self):
        """阻断项 A, prose half: a sentence is enough, a table is not required."""
        for path in documents():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                violation = viewer_prose_violation(line)
                self.assertIsNone(violation, f"{path.relative_to(PUBLISHABLE)}:{number}: {violation}")

    def test_the_viewer_guard_flags_grant_smuggling(self):
        """cur-189 #2/#3 与 cur-190 #1/#2 的夹具：**直接喂判据**，不必改文件来验假。

        - 否决词 + 同格放行（`禁止（但允许提问）`）= 违规；
        - 被否定的否决词不算否决（`未禁止` / `不禁止` / `非禁止` / `未严禁`）= 违规；
        - 英文放行（`Allow` / `Permitted`）= 违规；
        - 刨掉否决后仍提风险动作词（`禁止，可提问` / `否（可提问）` / `禁止，支持提问` /
          `禁止，放行提问` / `禁止，开启推理` / `禁止，准许生成` / `不得（仍可发起）`）= 违规。
        """
        clean = ("**禁止**", "禁止（网关 403）", "不允许", "不允许（见 §3）",
                 "not permitted", "Forbidden", "denied", "严禁", "不能", "不可")
        for cell in clean:
            self.assertIsNone(viewer_cell_violation(cell), f"合规纯否决被误判：{cell!r}")
        smuggled = ("允许（只读推理）", "禁止（但允许提问）", "不得发起；允许生成",
                    "禁止但允许继续提问", "Allow", "Permitted", "只读", "可推理", "",
                    "未禁止", "不禁止", "非禁止", "未严禁",
                    "禁止，可提问", "否（可提问）", "禁止，支持提问", "禁止，放行提问",
                    "禁止，开启推理", "禁止，准许生成", "不得（仍可发起）",
                    # cur-191 #1/#2：否定字与否决词之间夹空白/零宽字符，或英文 not·never，
                    # 都还是在放行 —— 否定口径必须与散文那条一致。
                    "未 禁止", "不 禁止", "无 禁止", "未\u200b禁止",
                    "not forbidden", "Not Forbidden", "never forbidden")
        for cell in smuggled:
            self.assertIsNotNone(viewer_cell_violation(cell), f"夹具没被抓住：{cell!r}")
        # 「纯否决」口径的已知代价：Viewer 列不许复述左边的动作名（要写成「无权」）。
        # 这属于**保守方向**（fail-loud），不是漏检 —— 写出来是为了让口径可被复核。
        self.assertIsNotNone(viewer_cell_violation("无权采纳、签名或写入"))

    def test_the_viewer_prose_guard_flags_grant_smuggling(self):
        """同上，散文判据的夹具（含「否决词在另一半」「引号提及」「把否决反过来用」）。"""
        clean = ("Viewer 只能读取", "Viewer 无权采纳、签名或写入。", "Viewer 越权写入",
                 '禁止再出现"Viewer 可推理/可起草"的表述。',
                 "injection chain, and the Viewer/physician permission matrix.",
                 '> Viewer 能做的只有"读已经存下来的东西"。',
                 # cur-191 #3：真否决里带「能/不能」，不能被当成放行。
                 "Viewer 不能生成草稿", "Viewer 不可能生成草稿",
                 "Viewer not permitted to create a session")
        for line in clean:
            self.assertIsNone(viewer_prose_violation(line), f"合规句被误判：{line!r}")
        smuggled = ("Viewer 允许生成草稿", "Viewer 推理可用", "Viewer 获准生成草稿",
                    "Viewer 允许只读推理", "Viewer 可以采纳草稿", "Viewer 可以起草；不得别的",
                    "Permitted for a Viewer to create a session",
                    "Viewer 可提问", "Viewer 支持生成草稿", "Viewer can generate drafts",
                    "Viewer may create a session", "Viewer is able to generate drafts",
                    "Viewer 不禁止生成草稿",
                    # cur-191 #1/#2/#3：夹空白/零宽的否定、英文 not、裸「能」+风险动作。
                    "Viewer 未 禁止生成草稿", "Viewer not forbidden to create",
                    "Viewer 能生成草稿", "Viewer 可提问")
        for line in smuggled:
            self.assertIsNotNone(viewer_prose_violation(line), f"夹具没被抓住：{line!r}")

    def test_production_runtime_boots_without_the_removed_tree(self):
        """cur-189 Finding #1（blocker）：删掉 registry 之后**生产侧**仍能导入。

        对象是生产唯一实现 `app.agent_runtime`，不是适配层：它从不 import 已删模块，
        `SKILLS` / `EVIDENCE_PLAN` / `dispatch` 都在它自己文件里。
        （它相对交付基线 `c0073e7` 逐字节未改 —— 这一条由送审时的 `git diff` 输出旁证。）
        """
        import app.agent_runtime as runtime
        self.assertTrue(callable(runtime.dispatch))
        self.assertTrue(runtime.SKILLS, "生产注册表空了")
        self.assertTrue(runtime.EVIDENCE_PLAN, "生产证据计划空了")
        source = (BACKEND / "app" / "agent_runtime.py").read_text(encoding="utf-8")
        for marker in ("skill_registry", "load_skills", "from .skills", "import skills"):
            self.assertNotIn(marker, source, f"生产运行时又依赖已删的第二实现：{marker}")
        self.assertEqual(removed_slice_copies(), [])

    def test_no_module_imports_the_removed_tree(self):
        """整个后端再没有任何模块 import 已删的第二实现（不只是文档里不再提它）。"""
        offenders = []
        for path in BACKEND.rglob("*.py"):
            if ".venv" in path.parts or "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.match(r"\s*(from|import)\s", line) and re.search(r"skill_registry|\bskills\.", line):
                    offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "还有模块在 import 已删的第二实现")

    def test_skill_md_leads_with_required_questions(self):
        """Official shape: `## Required questions` is the FIRST body section (对照文档 §A2)."""
        for directory in skill_dirs():
            body = (directory / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
            sections = [line.strip() for line in body.splitlines() if line.startswith("## ")]
            self.assertEqual(sections[0], "## Required questions", directory.name)

    def test_official_spec_files_exist(self):
        spec = ("SKILL.md", "skill-card.md", "skill_manifest.yaml", "validators/output_schema.json",
                "fixtures/README.md", "references/README.md", "evals/evals.json", "BENCHMARK.md")
        for directory in skill_dirs():
            for relative in spec:
                self.assertTrue((directory / relative).is_file(), f"{directory.name}/{relative}")

    def test_no_second_implementation_of_slice_logic(self):
        """阻断项 B：本层只能包生产，不能自带一份切片实现。

        已移除的是第二份切片实现：`code/backend/skills/PLAN.lock`、其下的
        `scripts/handler.py` 与 `scripts/entrypoint.py`，以及 `app/skill_registry.py`。
        同一目录里后来的工作流技能包不是那份复制实现，不在这道禁令内。
        """
        for directory in skill_dirs():
            self.assertFalse((directory / "scripts").exists(), directory.name)
        self.assertEqual(removed_slice_copies(), [],
                         "已移除的第二份切片实现又出现了")

    def test_no_document_points_at_the_removed_internal_tree(self):
        """删除第二实现后，文档里不能留下指向它的**悬空指针**（evals/BENCHMARK/references 都踩过）。

        只有「说明它被移除」的句子可以提到它 —— 每处提及都必须同时带移除语境。
        """
        for path in documents():
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if not any(marker in line for marker in REMOVED_TREE_MARKERS):
                    continue
                self.assertTrue(any(context in line for context in REMOVAL_CONTEXT),
                                f"{path.relative_to(PUBLISHABLE)}:{number}: 指向已移除的内部实现：{line}")

    def test_benchmark_files_declare_an_explicit_status(self):
        """阻断项 C：没跑就是 not executed；声称跑过就必须点名协议版本。"""
        self.assertTrue(benchmark_files(), "没有任何 BENCHMARK.md")
        for path in benchmark_files():
            text = path.read_text(encoding="utf-8")
            match = re.search(r"^Status: (.+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, f"{path.relative_to(PUBLISHABLE)}: 没有 Status 行")
            status = match.group(1).strip()
            self.assertTrue(status.startswith(("not executed", "executed")),
                            f"{path.relative_to(PUBLISHABLE)}: Status 必须是 not executed / executed")
            if status.startswith("executed"):
                self.assertIn(SK06_PROTOCOL_ID, text,
                              f"{path.relative_to(PUBLISHABLE)}: 声称已执行就必须写明协议版本")

    def test_pilot_results_are_always_flagged_invalid(self):
        """阻断项 C：提到 pilot（或任何 x/y 形分数）的文件必须同时标 invalid。"""
        for path in benchmark_files() + [PUBLISHABLE / "README.md"]:
            text = path.read_text(encoding="utf-8")
            if "pilot" not in text.lower() and not SCORE_LIKE.search(text):
                continue
            self.assertIn("invalid", text.lower(),
                          f"{path.relative_to(PUBLISHABLE)}: 引用了未按协议跑出的分数却没标 invalid")

    def test_evals_point_at_the_layer_benchmark(self):
        for directory in skill_dirs():
            evals = json.loads((directory / "evals" / "evals.json").read_text(encoding="utf-8"))
            self.assertIn("publishable/BENCHMARK.md", evals["method"], directory.name)
            self.assertIn("with skill vs without skill", evals["method"], directory.name)

    def test_the_adapter_calls_the_production_dispatch(self):
        """机械证明（阻断项 B）：适配层直接调生产唯一实现，不转手第二份实现。

        断言的是**源码**：导入生产 `dispatch`；不得再出现子进程桥接到 `skills/<tool>/scripts/entrypoint.py`。
        """
        source = ADAPTER_PY.read_text(encoding="utf-8")
        self.assertIn("from app.agent_runtime import dispatch", source)
        self.assertNotIn("entrypoint.py", source)
        self.assertNotIn("subprocess", source)

    def test_wrapped_internal_tools_exist_in_the_production_registry(self):
        for directory in skill_dirs():
            for tool in wrapped_tools(manifest(directory)):
                self.assertIn(tool, SKILLS, f"{directory.name}: {tool}")

    def test_the_orchestrator_covers_the_whole_production_evidence_plan(self):
        """woundtruth-record-review must read every planned slice, in the plan's order."""
        from app.agent_runtime import EVIDENCE_PLAN
        orchestrator = PUBLISHABLE / "woundtruth-record-review"
        self.assertTrue(orchestrator.is_dir(), "the orchestration skill is missing")
        self.assertEqual(wrapped_tools(manifest(orchestrator)), list(EVIDENCE_PLAN))

    def test_every_production_tool_is_reachable_through_the_layer(self):
        from app.agent_runtime import EVIDENCE_PLAN
        covered = sorted({tool for directory in skill_dirs()
                          for tool in wrapped_tools(manifest(directory))})
        self.assertEqual(covered, sorted(EVIDENCE_PLAN))

    def test_the_runtime_binding_is_frozen_and_covers_the_published_surface(self):
        """老夏 2026-09-20 22:47 §2 阻断 B：绑定表是**受审代码常量**，并与发布面、生产证据计划对齐。

        manifest 不能自证作用域；这张表才是运行时比对的权威，所以它必须：与 `PLAN.lock`/目录一一对应、
        与生产证据计划逐项同序、每个工具都在生产注册表里、且自身无重复。
        """
        from app.agent_runtime import EVIDENCE_PLAN
        bindings = load_adapter().SKILL_TOOL_BINDINGS
        lock = yaml.safe_load((PUBLISHABLE / "PLAN.lock").read_text(encoding="utf-8"))["skills"]
        self.assertEqual(sorted(bindings), sorted(lock))
        self.assertEqual(sorted(bindings), sorted(path.name for path in skill_dirs()))
        for skill, bound in bindings.items():
            with self.subTest(skill=skill):
                self.assertEqual(len(set(bound)), len(bound), "绑定表里有重复工具名")
                for tool in bound:
                    self.assertIn(tool, SKILLS, f"{skill}: {tool}")
        self.assertEqual(list(bindings["woundtruth-record-review"]), list(EVIDENCE_PLAN))
        self.assertEqual(sorted({tool for bound in bindings.values() for tool in bound}),
                         sorted(EVIDENCE_PLAN))

    def test_adapter_output_equals_the_internal_slice(self):
        """No drift: the publishable entry point returns exactly what production computes."""
        from app.agent_runtime import dispatch
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        for directory in skill_dirs():
            tools = wrapped_tools(manifest(directory))
            completed = subprocess.run([str(ADAPTER), directory.name,
                                        "--synthetic-fixture", str(SNAPSHOT)],
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            if len(tools) > 1:
                expected = {"evidence": {tool: dispatch(tool, {}, document)[0] for tool in tools}}
            else:
                expected = dispatch(tools[0], {}, document)[0]
            self.assertEqual(json.loads(completed.stdout), expected, directory.name)

    def test_skill_md_agrees_with_the_manifest(self):
        for directory in skill_dirs():
            text = (directory / "SKILL.md").read_text(encoding="utf-8")
            front = {}
            for line in text.split("---", 2)[1].splitlines():
                if line[:1].strip() and ":" in line:
                    key, value = line.split(":", 1)
                    front[key.strip()] = value.strip()
            self.assertEqual(json.loads(front["name"]), directory.name, directory.name)
            self.assertEqual(json.loads(front["description"]),
                             manifest(directory)["description"], directory.name)

    def test_red_lines_are_all_declared(self):
        for directory in skill_dirs():
            text = (directory / "skill_manifest.yaml").read_text(encoding="utf-8")
            for phrase in REQUIRED_RED_LINES:
                self.assertIn(phrase, text, f"{directory.name}: missing red line {phrase}")
            self.assertIn("not_for:", text)
            self.assertGreaterEqual(text.count("    - \""), 9, directory.name)

    def test_nothing_sensitive_is_declared_anywhere_in_the_layer(self):
        for path in documents():
            body = path.read_text(encoding="utf-8")
            for allowed in ALLOWED_URLS:
                body = re.sub(allowed, "", body)
            for pattern in LEAK_PATTERNS:
                self.assertIsNone(re.search(pattern, body), f"{path.relative_to(PUBLISHABLE)}: {pattern}")

    def test_evals_carry_negative_cases_and_exclude_cloud_models(self):
        for directory in skill_dirs():
            evals = json.loads((directory / "evals" / "evals.json").read_text(encoding="utf-8"))
            kinds = {case["kind"] for case in evals["cases"]}
            self.assertIn("negative", kinds, directory.name)
            self.assertTrue(evals["cloud_models"]["excluded"], directory.name)


if __name__ == "__main__":
    unittest.main()

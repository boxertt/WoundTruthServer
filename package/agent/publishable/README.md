# Publishable 层（对外可发布的 Skill）与内部证据工具的映射

> 依据：`LAOXIA_DECISION_AGENT_SKILLS_20260920_165253`（§2 SK-01 / §3 / §4 / §8 / §9）。
> 这一层**独立于生产运行时**：`app/agent_runtime.py` 一个字没动，生产注册表仍是它原来的那份。
> 生产运行时**不加载**本目录（第一阶段明确不接 Manifest Loader）。

## 1. Internal Tool ↔ Publishable Skill

| 内部证据工具（运行时名，**不改**） | 对外可发布 Skill | 覆盖内容 |
| --- | --- | --- |
| `get_record_overview` + `get_measurements` + `get_notes` + `get_integrity` | `woundtruth-record-review` | **编排**：按证据计划顺序读满四个切片后审阅 |
| `get_measurements` | `woundtruth-measurement-review` | 已保存测量的读取与解释（**不**从像素推断物理量） |
| `get_notes` | `woundtruth-note-draft` | 备注**草稿**（医生逐次确认后才可采纳） |
| `get_integrity` | `woundtruth-integrity-verify` | WREC/JSON、Hash、签名与证据完整性 |

四个包的 `status` 一律为 **`candidate`**（老夏 2026-09-20 22:12 §2）：本层是**研究与工程验证层**，
不是临床生产稳定能力；供应链、模型准入、端到端权限、当前版本 benchmark 与发布签名门全部通过前，
**不得**回到 `stable`。

**不采用** `wound-measure` / `wound-auto-measure` 这类会暗示"自动临床测量已经成立"的名字（§3）。
`woundtruth-report-draft` 属"以后可增加"，本阶段不建。

## 2. 患者范围由哪一层注入（§9 第 3 项）

范围**只**由可信层注入：医生确认的证据快照（`assistant_snapshot.prepare_snapshot`）已固定患者与记录范围，
Skill 与模型**都拿不到** `patient_id` / `record_id` / 文件路径参数。机械证明三条：

1. 本层每个 Skill 的 manifest 声明 `supply_chain.arguments: none`；适配层只放行**空参数对象**
   （生产 `dispatch(name, arguments, …)` 只接受 `arguments == {}`，其余一律拒绝）；
2. **临床路径不接受任何路径参数**：冻结快照只从 **stdin** 读入；只有 `--synthetic-fixture`（合成评测用）
   接受文件，且必须落在 `tests/fixtures/` 的规范根内 —— `../`、绝对路径、符号链接一律 fail-closed
   （老夏 2026-09-20 21:07 §2）；
3. **技能由名字选择，不由路径选择**：名字必须在 `publishable/PLAN.lock` 白名单内，且匹配
   `^[a-z0-9]+(?:-[a-z0-9]+)*$`；manifest 由适配层在 `publishable/` 内解析
   （`resolve()` containment + 拒符号链接），**不接受任意 manifest 路径**；
4. 请求级快照在原子上就是"当前获准范围"，Skill 是它的只读函数，没有"换一个患者"的入口。

> ⚠️ **边界澄清（老夏 2026-09-20 22:12 §4）**：从 **stdin** 读快照关掉的是「调用方传任意路径」，
> **它本身不是授权边界** —— stdin 既不证明调用方可信，也不证明 patient/record scope 已获授权。
> 本 CLI 是**开发/评测 Adapter**，只能由可信服务端在完成身份、角色与 scope 校验**并冻结快照之后**调用；
> 生产接入时授权边界必须位于 **stdin 之前**；直接调用本 CLI **不构成**临床授权，也不得作为面向终端用户的生产入口。

## 3. 权限矩阵（Viewer / Editor·Owner × 读取 / 推理 / 草稿 / 采纳 / 写入）

口径来源：`LAOXIA_DECISION_VIEWER_AI_READONLY_20260920.md`（老夏裁定；本矩阵与它逐条对齐，**不是我的解释**）。

| 动作 | Viewer | Editor / Owner |
| --- | --- | --- |
| 读取**已保存**的 AI 会话、草稿与采纳审计 | 允许只读 | 允许 |
| 创建会话 / 继续提问 / 发起推理 / **生成新的备注草稿** | **禁止** | 允许 |
| **采纳草稿进临床记录** | **禁止**（网关 403） | 允许，且**逐次确认** |
| 签名 / 修改 / 删除临床记录 | 禁止 | 仅经既有修订通道，本层不提供 |

> Viewer 能做的只有"读已经存下来的东西"。**任何需要模型跑一次的动作用户都做不了** ——
> 包括生成新的备注草稿（那本身就是一次推理）。服务端入口前的认证网关实施该边界，不靠前端隐藏按钮。
> 判据在 `tests/test_publishable_layer.py` 的两个纯函数里，口径写死在下面两条：
> **表格那一格必须是纯否决** —— 刨掉否决词之后，残留里不许再出现放行措辞或风险动作词，
> 所以 Viewer 这一列只写「禁止」，不复述左边那一列的动作名（复述会判违规，属保守方向）；
> **散文按分句查**「Viewer + 放行措辞 + 风险动作词」，把否决词反过来用的写法（「未禁止」、
> 「未 禁止」、「not forbidden」）以及引号里的引用都不算合规否决。这两条都会被夹具单测
> （同一用例里直接喂判据）。

## 4. 每个 Skill 都必须声明的红线

- 诊断、治疗决策、处方或任何自主临床决策
- 从彩图像素或模型 Mask 直接推导物理尺寸、面积、深度或体积
- 在没有有效深度、标定和统一几何合同时输出厘米、平方厘米或体积
- 把模型输出称为监管意义上的匿名化或去标识化结果
- 未经医生逐次确认，新增、修改、采纳、签名或删除临床记录
- 访问服务端批准范围之外的患者、记录或文件
- 把患者数据发送到云端；当前临床数据推理只允许本地模型
- 把 WREC 签名等同于内容医学正确，或等同于本 Skill 本身安全
- 把输出当作诊断结论；输出只定位为临床文书辅助与工程验证材料

## 5. 适配层为什么单独放（而且只有一份实现）

`tools/run-woundtruth-skill.sh`（入口）+ `tools/run_publishable_skill.py`（解析与调用）是这个仓里
**唯一**知道"技能→内部工具→快照来源"的地方。适配层**直接调用生产唯一实现**：

```text
publishable/PLAN.lock 白名单 + 名字语法            ← 调用方只能给"名字"
        → publishable/<skill>/skill_manifest.yaml      （resolve() containment，拒符号链接）
        → app.agent_runtime.dispatch(<内部工具名>, {}, 冻结快照)      # 生产运行时调的是同一个函数
```

快照从 **stdin** 读入（**不是**授权边界，见 §2）；`--synthetic-fixture` 仅供合成评测，
路径必须落在 `tests/fixtures/` 内。

适配层还做**运行时结构验证**（老夏 2026-09-20 22:12 §3；CI 的 `spec_check` 不能代替运行时边界检查）：
manifest 必须是 mapping 且 `name` == 请求的技能名、`layer == publishable`、`status` 属于允许值、
`supply_chain` 断言 `read_only: true` 与 `network/filesystem/arguments: none`、`side_effects: none`；
`wraps_internal_tool(s)` 必须是非空、无重复、无歧义（不得两个字段同时声明）的字符串列表；
快照 JSON 必须是 object。所有格式错误都是**受控 JSON 错误 + 非零退出码**，不抛 traceback。
测试：`tests/test_publishable_manifest_validation.py`。
负向面（名字语法 / 白名单 / 越界与软链 / 快照路径 / 额外参数 / 未知内部工具）**全部 fail-closed**，
由 `tests/test_publishable_adapter_scope.py` 逐条断言。

**Skill → 内部工具的唯一可信绑定（老夏 2026-09-20 22:47 §2 阻断 B）**：manifest 不能自证作用域 ——
只校验「非空、无重复、已注册」时，把 `woundtruth-measurement-review` 改绑 `get_record_overview`
（或删掉、换序 record-review 的四个切片）**仍会通过 `dispatch`**，对外 Skill 声明的证据面就此悄悄改变。
所以适配层里有一份**受审代码常量** `SKILL_TOOL_BINDINGS`（精确有序），运行时按**精确集合与顺序**比对
manifest：任何差异 `skill_binding_mismatch`、未列入绑定表的技能名 `skill_binding_missing`，一律 fail-closed；
**实际调用用的是绑定表**，不是 manifest 自己声明的列表。负向测试（改绑、缺一个、多一个、换序、
未列出的技能名）在 `tests/test_publishable_manifest_validation.py`。

**输入上限与对外错误（老夏 2026-09-20 22:47 §3）**：文件与 stdin 的上限都是**字节**上限 —— 文件先
`stat` 再按上限有界读取（不再先整读入内存），stdin 先读字节流再 UTF-8 解码（`read(n)` 数的是字符，
多字节文本会绕过 4 MiB 的字节预算）；未知异常对外只返回稳定通用码（`skill_adapter_internal_error`），
异常详情只写 stderr（那是启动它的可信服务端的日志；写日志文件本身会违反 manifest 的 `filesystem: none`）。

**不再有第二份切片实现**：已移除内部 `PLAN.lock`、`scripts/handler.py`、`scripts/entrypoint.py` 与 `app/skill_registry.py`（老夏 2026-09-20 18:19 §3 阻断项 B）。`code/backend/skills/` 里已移除的是那份第二份切片实现，后来的工作流技能包不在这道禁令内——"两份输出今天相等"不等于"明天不漂移"。
`tests/test_publishable_layer.py` 对已移除的第二份实现做硬断言，并证明适配层输出 == 生产切片输出。
`publishable/PLAN.lock` 保留：它冻结的是**对外发布面**，不是内部工具注册表。

因此环境差异只出现在适配层；**Skill 本体不含内网地址、端口、密钥、患者标识、私有路径或部署配置**（§2 SK-05）。

## 6. 与官方 Agent Skills 目录形态的差距（如实列出，未做就是未做）

已对齐：`SKILL.md`（正文**第一小节**就是 `## Required questions`）/ `skill-card.md` /
`skill_manifest.yaml`（`intended_use.not_for`、`supply_chain`、`side_effects`、`gates`）/
`validators/output_schema.json` / `fixtures/` / `evals/` / `BENCHMARK.md` / `references/`。
`tools/spec_check.py` 会逐项核对这套结构（它只核**本层**；已移除的第二份 `skills/` 切片实现不在这里复查）。

**还没有的四项**（官方主目录里有，我们没有）：

| 缺的 | 为什么没有 | 要补需要什么 |
| --- | --- | --- |
| 每个 Skill 自带的 `tests/` 目录 | 本层的可跑用例集中在 `tests/test_publishable_layer.py`（合同）与各 `evals/evals.json`（任务集） | 为每个 Skill 写独立用例目录 |
| `skill.oms.sig`（OpenSSF Model Signing 分离式签名） | 本仓没有签名密钥，也没有 OMS 工具链 | 一把项目签名密钥 + 官方签名流程；在此之前**不伪造签名文件** |
| Tier 2 语义去重（与目录内已有 skill 做重叠检测） | 我们只有一个目录、四个技能，且它们刻意互不重叠 | 上游目录或去重工具 |
| SkillSpector 全量安全扫描（68 种漏洞模式 / 17 类） | 该工具不在本机 | 装 SkillSpector 后跑一次，结果贴进 `references/` |

这四项都不影响第一阶段的"只读技能包 + 对照评测"，**但对外宣称时必须按差距说**，不能暗示已经过完整发布管线。

## 7. SK-06 对照评测：口径与现状（阻断项 C）

- 协议与结果**只**写在 `publishable/BENCHMARK.md`；四个 Skill 自己的 `BENCHMARK.md` 指回它，
  不各自维护一份口径；
- **现状：已执行两轮**（`Status: executed`，2026-09-20）：
  - **contract 2**（全量）：设备上 3 个标签、10 个任务 × 3 次配对重复 → **60 个配对格**
    （90 个标签格只作审计留档）；失败运行 0、空回答 0。逐格只记录了标签、**没有**记录运行时权重
    digest，所以本层**不**宣称「2 个唯一权重」，也**不**给出独立模型数量（老夏 2026-09-20 22:47 §1）。
    结论按老夏 2026-09-20 21:07 §5 **收窄**为：「目标 Skill 被预先选定后追加其正文，没有观察到
    安全性/正确性增益」，且**不得**外推成「整个 Skill 层没有增益」。
  - **contract 3**（量纲合同修订后的补跑）：`02` 暴露该 7B 标签把 `distanceCm` 当面积 → 量纲规则落进
    `SKILL.md` / manifest `not_for` / 负向 eval / 机器测试（版本 0.1.0 → **0.2.0**）→
    只重跑绑定该 Skill 的 4 个任务（24 配对格）。结果：A（7B）的量纲错误消失
    （with-skill 0/12 信号，且 `02`/`03` 人工复核全对；同一历史标签的 without-skill 组仍有 2 次编造面积、
    2/3 次量纲错述）。范围限定、延迟只作观察值等要求写在 `BENCHMARK.md` §3.5。
  - 结果表、逐任务表与**逐条人工复核**写在 `BENCHMARK.md` §3；完整可复核材料（每格的 `model` /
    `seed` / 输入输出哈希 / 耗时 / 用量）在仓库外：`~/sk06-results.contract2.json`、
    `~/sk06-results.contract3-measurement.json`；
- 2026-09-20 的旧一轮（曾报 69/100）已归档为 **pilot / invalid**（GB10 `~/sk06-pilot-invalid-20260920.json`）：
  它同时改了提示词与证据表示、从未注入任何 `SKILL.md` 正文、每格只跑一次、语言固定中文、
  还把提示注入一律要求成"整次拒绝"。它的数字**不得**进入 README、征文或比赛材料；
- 正式重跑的**唯一自变量** = 是否追加目标 Skill 的规范化 `SKILL.md` 正文；快照、证据 JSON、序列化、
  权限硬门、模型与生成参数两组**逐字节相同**。`tools/sk06_benchmark.py --dry-run` 出两组哈希对账，
  每次正式运行前 `assert_contract` 再硬断言一遍。

## 8. 模型准入（未来：按权重 digest 建准入；历史结果：只能按观测标签陈述）

来源：老夏 2026-09-20 21:07 §4。SK-06 contract 2 里那个 7B 标签（本层代号 A）**两组都服从了恶意备注**，
所以「Skill 正文能不能保护小模型」在本合同下的答案是否 —— 由此产生的产品门禁：

1. 患者级 Agent 的允许模型按**权重 digest / 经过验证的模型身份**管理，**不按标签**：标签可重复、可伪造，
   digest 不能。**但本轮逐格没有记录 digest**：建表时读到的 digest 只是设备当时的状态、未绑定到历史运行，
   所以本层的模型身份陈述**只按观测标签**，不能反过来用 digest 追认历史运行；
2. **准入按 digest 建立，历史失败运行的身份不被追认**：未来的患者级 allowlist 按权重 digest（或等价的
   不可变模型身份）建立；但在**逐格 digest 绑定**与**重新资格测试**完成之前，**建表时观察到的 7B 候选
   以及任何尚未资格化的 7B 都不得进入患者级 allowlist** —— `woundtruth-note-draft` 与
   `woundtruth-record-review` 面向患者级场景时不得使用它们。建表时读到的 digest 只是设备当时的观察值，
   **不得**据此把它追认为历史失败运行（本层代号 A 那条标签）的已证实身份；
3. 备注正文按**不可信证据**处理：后续生产接入需要服务端固定系统指令、结构化证据边界与专门的提示注入回归，
   **不得**宣称 Skill 正文提供了安全隔离；
4. **不宣称独立模型数量**：逐格没有 digest，60 个配对格**不能**外推成「2 个已验证独立权重」；对外只用
   「历史运行观测标签」陈述，不写「按唯一权重聚合」。

> ⚠️ **落地状态（老夏 2026-09-20 22:12 §5、2026-09-20 23:51 §1）**：以上是**待实现的产品策略**，
> **当前未在生产运行时强制执行** —— 生产侧既没有按 digest 的模型 allowlist，也没有拦截 7B 的代码路径。
> 生产实现只能**按未来的逐格 digest 绑定**建立准入；任何按 digest 的生产 allowlist 实现
> **需老夏另行授权**。在获得授权并落地之前，**不得**宣称该门禁已部署或已生效，也**不得**把后来读到的
> digest 说成「已按 digest 排除」了历史运行。

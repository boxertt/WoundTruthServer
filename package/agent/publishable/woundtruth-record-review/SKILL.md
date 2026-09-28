---
name: "woundtruth-record-review"
version: "0.1.0"
description: "Use when a clinician or engineer asks for a full review of the approved evidence scope: what was recorded, what was measured, what notes exist and whether the package is intact."
license: Apache-2.0
metadata:
  author: WoundTruth team
  tags: [woundtruth, publishable, read-only, clinical-workspace, agent-skill]
  layer: publishable
  wraps_internal_tools: [get_record_overview, get_measurements, get_notes, get_integrity]
---

# woundtruth-record-review

Read-only skill over the **request-scoped immutable evidence snapshot** of the WoundTruth clinical
workspace. It returns the internal evidence slice(s) it wraps, unchanged; it never touches storage,
the network or the filesystem, and it cannot write clinical data.

## Required questions

Ask these if not already clear:

1. **Which approved scope?** — 一次请求只覆盖医生已确认的一个范围（某份录像，或该患者的全部来源关联录像与时间线）。
2. **Review, or a treatment decision?** — 本 Skill 只做证据审阅与引用，不做治疗决策。

## When to use

Use when a clinician or engineer asks for a full review of the approved evidence scope: what was recorded, what was measured, what notes exist and whether the package is intact.

## When NOT to use

Do NOT use to search for, switch to, or compare other patients; do NOT use to decide treatment.

## What it returns

- `record_overview`
- `measurements`
- `notes`
- `integrity`

## What it wraps

`get_record_overview`, `get_measurements`, `get_notes`, `get_integrity` — read through the adapter, in the order above. This skill keeps no implementation of its
own: the adapter invokes those internal tools and returns their slices unchanged.

## Not for (hard limits)

- 诊断、治疗决策、处方或任何自主临床决策
- 从彩图像素或模型 Mask 直接推导物理尺寸、面积、深度或体积
- 在没有有效深度、标定和统一几何合同时输出厘米、平方厘米或体积
- 把模型输出称为监管意义上的匿名化或去标识化结果
- 未经医生逐次确认，新增、修改、采纳、签名或删除临床记录
- 访问服务端批准范围之外的患者、记录或文件
- 把患者数据发送到云端；当前临床数据推理只允许本地模型
- 把 WREC 签名等同于内容医学正确，或等同于本 Skill 本身安全
- 把输出当作诊断结论；输出只定位为临床文书辅助与工程验证材料
- 不允许搜索或切换到其他患者；范围由可信层冻结。

## Scope

The patient and recording scope is **injected by the trusted server layer** as a frozen,
request-scoped evidence snapshot. This skill takes no identifiers or paths as arguments and cannot
widen the scope. It is a read-only function of that snapshot.

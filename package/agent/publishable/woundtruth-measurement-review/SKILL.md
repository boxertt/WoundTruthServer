---
name: "woundtruth-measurement-review"
description: "Use when a clinician or engineer asks what was measured in the approved scope, with which tool, and on which source frames."
license: Apache-2.0
metadata:
  author: WoundTruth team
  version: "0.2.0"
  tags: "woundtruth, publishable, read-only, clinical-workspace, agent-skill"
  layer: publishable
  wraps_internal_tools: "get_measurements"
---

# woundtruth-measurement-review

Read-only skill over the **request-scoped immutable evidence snapshot** of the WoundTruth clinical
workspace. It returns the internal evidence slice(s) it wraps, unchanged; it never touches storage,
the network or the filesystem, and it cannot write clinical data.

## Required questions

Ask these if not already clear:

1. **Which approved scope?** — 范围由可信层冻结；本 Skill 不选患者或记录。
2. **Recorded values, or new measurements?** — 只读**已保存**的测量值；不从像素推导新的物理量。

## When to use

Use when a clinician or engineer asks what was measured in the approved scope, with which tool, and on which source frames.

## When NOT to use

Do NOT use to derive centimetres, square centimetres or volumes from images or model masks.

## What it returns

- `measurements`
- `measurementNotes`
- `recordNotes`

## What it wraps

`get_measurements` — read through the adapter, in the order above. This skill keeps no implementation of its
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
- 只报已保存的测量值；单位错误必须指出而不是换算成物理量
- 把 `distanceCm`（长度）改名、换算或解释成 `areaCm2`（面积）
- 在 `areaCm2` 缺失或为 `null` 时，用其他数字（长度、点距、图像估算、假设形状）充当面积
- 跨维度换算：长度不能变面积、面积不能变体积 —— 即使用户要求或假设形状（例如"当作正方形"）
- 输出数值不标注来源字段/测量工具/单位，或在字段与单位冲突时继续输出

## Unit and dimension contract (hard)

1. **`distanceCm` 永远是长度** —— 不得改名、换算或解释成 `areaCm2`。
2. **`areaCm2` 缺失或为 `null` 时**，只能回答「面积未记录 / 无法由现有证据得到」，**不得复用**其他数字。
3. **禁止跨维度换算**：长度不能变面积、面积不能变体积 —— 即使用户要求或假设形状（例如"当作正方形"）也不做。
4. **每个输出数值必须保留来源字段、测量工具与单位**；字段与单位冲突时**拒绝输出**并指出冲突。
5. **`line` / `curve` / `depthProfile` 的长度不能作为面积证据**；只有已保存的 `areaCm2` 才能作为面积证据。

## Scope

The patient and recording scope is **injected by the trusted server layer** as a frozen,
request-scoped evidence snapshot. This skill takes no identifiers or paths as arguments and cannot
widen the scope. It is a read-only function of that snapshot.

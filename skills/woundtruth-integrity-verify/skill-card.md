# Skill card — woundtruth-integrity-verify

## What this skill accepts

- The request-scoped, already-frozen evidence snapshot. Nothing else.
- No patient or record identifiers, no file paths, no URLs, no credentials, no arguments at all.

## What it never accepts

- A different patient or recording than the one the trusted layer froze.
- Real patient material in tests: this layer is developed and evaluated on synthetic fixtures only.

## What it wraps

`get_integrity` — invoked through the adapter; the slices are returned unchanged.

## What it does NOT prove

- That the clinical content is medically correct.
- That the package is de-identified to any regulatory standard.
- That this skill itself is safe: nothing here is a safety verdict.

## Provenance / trust pipeline

| Property | How it is enforced |
| --- | --- |
| read-only | manifest `supply_chain.read_only: true`, checked at load time |
| no network / no filesystem | manifest declares `none`; `tests/test_publishable_layer.py` scans this directory for endpoints, keys, private paths and model names |
| no arguments | manifest `supply_chain.arguments: none`; the adapter accepts a snapshot file only |
| no drift from production | the adapter invokes the internal tool(s); a test asserts the adapter output equals the production slice output |
| scope cannot widen | scope exists only inside the frozen snapshot built by the trusted layer |

## Not for

- 诊断、治疗决策、处方或任何自主临床决策
- 从彩图像素或模型 Mask 直接推导物理尺寸、面积、深度或体积
- 在没有有效深度、标定和统一几何合同时输出厘米、平方厘米或体积
- 把模型输出称为监管意义上的匿名化或去标识化结果
- 未经医生逐次确认，新增、修改、采纳、签名或删除临床记录
- 访问服务端批准范围之外的患者、记录或文件
- 把患者数据发送到云端；当前临床数据推理只允许本地模型
- 把 WREC 签名等同于内容医学正确，或等同于本 Skill 本身安全
- 把输出当作诊断结论；输出只定位为临床文书辅助与工程验证材料
- 签名只证明完整性与来源关系，不证明医学内容正确。

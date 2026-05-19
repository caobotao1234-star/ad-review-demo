# Demo 数据集说明

本目录包含 14 条精心设计的广告样本数据（demo_001 ~ demo_014），每条精确踩中一个特定的审核路径，用于验证分层审核系统的完整决策链路。

## 使用说明

- 所有 `media_path` 指向不存在的视频文件，系统会自动走 mock 模式
- mock 模式下使用 `mock_asr_text` 和 `mock_ocr_texts` 模拟 ASR/OCR 结果
- demo_001/demo_002 需要配合真实视频文件才能触发 L1 历史匹配（mock 模式下 L1 会跳过）
- demo_005 的 QR 检测需要真实视频画面中有二维码（mock 模式下 QR 不触发）

## 数据集总览

| 编号 | 场景 | 触发环节 | 期望决策 | 期望终止层 |
|------|------|----------|----------|------------|
| demo_001 | MD5 完全匹配历史违规视频 | L1 MD5 匹配 | REJECT | L1 |
| demo_002 | pHash 高相似历史违规视频 | L1 pHash 匹配 | REJECT | L1 |
| demo_003 | OCR 识别出 hard_block 词"高仿" | L2 关键词（OCR） | REJECT | L2 |
| demo_004 | ASR 转写出 hard_block 词"A货" | L2 关键词（ASR） | REJECT | L2 |
| demo_005 | 画面含二维码（QR 私域引流） | L2 QR 检测 | APPROVE（mock）/ 灰区（真实视频） | L3 |
| demo_006 | 金融敏感宣称 + 无金融资质 | L2 类目资质 | REJECT | L2 |
| demo_007 | 只命中 suspicious_slang 黑话 | L2 黑话加分 → L3 | NEXT → L3 判定 | L3 |
| demo_008 | 只缺品牌授权（无 hard_block） | L2 资质缺失加分 → L3 | NEXT → L3 判定 | L3 |
| demo_009 | 落地页价格冲突 + 私域引流词 | L2 落地页规则 → L3 | NEXT → L3 判定 | L3 |
| demo_010 | 低风险完全合规日用品 | 无风险信号 | APPROVE | L3 |
| demo_011 | 多信号累加超 L3 reject 阈值 | L3 风险融合 | REJECT | L3 |
| demo_012 | 灰区（有冲突但分数不够高） | L3 灰区 → L4 | AGENT_REVIEW | L4 |
| demo_013 | L4 Agent 高风险判定 | L4 Agent 审核 | REJECT | L4 |
| demo_014 | 医疗高敏感类目 → 强制人审 | L4 高敏感类目 | HUMAN_REVIEW | L4 |

## 各条数据详细分析

### demo_001: L1 MD5 完全匹配
- **触发条件**：视频文件与 `history_videos/violation_001.mp4` 完全相同（MD5 一致）
- **前提**：需要放入真实视频文件，mock 模式下 L1 不会触发
- **其它字段**：全部干净（L1 命中后直接跳出，后续层不执行）

### demo_002: L1 pHash 高相似
- **触发条件**：视频与历史违规视频视觉高度相似（重新编码/加水印版本）
- **前提**：需要放入真实视频文件，mock 模式下 L1 不会触发
- **其它字段**：全部干净

### demo_003: L2 OCR hard_block
- **触发词**：`mock_ocr_texts` 中的"高仿精品" → 命中 hard_block "高仿"
- **干净通道**：title、description、ASR、landing_page 均无违规词

### demo_004: L2 ASR hard_block
- **触发词**：`mock_asr_text` 中的"A货" → 命中 hard_block "A货"
- **干净通道**：title、description、OCR、landing_page 均无违规词

### demo_005: L2 QR 私域引流（需真实视频）
- **触发条件**：视频画面中含微信二维码（QR 检测）
- **mock 模式**：QR 不触发，所有文本干净 → L3 APPROVE
- **真实视频模式**：QR 加分 → 进入 L3 灰区

### demo_006: L2 金融敏感宣称 + 无资质
- **触发条件**：category="金融" + 含"保本/高收益/稳赚" + financial_license=null
- **触发逻辑**：金融敏感宣称 + 缺金融资质 → L2 直接 REJECT

### demo_007: L2 suspicious_slang → NEXT
- **触发词**：title"柜姐渠道" + description"渠道价" → suspicious_slang ×2 = +30
- **期望**：L2 risk_score=30，decision=NEXT，进入 L3

### demo_008: L2 缺品牌授权 → NEXT
- **触发条件**：category="箱包" + brand_authorization=null → +30
- **期望**：L2 risk_score=30，decision=NEXT，进入 L3

### demo_009: L2 落地页价格冲突 + 私域引流
- **触发条件**：文案含"免费" + landing_page.price=299（>100）→ +10；落地页含"加微信" → +20
- **期望**：L2 risk_score=30，decision=NEXT，进入 L3

### demo_010: L3 低风险 APPROVE
- **特点**：普通日用品，无任何风险信号
- **期望**：L2 risk_score=0 → L3 risk_score=0 → APPROVE

### demo_011: L3 多信号累加 REJECT
- **L2 信号**：内部福利(+15) + 渠道价(+15) + 缺品牌授权(+30) + 加微信(+20) + 原厂尾单(+15) = 95
- **L3 信号**：官方正品+无授权(+30) + 正品vs渠道货/尾单(+20) + 历史违规(+10) = 60
- **总分**：约 155，超过 l3_reject_score=120 → REJECT

### demo_012: L3 灰区 → AGENT_REVIEW
- **L2 信号**：缺品牌授权(+30) + 原厂尾单(+15) = 45
- **L3 信号**：正品vs渠道货/尾单(+20) = 20
- **总分**：约 65，在 21-119 之间 + 有冲突信号 → AGENT_REVIEW

### demo_013: L4 Agent 高风险 → REJECT
- **L2 信号**：懂的来(+15) + 缺品牌授权(+30) + 原厂尾单(+15) = 60
- **L3 信号**：官方正品+无授权(+30) + 正品vs渠道货/尾单(+20) + 历史违规(+10) = 60
- **总分**：约 120，但因为 l3_reject_score=120 是 >=，刚好触发 L3 REJECT...
- **调整**：history_violation_count=2 → +10，总分约 100-110 → 灰区 → AGENT_REVIEW → MockAgent 看到高分 → REJECT

### demo_014: L4 高敏感类目 → HUMAN_REVIEW
- **L2 信号**：缺医疗资质(+30)
- **L3 信号**：无额外冲突
- **总分**：约 30-40，灰区 + 医疗类目 → AGENT_REVIEW → L4 高敏感类目强制 HUMAN_REVIEW

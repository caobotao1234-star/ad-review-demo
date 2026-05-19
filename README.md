# 广告内容审核分层决策系统（Ad Review Demo）

基于 5 层分层架构的广告内容审核系统，支持 MD5/pHash 前置否决、规则引擎、风险融合、多模态 Agent 审核和策略自优化。

---

## 分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    广告素材输入                           │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  L1 历史召回层   MD5 精确匹配 / pHash 相似匹配           │
│  ─ 命中即 REJECT，短路退出 ─                            │
└────────────────────────┬────────────────────────────────┘
                         ▼ (未命中)
┌─────────────────────────────────────────────────────────┐
│  L2 规则引擎层   OCR · ASR · QR · 关键词 · 类目资质      │
│  ─ hard_block 命中即 REJECT / 金融敏感即 REJECT ─        │
└────────────────────────┬────────────────────────────────┘
                         ▼ (NEXT)
┌─────────────────────────────────────────────────────────┐
│  L3 风险融合层   一致性校验 · 文本嵌入 · 多信号加权       │
│  ─ 总分 ≥120 REJECT / ≤20 APPROVE / 中间灰区 ─         │
└────────────────────────┬────────────────────────────────┘
                         ▼ (AGENT_REVIEW)
┌─────────────────────────────────────────────────────────┐
│  L4 Agent 审核层  多模态看图 + 工具调用 + 交叉验证        │
│  ─ LLM 综合研判，高敏感类目强制 HUMAN_REVIEW ─           │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  L5 策略层       申诉复核 Agent · 策略自优化 Agent        │
└─────────────────────────────────────────────────────────┘
```

| 层级 | 模块 | 职责 | 决策能力 |
|------|------|------|----------|
| L1 | 历史召回 | MD5 精确匹配 + pHash 视觉相似匹配 | REJECT / NEXT |
| L2 | 规则引擎 | OCR/ASR/QR 提取 + 关键词 + 类目资质 | REJECT / NEXT |
| L3 | 风险融合 | 一致性校验 + 文本嵌入 + 多信号加权 | REJECT / APPROVE / AGENT_REVIEW |
| L4 | Agent 审核 | LLM 多模态研判 + function calling | REJECT / APPROVE / HUMAN_REVIEW |
| L5 | 策略层 | 申诉复核 + 关键词/阈值自优化建议 | 建议（需人工确认） |

---

## L4 Agent 能力

L4 层使用 LLM Agent 对灰区广告进行深度审核：

- **多模态看图**：将视频关键帧编码为 base64 图片，随 prompt 一起发送给视觉模型，让 Agent 直接"看到"广告画面
- **工具调用（Function Calling）**：Agent 可调用 `check_brand_database`、`verify_qualification`、`search_violation_history` 等工具获取外部信息
- **交叉验证**：对比文案宣称 vs 落地页内容 vs 资质信息 vs 视觉画面，发现矛盾点
- **高敏感类目保护**：医疗/金融等高敏感类目强制输出 HUMAN_REVIEW

---

## 快速开始

**Step 1：安装依赖**

```bash
pip install -r requirements.txt
```

**Step 2：配置 LLM API**

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API 信息
```

`.env` 示例：
```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini
```

**Step 3：运行审核**

```bash
python main.py review --meta samples/demo_003.json
```

---

## 命令示例

### 单条广告审核

```bash
python main.py review --meta samples/demo_003.json
```

输出示例：
```
[MediaPreprocessor] mock=True frame_count=0
[L1Recall] decision=NEXT reason=no_history_match
[L2RuleEngine] decision=REJECT risk_score=100 signals=['hard_block:高仿']
[Done] final_decision=REJECT output=outputs/review_result_demo_003.json
```

### 申诉复核

```bash
python main.py appeal --appeal samples/appeal_001.json
```

输出示例：
```
[L5AppealAgent] appeal_id=appeal_001 suggestion=REJECT_UPHELD confidence=0.85
  reason: 广告文案明确含有违禁词...
[Done] output=outputs/appeal_result_appeal_001.json
```

### 策略优化

```bash
python main.py optimize --logs data/optimization_logs.json
```

输出示例：
```
[L5StrategyAgent] target=reduce_false_positive
  problem: 部分正常广告被误判...
  suggestion: action=add_whitelist route=suspicious_slang words=[...]
[Done] output=outputs/strategy_suggestion.json
[Done] candidate_keywords=outputs/candidate_keywords.yaml
```

---

## Demo 数据集总览

14 条精心设计的样本，每条精确踩中一个审核路径：

| 编号 | 场景 | 触发环节 | 期望决策 | 终止层 |
|------|------|----------|----------|--------|
| demo_001 | MD5 完全匹配历史违规视频 | L1 MD5 | REJECT | L1 |
| demo_002 | pHash 高相似历史违规视频 | L1 pHash | REJECT | L1 |
| demo_003 | OCR 识别出 hard_block "高仿" | L2 关键词 | REJECT | L2 |
| demo_004 | ASR 转写出 hard_block "A货" | L2 关键词 | REJECT | L2 |
| demo_005 | 画面含二维码（私域引流） | L2 QR | 灰区 | L3 |
| demo_006 | 金融敏感宣称 + 无资质 | L2 类目 | REJECT | L2 |
| demo_007 | suspicious_slang 黑话累加 | L2→L3 | L3 判定 | L3 |
| demo_008 | 缺品牌授权（无 hard_block） | L2→L3 | L3 判定 | L3 |
| demo_009 | 落地页价格冲突 + 私域引流 | L2→L3 | L3 判定 | L3 |
| demo_010 | 低风险合规日用品 | 无风险 | APPROVE | L3 |
| demo_011 | 多信号累加超阈值 | L3 融合 | REJECT | L3 |
| demo_012 | 灰区（有冲突但分数不够） | L3→L4 | AGENT_REVIEW | L4 |
| demo_013 | L4 Agent 高风险判定 | L4 Agent | REJECT | L4 |
| demo_014 | 医疗高敏感类目 | L4 强制 | HUMAN_REVIEW | L4 |

> demo_001/002 需要真实视频文件才能触发 L1；demo_005 需要真实含二维码视频。无视频时自动走 mock 模式。

---

## 工具脚本

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `scripts/build_history_fingerprints.py` | 从 `history_videos/` 目录的视频生成指纹库 `data/history_fingerprints.json` | `python scripts/build_history_fingerprints.py` |
| `scripts/generate_ad_meta.py` | 为 `samples/` 下的真实视频批量生成配套广告 JSON | `python scripts/generate_ad_meta.py` |
| `scripts/run_all_demo.py` | 一键跑通所有样例，打印汇总报告（覆盖层/决策类型） | `python scripts/run_all_demo.py` |

---

## 配置文件

| 文件 | 说明 |
|------|------|
| `config/thresholds.yaml` | 各层决策阈值（L1 相似度、L2 拒绝分、L3 拒绝/通过分、Agent 置信度） |
| `config/keywords.yaml` | 三级关键词库：hard_block（直接拒绝）、normalized_block（归一化匹配）、suspicious_slang（加分） |
| `config/category_rules.yaml` | 类目资质要求 + 敏感宣称词（箱包/金融/医疗/功效） |
| `config/runtime.yaml` | 运行时开关：OCR/ASR/QR 启用、采样帧数、模型大小、LLM 模式 |
| `.env` | LLM API 配置：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` |

---

## 否决项短路机制

系统采用"命中即终止"的短路设计，高确定性信号优先处理：

```
MD5 精确匹配 → 直接 REJECT（L1 终止）
     ↓ 未命中
pHash 相似匹配 → 直接 REJECT（L1 终止）
     ↓ 未命中
hard_block 关键词 → 直接 REJECT（L2 终止）
     ↓ 未命中
金融敏感宣称 + 无资质 → 直接 REJECT（L2 终止）
     ↓ 未命中
L3 风险总分 ≥ 120 → 直接 REJECT（L3 终止）
     ↓ 灰区
进入 L4 Agent 深度审核
```

设计原则：确定性越高的信号越早判定，避免浪费后续计算资源。

---

## 降级机制

| 场景 | 降级行为 | 触发条件 |
|------|----------|----------|
| 视频文件不存在 | 自动走 mock 模式，使用 JSON 中的 mock_asr_text / mock_ocr_texts | 文件路径无效 |
| OCR 模型未安装 | 跳过 OCR，仅用 mock_ocr_texts | `enable_ocr: false` 或 PaddleOCR 未安装 |
| ASR 模型加载失败 | 使用 mock_asr_text 替代 | faster-whisper 加载异常 |
| LLM API 不可用 | L4 输出 HUMAN_REVIEW（兜底人审） | API 超时/报错 |
| LLM 响应超时 | 120 秒超时后降级为 HUMAN_REVIEW | 火山引擎冷启动等场景 |
| 文本嵌入模型未安装 | 跳过嵌入相似度计算，不影响其他信号 | sentence-transformers 未安装 |
| QR 检测无结果 | 跳过 QR 加分 | 视频无二维码或 mock 模式 |

---

## 常见问题

**Q: 没有视频文件能跑吗？**
A: 可以。系统自动走 mock 模式，使用 JSON 中的 `mock_asr_text` 和 `mock_ocr_texts` 模拟 ASR/OCR 结果。L1 历史匹配和 QR 检测在 mock 模式下不触发。

**Q: 支持哪些 LLM？**
A: 任何兼容 OpenAI API 格式的服务：火山引擎 Ark、DeepSeek、OpenAI、Ollama 本地部署等。在 `.env` 中配置 `LLM_BASE_URL` 即可。

**Q: L4 Agent 调用超时怎么办？**
A: 默认 timeout 为 120 秒（火山引擎冷启动可能需要较长时间）。超时后自动降级为 HUMAN_REVIEW。

**Q: 如何测试 L1 历史召回？**
A: 把违规视频放到 `history_videos/` 目录，运行 `python scripts/build_history_fingerprints.py` 生成指纹库，然后用相同视频（或重编码版本）作为输入测试。

**Q: 如何添加新的关键词？**
A: 编辑 `config/keywords.yaml`，在对应级别（hard_block / normalized_block / suspicious_slang）下添加词条。

**Q: OCR 需要额外安装吗？**
A: 是的。OCR 依赖 PaddleOCR，需手动安装：`pip install paddleocr`。不安装时系统使用 mock 数据。

**Q: 输出结果在哪？**
A: 所有审核结果 JSON 输出到 `outputs/` 目录，文件名格式为 `review_result_{ad_id}.json`。

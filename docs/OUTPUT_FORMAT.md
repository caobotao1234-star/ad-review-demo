# 审核结果 JSON 格式说明

本文档详细解释 `review_result_<ad_id>.json` 输出文件中每个字段的含义。

---

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ad_id | string | 广告 ID |
| final_decision | string | 最终决策：`APPROVE` / `REJECT` / `HUMAN_REVIEW` |
| terminated_at | string | 在哪一层终止：`L1` / `L2` / `L3` / `L4` |
| layers | array | 每一层的详细结果（按执行顺序） |
| timings | object | 每个节点的耗时（秒） |

---

## layers 数组中每个元素

| 字段 | 类型 | 说明 |
|------|------|------|
| layer | string | 层名称：`L1` / `L2` / `L3` / `L4` |
| decision | string | 该层决策：`APPROVE` / `REJECT` / `NEXT` / `AGENT_REVIEW` / `HUMAN_REVIEW` |
| risk_score | int | 该层累计风险分 |
| reason_code | string | 结构化理由代码（如 `L2_HARD_BLOCK_HIT`） |
| reason | string | 人类可读的理由文本 |
| signals | array | 命中的风险信号列表 |
| evidence | array | 证据列表 |
| extra | object | 层私有字段（如 L4 的 `confidence`、`visual_analysis`） |

---

## signals 数组中每个元素

| 字段 | 类型 | 说明 |
|------|------|------|
| source | string | 信号来源类型：`keyword` / `category` / `landing_page` / `history` / `embedding` / `consistency` / `ocr` / `asr` / `qr` |
| code | string | 信号代码（ReasonCode 枚举值） |
| detail | string | 详细描述，包含命中词和来源位置 |
| score_delta | int | 该信号贡献的风险分 |

---

## evidence 数组中每个元素

| 字段 | 类型 | 说明 |
|------|------|------|
| source | string | 证据来源类型 |
| raw | string | 原始文本（命中的关键词原文） |
| normalized | string | 归一化后的文本 |
| location | string | **精确来源位置**（见下表） |

### location 字段取值说明

| 值 | 含义 |
|----|------|
| title | 命中来自广告标题 |
| description | 命中来自广告描述 |
| ocr:frame_0001 | 命中来自 OCR 识别的第 N 帧文字 |
| asr | 命中来自 ASR 语音转写文本 |
| landing_page | 命中来自落地页文本 |
| qr_code | 命中来自二维码解码内容 |

---

## timings 字段

| 键 | 说明 |
|----|------|
| config_load | 配置文件加载耗时 |
| media_preprocess | 视频抽帧 + pHash + 音频提取耗时 |
| L1_recall | L1 MD5 + pHash 匹配耗时 |
| L2_ocr | OCR 识别耗时 |
| L2_asr | ASR 转写耗时 |
| L2_qr | QR 检测耗时 |
| L2_rule_engine | L2 规则引擎评估耗时 |
| L2_total | L2 层总耗时 |
| L3_consistency | L3 一致性检查耗时 |
| L3_embedding | L3 文本嵌入相似度计算耗时 |
| L3_fusion | L3 风险融合决策耗时 |
| L3_total | L3 层总耗时 |
| L4_agent | L4 Agent 调用耗时（含 LLM API 等待时间） |
| pipeline_total | 整个审核流水线总耗时 |

> 所有时间单位为秒（浮点数）。控制台打印时转换为毫秒显示。

---

## 示例

以下是一个完整的 `review_result` JSON 示例，展示 L2 层 evidence 精确标注来源的情况：

```json
{
  "ad_id": "ad_006",
  "final_decision": "REJECT",
  "terminated_at": "L2",
  "layers": [
    {
      "layer": "L1",
      "decision": "NEXT",
      "risk_score": 0,
      "reason_code": "L1_NO_MATCH",
      "reason": "历史指纹未命中任何记录",
      "signals": [],
      "evidence": [],
      "extra": {}
    },
    {
      "layer": "L2",
      "decision": "REJECT",
      "risk_score": 40,
      "reason_code": "L2_HARD_BLOCK_HIT",
      "reason": "命中强违规关键词: 代开发票，来源: ocr:frame_0003",
      "signals": [
        {
          "source": "keyword",
          "code": "L2_HARD_BLOCK_HIT",
          "detail": "代开发票 (来源: ocr:frame_0003)",
          "score_delta": 40
        }
      ],
      "evidence": [
        {
          "source": "keyword",
          "raw": "代开发票",
          "normalized": "代开发票",
          "location": "ocr:frame_0003"
        }
      ],
      "extra": {}
    }
  ],
  "timings": {
    "config_load": 0.004,
    "media_preprocess": 0.120,
    "L1_recall": 0.001,
    "L2_ocr": 0.350,
    "L2_asr": 0.800,
    "L2_qr": 0.005,
    "L2_rule_engine": 0.002,
    "L2_total": 1.157,
    "pipeline_total": 1.282
  }
}
```

### 示例说明

- `evidence[0].location` 为 `"ocr:frame_0003"`，表示关键词 "代开发票" 是在视频第 3 帧的 OCR 文字中命中的
- `signals[0].detail` 包含来源信息 `"代开发票 (来源: ocr:frame_0003)"`，便于快速定位问题素材
- 由于命中了 `hard_block` 关键词，L2 层直接返回 `REJECT`，流水线在 L2 终止，不再执行 L3/L4

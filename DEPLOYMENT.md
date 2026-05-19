# 部署与运行手册

从零到全部环节真实运行的傻瓜式操作指南。

---

## 你需要准备什么

| 准备项 | 说明 | 必须？ |
|--------|------|--------|
| 视频文件 | 用于测试的 .mp4 广告视频（无视频也能跑 mock 模式） | 可选 |
| LLM API Key | 任何 OpenAI 兼容 API（火山引擎 Ark / DeepSeek / OpenAI / Ollama） | L4/L5 必须 |

> 没有视频文件也能跑通 L2~L5 全链路（mock 模式）。没有 LLM API Key 时 L4 会降级为 HUMAN_REVIEW。

---

## 一键部署步骤

### Step 1: 安装系统依赖

```bash
# Ubuntu/Debian
sudo apt install ffmpeg python3.11 python3.11-venv

# macOS
brew install ffmpeg python@3.11

# Windows: 安装 Python 3.11+ 并确保 ffmpeg 在 PATH 中
```

### Step 2: 克隆项目 + 创建虚拟环境 + 安装依赖

```bash
git clone <your-repo-url> ad-review-demo
cd ad-review-demo
python3.11 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: 配置 LLM API

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 LLM 服务信息：

```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini
```

> 四种 LLM 配置示例见下方"LLM API 配置"章节。

### Step 4: 放入视频文件

```bash
# 待审核视频放到 samples/ 目录
samples/demo_001.mp4
samples/demo_002.mp4
...
samples/demo_014.mp4

# 历史违规/安全视频放到 history_videos/ 目录
history_videos/violation_001.mp4
history_videos/violation_002.mp4
history_videos/safe_001.mp4
```

命名规则：
- 待审核视频：`samples/demo_XXX.mp4`，与 `samples/demo_XXX.json` 中的 `media_path` 对应
- 历史视频：`history_videos/violation_XXX.mp4` 或 `history_videos/safe_XXX.mp4`

### Step 5: 生成历史指纹库

```bash
python scripts/build_history_fingerprints.py
```

输出：`data/history_fingerprints.json`（L1 层用于 MD5/pHash 匹配的指纹库）

### Step 6: 生成广告 JSON（可选，已有 demo 数据可跳过）

```bash
python scripts/generate_ad_meta.py
```

输出：为 `samples/` 下的视频生成配套的广告元信息 JSON 文件。

> 项目已自带 14 条 demo 数据（demo_001~014.json），如果只跑 demo 可跳过此步。

### Step 7: 一键验证全部样例

```bash
python scripts/run_all_demo.py
```

该脚本会：
1. 依次审核所有广告样例
2. 执行申诉复核
3. 执行策略优化分析
4. 打印汇总报告（覆盖了哪些层、哪些决策类型）

### Step 8: 查看输出

```bash
ls outputs/
```

输出文件：
- `outputs/review_result_demo_XXX.json` — 每条广告的审核结果
- `outputs/appeal_result_appeal_XXX.json` — 申诉复核结果
- `outputs/strategy_suggestion.json` — 策略优化建议
- `outputs/candidate_keywords.yaml` — 候选关键词建议

---

## 视频文件准备指南

### 文件存放位置

| 目录 | 用途 | 示例 |
|------|------|------|
| `samples/` | 待审核的广告视频 | `samples/demo_001.mp4` |
| `history_videos/` | 历史违规/安全视频（用于 L1 指纹库） | `history_videos/violation_001.mp4` |

### 命名规则

- 待审核视频：`demo_001.mp4` ~ `demo_014.mp4`，文件名必须与对应 JSON 中 `media_path` 字段一致
- 历史违规视频：`violation_XXX.mp4`
- 历史安全视频：`safe_XXX.mp4`

### 特殊要求的视频

| 视频 | 特殊要求 | 原因 |
|------|----------|------|
| `demo_001.mp4` | 必须与 `history_videos/violation_001.mp4` 完全相同（同一文件复制） | 测试 L1 MD5 精确匹配 |
| `demo_002.mp4` | 必须与某个历史违规视频视觉高度相似（如重编码/加水印版本） | 测试 L1 pHash 相似匹配 |
| `demo_005.mp4` | 视频画面中必须包含微信二维码 | 测试 L2 QR 私域引流检测 |

> 其他视频无特殊要求，任意广告视频即可。没有视频时系统自动走 mock 模式。

---

## 各环节真实运行检查表

| 环节 | 真实运行条件 | 验证方法 | mock 模式行为 |
|------|-------------|----------|---------------|
| L1 MD5 匹配 | 视频文件存在 + 指纹库有对应 MD5 | demo_001 输出 `terminated_at=L1` | 跳过，输出 NEXT |
| L1 pHash 匹配 | 视频文件存在 + 指纹库有相似帧 | demo_002 输出 `terminated_at=L1` | 跳过，输出 NEXT |
| L2 OCR | `enable_ocr: true` + PaddleOCR 已安装 | 日志显示 `mock=False` | 使用 mock_ocr_texts |
| L2 ASR | 视频有音轨 + faster-whisper 正常 | 日志显示 `mock=False` | 使用 mock_asr_text |
| L2 QR | 视频画面含二维码 | demo_005 输出 QR 检测结果 | 不触发 |
| L2 关键词 | 文本中含 hard_block 词 | demo_003/004 输出 `terminated_at=L2` | 正常触发 |
| L3 风险融合 | L2 输出 NEXT | demo_007~012 进入 L3 | 正常触发 |
| L4 Agent | L3 输出 AGENT_REVIEW + LLM API 可用 | demo_012~014 进入 L4 | API 不可用时降级 HUMAN_REVIEW |
| L5 申诉 | LLM API 可用 | appeal_001 有输出 | API 不可用时报错 |
| L5 策略 | LLM API 可用 | strategy_suggestion.json 有内容 | API 不可用时报错 |

---

## 配置调优

### 阈值调整（`config/thresholds.yaml`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `l1_history_match_threshold` | 0.85 | pHash 相似度阈值（越低越严格） |
| `l1_hamming_threshold` | 8 | pHash 汉明距离阈值（越大越宽松） |
| `l2_reject_score` | 60 | L2 直接拒绝的风险分阈值 |
| `l3_reject_score` | 120 | L3 拒绝阈值 |
| `l3_approve_score` | 20 | L3 通过阈值（≤ 此分数直接通过） |
| `agent_confidence_auto_threshold` | 0.7 | L4 Agent 自动决策的置信度阈值 |

### 关键词管理（`config/keywords.yaml`）

三级关键词体系：
- `hard_block`：命中即 REJECT，无需累加（如"高仿"、"A货"）
- `normalized_block`：文本归一化后匹配即 REJECT（如"1比1"→"1:1"）
- `suspicious_slang`：每命中一个加 15 分，累加后进入 L3（如"柜姐渠道"、"懂的来"）

### 类目规则（`config/category_rules.yaml`）

定义每个类目的必要资质和敏感宣称词：
- 箱包：需 `brand_authorization`
- 金融：需 `financial_license`
- 医疗：需 `medical_license`

---

## 模型下载说明

| 模型 | 用途 | 下载方式 |
|------|------|----------|
| faster-whisper (small) | ASR 语音转写 | 首次运行自动从 HuggingFace 下载 |
| PaddleOCR | 文字识别（可选） | `pip install paddleocr` 后自动下载 |
| sentence-transformers | 文本嵌入相似度（可选） | `pip install sentence-transformers` 后自动下载 |

### HuggingFace 镜像设置（国内加速）

```bash
# 方式 1: 环境变量
export HF_ENDPOINT=https://hf-mirror.com

# 方式 2: 写入 .env
echo "HF_ENDPOINT=https://hf-mirror.com" >> .env
```

> 所有模型首次运行时自动下载，无需手动操作。国内用户建议设置镜像加速。

---

## LLM API 配置

L4 Agent 和 L5 策略层需要 LLM API。支持任何 OpenAI 兼容接口，timeout 已设为 120 秒（火山引擎冷启动可能较慢）。

### 火山引擎 Ark

```
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=your-ark-api-key
LLM_MODEL=ep-xxxxxxxx-xxxx
```

### DeepSeek

```
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-deepseek-key
LLM_MODEL=deepseek-chat
```

### OpenAI

```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=gpt-4o-mini
```

### Ollama（本地部署）

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:14b
```

> L4 Agent 支持多模态看图（发送视频关键帧图片），建议使用支持视觉的模型（如 gpt-4o、qwen-vl）。
> 工具调用（function calling）需要模型支持 tools 参数。
> timeout=120 秒，火山引擎首次调用可能需要等待冷启动。

---

## FAQ

**Q: 完全没有视频文件，能跑通吗？**
A: 能。系统自动走 mock 模式，L2~L5 全链路正常运行。只有 L1 历史匹配和 L2 QR 检测在 mock 模式下不触发。

**Q: 只有 LLM API Key 没有视频，哪些环节能真实运行？**
A: L2 关键词/类目规则（用 mock 文本）、L3 风险融合、L4 Agent 审核（用文本信息研判）、L5 申诉/策略 全部真实运行。

**Q: 火山引擎 Ark 调用很慢怎么办？**
A: 首次调用可能触发冷启动，需要 30~60 秒。系统 timeout 已设为 120 秒。如果仍然超时，检查网络或换用 DeepSeek/OpenAI。

**Q: L4 Agent 的多模态看图需要什么模型？**
A: 需要支持图片输入的视觉模型（如 gpt-4o、gpt-4o-mini、qwen-vl-plus）。如果模型不支持图片，Agent 会仅基于文本信息审核。

**Q: L4 Agent 的工具调用（function calling）是什么？**
A: Agent 可以调用预定义的工具函数（如查询品牌数据库、验证资质、搜索历史违规记录），获取额外信息后做出更准确的判断。需要模型支持 OpenAI tools 格式。

**Q: 如何确认每一层都真实运行了？**
A: 运行 `python scripts/run_all_demo.py`，查看汇总报告中"覆盖的终止层"是否包含 L1~L4。如果 L1 未覆盖，说明需要放入真实视频并生成指纹库。

**Q: PaddleOCR 安装失败怎么办？**
A: PaddleOCR 是可选依赖。不安装时系统使用 JSON 中的 `mock_ocr_texts` 字段。如需真实 OCR，参考 PaddlePaddle 官方文档安装。

**Q: 如何添加新的测试视频？**
A: 三步操作：
1. 把视频放到 `samples/` 目录，命名为 `real_XXX.mp4`
2. 编辑 `scripts/generate_ad_meta.py` 中的 `AD_TEMPLATES` 列表，添加对应元信息
3. 运行 `python scripts/generate_ad_meta.py` 生成 JSON

**Q: 如何测试 L1 历史召回？**
A: 四步操作：
1. 把违规视频放到 `history_videos/` 目录
2. 运行 `python scripts/build_history_fingerprints.py` 生成指纹库
3. 把相同视频（或重编码版本）复制到 `samples/` 作为待审核视频
4. 运行 `python main.py review --meta samples/对应的.json`

**Q: 输出的 JSON 结构是什么样的？**
A: 每个审核结果包含 `ad_id`、`final_decision`（APPROVE/REJECT/HUMAN_REVIEW）、`terminated_at`（L1~L4）、`layers`（每层的详细信号和分数）。

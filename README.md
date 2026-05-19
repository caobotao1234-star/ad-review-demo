# 广告内容审核分层决策系统 (Ad Review Demo)

基于分层决策架构的广告内容审核命令行 Demo，覆盖从媒体预处理到 Agent 智能复核的完整链路。支持三种运行模式：主链路审核（review）、申诉复核（appeal）、策略优化（optimize）。

## 分层架构

```
广告素材 → MediaPreprocessor → L1 → L2 → L3 → L4 → 最终决策
                                                ↘ L5（离线）
```

| 层级 | 模块 | 职责 |
|------|------|------|
| Media | MediaPreprocessor | 视频抽帧、音频提取、指纹计算 |
| L1 | L1Recall | 历史指纹匹配，快速放行/拦截已知素材 |
| L2 | L2RuleEngine | 关键词匹配、类目资质校验、落地页规则 |
| L3 | L3RiskFusion | 一致性检测 + 语义相似度 + 风险分融合决策 |
| L4 | L4AgentReview | LLM Agent 在线复核灰区广告 |
| L5 | L5AppealAgent / L5StrategyAgent | 离线申诉复核 + 策略优化建议 |

## Agent 角色

### 在线复核 Agent（L4）

当 L3 风险分落入灰区（既不够拒绝也不够放行）时，调用 LLM Agent 进行深度复核。Agent 会综合历史案例、政策文档、证据链进行推理，输出结构化 JSON 决策。

### 离线策略优化 Agent（L5）

- **申诉 Agent**：对已拒绝广告的申诉进行复核，判断是否建议通过或需要补充材料
- **策略 Agent**：分析历史审核日志，发现规则漏洞，生成候选关键词和策略优化建议

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行三个命令

```bash
# 主链路审核
python main.py review --meta samples/ad_003.json

# 申诉复核
python main.py appeal --appeal samples/appeal_001.json

# 策略优化
python main.py optimize --logs data/optimization_logs.json
```

## Windows 开发运行

```powershell
# 1. 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量（可选，无 key 时自动使用 MockAgent）
copy .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 4. 运行
python main.py review --meta samples/ad_001.json

# 5. 运行测试
pytest tests/ -v
```

## Ubuntu 部署运行

```bash
# 1. 系统依赖
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg

# 2. 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. （可选）CUDA 加速 ASR
# 确保已安装 NVIDIA 驱动和 CUDA Toolkit
# faster-whisper 会自动检测 GPU
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 6. 运行
python main.py review --meta samples/ad_001.json
```

## 依赖说明

| 包名 | 用途 | 必需 |
|------|------|------|
| pydantic | 数据模型校验 | ✅ |
| pyyaml | 配置文件解析 | ✅ |
| python-dotenv | .env 环境变量加载 | ✅ |
| opencv-python | 视频抽帧 | ✅ |
| imagehash / Pillow | 视频指纹（pHash） | ✅ |
| numpy | 数值计算 | ✅ |
| faster-whisper | ASR 语音识别 | ✅（无 ffmpeg 时自动降级） |
| pytest / hypothesis | 测试框架 | 开发 |
| paddleocr | OCR 文字识别 | 可选 |
| sentence-transformers | 文本向量相似度 | 可选 |

## ffmpeg 安装

faster-whisper 的音频提取依赖 ffmpeg。

### Windows

1. 从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 release full 版本
2. 解压到 `C:\ffmpeg`
3. 将 `C:\ffmpeg\bin` 添加到系统 PATH
4. 验证：`ffmpeg -version`

### Ubuntu

```bash
sudo apt install -y ffmpeg
ffmpeg -version
```

> 如果没有安装 ffmpeg，系统会自动降级：跳过音频提取，使用广告 meta 中的 `mock_asr_text` 字段作为 ASR 文本。

## faster-whisper ASR 配置

在 `config/runtime.yaml` 中配置：

```yaml
enable_asr: true
asr_model_size: small      # tiny / base / small / medium / large-v3
asr_device: auto           # auto / cpu / cuda
asr_compute_type: int8_float16  # int8 / int8_float16 / float16 / float32
```

### 4090 推荐配置

```yaml
asr_model_size: large-v3
asr_device: cuda
asr_compute_type: float16
```

> 首次运行会自动下载模型文件（small ~500MB，large-v3 ~3GB）。
> 无 GPU 时 `asr_device: auto` 会自动回退到 CPU + int8。

## LLM API 配置

在 `.env` 文件中配置：

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini
```

支持任何 OpenAI 兼容 API（如 DeepSeek、通义千问、本地 Ollama 等）。

### MockAgent 说明

当 `LLM_API_KEY` 未设置或 `config/runtime.yaml` 中 `llm_enabled: false` 时，系统自动使用内置 MockAgent：

- **L4 复核**：根据风险分高低返回 REJECT/APPROVE/HUMAN_REVIEW
- **L5 申诉**：根据是否有补充材料返回建议
- **L5 策略**：返回固定的策略优化建议结构

MockAgent 保证系统在无 LLM 环境下完整可运行，输出结构与真实 Agent 一致。

## 命令示例与输出

### review 命令

```bash
python main.py review --meta samples/ad_003.json
```

输出 `outputs/review_result_ad_003.json`：

```json
{
  "ad_id": "ad_003",
  "final_decision": "APPROVE",
  "terminated_at": "L3",
  "layers": [...]
}
```

### appeal 命令

```bash
python main.py appeal --appeal samples/appeal_001.json
```

输出 `outputs/appeal_result_appeal_001.json`：

```json
{
  "appeal_id": "appeal_001",
  "appeal_suggestion": "NEED_MORE_MATERIALS",
  "confidence": 0.65,
  "reason": "...",
  "required_extra_materials": ["品牌授权书"],
  "policy_refs": ["policy_brand_001"]
}
```

### optimize 命令

```bash
python main.py optimize --logs data/optimization_logs.json
```

输出：
- `outputs/strategy_suggestion.json` — 策略优化建议
- `outputs/candidate_keywords.yaml` — 候选关键词列表

```json
{
  "optimization_target": "减少箱包类目误放行",
  "problem": "黑话词汇未被现有规则覆盖",
  "suggestions": [...],
  "requires_human_approval": true
}
```

## Demo Mock vs 生产替换

| 模块 | Demo 行为 | 生产替换方案 |
|------|-----------|-------------|
| MediaPreprocessor | 无视频文件时生成 mock 帧数据 | 接入真实视频存储，抽帧+音频提取 |
| L1Recall | 本地 JSON 指纹库匹配 | 接入 Redis/Milvus 向量库 |
| L2 OCR | 使用 meta 中 mock_ocr_texts | 接入 PaddleOCR / 云端 OCR API |
| L2 ASR | 无 ffmpeg 时使用 mock_asr_text | 部署 faster-whisper GPU 服务 |
| L2 QR | 基于 OpenCV 简单检测 | 接入专业二维码解析服务 |
| L3 TextEmbedding | token overlap 简单相似度 | 接入 sentence-transformers / BGE |
| L4/L5 Agent | MockAgent 确定性返回 | 接入 GPT-4o / DeepSeek / 自部署模型 |
| ReportWriter | 本地 JSON 文件输出 | 接入审核平台 API / 消息队列 |

## 常见问题

### 没有视频文件怎么办？

系统会自动降级为 mock 模式，使用广告 meta JSON 中的 `mock_asr_text` 和 `mock_ocr_texts` 字段。所有 samples 目录下的示例都不依赖真实视频文件。

### 没有安装 ffmpeg 怎么办？

音频提取会跳过，ASR 使用 meta 中的 mock 文本。不影响主链路运行。

### 没有 GPU 怎么办？

faster-whisper 会自动回退到 CPU 模式（`asr_device: auto`）。Demo 场景下由于使用 mock ASR 文本，GPU 不是必需的。

### ASR 模型下载失败怎么办？

1. 检查网络连接
2. 可手动下载模型放到 `~/.cache/huggingface/hub/` 对应目录
3. 或设置 `enable_asr: false` 跳过 ASR，使用 mock 文本

### 没有 LLM API Key 怎么办？

系统自动使用 MockAgent，L4/L5 层会返回确定性的 mock 结果。所有命令均可正常运行，输出结构与接入真实 LLM 时一致。

### 测试怎么运行？

```bash
# 运行全部测试
pytest tests/ -v

# 只运行单元测试（不含 CLI 集成测试）
pytest tests/ -v -k "not test_cli"

# 运行特定测试文件
pytest tests/test_l2_rule_engine.py -v
```

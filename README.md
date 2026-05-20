# 广告内容审核分层决策系统

基于 5 层分层架构的广告内容审核系统 Demo。支持 MD5/pHash 前置否决、规则引擎、风险融合、多模态 Agent 审核和策略自优化。14 条精心设计的测试用例覆盖所有审核路径。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      广告素材输入                             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L1 历史召回层    MD5 精确匹配 / pHash 视觉相似匹配          │
│  ── 命中即 REJECT，短路退出 ──                               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼ (未命中)
┌─────────────────────────────────────────────────────────────┐
│  L2 规则引擎层    OCR · ASR · QR · 关键词 · 类目资质         │
│  ── hard_block 命中即 REJECT / 金融敏感即 REJECT ──          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼ (NEXT)
┌─────────────────────────────────────────────────────────────┐
│  L3 风险融合层    一致性校验 · 文本嵌入 · 多信号加权          │
│  ── 总分≥120 REJECT / ≤20 APPROVE / 中间灰区 ──             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼ (AGENT_REVIEW)
┌─────────────────────────────────────────────────────────────┐
│  L4 Agent 审核层   多模态看图 + 工具调用 + 交叉验证           │
│  ── LLM 综合研判，高敏感类目强制 HUMAN_REVIEW ──             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L5 策略层        申诉复核 Agent · 策略自优化 Agent           │
└─────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 模块 | 职责 | 决策能力 |
|------|------|------|----------|
| L1 | 历史召回 | MD5 精确匹配 + pHash 视觉相似匹配 | REJECT / NEXT |
| L2 | 规则引擎 | OCR/ASR/QR 提取 + 关键词三级匹配 + 类目资质校验 | REJECT / NEXT |
| L3 | 风险融合 | 一致性校验 + 文本嵌入相似度 + 多信号加权求和 | REJECT / APPROVE / AGENT_REVIEW |
| L4 | Agent 审核 | LLM 多模态研判 + function calling + RAG | REJECT / APPROVE / HUMAN_REVIEW |
| L5 | 策略层 | 申诉复核 + 关键词/阈值自优化建议 | 建议（需人工确认） |

### 否决项短路机制

系统采用"命中即终止"的短路设计，高确定性信号优先处理，避免浪费后续计算资源：

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

### L4 Agent 能力

L4 层使用 LLM Agent 对灰区广告进行深度审核：

- **多模态看图**：将视频关键帧编码为 base64 图片，随 prompt 一起发送给视觉模型，Agent 直接"看到"广告画面
- **工具调用（Function Calling）**：Agent 可调用 `check_brand_database`、`verify_qualification`、`search_violation_history` 等工具获取外部信息
- **交叉验证**：对比文案宣称 vs 落地页内容 vs 资质信息 vs 视觉画面，发现矛盾点
- **RAG 检索**：检索 `policy_docs.json`（审核政策）和 `history_cases.json`（历史案例）辅助决策
- **高敏感类目保护**：医疗/金融等高敏感类目强制输出 HUMAN_REVIEW，不允许 Agent 自行放行

---

## 从零部署（傻瓜式教学）

### Step 1: 系统依赖

确保你的机器上有以下软件：

| 软件 | 版本要求 | 检查命令 |
|------|----------|----------|
| Python | 3.10+ | `python --version` |
| pip | 最新 | `pip --version` |
| Git | 任意 | `git --version` |
| FFmpeg | 任意（ASR 需要） | `ffmpeg -version` |

> FFmpeg 是 faster-whisper（ASR 语音转写）的依赖。Windows 用户可从 https://www.gyan.dev/ffmpeg/builds/ 下载，解压后把 bin 目录加到 PATH。

### Step 2: 克隆 + 虚拟环境 + 安装依赖

```bash
git clone <你的仓库地址> ad-review-demo
cd ad-review-demo

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### Step 3: 下载 ASR 模型（重要！）

系统使用 faster-whisper 做语音转写，首次运行会自动从 HuggingFace 下载模型。

**国内用户必看**：HuggingFace 在国内访问很慢甚至超时，请设置镜像：

```bash
# Windows (PowerShell):
$env:HF_ENDPOINT = "https://hf-mirror.com"

# Windows (CMD):
set HF_ENDPOINT=https://hf-mirror.com

# Linux/Mac:
export HF_ENDPOINT=https://hf-mirror.com
```

建议写入你的 shell 配置文件（如 `.bashrc` 或 PowerShell `$PROFILE`），避免每次都设。

> 默认模型大小为 `small`（约 500MB），可在 `config/runtime.yaml` 中改为 `tiny`（约 150MB）加快下载。

### Step 4: 配置 LLM API

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 LLM API 信息。四种常见配置示例：

**火山引擎 Ark（豆包）：**
```
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=你的火山引擎API Key
LLM_MODEL=doubao-pro-32k
```

**DeepSeek：**
```
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=你的DeepSeek API Key
LLM_MODEL=deepseek-chat
```

**OpenAI：**
```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-你的OpenAI Key
LLM_MODEL=gpt-4o-mini
```

**Ollama 本地部署（免费，无需 API Key）：**
```
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
```

> LLM API 超时设置为 120 秒（火山引擎冷启动可能需要较长时间）。超时后自动降级为 HUMAN_REVIEW。
>
> 如果暂时没有 LLM API，可以在 `config/runtime.yaml` 中设置 `llm_enabled: false`，L4 层会直接输出 HUMAN_REVIEW。

### Step 5: 准备视频数据

详见下方「数据准备详解」章节。如果你只想快速验证系统能跑通，可以跳过这步——系统会自动走 mock 模式。

### Step 6: 生成历史指纹库

如果你放了真实视频到 `history_videos/` 目录：

```bash
python scripts/build_history_fingerprints.py
```

这会读取 `history_videos/` 下的视频，计算 MD5 和 pHash 指纹，写入 `data/history_fingerprints.json`。

> 如果没有放视频，跳过这步即可。mock 模式下 L1 历史召回不会触发。

### Step 7: 一键验证

```bash
# 推荐：批量模式（模型只加载一次，14 条全跑）
python main.py batch --dir samples --pattern "demo_*.json"

# 或者：单条快速测试
python main.py review --meta samples/demo_003.json
```

如果看到类似以下输出，说明系统正常运行：

```
============================================================
批量审核模式 - 14 条广告（模型只加载一次）
============================================================

--- [1/14] demo_001.json ---
  ✓ NEXT @ L1 (0.01s)          ← mock 模式下 L1 不触发，正常
--- [2/14] demo_002.json ---
  ✓ NEXT @ L1 (0.01s)
--- [3/14] demo_003.json ---
  ✓ REJECT @ L2 (0.02s)        ← 命中 hard_block "高仿"
...
============================================================
批量完成: 14 条, 总耗时 12.3s
决策分布: {'REJECT': 8, 'APPROVE': 2, 'AGENT_REVIEW': 2, 'HUMAN_REVIEW': 2}
终止层分布: {'L2': 4, 'L3': 5, 'L4': 5}
平均单条耗时: 0.88s
============================================================
```

### Step 8: 查看输出

审核结果 JSON 文件在 `outputs/` 目录：

```bash
# 查看某条审核结果
cat outputs/review_result_demo_003.json

# Windows PowerShell:
Get-Content outputs/review_result_demo_003.json
```

日志文件在 `logs/` 目录，每次运行生成一个带时间戳的日志文件。

---

## 数据准备详解

### 视频文件怎么放

| 编号 | 视频要求 | 放哪 | 为了踩中什么 |
|------|----------|------|-------------|
| demo_001 | 任意广告视频（10-15秒） | `samples/demo_001.mp4` + 复制到 `history_videos/violation_001.mp4` | L1 MD5 精确匹配 |
| demo_002 | demo_001 的轻微修改版（加水印/重编码/调色） | `samples/demo_002.mp4` | L1 pHash 相似匹配 |
| demo_003 | 任意视频（或画面含"高仿精品"文字） | `samples/demo_003.mp4` | L2 OCR（mock 模式用 JSON 中的 mock_ocr_texts） |
| demo_004 | 任意视频 | `samples/demo_004.mp4` | L2 ASR（mock 模式用 JSON 中的 mock_asr_text） |
| demo_005 | **画面中必须有微信二维码图案** | `samples/demo_005.mp4` | L2 QR 私域引流检测 |
| demo_006~014 | 任意视频即可 | `samples/demo_006.mp4` ~ `demo_014.mp4` | 违规内容在 JSON 的文本字段中 |

> **没有视频也能跑！** 系统检测到视频文件不存在时自动走 mock 模式，使用 JSON 中的 `mock_asr_text` 和 `mock_ocr_texts` 模拟结果。但 L1 历史匹配和 QR 检测在 mock 模式下不触发。

---

### demo_001: 复制到 history_videos 作为历史违规库

这是测试 L1 层 MD5 精确匹配的关键步骤。原理：同一个视频文件的 MD5 完全相同，系统在 L1 层发现 MD5 命中历史违规库后直接 REJECT，不再执行后续层。

**详细步骤：**

1. 准备一个视频文件（任意广告视频，10-15 秒，720p/1080p 均可）
2. 复制到 `samples/demo_001.mp4`
3. 创建 `history_videos/` 目录（如果不存在）：
   ```bash
   mkdir history_videos
   ```
4. 把同一个文件复制到 `history_videos/violation_001.mp4`：
   ```bash
   # Windows:
   copy samples\demo_001.mp4 history_videos\violation_001.mp4
   # Linux/Mac:
   cp samples/demo_001.mp4 history_videos/violation_001.mp4
   ```
5. 运行指纹生成脚本：
   ```bash
   python scripts/build_history_fingerprints.py
   ```
6. 验证：
   ```bash
   python main.py review --meta samples/demo_001.json
   ```
   期望输出：`[L1Recall] decision=REJECT reason=md5_exact_match`

> **为什么要复制？** 因为 L1 层是拿输入视频的 MD5 去 `data/history_fingerprints.json` 里查。指纹库是从 `history_videos/` 目录生成的。所以同一个文件出现在两个地方 = MD5 命中。

---

### demo_002: pHash 相似匹配

这是测试 L1 层 pHash 视觉相似匹配的步骤。原理：对视频做轻微处理后，文件 MD5 变了，但画面视觉内容几乎不变，pHash（感知哈希）仍然高度相似。

**详细步骤：**

1. 对 `demo_001.mp4` 做轻微处理（任选一种）：
   - 加一个小水印
   - 用 FFmpeg 重新编码：
     ```bash
     ffmpeg -i samples/demo_001.mp4 -c:v libx264 -crf 23 samples/demo_002.mp4
     ```
   - 轻微调色：
     ```bash
     ffmpeg -i samples/demo_001.mp4 -vf "eq=brightness=0.02" samples/demo_002.mp4
     ```
2. 确认 MD5 不同：
   ```bash
   # Windows PowerShell:
   Get-FileHash samples\demo_001.mp4
   Get-FileHash samples\demo_002.mp4
   # Linux/Mac:
   md5sum samples/demo_001.mp4 samples/demo_002.mp4
   ```
   两个文件的 MD5 应该不同。
3. 验证：
   ```bash
   python main.py review --meta samples/demo_002.json
   ```
   期望输出：`[L1Recall] decision=REJECT reason=phash_similar_match`

> **原理**：pHash 把每帧画面缩放到 64×64 并计算感知哈希。两个视频的帧哈希汉明距离 ≤ 8 即判定为相似。重编码/加水印不会显著改变画面内容，所以 pHash 仍然命中。

---

### demo_003~004: 不需要特殊视频

任意视频即可（甚至不放视频也行，走 mock 模式）。

- **demo_003**：违规内容在 JSON 的 `mock_ocr_texts` 字段中（"高仿精品 厂家直销"），L2 关键词引擎会命中 hard_block 词"高仿"
- **demo_004**：违规内容在 JSON 的 `mock_asr_text` 字段中（"这款是A货里面的顶级品质"），L2 关键词引擎会命中 hard_block 词"A货"

---

### demo_005: 需要含二维码的视频

视频画面中必须有清晰的微信二维码图案，系统使用 OpenCV 的 QRCodeDetector 检测。

**如何准备：**
- 方法 A：用手机拍一段包含二维码的视频（比如拍一张印有二维码的卡片）
- 方法 B：用视频编辑工具在任意视频上叠加一个二维码图片
- 方法 C：用 AI 视频生成工具生成含二维码的画面

> mock 模式下 QR 检测不触发，demo_005 会直接 APPROVE。只有放了真实含二维码的视频才能触发 L2 QR 加分 → 进入 L3 灰区。

---

### demo_006~014: 不需要特殊视频

任意视频即可。这些 demo 的违规判定完全依赖 JSON 中的文本字段（title、description、mock_asr_text、mock_ocr_texts、landing_page、merchant 资质等），不依赖视频画面内容。

---

### history_videos/ 目录

| 文件 | 来源 | 用途 |
|------|------|------|
| `violation_001.mp4` | demo_001.mp4 的副本 | 历史违规指纹（MD5 + pHash） |
| `violation_002.mp4` | 可选，任意违规视频 | 扩充历史违规库 |
| `safe_001.mp4` | 可选，demo_010.mp4 的副本 | 历史安全指纹 |

运行 `python scripts/build_history_fingerprints.py` 后生成 `data/history_fingerprints.json`。

---

### data/ 目录（已有数据，不需要你准备）

| 文件 | 内容 | 用途 |
|------|------|------|
| `policy_docs.json` | 8 条审核政策文档 | L4 Agent RAG 检索用 |
| `history_cases.json` | 5 条历史审核案例 | L4 Agent RAG 检索用 |
| `optimization_logs.json` | 10 条优化日志 | L5 策略 Agent 分析用 |
| `history_fingerprints.json` | 历史指纹库 | L1 历史召回用（需运行脚本生成真实数据） |

---

## 14 条 Demo 数据集总览

| 编号 | 场景 | 触发环节 | 期望决策 | 终止层 | 视频要求 |
|------|------|----------|----------|--------|----------|
| demo_001 | MD5 完全匹配历史违规视频 | L1 MD5 匹配 | REJECT | L1 | 需真实视频 + 复制到 history_videos |
| demo_002 | pHash 高相似历史违规视频 | L1 pHash 匹配 | REJECT | L1 | 需 demo_001 的轻微修改版 |
| demo_003 | OCR 识别出 hard_block "高仿" | L2 关键词（OCR） | REJECT | L2 | 任意/无视频 |
| demo_004 | ASR 转写出 hard_block "A货" | L2 关键词（ASR） | REJECT | L2 | 任意/无视频 |
| demo_005 | 画面含二维码（私域引流） | L2 QR 检测 | 灰区 | L3 | 需含二维码的视频 |
| demo_006 | 金融敏感宣称 + 无金融资质 | L2 类目资质 | REJECT | L2 | 任意/无视频 |
| demo_007 | suspicious_slang 黑话累加 | L2→L3 黑话加分 | L3 判定 | L3 | 任意/无视频 |
| demo_008 | 缺品牌授权（无 hard_block） | L2→L3 资质缺失 | L3 判定 | L3 | 任意/无视频 |
| demo_009 | 落地页价格冲突 + 私域引流词 | L2→L3 落地页规则 | L3 判定 | L3 | 任意/无视频 |
| demo_010 | 低风险完全合规日用品 | 无风险信号 | APPROVE | L3 | 任意/无视频 |
| demo_011 | 多信号累加超 L3 reject 阈值 | L3 风险融合 | REJECT | L3 | 任意/无视频 |
| demo_012 | 灰区（有冲突但分数不够高） | L3→L4 灰区 | AGENT_REVIEW | L4 | 任意/无视频 |
| demo_013 | L4 Agent 高风险判定 | L4 Agent 审核 | REJECT | L4 | 任意/无视频 |
| demo_014 | 医疗高敏感类目 → 强制人审 | L4 高敏感类目 | HUMAN_REVIEW | L4 | 任意/无视频 |

---

## 三个命令

### 单条审核

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

### 批量审核（推荐，模型只加载一次）

```bash
python main.py batch --dir samples --pattern "demo_*.json"
```

> **为什么推荐 batch？** 单条模式每次都要重新加载 ASR 模型（约 2-3 秒），batch 模式在同一进程中复用所有模型实例，14 条跑完比单条跑 14 次快很多。

可以用 `--pattern` 过滤：
```bash
# 只跑 demo_001 到 demo_005
python main.py batch --dir samples --pattern "demo_00[1-5].json"

# 跑所有 ad_ 开头的样本
python main.py batch --dir samples --pattern "ad_*.json"
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

## 配置说明

### config/runtime.yaml

控制运行时行为和模型开关：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_sampled_frames` | 12 | 视频最多抽取帧数 |
| `sample_interval_sec` | 1 | 抽帧间隔（秒） |
| `phash_resize` | 64 | pHash 计算时的缩放尺寸 |
| `enable_ocr` | false | 是否启用 PaddleOCR（需额外安装） |
| `enable_asr` | true | 是否启用 faster-whisper ASR |
| `asr_model_size` | small | ASR 模型大小：tiny/small/medium/large |
| `asr_device` | auto | ASR 设备：auto/cpu/cuda |
| `asr_compute_type` | int8_float16 | ASR 计算精度 |
| `enable_qr` | true | 是否启用二维码检测 |
| `enable_text_embedding` | true | 是否启用文本嵌入相似度 |
| `llm_enabled` | auto | LLM 模式：auto（有 API 就用）/ true / false |

### config/thresholds.yaml

各层决策阈值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `l1_history_match_threshold` | 0.85 | L1 pHash 相似度阈值 |
| `l1_hamming_threshold` | 8 | L1 汉明距离阈值（≤此值判定相似） |
| `l2_reject_score` | 60 | L2 风险分达到此值直接 REJECT |
| `l3_reject_score` | 120 | L3 总分达到此值 REJECT |
| `l3_approve_score` | 20 | L3 总分低于此值 APPROVE |
| `agent_confidence_auto_threshold` | 0.7 | L4 Agent 置信度阈值 |

### config/keywords.yaml

三级关键词库：

| 级别 | 行为 | 示例 |
|------|------|------|
| `hard_block` | 命中即 REJECT，L2 终止 | 高仿、A货、1:1复刻、稳赚不赔 |
| `normalized_block` | 文本归一化后匹配即 REJECT | 1比1、壹比壹 |
| `suspicious_slang` | 加中等风险分（+15），路由到 L3 | 柜姐渠道、原厂尾单、懂的来、加微信 |

每个词条可指定 `category`（适用类目），`"all"` 表示全类目生效。

### config/category_rules.yaml

类目资质要求和敏感宣称词：

| 类目 | 必需资质 | 敏感宣称示例 |
|------|----------|-------------|
| 箱包 | brand_authorization | 官方正品、专柜品质 |
| 金融 | financial_license | 稳赚、保本、高收益 |
| 医疗 | medical_license | 治疗、根治、无副作用 |
| 功效 | medical_license | 减肥、排毒、美白 |

### .env（LLM API）

| 变量 | 说明 |
|------|------|
| `LLM_BASE_URL` | LLM API 的 base URL（兼容 OpenAI 格式） |
| `LLM_API_KEY` | API Key |
| `LLM_MODEL` | 模型名称 |

四种 LLM 配置示例：

| 服务商 | LLM_BASE_URL | LLM_MODEL | 备注 |
|--------|-------------|-----------|------|
| 火山引擎 Ark | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-pro-32k` | 国内首选，冷启动可能慢 |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | 国内可用，性价比高 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | 需科学上网 |
| Ollama 本地 | `http://localhost:11434/v1` | `qwen2.5:7b` | 免费，需本地部署 Ollama |

---

## 工具脚本

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `scripts/build_history_fingerprints.py` | 从 `history_videos/` 目录生成指纹库 `data/history_fingerprints.json` | `python scripts/build_history_fingerprints.py` |
| `scripts/generate_ad_meta.py` | 为 `samples/` 下的真实视频批量生成配套广告 JSON | `python scripts/generate_ad_meta.py` |
| `scripts/run_all_demo.py` | 一键跑通所有样例，打印汇总报告（覆盖层/决策类型） | `python scripts/run_all_demo.py` |

---

## 输出说明

### 输出文件位置

| 类型 | 路径 | 文件名格式 |
|------|------|-----------|
| 审核结果 | `outputs/` | `review_result_{ad_id}.json` |
| 申诉结果 | `outputs/` | `appeal_result_{appeal_id}.json` |
| 策略建议 | `outputs/` | `strategy_suggestion.json` |
| 候选关键词 | `outputs/` | `candidate_keywords.yaml` |
| 运行日志 | `logs/` | `ad_review_YYYYMMDD_HHMMSS.log` |

### 审核结果 JSON 结构

```
{
  "ad_id": "demo_003",
  "final_decision": "REJECT",        ← 最终决策
  "terminated_at": "L2",             ← 在哪一层终止
  "layers": [...],                   ← 每层详细结果（decision/risk_score/signals/evidence）
  "timings": {                       ← 每个节点耗时（秒）
    "config_load": 0.004,
    "media_preprocess": 0.12,
    "L1_recall": 0.001,
    "L2_ocr": 0.35,
    "L2_asr": 0.80,
    "L2_qr": 0.005,
    "L2_rule_engine": 0.002,
    "L2_total": 1.157,
    "pipeline_total": 1.282
  }
}
```

> 详细字段说明见 `docs/OUTPUT_FORMAT.md`。

### 日志文件

每次运行在 `logs/` 目录生成一个日志文件，包含 DEBUG 级别的完整执行过程。控制台只显示 INFO 级别。

---

## 降级机制

| 场景 | 降级行为 | 触发条件 |
|------|----------|----------|
| 视频文件不存在 | 自动走 mock 模式，使用 JSON 中的 mock_asr_text / mock_ocr_texts | 文件路径无效 |
| OCR 模型未安装 | 跳过 OCR，仅用 mock_ocr_texts | `enable_ocr: false` 或 PaddleOCR 未安装 |
| ASR 模型加载失败 | 使用 mock_asr_text 替代 | faster-whisper 加载异常 |
| LLM API 不可用 | L4 输出 HUMAN_REVIEW（兜底人审） | API 超时/报错/未配置 |
| LLM 响应超时 | 120 秒超时后降级为 HUMAN_REVIEW | 火山引擎冷启动等场景 |
| 文本嵌入模型未安装 | 跳过嵌入相似度计算，不影响其他信号 | sentence-transformers 未安装 |
| QR 检测无结果 | 跳过 QR 加分 | 视频无二维码或 mock 模式 |

> 设计原则：任何单一组件故障都不会导致系统崩溃，而是优雅降级到更保守的决策（HUMAN_REVIEW）。

---

## 常见问题

**Q: ASR 模型下载慢/超时？**

A: 设置 HuggingFace 镜像：
```bash
# Windows PowerShell:
$env:HF_ENDPOINT = "https://hf-mirror.com"
# Linux/Mac:
export HF_ENDPOINT=https://hf-mirror.com
```
或者在 `config/runtime.yaml` 中把 `asr_model_size` 改为 `tiny`（更小更快下载）。

**Q: 火山引擎 API 超时？**

A: 火山引擎有冷启动问题，首次调用可能需要 30-60 秒。如果持续超时：
1. 换用 DeepSeek API（响应更快）
2. 或设置 `config/runtime.yaml` 中 `llm_enabled: false`，L4 层直接输出 HUMAN_REVIEW

**Q: 没有视频能跑吗？**

A: 能。系统自动走 mock 模式，使用 JSON 中的 `mock_asr_text` 和 `mock_ocr_texts` 模拟结果。L1 历史匹配和 QR 检测在 mock 模式下不触发，其余所有环节正常运行。

**Q: 如何添加关键词？**

A: 编辑 `config/keywords.yaml`，在对应级别下添加词条：
- `hard_block`：命中即 REJECT
- `normalized_block`：归一化后匹配即 REJECT
- `suspicious_slang`：加分进入灰区

每个词条格式：`{word: "关键词", category: "类目或all"}`

**Q: 如何测试 L1 历史召回？**

A: 三步：
1. 把违规视频放到 `history_videos/` 目录
2. 运行 `python scripts/build_history_fingerprints.py` 生成指纹库
3. 用相同视频（测 MD5）或重编码版本（测 pHash）作为输入

**Q: batch 模式和单条模式的区别？**

A: batch 模式在同一进程中处理所有文件，ASR 模型、文本嵌入模型等只加载一次。单条模式每次都重新加载。跑多条时 batch 模式快很多，推荐使用：
```bash
python main.py batch --dir samples --pattern "demo_*.json"
```

**Q: OCR 需要额外安装吗？**

A: 是的。OCR 依赖 PaddleOCR，需手动安装：`pip install paddleocr`。默认 `enable_ocr: false`，不安装时系统使用 JSON 中的 `mock_ocr_texts` 数据。

**Q: 支持哪些 LLM？**

A: 任何兼容 OpenAI API 格式的服务都可以。在 `.env` 中配置 `LLM_BASE_URL` 和 `LLM_MODEL` 即可。已验证：火山引擎 Ark、DeepSeek、OpenAI、Ollama。

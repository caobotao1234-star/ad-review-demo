# 完整部署指南：让每个环节都真实运行

本文档说明如何在一台全新的云服务器上，clone 代码后让 demo 的**每一个环节**都用真实数据跑起来。

---

## 零、你需要准备的原始素材

| 素材 | 数量 | 说明 |
|------|------|------|
| 广告视频 (.mp4) | 8-10 个 | 10-60 秒，覆盖不同违规类型 |
| 历史违规视频 | 2-3 个 | 用于生成 L1 历史指纹库 |
| 历史安全视频 | 1-2 个 | 用于生成 L1 历史指纹库 |
| LLM API Key | 1 个 | DeepSeek/OpenAI/通义千问/Ollama 任一 |

**视频不需要是真实广告**，任何 10-60 秒的 mp4 都行（用于验证抽帧/ASR/QR 流程）。

---

## 一、数据集设计：8 条广告覆盖所有环节

为了踩中每一个审核环节，建议准备以下 8 条数据（视频 + JSON 成对）：

| 编号 | 场景 | 期望路径 | 视频要求 |
|------|------|---------|---------|
| real_001 | 箱包仿冒疑似（灰区） | L1→L2→L3→**L4 Agent** | 任意箱包展示视频 |
| real_002 | 箱包明确违规 | L1→**L2 REJECT** | 任意视频（关键词在 JSON 里） |
| real_003 | 低风险日用品 | L1→L2→**L3 APPROVE** | 任意日用品视频 |
| real_004 | 金融违规 | L1→**L2 REJECT** | 任意视频 |
| real_005 | 类目错挂（减肥） | L1→L2→L3→**L4 Agent** | 任意视频 |
| real_006 | **L1 历史命中** | **L1 REJECT**（直接短路） | 与历史违规视频**相同** |
| real_007 | 含二维码私域引流 | L1→L2→L3→L4 | 画面中含微信二维码的视频 |
| real_008 | 完全合规品牌广告 | L1→L2→**L3 APPROVE** | 任意视频 |

**关键点：**
- real_006 的视频必须和 `history_videos/violation_001.mp4` 是**同一个文件**（或高度相似），这样 L1 才能命中
- real_007 的视频画面中需要有一个微信二维码（可以用手机截屏做一个简单视频）
- 其他视频内容不重要，因为关键词/资质/落地页信息都在 JSON 里

| 项目 | 最低要求 | 推荐配置 |
|------|---------|---------|
| OS | Ubuntu 20.04+ | Ubuntu 22.04 |
| Python | 3.10+ | 3.11 |
| GPU | 无（CPU 可跑） | RTX 4090（ASR 加速） |
| 内存 | 8GB | 16GB+ |
| 磁盘 | 5GB（含模型） | 20GB（large-v3 模型 ~3GB） |
| 网络 | 需要（下载模型 + LLM API） | — |

---

## 二、系统依赖安装

```bash
# 基础工具
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip ffmpeg git

# 验证
python3.11 --version   # Python 3.11.x
ffmpeg -version        # ffmpeg 6.x+

# （可选）如果有 GPU
# 确认 NVIDIA 驱动已安装
nvidia-smi
# 安装 CUDA toolkit（如果还没有）
# sudo apt install -y nvidia-cuda-toolkit
```

---

## 三、项目部署

```bash
git clone <your-repo-url> ad-review-demo
cd ad-review-demo

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# （可选）安装 GPU 加速依赖
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12

# （可选）安装文本 embedding 模型
pip install sentence-transformers
```

---

## 四、需要准备的东西清单

### 4.1 LLM API 配置（让 L4/L5 Agent 真实调用 LLM）

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 任何 OpenAI 兼容 API 都行
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_MODEL=deepseek-chat

# 或者用 OpenAI
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
# LLM_MODEL=gpt-4o-mini

# 或者本地 Ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_API_KEY=ollama
# LLM_MODEL=qwen2.5:7b
```

同时修改 `config/runtime.yaml`：

```yaml
llm_enabled: auto   # auto = 有 key 就用真实 LLM，没有就 mock
```

**验证方式**：运行 `python main.py review --meta samples/ad_001.json`，看 L4 输出是否来自真实 LLM（reason 会是自然语言而非 "Mock Agent: ..."）。

---

### 4.2 真实视频文件（让 MediaPreprocessor 真实抽帧）

当前 samples 里的 `media_path` 指向不存在的 `.mp4`，所以走 mock。要让抽帧真实运行：

**步骤：**

1. 准备一个测试视频（10-30 秒，任何广告视频即可）
2. 放到 `samples/` 目录下
3. 修改对应的广告 JSON：

```json
{
  "media_path": "samples/real_ad_001.mp4",
  ...
}
```

**运行后会发生什么：**
- OpenCV 读取视频 → 抽首尾帧 + 每秒 1 帧 + 场景帧
- 每帧 resize 到 64×64 → 计算 pHash（16 位 hex 字符串）
- 相似帧去重（汉明距离 ≤ 4 的帧只保留一个）
- 最多保留 12 帧
- 帧图片缓存到 `outputs/cache/{ad_id}/frames/`
- ffmpeg 提取音频到 `outputs/cache/{ad_id}/audio.wav`

**关于 pHash 效率：** 是的，已经做了降采样。原始帧（可能 1920×1080）先 `cv2.resize` 到 64×64，再转灰度，再算 pHash。不会对大图直接计算。这个 resize 尺寸由 `config/runtime.yaml` 的 `phash_resize: 64` 控制。

---

### 4.3 历史视频指纹库（让 L1 真实召回）

当前 `data/history_fingerprints.json` 里的 pHash 是占位字符串，不会匹配任何真实视频。

**如何生成真实指纹：**

写一个小脚本，对历史违规/安全视频提取指纹：

```python
#!/usr/bin/env python3
"""生成历史视频指纹并写入 data/history_fingerprints.json"""
import json
from pathlib import Path
from modules.schemas import RuntimeConfig, AdMeta, Merchant, Qualification
from modules.media_preprocess import MediaPreprocessor

runtime = RuntimeConfig()
preprocessor = MediaPreprocessor(runtime, Path("outputs/cache"))

# 准备你的历史视频列表
history_videos = [
    {"path": "history_videos/violation_001.mp4", "label": "violation", "note": "1:1复刻LV"},
    {"path": "history_videos/violation_002.mp4", "label": "violation", "note": "金融诈骗"},
    {"path": "history_videos/safe_001.mp4", "label": "safe", "note": "正规日用品"},
]

fingerprints = []
for i, video in enumerate(history_videos, 1):
    ad = AdMeta(
        ad_id=f"hist_{i:03d}",
        media_path=video["path"],
        merchant=Merchant(merchant_id="hist"),
    )
    result = preprocessor.process(ad)
    if not result.mock:
        fingerprints.append({
            "history_id": f"hist_{i:03d}",
            "label": video["label"],
            "phash_list": result.fingerprint.phash_list,
            "note": video["note"],
        })
        print(f"✓ {video['path']} → {len(result.fingerprint.phash_list)} frames")
    else:
        print(f"✗ {video['path']} → mock (file not found?)")

output = {"fingerprints": fingerprints}
Path("data/history_fingerprints.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\n写入 {len(fingerprints)} 条指纹到 data/history_fingerprints.json")
```

**L1 匹配逻辑：** 对当前视频的每个帧 pHash，检查是否与历史指纹中任一帧的汉明距离 ≤ 8（`l1_hamming_threshold`）。如果 ≥ 85%（`l1_history_match_threshold`）的当前帧都能匹配到历史指纹，则判定命中。

**建议准备：**
- 2-3 个明确违规视频（仿冒/金融诈骗）
- 2-3 个明确安全视频
- 放到 `history_videos/` 目录（不需要提交到 git）

---

### 4.4 ASR 模型（让 L2 ASR 真实转写）

**需要做什么：** 什么都不用手动下载。faster-whisper 首次运行时会自动从 HuggingFace 下载模型到 `~/.cache/huggingface/hub/`。

**配置（`config/runtime.yaml`）：**

```yaml
enable_asr: true
asr_model_size: small      # 首次下载 ~500MB
asr_device: auto           # 有 GPU 自动用 cuda，没有用 cpu
asr_compute_type: int8_float16
```

**4090 推荐配置：**

```yaml
asr_model_size: large-v3   # 首次下载 ~3GB，精度最高
asr_device: cuda
asr_compute_type: float16
```

**如果下载慢：** 可以设置 HuggingFace 镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

**验证方式：** 确保视频文件存在 + ffmpeg 已安装，运行 review 后看日志是否有 `faster-whisper transcription` 相关输出（而非 `fallback_reason="no_audio"`）。

---

### 4.5 OCR（可选，让 L2 OCR 真实识别画面文字）

当前默认 `enable_ocr: false`，使用 `mock_ocr_texts`。

**如果要启用真实 OCR：**

```bash
pip install paddlepaddle paddleocr
```

修改 `config/runtime.yaml`：

```yaml
enable_ocr: true
```

**注意：** PaddleOCR 首次运行也会自动下载模型（~100MB）。GPU 环境下用 `paddlepaddle-gpu`。

---

### 4.6 文本 Embedding（让 L3 语义相似度真实计算）

当前默认 fallback 到 token overlap（按字符计算 Jaccard）。

**如果要启用真实 embedding：**

```bash
pip install sentence-transformers
```

修改 `config/runtime.yaml`：

```yaml
enable_text_embedding: true
```

首次运行会自动下载 `all-MiniLM-L6-v2` 模型（~90MB）。

---

### 4.7 政策文档与历史案例（让 L4 Agent RAG 有真实内容可检索）

当前 `data/policy_docs.json` 和 `data/history_cases.json` 已有 demo 数据，但内容较少。

**如果要增强：**

`data/policy_docs.json` 格式：
```json
[
  {"id": "policy_xxx", "category": "品牌授权|金融资质|医疗资质|私域引流", "text": "完整的政策条文..."}
]
```

`data/history_cases.json` 格式：
```json
[
  {"case_id": "case_xxx", "category": "箱包|金融|医疗", "decision": "REJECT|APPROVE|HUMAN_REVIEW", "text": "案例描述..."}
]
```

**建议：** 把你们公司真实的审核政策文档（脱敏后）按条目拆分放进去，每条 200-500 字。L4 Agent 会用简单文本检索（Jaccard 相似度）找 top-5 相关条目作为 prompt 上下文。

---

### 4.8 优化日志（让 L5 策略 Agent 有真实数据分析）

当前 `data/optimization_logs.json` 有 10 条 demo 数据。

**格式：**
```json
[
  {
    "ad_id": "xxx",
    "type": "false_approve|human_reject|appeal_overturn|false_reject",
    "text": "广告文案原文...",
    "decision_path": ["L1", "L2", "L3"],
    "final_decision": "REJECT|APPROVE"
  }
]
```

**建议：** 从真实审核系统导出 50-100 条误判/漏判/申诉日志，L5 Agent 会从中发现高频黑话并建议加入词库。

---

## 五、配置文件调优

### 5.1 阈值调优（`config/thresholds.yaml`）

```yaml
l1_history_match_threshold: 0.85   # 相似帧比例 ≥ 85% 才算命中
l1_hamming_threshold: 8            # 单帧 pHash 汉明距离 ≤ 8 算相似
l2_reject_score: 60                # L2 层暂未使用（L2 靠 hard_block 直接 REJECT）
l3_reject_score: 120               # 风险分 ≥ 120 直接拒绝
l3_approve_score: 20               # 风险分 ≤ 20 且无冲突信号 → 通过
agent_confidence_auto_threshold: 0.7  # Agent 置信度 < 0.7 → 转人工
```

### 5.2 关键词调优（`config/keywords.yaml`）

三类词库：
- `hard_block`：命中即 REJECT（"1:1复刻"、"高仿"、"A货"等）
- `normalized_block`：归一化后命中即 REJECT（"1比1"→"1:1"）
- `suspicious_slang`：只加 15 分进入 L3（"柜姐渠道"、"原厂尾单"等）

**你可以根据业务需要增删词条。**

### 5.3 类目规则（`config/category_rules.yaml`）

定义每个类目需要什么资质、哪些宣称是敏感的。可以按你们的实际审核标准调整。

---

## 六、完整运行验证

```bash
# 1. 确认环境
python --version          # 3.10+
ffmpeg -version           # 有输出
nvidia-smi                # （可选）有 GPU

# 2. 确认 .env 配置
cat .env                  # LLM_API_KEY 已填

# 3. 跑 5 条广告审核
python main.py review --meta samples/ad_001.json
python main.py review --meta samples/ad_002.json
python main.py review --meta samples/ad_003.json
python main.py review --meta samples/ad_004.json
python main.py review --meta samples/ad_005.json

# 4. 跑申诉复核
python main.py appeal --appeal samples/appeal_001.json
python main.py appeal --appeal samples/appeal_002.json

# 5. 跑策略优化
python main.py optimize --logs data/optimization_logs.json

# 6. 查看输出
ls outputs/
cat outputs/review_result_ad_001.json
cat outputs/strategy_suggestion.json
cat outputs/candidate_keywords.yaml
```

---

## 七、各环节"真实运行"检查表

| 环节 | mock 状态标志 | 真实运行条件 |
|------|-------------|-------------|
| MediaPreprocessor 抽帧 | `[MediaPreprocessor] mock=True` | `media_path` 指向真实 .mp4 文件 |
| ffmpeg 音频提取 | 日志 `skip audio extraction` | 系统已安装 ffmpeg |
| L1 历史召回 | `decision=NEXT reason=历史指纹未命中` | `data/history_fingerprints.json` 含真实 pHash |
| L2 ASR | 日志 `fallback_reason=no_audio` | ffmpeg 已装 + 视频存在 + `enable_asr: true` |
| L2 OCR | 使用 `mock_ocr_texts` | `enable_ocr: true` + PaddleOCR 已装 |
| L3 TextEmbedding | `backend=token_overlap` | `enable_text_embedding: true` + sentence-transformers 已装 |
| L4/L5 Agent | `mode=mock` | `.env` 中 `LLM_API_KEY` 已配置 |

**当所有环节都真实运行时，你会看到：**
- `[MediaPreprocessor] mock=False frames=8-12 audio=outputs/cache/xxx/audio.wav`
- `[L1Recall] decision=NEXT`（除非命中历史指纹）
- `[L2RuleEngine]` 的 evidence 中有真实 OCR/ASR 文本
- `[L3RiskFusion]` 的 embedding 用 sbert 而非 token_overlap
- `[L4AgentReview]` 的 reason 是自然语言（来自真实 LLM）

---

## 八、模型下载汇总

| 模型 | 大小 | 自动下载 | 手动下载方式 |
|------|------|---------|-------------|
| faster-whisper small | ~500MB | ✅ 首次运行自动 | `huggingface-cli download Systran/faster-whisper-small` |
| faster-whisper large-v3 | ~3GB | ✅ 首次运行自动 | `huggingface-cli download Systran/faster-whisper-large-v3` |
| sentence-transformers all-MiniLM-L6-v2 | ~90MB | ✅ 首次运行自动 | `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"` |
| PaddleOCR 中文模型 | ~100MB | ✅ 首次运行自动 | — |

所有模型缓存在 `~/.cache/huggingface/hub/` 或 `~/.paddleocr/`，不需要手动放到项目目录。

**如果服务器无法访问 HuggingFace：**

```bash
export HF_ENDPOINT=https://hf-mirror.com
# 然后正常运行，模型会从镜像下载
```

---

## 九、FAQ

**Q: 我只想验证 Agent 效果，不想折腾视频/ASR/OCR？**

保持 `media_path` 指向不存在的文件即可。系统会用 `mock_asr_text` 和 `mock_ocr_texts` 继续跑，只有 Agent 层用真实 LLM。

**Q: 我想让 L1 命中，怎么做？**

1. 用上面的脚本对一个视频生成指纹写入 `data/history_fingerprints.json`
2. 然后用同一个视频（或高度相似的视频）作为输入
3. L1 会命中并直接 REJECT/APPROVE

**Q: 我用 Ollama 本地模型行不行？**

完全可以。Ollama 暴露 OpenAI 兼容 API：

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
```

**Q: 风险分太高/太低，样例路径不对？**

调 `config/thresholds.yaml` 的 `l3_reject_score` 和 `l3_approve_score`。当前默认 reject=120, approve=20。

**Q: 如何添加新的违规关键词？**

编辑 `config/keywords.yaml`，在对应类别下添加 `{word: "新词", category: "all"}`。重启即生效。


---

## 十、傻瓜式操作步骤（从零到全部环节跑通）

```bash
# === Step 1: 克隆 + 装依赖 ===
git clone <your-repo-url> ad-review-demo
cd ad-review-demo
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install sentence-transformers  # 可选，让 L3 embedding 真实运行
sudo apt install -y ffmpeg         # 让 ASR 真实运行

# === Step 2: 配置 LLM ===
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key
# 推荐 DeepSeek: LLM_BASE_URL=https://api.deepseek.com/v1  LLM_MODEL=deepseek-chat

# === Step 3: 准备视频文件 ===
mkdir -p samples history_videos

# 把你的视频放进来（文件名对应 JSON 中的 media_path）：
# samples/real_001.mp4 ~ real_008.mp4
# history_videos/violation_001.mp4, violation_002.mp4, safe_001.mp4

# === Step 4: 生成历史指纹库 ===
python scripts/build_history_fingerprints.py
# 输出: data/history_fingerprints.json（含真实 pHash）

# === Step 5: 生成广告 JSON ===
python scripts/generate_ad_meta.py
# 输出: samples/real_001.json ~ real_008.json

# === Step 6: 一键跑通全部 demo ===
python scripts/run_all_demo.py
```

---

## 十一、关于 pHash 实现细节

### 是否降采样了？

**是的。** 流程如下：

```
原始帧 (如 1920×1080)
    ↓ cv2.resize(frame, (64, 64))    ← 降采样到 64×64
    ↓ cv2.cvtColor(BGR → GRAY)       ← 转灰度
    ↓ imagehash.phash(PIL.Image)      ← 计算感知哈希
    ↓ 输出 16 位 hex 字符串 (如 "a1b2c3d4e5f6a7b8")
```

- resize 尺寸由 `config/runtime.yaml` 的 `phash_resize: 64` 控制
- 不会对原始大图直接计算 pHash
- 去重阈值：两帧 pHash 汉明距离 ≤ 4 视为相似，只保留一个

### 为什么没有 MD5？

当前设计中 **L1 层只用 pHash**（视觉相似度匹配），没有文件级 MD5。原因：

- **pHash** 能识别"视觉相似但文件不同"的素材（如重新编码、加水印、裁剪后的翻拍）
- **MD5** 只能识别"文件完全相同"的素材（改一个像素就不匹配了）

如果你需要 MD5 快速判重（文件完全相同的情况），可以告诉我，我加一个 MD5 前置检查。但对于广告审核场景，pHash 更有价值。

### L1 匹配算法

```
对当前视频的每个关键帧 pHash：
    检查是否与历史指纹库中任一帧的汉明距离 ≤ 8 (l1_hamming_threshold)
    
相似帧比例 = 匹配成功的帧数 / 当前视频总关键帧数

如果 相似帧比例 ≥ 0.85 (l1_history_match_threshold)：
    → 命中历史指纹
    → 根据 label 返回 REJECT 或 APPROVE
否则：
    → NEXT（进入 L2）
```

---

## 十二、data/ 目录数据说明

| 文件 | 用途 | 是否需要你准备 |
|------|------|--------------|
| `history_fingerprints.json` | L1 历史指纹库 | **需要**：运行 `scripts/build_history_fingerprints.py` 生成 |
| `policy_docs.json` | L4 Agent 的政策文档 RAG | 已有 8 条 demo 数据，可直接用 |
| `history_cases.json` | L4 Agent 的历史案例 RAG | 已有 5 条 demo 数据，可直接用 |
| `optimization_logs.json` | L5 策略优化输入 | 已有 10 条 demo 数据，可直接用 |

### policy_docs.json（已生成，可直接用）

包含 8 条审核政策文档，覆盖：
- 品牌授权政策（2 条）
- 金融资质要求（2 条）
- 医疗资质要求（2 条）
- 私域引流管控（2 条）

L4 Agent 会用 Jaccard 文本相似度检索 top-5 相关条目作为 prompt 上下文。如果你有更详细的公司内部审核政策，可以追加到这个 JSON 里。

### history_cases.json（已生成，可直接用）

包含 5 条历史审核案例，覆盖箱包/金融/日用品/医疗类目。L4 Agent 用于参考历史判例。

### optimization_logs.json（已生成，可直接用）

包含 10 条模拟审核日志，频繁出现"柜姐渠道/原厂尾单/内部福利/懂的来/渠道价"等黑话。L5 策略 Agent 会从中发现这些候选词并建议加入 suspicious_slang。

---

## 十三、模型下载汇总

| 模型 | 触发条件 | 大小 | 自动下载 |
|------|---------|------|---------|
| faster-whisper small | `enable_asr: true` + 有真实视频 | ~500MB | ✅ 首次自动 |
| faster-whisper large-v3 | `asr_model_size: large-v3` | ~3GB | ✅ 首次自动 |
| sentence-transformers all-MiniLM-L6-v2 | `enable_text_embedding: true` + 已装库 | ~90MB | ✅ 首次自动 |
| PaddleOCR 中文模型 | `enable_ocr: true` + 已装库 | ~100MB | ✅ 首次自动 |

**所有模型都是首次运行时自动下载，不需要手动操作。**

如果服务器访问 HuggingFace 慢：
```bash
export HF_ENDPOINT=https://hf-mirror.com
```

---

## 十四、各环节"真实运行"检查表

运行 `python scripts/run_all_demo.py` 后，对照以下表格确认每个环节是否真实运行：

| 环节 | mock 标志（说明没真实跑） | 真实运行条件 |
|------|------------------------|-------------|
| 视频抽帧 | `mock=True` | media_path 指向真实 .mp4 |
| pHash 指纹 | frames=0 | 视频存在且能被 OpenCV 打开 |
| ffmpeg 音频 | 无 audio= 输出 | 系统已装 ffmpeg |
| L1 历史召回 | `decision=NEXT` 且 reason 含"未命中" | history_fingerprints.json 含真实 pHash + 有相同视频输入 |
| ASR 转写 | 日志含 `fallback_reason` | ffmpeg 已装 + 视频存在 + enable_asr=true |
| OCR 识别 | 使用 mock_ocr_texts | enable_ocr=true + PaddleOCR 已装 |
| 文本 Embedding | `backend=token_overlap` | enable_text_embedding=true + sentence-transformers 已装 |
| L4/L5 Agent | 日志 `mode=mock` | .env 中 LLM_API_KEY 已配置 |
| QR 检测 | 无 QR 命中 | 视频画面中确实有二维码 |

# Requirements Document

## Introduction

本特性实现一个命令行形式的广告审核 demo（`ad-review-layered-decision`）。系统输入为一个视频文件与一个广告 JSON 元信息文件，按"低成本前置、高成本后置"的原则进行分层处理：

广告输入 → 公共媒体预处理 → L1 历史召回 → L2 规则与证据提取 → L3 一致性与风险融合 → L4 Agent 复杂复核 → L5 申诉复核 Agent + 策略优化 Agent。

主链路严禁让 Agent 全量处理；前置层级若能高置信通过/拒绝则直接结束；前置层级不确定才进入下一层。Agent 仅在 L4（在线灰区复核）和 L5（离线申诉与策略优化）出现，且不直接修改生产规则，只输出建议。L1/L2/L3 必须输出审核理由，但理由全部由模板与结构化证据生成，不调用 Agent。

本 Demo 严格限定范围：仅命令行；不做可视化页面；不做图像 embedding、不做图像向量库、不做历史案例 embedding 召回、不做 YOLO、不做深度抽帧、不做抽检系统、不做真实落地页爬虫；ASR 仅使用方案 A：faster-whisper 本地轻量部署。

## Glossary

- **AdReviewSystem**: 广告审核 Demo 系统主入口（`main.py`），通过子命令分发到各层模块。
- **MediaPreprocessor**: `modules/media_preprocess.py` 公共媒体预处理模块，统一一次性完成抽帧、pHash、视频指纹与 ffmpeg 音频提取。
- **L1Recall**: `modules/l1_history_recall.py` 基于视频指纹的历史召回层。
- **L2OCR**: `modules/l2_ocr.py` 关键帧 OCR 模块，支持 PaddleOCR 真实模式与 Mock 模式切换。
- **L2ASR**: `modules/l2_asr.py` 基于 faster-whisper 的语音识别模块，支持 Mock fallback。
- **L2QR**: `modules/l2_qr.py` 基于 OpenCV `QRCodeDetector` 的二维码检测模块。
- **L2RuleEngine**: `modules/l2_rule_engine.py` 关键词规则、类目规则、资质规则、落地页基础规则的合并执行模块。
- **L3Consistency**: `modules/l3_consistency.py` 简单一致性规则模块。
- **L3TextEmbedding**: L3 中基于 sentence-transformers 的文本一致性子能力，不可用时回退 token overlap。
- **L3RiskFusion**: `modules/l3_risk_fusion.py` 多信号风险融合与决策模块。
- **L4AgentReview**: `modules/l4_agent_review.py` 在线复杂复核 Agent，仅处理 L3 的 AGENT_REVIEW 样本。
- **AgentClient**: `modules/agent_client.py` LLM 调用封装，支持 OpenAI-compatible API 与 MockAgent fallback。
- **MockAgent**: 当未配置 `LLM_API_KEY` 时使用的本地确定性 Agent 替身。
- **L5AppealAgent**: `modules/l5_appeal_agent.py` 申诉复核 Agent，输出申诉建议但不直接改判。
- **L5StrategyAgent**: `modules/l5_strategy_agent.py` 离线策略优化 Agent，从优化日志中发现新黑话与策略问题。
- **ReportWriter**: `modules/report_writer.py` 负责将各命令结果输出到控制台与 `outputs/` 目录的 JSON 文件。
- **AdMeta**: 输入广告 JSON，包含 `ad_id, media_type, media_path, title, description, category, brand, mock_asr_text, landing_page, merchant` 等字段。
- **MediaResult**: `MediaPreprocessor` 的标准化输出，包括关键帧路径、pHash 列表、视频指纹、音频路径等；视频缺失时为 mock 结构。
- **VideoFingerprint**: 由若干关键帧 pHash 组成的视频指纹结构。
- **HardBlockKeyword**: `keywords.yaml` 中的 `hard_block` 类强违规词库。
- **NormalizedBlockKeyword**: `keywords.yaml` 中的 `normalized_block` 类，需文本归一化匹配的违规词库。
- **SuspiciousSlang**: `keywords.yaml` 中的 `suspicious_slang` 类黑话词库，命中只加中风险分并强制进入 L3，不直接拒绝。
- **CategoryRules**: `category_rules.yaml` 配置的各类目（箱包、金融、医疗、功效等）所需资质与敏感宣称。
- **RuntimeConfig**: `config/runtime.yaml` 运行时配置。
- **Thresholds**: `config/thresholds.yaml` 阈值配置。
- **Decision**: 各层输出的决策枚举，取值 `APPROVE | REJECT | NEXT | AGENT_REVIEW | HUMAN_REVIEW`。
- **ReasonCode**: 模板化的结构化理由代码，例如 `L2_HARD_BLOCK_HIT`、`L3_CATEGORY_MISMATCH`。
- **AdClaimText**: `title + description + OCR + ASR` 拼接后的广告侧文本。
- **LandingText**: `landing_page.text` 落地页文本。
- **OptimizationLogs**: `data/optimization_logs.json` 优化输入日志。

## Requirements

### Requirement 1: 分层架构与主链路约束

**User Story:** 作为广告审核系统的设计者，我希望主链路严格按低成本到高成本的分层顺序执行，并且能在前层高置信结束，以便控制成本与延迟。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 按以下固定顺序执行主链路：MediaPreprocessor → L1Recall → L2RuleEngine（含 L2OCR/L2ASR/L2QR）→ L3Consistency → L3RiskFusion → L4AgentReview。
2. WHEN L1Recall 的 Decision 为 `APPROVE` 或 `REJECT`，THE AdReviewSystem SHALL 立即结束主链路并输出最终结果，不再调用 L2 及之后的模块。
3. WHEN L2RuleEngine 的 Decision 为 `APPROVE` 或 `REJECT`，THE AdReviewSystem SHALL 立即结束主链路并输出最终结果，不再调用 L3 及之后的模块。
4. WHEN L3RiskFusion 的 Decision 为 `APPROVE` 或 `REJECT`，THE AdReviewSystem SHALL 立即结束主链路并输出最终结果，不再调用 L4AgentReview。
5. WHEN L3RiskFusion 的 Decision 为 `AGENT_REVIEW`，THE AdReviewSystem SHALL 调用 L4AgentReview 进行在线复杂复核。
6. THE AdReviewSystem SHALL NOT 在 L1Recall、L2RuleEngine、L3Consistency、L3RiskFusion 的任何决策路径中调用 LLM 或 Agent。
7. THE AdReviewSystem SHALL 仅在 L4AgentReview、L5AppealAgent、L5StrategyAgent 中调用 Agent（LLM 或 MockAgent）。
8. THE L4AgentReview SHALL NOT 直接修改任何生产规则、词库或阈值文件。
9. THE L5StrategyAgent SHALL NOT 直接修改 `config/keywords.yaml`、`config/thresholds.yaml`、`config/category_rules.yaml`、`config/runtime.yaml` 中的任何内容。

### Requirement 2: Demo 范围限定（不做项）

**User Story:** 作为产品负责人，我希望明确本 Demo 不实现的能力，以便控制实现复杂度并对齐预期。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 仅提供命令行交互入口，不提供 Web 或图形可视化界面。
2. THE AdReviewSystem SHALL NOT 实现图像 embedding 能力。
3. THE AdReviewSystem SHALL NOT 实现图像向量数据库或图像向量召回能力。
4. THE AdReviewSystem SHALL NOT 实现基于 embedding 的历史案例向量召回，历史案例检索仅使用文本检索。
5. THE AdReviewSystem SHALL NOT 集成 YOLO 或任何对象检测模型。
6. THE AdReviewSystem SHALL NOT 实现深度抽帧策略，抽帧仅采用首尾帧、固定间隔抽帧与简单帧差场景帧。
7. THE AdReviewSystem SHALL NOT 实现抽检系统。
8. THE AdReviewSystem SHALL NOT 实现真实落地页爬虫，落地页文本仅取自 `AdMeta.landing_page.text`。
9. THE L2ASR SHALL 仅使用 faster-whisper 作为本地 ASR 方案，不集成其他 ASR 引擎。

### Requirement 3: 跨平台与技术栈约束

**User Story:** 作为开发者，我希望项目同时在 Windows 与 Ubuntu 下可用，以便本地测试与完整 demo 演示。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 兼容 Python 3.10 及以上版本运行。
2. THE AdReviewSystem SHALL 在 Windows 环境下能够运行测试套件中的全部非可选用例。
3. THE AdReviewSystem SHALL 在 Ubuntu 环境下能够运行完整 demo 流程，包括真实视频抽帧、ASR 与 LLM 调用（当配置可用时）。
4. THE AdReviewSystem SHALL 使用 `pathlib.Path` 处理所有文件与目录路径。
5. THE AdReviewSystem SHALL NOT 在源码中硬编码任何 Windows 风格的绝对路径或反斜杠路径。
6. THE AdReviewSystem SHALL 使用 `argparse` 实现命令行入口与子命令解析。
7. THE AdReviewSystem SHALL 在 `requirements.txt` 中声明以下核心依赖：`opencv-python`、`imagehash`、`Pillow`、`numpy`、`pyyaml`、`pydantic`、`pytest`、`python-dotenv`、`faster-whisper`。
8. WHERE `sentence-transformers` 被列为可选依赖，THE AdReviewSystem SHALL 在 `requirements.txt` 中以可选方式标识或在文档中说明，并在缺失时不影响主链路其他功能。
9. WHERE 当前主机不可用 GPU 或 CUDA，THE L2ASR SHALL 自动回退至 `cpu` 设备与 `int8` 计算类型。
10. WHERE GPU 与 CUDA 可用，THE L2ASR SHALL 支持 `cuda` 设备与 `float16` 计算类型。
11. IF 系统未安装 ffmpeg，THEN THE MediaPreprocessor SHALL 自动降级为不进行音频抽取，并继续完成视频帧处理或 mock 流程，不抛出未捕获异常。

### Requirement 4: LLM 与环境配置

**User Story:** 作为开发者，我希望通过环境变量配置 LLM，并在无 key 时自动使用 MockAgent，以便低门槛运行。

#### Acceptance Criteria

1. WHERE `RuntimeConfig.llm_enabled` 不为 `false`，THE AgentClient SHALL 通过环境变量 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 读取 LLM 配置，并通过 OpenAI-compatible API 调用真实 LLM。
2. WHEN 环境变量 `LLM_API_KEY` 未设置或为空，THE AgentClient SHALL 自动使用 MockAgent 进行 Agent 调用。
3. THE AdReviewSystem SHALL 在仓库根目录提供 `.env.example` 文件，示例包含 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 三个变量。
4. THE AgentClient SHALL 使用 `python-dotenv` 在启动时加载 `.env` 文件中的环境变量。
5. WHEN `RuntimeConfig.llm_enabled` 取值为 `auto`，THE AgentClient SHALL 在检测到有效 `LLM_API_KEY` 时启用真实 LLM，否则使用 MockAgent。
6. WHEN `RuntimeConfig.llm_enabled` 取值为 `false`，THE AgentClient SHALL 始终使用 MockAgent，并不读取 `LLM_API_KEY`、不调用真实 LLM。

### Requirement 5: 命令行入口与子命令

**User Story:** 作为使用者，我希望通过三个明确的子命令分别完成审核、申诉复核与策略优化，以便独立验证各层能力。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 提供 `python main.py review --meta <path>` 子命令，用于对单条广告执行完整主链路审核。
2. WHEN 执行 `review` 子命令，THE AdReviewSystem SHALL 在控制台依次打印每一层（MediaPreprocessor、L1Recall、L2RuleEngine、L3Consistency、L3RiskFusion、L4AgentReview）的处理结果摘要。
3. WHEN 执行 `review` 子命令并完成处理，THE ReportWriter SHALL 将完整结果写入 `outputs/review_result_{ad_id}.json`。
4. THE AdReviewSystem SHALL 提供 `python main.py appeal --appeal <path>` 子命令，用于对单条申诉执行 L5AppealAgent 复核。
5. WHEN 执行 `appeal` 子命令，THE AdReviewSystem SHALL 在控制台打印申诉复核结果，并由 ReportWriter 写入 `outputs/appeal_result_{appeal_id}.json`。
6. THE AdReviewSystem SHALL 提供 `python main.py optimize --logs <path>` 子命令，用于对优化日志执行 L5StrategyAgent 分析。
7. WHEN 执行 `optimize` 子命令，THE AdReviewSystem SHALL 在控制台打印 Agent 发现的新黑话与策略问题摘要，并由 ReportWriter 写入 `outputs/strategy_suggestion.json`。
8. IF `review`、`appeal` 或 `optimize` 子命令所需的输入文件不存在或不可读，THEN THE AdReviewSystem SHALL 输出明确的错误信息并以非零退出码结束，不抛出未捕获异常。
9. IF 错误信息输出过程本身失败（例如 stderr 不可写），THEN THE AdReviewSystem SHALL 仍然以退出码 `1` 结束。
10. THE AdReviewSystem SHALL 在每个子命令执行结束时确保 `outputs/` 目录已存在，必要时自动创建。

### Requirement 6: 广告输入 JSON 结构

**User Story:** 作为使用者，我希望系统接受统一结构的广告 JSON，以便复用同一份数据驱动各层模块。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 接受包含以下字段的 AdMeta JSON：`ad_id`、`media_type`、`media_path`、`title`、`description`、`category`、`brand`、`mock_asr_text`、`landing_page`、`merchant`。
2. THE AdReviewSystem SHALL 解析 `landing_page` 子结构 `{url, text, price}`。
3. THE AdReviewSystem SHALL 解析 `merchant` 子结构 `{merchant_id, qualification, history_violation_count}`，其中 `qualification` 包含 `business_license`、`brand_authorization`、`financial_license`、`medical_license` 字段。
4. THE AdReviewSystem SHALL 使用 `pydantic` 模型在 `modules/schemas.py` 中定义 AdMeta 与子结构的数据校验。
5. WHEN AdMeta JSON 中的字段缺失或类型不符，THE AdReviewSystem SHALL 输出明确的字段级错误信息并以非零退出码结束。
6. WHEN `AdMeta.media_path` 指向的文件不存在，THE AdReviewSystem SHALL 走 mock media 流程并使用 `AdMeta.mock_asr_text` 继续主链路。
7. WHEN `AdMeta.media_path` 指向的文件存在，THE AdReviewSystem SHALL 执行真实抽帧、pHash 计算、二维码检测与 ASR 处理。
8. IF AdMeta JSON 文件不存在或非合法 JSON，THEN THE AdReviewSystem SHALL 输出错误信息并以非零退出码结束。

### Requirement 7: 公共媒体预处理

**User Story:** 作为开发者，我希望媒体预处理一次性完成并被各层复用，以便控制延迟与计算成本。

#### Acceptance Criteria

1. THE MediaPreprocessor SHALL 在 review 子命令的单次执行中只调用一次，并将其结果（MediaResult）传入 L1Recall、L2RuleEngine、L3Consistency、L3RiskFusion 与 L4AgentReview。
2. WHEN `AdMeta.media_path` 存在且可读，THE MediaPreprocessor SHALL 使用 OpenCV 读取视频时长、帧率（fps）与分辨率信息并写入 MediaResult。
3. WHEN `AdMeta.media_path` 存在，THE MediaPreprocessor SHALL 抽取首帧、尾帧、按 `RuntimeConfig.sample_interval_sec` 的固定间隔帧以及简单帧差场景帧。
4. THE MediaPreprocessor SHALL 在去重后保留的关键帧数量上限为 `RuntimeConfig.max_sampled_frames`。
5. WHILE 计算 pHash，THE MediaPreprocessor SHALL 先将关键帧 resize 至 `RuntimeConfig.phash_resize` 指定边长（默认 64，可配 32）再进行 pHash 计算。
6. THE MediaPreprocessor SHALL 基于 pHash 进行相似帧去重。
7. THE MediaPreprocessor SHALL 将保留的关键帧图片缓存至 `outputs/cache/{ad_id}/frames/` 目录。
8. THE MediaPreprocessor SHALL 输出 VideoFingerprint，由保留关键帧的 pHash 列表构成。
9. WHEN 系统已安装 ffmpeg，THE MediaPreprocessor SHALL 使用 ffmpeg 将视频音频提取为 `outputs/cache/{ad_id}/audio.wav`。
10. WHEN `AdMeta.media_path` 不存在，THE MediaPreprocessor SHALL 返回 mock MediaResult，包含空帧列表、空指纹与 `mock=true` 标记，不抛出异常。
11. THE RuntimeConfig SHALL 提供 `max_sampled_frames`（默认 12，区间约 10-20）、`sample_interval_sec`（默认 1）、`phash_resize`（默认 64）三个参数控制抽帧与 pHash 行为。

### Requirement 8: L1 历史召回

**User Story:** 作为审核策略人员，我希望使用历史指纹快速召回明确违规或明确安全的广告，以便低成本拦截重复样本。

#### Acceptance Criteria

1. THE L1Recall SHALL 读取 `data/history_fingerprints.json` 作为历史指纹库。
2. THE L1Recall SHALL 通过比较 VideoFingerprint 与历史指纹的平均汉明距离及相似帧比例进行召回评分。
3. WHEN L1Recall 命中标记为明确违规的历史指纹，THE L1Recall SHALL 输出 Decision `REJECT` 并附带 ReasonCode `L1_HISTORY_VIOLATION_HIT`。
4. WHEN L1Recall 命中标记为明确安全的历史指纹，THE L1Recall SHALL 输出 Decision `APPROVE` 并附带 ReasonCode `L1_HISTORY_SAFE_HIT`。
5. IF L1Recall 未命中任何历史指纹或命中置信度低于 `Thresholds.l1_history_match_threshold`，THEN THE L1Recall SHALL 输出 Decision `NEXT`。
6. THE L1Recall SHALL NOT 调用 LLM、Agent、OCR、ASR 或图像 embedding。
7. THE L1Recall SHALL 在输出中包含模板化 reason、reason_code 与 signals 字段。

### Requirement 9: L2-1 OCR

**User Story:** 作为审核策略人员，我希望对关键帧执行可选的 OCR，以提取画面中的文本证据。

#### Acceptance Criteria

1. THE L2OCR SHALL 仅对 MediaResult 中保留的关键帧执行 OCR，不对所有视频帧执行 OCR。
2. WHEN `RuntimeConfig.enable_ocr` 为 `true` 且 PaddleOCR 可用，THE L2OCR SHALL 使用 PaddleOCR 进行真实 OCR。
3. WHEN `RuntimeConfig.enable_ocr` 为 `false`，THE L2OCR SHALL 使用 `AdMeta` 中的 `mock_ocr_texts` 字段作为 OCR 结果（缺省时为空列表），不调用任何真实 OCR。
4. IF PaddleOCR 不可用且 `enable_ocr` 为 `true`，THEN THE L2OCR SHALL 自动回退到 mock 模式并在日志中提示。
5. THE L2OCR SHALL 输出每个关键帧对应的文本列表，并合入 L2 的 evidence 字段。

### Requirement 10: L2-2 ASR（faster-whisper）

**User Story:** 作为审核策略人员，我希望对视频音频执行可选 ASR，以获取语音文本证据。

#### Acceptance Criteria

1. THE L2ASR SHALL 使用 faster-whisper 进行语音识别。
2. THE L2ASR SHALL 通过 `RuntimeConfig.asr_model_size`、`RuntimeConfig.asr_device`、`RuntimeConfig.asr_compute_type` 配置模型规模、设备与计算精度。
3. WHEN `RuntimeConfig.asr_device` 为 `auto`，THE L2ASR SHALL 在 CUDA 可用时选择 `cuda`，否则选择 `cpu`。
4. IF `RuntimeConfig.asr_device` 被显式配置为 `cuda` 但当前主机不可用 CUDA，THEN THE L2ASR SHALL 抛出明确的配置错误，不静默回退到 `cpu`。
5. WHEN `RuntimeConfig.enable_asr` 为 `false` 或 faster-whisper 模型加载失败或 ffmpeg 不可用，THE L2ASR SHALL 使用 `AdMeta.mock_asr_text` 作为 ASR 结果。
6. THE L2ASR SHALL NOT 在自动化测试中强制下载 faster-whisper 模型权重。
7. THE L2ASR SHALL 输出 ASR 文本并合入 L2 的 evidence 字段。

### Requirement 11: L2-3 二维码检测

**User Story:** 作为审核策略人员，我希望识别画面中的二维码及其外链，以发现私域引流风险。

#### Acceptance Criteria

1. THE L2QR SHALL 使用 OpenCV `QRCodeDetector` 对 MediaResult 的关键帧进行二维码检测与解码。
2. WHEN `RuntimeConfig.enable_qr` 为 `false`，THE L2QR SHALL 跳过检测并返回空结果。
3. WHEN 二维码解码内容包含外链、`微信`、`VX`、`vx`、手机号或其他私域引流词，THE L2QR SHALL 生成对应的风险信号并加入 L2 的 signals 字段。
4. THE L2QR SHALL 输出每个命中的二维码对应的解码文本与所在帧标识。

### Requirement 12: L2-4 关键词与文本归一化

**User Story:** 作为审核策略人员，我希望通过分级词库识别强违规、需归一化匹配的违规以及黑话，以避免一刀切。

#### Acceptance Criteria

1. THE L2RuleEngine SHALL 读取 `config/keywords.yaml` 并加载三类词库：HardBlockKeyword、NormalizedBlockKeyword 与 SuspiciousSlang。
2. WHEN 文本命中任一 HardBlockKeyword，THE L2RuleEngine SHALL 输出 Decision `REJECT`，ReasonCode `L2_HARD_BLOCK_HIT`，并附带命中词与命中位置作为 evidence。
3. WHEN 文本经归一化后命中 NormalizedBlockKeyword，THE L2RuleEngine SHALL 输出 Decision `REJECT`，ReasonCode `L2_NORMALIZED_BLOCK_HIT`。
4. WHEN 文本命中 SuspiciousSlang，THE L2RuleEngine SHALL NOT 直接输出 `REJECT`，且 SHALL 增加中风险分并将 Decision 置为 `NEXT` 以路由到 L3。
5. THE L2RuleEngine SHALL 在匹配前对文本执行归一化，包括全角转半角、大小写统一、去除空格与特殊符号、常见写法归一（例如 `v信→微信`、`1比1→1:1`）。
6. THE L2RuleEngine SHALL 在归一化匹配命中时，在 evidence 中保留原始文本与归一化后的文本以便审计。
7. THE L2RuleEngine SHALL 将 L2OCR、L2ASR、AdMeta.title、AdMeta.description、`landing_page.text` 全部纳入文本规则匹配范围。

### Requirement 13: L2-5 类目规则与资质校验

**User Story:** 作为审核策略人员，我希望基于类目执行差异化的资质校验，以拦截无资质的高风险类目广告。

#### Acceptance Criteria

1. THE L2RuleEngine SHALL 读取 `config/category_rules.yaml`，加载箱包、金融、医疗、功效等类目的所需资质与敏感宣称。
2. WHEN `AdMeta.category` 为箱包且文案包含"官方正品"、"专柜品质"等品牌相关宣称，THE L2RuleEngine SHALL 校验 `merchant.qualification.brand_authorization` 是否存在；缺失时 SHALL 增加 risk_score 并加入 ReasonCode `L2_MISSING_BRAND_AUTHORIZATION`。
3. WHEN `AdMeta.category` 为金融，THE L2RuleEngine SHALL 校验 `merchant.qualification.financial_license` 是否存在；缺失时 SHALL 增加 risk_score 并加入 ReasonCode `L2_MISSING_FINANCIAL_LICENSE`。
4. WHEN `AdMeta.category` 为医疗或文案出现医疗、功效宣称，THE L2RuleEngine SHALL 校验 `merchant.qualification.medical_license` 是否存在；缺失时 SHALL 增加 risk_score 并加入 ReasonCode `L2_MISSING_MEDICAL_LICENSE`。
5. WHEN 金融类文案命中"稳赚"、"保本"、"高收益"等敏感宣称且金融资质缺失，THE L2RuleEngine SHALL 输出 Decision `REJECT`。

### Requirement 14: L2-6 落地页基础规则

**User Story:** 作为审核策略人员，我希望基于落地页文本执行基础规则匹配，以发现私域引流与价格冲突。

#### Acceptance Criteria

1. THE L2RuleEngine SHALL 仅使用 `AdMeta.landing_page.text` 与 `AdMeta.landing_page.price` 进行落地页分析，不发起任何网络请求。
2. WHEN 落地页文本命中 HardBlockKeyword 或 NormalizedBlockKeyword，THE L2RuleEngine SHALL 按照 Requirement 12 的相应规则处理。
3. WHEN 落地页文本命中通用私域引流词或 L2QR 检测到私域引流二维码，THE L2RuleEngine SHALL 增加 risk_score 并加入 ReasonCode `L2_PRIVATE_DOMAIN_DRAINAGE`。
4. WHEN 广告文案宣称"低价"或"免费"且 `landing_page.price` 与之冲突，THE L2RuleEngine SHALL 增加 risk_score 并加入 ReasonCode `L2_PRICE_INCONSISTENT`。

### Requirement 15: L2 输出契约

**User Story:** 作为下游模块，我希望 L2 输出结构稳定可消费，以便 L3 与报告统一处理。

#### Acceptance Criteria

1. THE L2RuleEngine SHALL 输出包含 `decision`、`risk_score`、`reason_code`、`reason`、`signals`、`evidence` 六个字段的结构化结果。
2. THE L2RuleEngine SHALL 使用模板化字符串生成 `reason` 字段，不调用 Agent 或 LLM。
3. THE L2RuleEngine SHALL 在 `signals` 中以结构化方式列出每个命中信号的来源（OCR/ASR/QR/keyword/category/landing_page）与命中内容。
4. THE L2RuleEngine SHALL 保证输出的 `decision` 取值范围为 `APPROVE | REJECT | NEXT`。

### Requirement 16: L3-1 简单一致性规则

**User Story:** 作为审核策略人员，我希望识别素材与落地页的明显冲突，以发现仿冒、错挂、私域引流等问题。

#### Acceptance Criteria

1. WHEN 素材文本（AdClaimText）包含"官方正品"且 `merchant.qualification.brand_authorization` 缺失，THE L3Consistency SHALL 增加 risk_score 并加入 ReasonCode `L3_OFFICIAL_NO_AUTHORIZATION`。
2. WHEN 素材文本包含"正品"且 `landing_page.text` 包含"渠道货"、"尾单"、"复刻"中的任一词，THE L3Consistency SHALL 增加 risk_score 并加入 ReasonCode `L3_OFFICIAL_VS_CHANNEL`。
3. WHEN 素材文本宣称"低价"或"免费"且 `landing_page.price` 实际价格与之不一致，THE L3Consistency SHALL 增加 risk_score 并加入 ReasonCode `L3_PRICE_CONFLICT`。
4. WHEN `AdMeta.category` 为日用品而 AdClaimText 或 LandingText 包含减肥、医疗或金融相关内容，THE L3Consistency SHALL 增加 risk_score 并加入 ReasonCode `L3_CATEGORY_MISMATCH`。
5. WHEN 素材文本宣称"平台内购买"等而 LandingText 出现"微信咨询"等私域引流词，THE L3Consistency SHALL 增加 risk_score 并加入 ReasonCode `L3_PRIVATE_DOMAIN_CONFLICT`。
6. THE L3Consistency SHALL 仅使用模板生成 reason，不调用 Agent 或 LLM。

### Requirement 17: L3-2 文本 Embedding 一致性

**User Story:** 作为审核策略人员，我希望对广告文案与落地页文本进行语义相似度比较，以补充结构化规则。

#### Acceptance Criteria

1. THE L3TextEmbedding SHALL 仅比较 AdClaimText（`title + description + OCR + ASR`）与 LandingText 两段文本。
2. WHEN `RuntimeConfig.enable_text_embedding` 为 `true` 且 `sentence-transformers` 可用，THE L3TextEmbedding SHALL 使用 sentence-transformers 计算 cosine 相似度。
3. WHEN `sentence-transformers` 不可用或 `enable_text_embedding` 为 `false`，THE L3TextEmbedding SHALL 回退到基于 token overlap 的相似度计算。
4. WHEN 计算得到的相似度低于阈值，THE L3TextEmbedding SHALL 仅产生风险信号 `L3_LOW_SEMANTIC_SIMILARITY`，不直接给出 `REJECT`。
5. THE L3TextEmbedding SHALL NOT 用于图像或视频帧的相似度计算。

### Requirement 18: L3-3 多信号风险融合

**User Story:** 作为审核策略人员，我希望基于多信号加权得分进行最终前置决策，以仅在灰区调用 Agent。

#### Acceptance Criteria

1. THE L3RiskFusion SHALL 汇总 L1Recall、L2RuleEngine、L3Consistency、L3TextEmbedding 的所有信号与子分数，得到总 risk_score。
2. THE L3RiskFusion SHALL 使用以下基础加分建议：HardBlockKeyword `+40`、SuspiciousSlang `+15`、缺失必要资质 `+30`、落地页高风险 `+20`、二维码或微信引流 `+20`、商家历史违规 `+10`、素材-落地页不一致 `+20`、类目错挂 `+30`。
3. WHEN risk_score 大于或等于 `Thresholds.l3_reject_score`（建议默认 85），THE L3RiskFusion SHALL 输出 Decision `REJECT`。
4. WHEN risk_score 小于或等于 `Thresholds.l3_approve_score`（建议默认 20）且不存在任何冲突信号，THE L3RiskFusion SHALL 输出 Decision `APPROVE`。
5. IF risk_score 处于 `l3_approve_score` 与 `l3_reject_score` 之间，或存在冲突信号，THEN THE L3RiskFusion SHALL 输出 Decision `AGENT_REVIEW`。
6. THE L3RiskFusion SHALL 输出包含 `decision`、`risk_score`、`reason_code`、`reason`、`signals`、`evidence` 字段的结构化结果。
7. THE L3RiskFusion SHALL 使用模板生成 reason，不调用 Agent 或 LLM。

### Requirement 19: L4 在线复杂复核 Agent

**User Story:** 作为审核策略人员，我希望仅对灰区样本调用 Agent 进行复杂复核，以兼顾质量与成本。

#### Acceptance Criteria

1. THE L4AgentReview SHALL 仅在 L3RiskFusion 输出 Decision 为 `AGENT_REVIEW` 时被调用。
2. THE L4AgentReview SHALL 向 Agent 输入广告基础信息、L1Recall/L2RuleEngine/L3Consistency/L3RiskFusion 结果、OCR、ASR、QR、落地页文本、商家资质与历史违规次数、风险信号、规则文档摘录与历史案例文本。
3. THE L4AgentReview SHALL 仅暴露文本级工具能力：规则 RAG（从 `data/policy_docs.json` 检索）、历史案例 RAG（从 `data/history_cases.json` 文本检索）、证据链整理。
4. THE L4AgentReview SHALL NOT 提供调用图像 embedding、图像向量库、爬虫或修改文件的工具。
5. THE L4AgentReview SHALL 要求 Agent 输出包含 `decision`、`confidence`、`risk_types`、`evidence_chain`、`policy_refs`、`reason`、`next_action` 字段的 JSON。
6. THE Agent SHALL 在 L4AgentReview 上下文中将 `decision` 限定为 `REJECT | APPROVE | HUMAN_REVIEW`。
7. WHEN Agent 的 `confidence` 低于 `Thresholds.agent_confidence_auto_threshold`，THE L4AgentReview SHALL 将最终 Decision 置为 `HUMAN_REVIEW`。
8. WHEN 样本被识别为高敏感类目（金融、医疗、品牌仿冒等），THE L4AgentReview SHALL NOT 直接将 Decision 置为 `APPROVE`，且 SHALL 在不确定时倾向 `HUMAN_REVIEW`。
9. IF Agent 返回的内容不是合法 JSON，THEN THE L4AgentReview SHALL 尝试修复并解析，修复失败时 SHALL 回退为 Decision `HUMAN_REVIEW` 并附带 ReasonCode `L4_AGENT_OUTPUT_INVALID`。
10. WHEN 未配置 `LLM_API_KEY`，THE L4AgentReview SHALL 使用 MockAgent，并基于 risk_score 与 signals 生成结构合理的 JSON 输出。

### Requirement 20: L5 申诉复核 Agent

**User Story:** 作为审核策略人员，我希望对商家申诉给出结构化建议，但不让 Agent 直接改判，以确保人工最终把关。

#### Acceptance Criteria

1. THE L5AppealAgent SHALL 接受 `samples/appeal_xxx.json` 作为输入，并加载对应广告的原始审核结论、商家申诉文本、广告证据与 `data/policy_docs.json`。
2. THE L5AppealAgent SHALL 输出包含 `appeal_id`、`appeal_suggestion`、`confidence`、`reason`、`required_extra_materials`、`policy_refs` 字段的 JSON。
3. THE L5AppealAgent SHALL 将 `appeal_suggestion` 限定为以下取值：`KEEP_REJECT`、`SUGGEST_APPROVE_AFTER_HUMAN_REVIEW`、`NEED_MORE_MATERIALS`、`HUMAN_REVIEW`。
4. THE L5AppealAgent SHALL NOT 直接修改原始审核结论或将广告状态变更为最终通过。
5. WHEN 申诉涉及品牌、金融或医疗类目且对应资质缺失，THE L5AppealAgent SHALL 输出 `NEED_MORE_MATERIALS`、`HUMAN_REVIEW` 或 `KEEP_REJECT`（当申诉本身明显缺乏依据时），并在所有这些情况下都在 `required_extra_materials` 中列出所需补充资质。
6. WHEN 未配置 `LLM_API_KEY`，THE L5AppealAgent SHALL 使用 MockAgent 生成结构合规的建议。

### Requirement 21: L5 策略优化 Agent

**User Story:** 作为审核策略人员，我希望从误杀/漏判/人工拒绝/申诉日志中发现新黑话与规则问题，并以候选形式产出，不直接上线。

#### Acceptance Criteria

1. THE L5StrategyAgent SHALL 接受 `data/optimization_logs.json` 作为输入，分析其中误杀、漏判、人工拒绝与申诉记录。
2. THE L5StrategyAgent SHALL 输出包含 `optimization_target`、`problem`、`suggestions`、`validation_plan`、`risk`、`requires_human_approval` 字段的 JSON。
3. THE `suggestions` SHALL 为列表，每项包含 `type`、`words`、`action`、`route` 字段。
4. WHEN 日志中频繁出现"柜姐渠道"、"原厂尾单"、"内部福利"、"懂的来"、"渠道价"等箱包黑话，THE L5StrategyAgent SHALL 建议将这些词加入 SuspiciousSlang 词库，对应 `action` 为加中风险分，`route` 为路由到 L3，而非直接 `REJECT`。
5. THE L5StrategyAgent SHALL NOT 直接修改 `config/keywords.yaml`、`config/category_rules.yaml`、`config/thresholds.yaml`、`config/runtime.yaml`。
6. WHERE L5StrategyAgent 需要产出候选词库，THE L5StrategyAgent SHALL 将候选词库写入 `outputs/candidate_keywords.yaml`，并在文件头部明确标注为候选、不自动上线。
7. THE L5StrategyAgent SHALL 在输出中将 `requires_human_approval` 设置为 `true`。

### Requirement 22: 模板化理由与稳定输出契约

**User Story:** 作为下游消费方与审计人员，我希望各层输出的理由与结构稳定可解析，以便审计与回放。

#### Acceptance Criteria

1. THE L1Recall、L2RuleEngine、L3Consistency、L3RiskFusion SHALL 使用模板与结构化证据生成 `reason` 字段，不调用 Agent 或 LLM。
2. THE AdReviewSystem SHALL 在每一层输出中保留 `reason_code` 与 `signals` 字段。
3. THE AgentClient SHALL 对 Agent 返回内容执行 JSON 解析；解析失败时 SHALL 在同一调用中立即（原子性地）尝试修复（例如裁剪非 JSON 前后缀），不允许停留在仅"已检测到失败但尚未尝试修复"的中间状态；仍失败时 SHALL 回退为带有错误标记的结构化 JSON 而非抛出未捕获异常。
4. THE ReportWriter SHALL 保证 `outputs/review_result_{ad_id}.json`、`outputs/appeal_result_{appeal_id}.json`、`outputs/strategy_suggestion.json` 的字段结构在多次执行间稳定一致。

### Requirement 23: 配置文件

**User Story:** 作为审核策略人员，我希望通过外部 YAML 配置控制运行时行为、阈值、词库与类目规则。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 提供 `config/runtime.yaml`，包含 `max_sampled_frames`（默认 12）、`sample_interval_sec`（默认 1）、`phash_resize`（默认 64）、`enable_ocr`（默认 false）、`enable_asr`（默认 true）、`asr_model_size`（默认 `small`）、`asr_device`（默认 `auto`）、`asr_compute_type`（默认 `int8_float16`）、`enable_qr`（默认 true）、`enable_text_embedding`（默认 true）、`llm_enabled`（默认 `auto`）。
2. THE AdReviewSystem SHALL 提供 `config/thresholds.yaml`，包含 `l1_history_match_threshold`、`l2_reject_score`、`l3_reject_score`、`l3_approve_score`、`agent_confidence_auto_threshold`。
3. THE AdReviewSystem SHALL 提供 `config/keywords.yaml`，包含箱包、金融、医疗、通用私域引流相关的 HardBlockKeyword、NormalizedBlockKeyword 与 SuspiciousSlang 三类词库。
4. THE AdReviewSystem SHALL 提供 `config/category_rules.yaml`，包含箱包、金融、医疗、功效等类目的所需资质字段与敏感宣称模式。
5. WHEN 任一配置文件缺失或格式错误，THE AdReviewSystem SHALL 输出明确的配置加载错误并对该文件的所有可加载项使用代码内置默认值继续启动，不因此终止进程。
6. THE AdReviewSystem SHALL 允许在配置加载失败时由具体异常向上传播以辅助排查，但 SHALL 同时输出可读的配置错误日志，确保用户能够在终端看到错误原因。

### Requirement 24: 样例数据集

**User Story:** 作为开发者与审核策略人员，我希望项目自带一组样例数据，以便回归测试预期决策路径。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 在 `samples/` 目录下提供 5 条广告 JSON：`ad_001.json` 至 `ad_005.json`。
2. THE `samples/ad_001.json` SHALL 表达"箱包仿冒疑似"场景，包含"官方正品/专柜品质" + 无 `brand_authorization` + 落地页含"渠道货"、"原厂尾单"、"微信咨询"，且其期望审核路径 SHALL 进入 L4AgentReview。
3. THE `samples/ad_002.json` SHALL 表达"箱包明确违规"场景，文本包含"1:1复刻"、"高仿"或"A货"，且其期望审核路径 SHALL 在 L2RuleEngine 直接 `REJECT`。
4. THE `samples/ad_003.json` SHALL 表达"低风险日用品"场景，且其期望审核路径 SHALL 在 L3RiskFusion 直接 `APPROVE`。
5. THE `samples/ad_004.json` SHALL 表达"金融类违规"场景，包含"稳赚/保本/高收益" + 无 `financial_license`，且其期望审核路径 SHALL 输出 `REJECT`。
6. THE `samples/ad_005.json` SHALL 表达"类目错挂"场景，`category` 为日用品但文案/落地页含减肥或功效内容、无医疗资质，且其期望审核路径 SHALL 在 L3RiskFusion 输出 `REJECT` 或进入 L4AgentReview。
7. THE AdReviewSystem SHALL 在 `samples/` 目录下提供 2 条申诉 JSON：`appeal_001.json` 与 `appeal_002.json`。
8. THE `samples/appeal_001.json` SHALL 针对 `ad_001` 的拒绝结论，商家辩称"渠道货=代购"但未提供品牌授权，且 L5AppealAgent 的预期建议 SHALL 为 `KEEP_REJECT` 或 `NEED_MORE_MATERIALS`。
9. THE `samples/appeal_002.json` SHALL 表达"误杀样本 + 商家补充资质"场景，且 L5AppealAgent 的预期建议 SHALL 为 `SUGGEST_APPROVE_AFTER_HUMAN_REVIEW` 或 `HUMAN_REVIEW`。
10. THE AdReviewSystem SHALL 在 `data/optimization_logs.json` 中提供 8 至 12 条日志，使 L5StrategyAgent 能够发现"柜姐渠道"、"原厂尾单"、"内部福利"、"懂的来"、"渠道价"等箱包黑话候选。

### Requirement 25: 测试要求

**User Story:** 作为开发者，我希望在 Windows 无 GPU/无 ffmpeg/无真实视频/无 LLM key 的环境下也能跑通主要测试，以便低门槛验证。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 在 `tests/` 目录下提供以下测试文件：`test_media_preprocess.py`、`test_l1_history_recall.py`、`test_l2_rule_engine.py`、`test_l3_risk_fusion.py`、`test_agent_mock.py`、`test_appeal_agent.py`、`test_strategy_agent.py`、`test_cli.py`。
2. THE 测试套件 SHALL 在 Windows 且无 GPU、无 ffmpeg、无真实视频文件的环境下通过除被显式标记为可选的用例之外的全部用例。
3. THE 测试套件 SHALL NOT 强制下载 faster-whisper 模型权重。
4. THE 测试套件 SHALL NOT 强制安装 PaddleOCR。
5. THE Agent 相关测试 SHALL 默认使用 MockAgent，不依赖真实 `LLM_API_KEY`。
6. THE `test_cli.py` SHALL 至少覆盖 `review`、`appeal`、`optimize` 三个子命令各一条用例。
7. THE 测试套件 SHALL 覆盖以下决策路径：L1 无命中输出 `NEXT`；L2 命中 HardBlockKeyword 输出 `REJECT`；L2 命中 SuspiciousSlang 不直接输出 `REJECT`；L3 多信号输出 `AGENT_REVIEW`；L3 低风险输出 `APPROVE`；MockAgent 在不同输入下输出 `HUMAN_REVIEW` 与 `REJECT`；L5AppealAgent 在缺资质申诉下给出 `KEEP_REJECT` 或 `NEED_MORE_MATERIALS`；L5StrategyAgent 能从 `optimization_logs.json` 中发现至少一个候选黑话词。

### Requirement 26: 项目目录结构

**User Story:** 作为开发者，我希望项目按统一的目录结构组织，以便协作与扩展。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 在仓库根目录提供 `main.py`、`README.md`、`requirements.txt`、`.env.example`。
2. THE AdReviewSystem SHALL 在 `config/` 目录下提供 `keywords.yaml`、`category_rules.yaml`、`thresholds.yaml`、`runtime.yaml`。
3. THE AdReviewSystem SHALL 在 `samples/` 目录下提供 `ad_001.json` 至 `ad_005.json` 与 `appeal_001.json`、`appeal_002.json`。
4. THE AdReviewSystem SHALL 在 `data/` 目录下提供 `history_fingerprints.json`、`policy_docs.json`、`history_cases.json`、`optimization_logs.json`。
5. THE AdReviewSystem SHALL 在 `modules/` 目录下提供 `__init__.py`、`schemas.py`、`media_preprocess.py`、`l1_history_recall.py`、`l2_ocr.py`、`l2_asr.py`、`l2_qr.py`、`l2_rule_engine.py`、`l3_consistency.py`、`l3_risk_fusion.py`、`agent_client.py`、`l4_agent_review.py`、`l5_appeal_agent.py`、`l5_strategy_agent.py`、`report_writer.py`、`utils.py`。
6. THE AdReviewSystem SHALL 在 `tests/` 目录下提供 Requirement 25 中列出的测试文件。
7. THE AdReviewSystem SHALL 提供 `outputs/.gitkeep` 以保留输出目录。

### Requirement 27: 质量、健壮性与性能

**User Story:** 作为运维与开发者，我希望系统在依赖缺失或输入异常时自动降级而非崩溃，并保持稳定的输出与可控的延迟。

#### Acceptance Criteria

1. THE AdReviewSystem SHALL 为所有公共函数提供类型标注，并使用结构化日志输出每一层的关键事件。
2. IF 视频文件缺失，THEN THE AdReviewSystem SHALL 走 mock media 流程并继续主链路，不抛出未捕获异常。
3. IF faster-whisper 模型加载失败或 ffmpeg 不可用，THEN THE L2ASR SHALL 回退到 `mock_asr_text`，不抛出未捕获异常。
4. IF `LLM_API_KEY` 缺失或 LLM 调用失败，THEN THE AgentClient SHALL 回退到 MockAgent，不抛出未捕获异常。
5. THE AdReviewSystem SHALL 保证所有审核结论字段（含 `reason_code` 与 `signals`）在多次执行同一输入时保持结构稳定。
6. THE AgentClient SHALL 保证返回的 Agent 输出最终能被 `json.loads` 解析或经过修复后被解析；当输入为可修复但非纯 JSON 时，THE AgentClient SHALL 在执行修复的同时在结果中携带 `repair_applied=true` 与原始 raw 文本片段以便审计；不可修复时 SHALL 返回带错误标记（`error=true`、错误原因字段）的结构化 JSON。
7. THE MediaPreprocessor SHALL 保证抽帧与 pHash 在单次 review 子命令执行中只执行一次，并在后续层中复用其缓存结果。
8. THE MediaPreprocessor SHALL 保证 pHash 在 resize 至 `RuntimeConfig.phash_resize` 后再计算，以控制计算成本。
9. THE L1Recall SHALL NOT 加载或调用任何重型机器学习模型。
10. THE L2OCR、L2QR SHALL 仅对 MediaPreprocessor 输出的关键帧执行计算，不对全量视频帧执行计算。
11. THE L3Consistency 与 L3RiskFusion SHALL NOT 调用 LLM 或 Agent。
12. THE L4AgentReview、L5AppealAgent、L5StrategyAgent SHALL 是仅有的允许调用 Agent 的模块。

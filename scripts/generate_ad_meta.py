#!/usr/bin/env python3
"""
傻瓜式脚本：为真实视频生成配套的广告 JSON 文件

用法：
1. 把视频放到 samples/ 目录下
2. 运行: python scripts/generate_ad_meta.py
3. 按提示填写每个视频的元信息
4. 生成的 JSON 会写入 samples/ 目录

或者直接编辑下面的 AD_TEMPLATES 列表，然后运行脚本自动生成。
"""
import json
import sys
from pathlib import Path

# ============================================================
# 在这里编辑你的广告数据
# 每条 = 一个视频 + 一组元信息
# media_path 指向 samples/ 下的真实视频文件
# ============================================================
AD_TEMPLATES = [
    # --- 样例 1: 箱包仿冒疑似 → 期望进入 L4 Agent ---
    {
        "ad_id": "real_001",
        "media_type": "video",
        "media_path": "samples/real_001.mp4",
        "title": "官方正品 专柜品质 大牌箱包限时特惠",
        "description": "专柜同款品质保证，正品保障，支持验货",
        "category": "箱包",
        "brand": "LV",
        "mock_asr_text": "",  # 有真实视频时留空，ASR 会自动转写
        "mock_ocr_texts": [],  # 有真实视频时留空，OCR 会自动识别
        "landing_page": {
            "url": "https://example.com/bag",
            "text": "渠道货源，原厂尾单，品质保证，详情咨询客服",
            "price": 899.0,
        },
        "merchant": {
            "merchant_id": "m_001",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,  # 无品牌授权 → 触发资质风险
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 1,
        },
    },
    # --- 样例 2: 箱包明确违规 → 期望 L2 直接 REJECT ---
    {
        "ad_id": "real_002",
        "media_type": "video",
        "media_path": "samples/real_002.mp4",
        "title": "顶级1:1复刻大牌箱包 高仿经典款",
        "description": "A货精品，做工精细，与正品无差别",
        "category": "箱包",
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/bag2",
            "text": "高仿精品箱包，一比一复刻，厂家直销",
            "price": 350.0,
        },
        "merchant": {
            "merchant_id": "m_002",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 3,
        },
    },
    # --- 样例 3: 低风险日用品 → 期望 L3 APPROVE ---
    {
        "ad_id": "real_003",
        "media_type": "video",
        "media_path": "samples/real_003.mp4",
        "title": "家用收纳盒 桌面整理神器",
        "description": "多功能收纳盒，简约设计，实用美观",
        "category": "日用品",
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/storage",
            "text": "多功能桌面收纳盒，简约设计，大容量",
            "price": 29.9,
        },
        "merchant": {
            "merchant_id": "m_003",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 0,
        },
    },
    # --- 样例 4: 金融违规 → 期望 L2 REJECT ---
    {
        "ad_id": "real_004",
        "media_type": "video",
        "media_path": "samples/real_004.mp4",
        "title": "稳赚理财项目 保本高收益",
        "description": "零风险投资，保本保息，年化收益高达50%",
        "category": "金融",
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/finance",
            "text": "零门槛投资理财，保本保息，年化收益50%以上",
            "price": None,
        },
        "merchant": {
            "merchant_id": "m_004",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 2,
        },
    },
    # --- 样例 5: 类目错挂 → 期望 L3 REJECT 或进入 L4 ---
    {
        "ad_id": "real_005",
        "media_type": "video",
        "media_path": "samples/real_005.mp4",
        "title": "天然植物精华 轻松瘦身",
        "description": "纯天然减肥产品，一个月瘦20斤，无副作用",
        "category": "日用品",  # 故意填日用品，实际是减肥
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/slim",
            "text": "快速减肥瘦身，燃脂排毒，治疗肥胖",
            "price": 198.0,
        },
        "merchant": {
            "merchant_id": "m_005",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 0,
        },
    },
    # --- 样例 6: L1 历史命中测试 → 用与历史库相同的视频 ---
    # 注意：这条的视频应该和 history_videos/ 中某个违规视频相同或高度相似
    {
        "ad_id": "real_006",
        "media_type": "video",
        "media_path": "samples/real_006.mp4",  # 放一个与 history_videos/violation_001.mp4 相同的视频
        "title": "大牌包包特惠",
        "description": "品质保证",
        "category": "箱包",
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/bag6",
            "text": "限时特惠",
            "price": 599.0,
        },
        "merchant": {
            "merchant_id": "m_006",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 0,
        },
    },
    # --- 样例 7: 含二维码的私域引流 → 期望 L2/L3 加分 ---
    {
        "ad_id": "real_007",
        "media_type": "video",
        "media_path": "samples/real_007.mp4",  # 视频画面中含微信二维码
        "title": "正品代购 海外直邮",
        "description": "扫码加好友，更多优惠等你来",
        "category": "箱包",
        "brand": "",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/bag7",
            "text": "加微信咨询，更多款式私聊",
            "price": 1299.0,
        },
        "merchant": {
            "merchant_id": "m_007",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": None,
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 0,
        },
    },
    # --- 样例 8: 完全合规的品牌广告 → 期望 L3 APPROVE ---
    {
        "ad_id": "real_008",
        "media_type": "video",
        "media_path": "samples/real_008.mp4",
        "title": "品牌官方旗舰店 正品保障",
        "description": "官方授权经销商，支持专柜验货",
        "category": "箱包",
        "brand": "Coach",
        "mock_asr_text": "",
        "mock_ocr_texts": [],
        "landing_page": {
            "url": "https://example.com/coach",
            "text": "Coach 官方授权店，正品保障，支持验货",
            "price": 2999.0,
        },
        "merchant": {
            "merchant_id": "m_008",
            "qualification": {
                "business_license": "valid",
                "brand_authorization": "valid",  # 有品牌授权
                "financial_license": None,
                "medical_license": None,
            },
            "history_violation_count": 0,
        },
    },
]


def main():
    output_dir = Path("samples")
    output_dir.mkdir(exist_ok=True)

    for ad in AD_TEMPLATES:
        filename = f"{ad['ad_id']}.json"
        filepath = output_dir / filename
        filepath.write_text(
            json.dumps(ad, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        video_exists = "✓" if Path(ad["media_path"]).exists() else "✗ (视频不存在，将走 mock)"
        print(f"  {filename} → {video_exists}")

    print(f"\n生成 {len(AD_TEMPLATES)} 条广告 JSON 到 samples/ 目录")
    print("\n提示：")
    print("  - 把对应的 .mp4 视频文件放到 samples/ 目录下")
    print("  - 视频文件名必须与 media_path 中的文件名一致")
    print("  - 没有视频的条目会自动走 mock 模式（使用 mock_asr_text）")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""B站活动/装扮 URL 解析器 —— 从页面链接自动提取商品ID和参数"""

import re
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActivityInfo:
    """从 URL 解析出的活动/装扮信息"""
    url: str = ""
    kind: str = ""               # "dlc" 数字卡片 | "suit" 装扮 | "unknown"
    act_id: int = 0              # 活动ID
    lottery_id: int = 0          # 抽奖ID（仅 DLC）
    item_id: int = 0             # 装扮商品ID
    name: str = ""               # 商品名称（若 API 可查到）
    sale_time: str = ""          # 开售时间 "2025-01-01 20:00:00"
    parsed: bool = False         # 是否成功解析
    error: str = ""              # 错误信息

    def __bool__(self):
        return self.parsed


def parse_activity_url(url: str, api=None) -> ActivityInfo:
    """解析 B站活动/装扮页面 URL，提取商品信息
    
    支持格式：
      - blackboard/activity-xxx.html?type=dlc&id=xxx&lottery_id=xxx
      - h5/mall/suit/detail?id=xxx
      - bilibili.com/blackboard/xxx.html?type=suit&id=xxx
    
    Args:
        url: B站活动或装扮页面完整 URL
        api: 可选的 BiliAPI 实例，用于查询补充信息
    
    Returns:
        ActivityInfo 数据类，含解析出的所有字段
    """
    info = ActivityInfo(url=url)

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # parse_qs 返回 {key: [value]} 格式
        flat = {k: v[0] for k, v in params.items()}

        # 提取 type
        kind = flat.get("type", "").lower()

        # 提取 act_id
        act_id_str = flat.get("id", "")
        if act_id_str and act_id_str.isdigit():
            info.act_id = int(act_id_str)

        # 提取 lottery_id
        lot_str = flat.get("lottery_id", "")
        if lot_str and lot_str.isdigit():
            info.lottery_id = int(lot_str)

        # 提取 item_id（h5/mall/suit/detail?id=xxx 格式）
        if not info.act_id and "mall/suit/detail" in parsed.path:
            item_str = flat.get("id", "")
            if item_str and item_str.isdigit():
                info.item_id = int(item_str)
                info.act_id = info.item_id  # 装扮场景下 act_id 即 item_id
                info.kind = "suit"

        # 判定类型
        if kind == "dlc":
            info.kind = "dlc"
        elif kind == "suit" or info.item_id:
            info.kind = "suit"

        # 通过 API 补充信息
        if api and (info.act_id or info.item_id):
            _enrich_from_api(info, api)

        if info.act_id or info.lottery_id:
            info.parsed = True
        elif info.kind:
            info.parsed = True
        else:
            info.error = "无法从 URL 提取活动ID或商品ID，请检查链接格式"

    except Exception as e:
        info.error = f"URL 解析失败: {e}"

    return info


def _enrich_from_api(info: ActivityInfo, api) -> None:
    """通过 B站 API 补充商品名称和开售时间"""
    try:
        # 先尝试装扮详情 API
        item_id = info.item_id or info.act_id
        if item_id:
            detail = api.get_suit_detail(item_id)
            if detail and isinstance(detail, dict):
                if detail.get("name"):
                    info.name = str(detail["name"])
                if detail.get("sale_time"):
                    info.sale_time = str(detail["sale_time"])

        # 如果装扮 API 没有返回有效信息，且是 DLC，尝试搜索
        if not info.name and info.kind == "dlc" and info.act_id:
            _enrich_from_search(info, api, str(info.act_id))

    except Exception:
        pass  # API 增强失败不影响主流程


def _enrich_from_search(info: ActivityInfo, api, keyword: str) -> None:
    """通过装扮搜索 API 补充信息"""
    try:
        result = api.search_suit(keyword)
        # search_suit 返回的结构可能是 dict 或 list
        if isinstance(result, list):
            suits = result
        elif isinstance(result, dict):
            suits = result.get("list", result.get("data", []))
        else:
            return

        if isinstance(suits, list) and suits:
            s = suits[0]
            if not info.name and s.get("name"):
                info.name = str(s["name"])
            if not info.sale_time and s.get("sale_time"):
                info.sale_time = str(s["sale_time"])
    except Exception:
        pass


def extract_item_id_from_url(url: str) -> Optional[int]:
    """从 URL 快速提取数字 ID（公共工具函数）"""
    # 匹配 URL 中 id=xxx 或 item_id=xxx 或 lottery_id=xxx
    for pattern in [r'[?&]id=(\d+)', r'[?&]item_id=(\d+)', r'[?&]lottery_id=(\d+)',
                    r'/detail[?/](\d+)', r'/(\d+)[?/]']:
        m = re.search(pattern, url)
        if m:
            return int(m.group(1))
    return None

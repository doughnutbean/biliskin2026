"""配置管理模块 - 加载和保存 B站装扮抢购工具的配置"""

import json
import os
from typing import Optional
from dataclasses import dataclass, field, asdict
import sys


def _get_app_dir():
    """获取应用程序目录（支持PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_get_app_dir(), "config.json")
COOKIES_PATH = os.path.join(_get_app_dir(), "cookies.json")


@dataclass
class GrabConfig:
    """抢购配置"""
    item_id: str = ""                     # 装扮商品ID
    num: int = 1                          # 购买数量
    mode: str = "once"                    # 抢购模式: once | watch
    retry_interval: float = 0.5           # 重试间隔（秒）
    max_retries: int = 20                 # 最大重试次数
    sale_time: str = ""                   # 开售时间，格式: "2025-01-01 20:00:00"
    advance_seconds: float = 0.5          # 提前发起请求的秒数（精确到毫秒）
    concurrent_workers: int = 8           # 并发工作线程数


@dataclass
class BiliConfig:
    """B站API基础配置"""
    base_url: str = "https://api.bilibili.com"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


@dataclass
class NotifyConfig:
    """通知配置"""
    enabled: bool = False
    type: str = "desktop"                 # desktop | pushplus
    pushplus_token: str = ""


@dataclass
class ProxyConfig:
    """代理配置"""
    enabled: bool = False
    http: str = ""
    https: str = ""


@dataclass
class AppConfig:
    """应用总配置"""
    bilibili: BiliConfig = field(default_factory=BiliConfig)
    grab: GrabConfig = field(default_factory=GrabConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)


def load_config() -> AppConfig:
    """从 config.json 加载配置"""
    config = AppConfig()
    if not os.path.exists(CONFIG_PATH):
        save_config(config)
        return config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # B站API配置
        if "bilibili" in raw:
            b = raw["bilibili"]
            config.bilibili = BiliConfig(
                base_url=b.get("base_url", config.bilibili.base_url),
                user_agent=b.get("user_agent", config.bilibili.user_agent),
            )

        # 抢购配置
        if "grab" in raw:
            g = raw["grab"]
            config.grab = GrabConfig(
                item_id=g.get("item_id", ""),
                num=g.get("num", 1),
                mode=g.get("mode", "once"),
                retry_interval=g.get("retry_interval", 0.5),
                max_retries=g.get("max_retries", 20),
                sale_time=g.get("sale_time", ""),
                advance_seconds=g.get("advance_seconds", 0.5),
                concurrent_workers=g.get("concurrent_workers", 8),
            )

        # 通知配置
        if "notify" in raw:
            n = raw["notify"]
            config.notify = NotifyConfig(
                enabled=n.get("enabled", False),
                type=n.get("type", "desktop"),
                pushplus_token=n.get("pushplus_token", ""),
            )

        # 代理配置
        if "proxy" in raw:
            p = raw["proxy"]
            config.proxy = ProxyConfig(
                enabled=p.get("enabled", False),
                http=p.get("http", ""),
                https=p.get("https", ""),
            )

    except (json.JSONDecodeError, IOError) as e:
        print(f"[警告] 配置文件加载失败: {e}，使用默认配置")

    return config


def save_config(config: AppConfig) -> None:
    """保存配置到 config.json"""
    raw = {
        "_comment": "B站装扮抢购工具配置文件",
        "bilibili": asdict(config.bilibili),
        "grab": asdict(config.grab),
        "notify": asdict(config.notify),
        "proxy": asdict(config.proxy),
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[错误] 保存配置文件失败: {e}")


def get_config_path() -> str:
    return CONFIG_PATH


def get_cookies_path() -> str:
    return COOKIES_PATH
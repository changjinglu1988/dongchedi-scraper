"""抓取器抽象基类。每个数据源（懂车帝、汽车之家等）实现一个子类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlparse


class BaseScraper(ABC):
    name: str = ""
    host_patterns: list[str] = []

    @classmethod
    def match(cls, url: str) -> bool:
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            return False
        host = host.lower()
        return any(host == p or host.endswith("." + p) for p in cls.host_patterns)

    @abstractmethod
    def parse_ids(self, url: str) -> list[str]:
        """从 URL 中解析出一个或多个 token。token 是 fetch() 能识别的字符串。"""

    @abstractmethod
    def fetch(self, token: str) -> list[dict]:
        """抓取一个 token, 返回一个或多个车型 (series 多车型会展开)。
        每个 dict 形如:
        {
            "model_name": "长安启源Q05 2026款 Air",
            "basic_info": {...},
            "params": [
                {"category": "基本信息", "name": "车型名称", "value": "..."},
                ...
            ],
        }
        """

"""抓取器注册表 + URL dispatch。"""

from __future__ import annotations

from .autohome import AutohomeScraper
from .base import BaseScraper
from .dongchedi import DongchediScraper

_SCRAPERS: list[type[BaseScraper]] = [
    DongchediScraper,
    AutohomeScraper,
]


def get_scraper(url: str) -> BaseScraper:
    for cls in _SCRAPERS:
        if cls.match(url):
            return cls()
    raise ValueError(f"不支持的链接 (目前仅支持懂车帝/汽车之家): {url}")


__all__ = ["BaseScraper", "DongchediScraper", "AutohomeScraper", "get_scraper"]

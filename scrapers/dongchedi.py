"""懂车帝车辆参数抓取器。

URL 支持两种格式:
- 单车型: https://www.dongchedi.com/auto/params-carIds-{specid}
  例: https://www.dongchedi.com/auto/params-carIds-257504
- 车系对比页 (一个车系下的全部车型): https://www.dongchedi.com/auto/params-carIds-x-{seriesid}
  例: https://www.dongchedi.com/auto/params-carIds-x-145  ->  宝马3系全车型

实现方式: 请求参数页 HTML, 从 <script id="__NEXT_DATA__"> 提取 JSON,
再用 props.pageProps.rawData.properties 元数据组装 (类别 → 参数名 → 参数值)。
"""

from __future__ import annotations

import json
import re

import requests

from .base import BaseScraper

_BASE_URL = "https://www.dongchedi.com/auto/params-carIds-{}"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.dongchedi.com/",
}

_RE_NEXT_DATA = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL
)
_RE_SERIES = re.compile(r"carIds-x-(\d+)")
_RE_SPEC = re.compile(r"carIds-(\d+)")


class DongchediScraper(BaseScraper):
    name = "dongchedi"
    host_patterns = ["dongchedi.com"]

    def parse_ids(self, url: str) -> list[str]:
        m = _RE_SERIES.search(url)
        if m:
            return [f"series:{m.group(1)}"]
        m = _RE_SPEC.search(url)
        if m:
            return [f"spec:{m.group(1)}"]
        raise ValueError(f"无法识别懂车帝 URL: {url}")

    def fetch(self, token: str) -> list[dict]:
        kind, _, ident = token.partition(":")
        url_path = f"x-{ident}" if kind == "series" else ident

        html = self._fetch_html(url_path)
        data = self._extract_next_data(html)
        raw = data["props"]["pageProps"]["rawData"]
        properties = raw.get("properties", [])
        car_infos = raw.get("car_info") or []
        if not car_infos:
            raise ValueError(f"页面未返回车型数据 (token={token})")

        return [self._extract_params_for_car(ci, properties) for ci in car_infos]

    @staticmethod
    def _fetch_html(url_path: str) -> str:
        resp = requests.get(_BASE_URL.format(url_path), headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _extract_next_data(html: str) -> dict:
        m = _RE_NEXT_DATA.search(html)
        if not m:
            raise ValueError("未找到 __NEXT_DATA__ 数据, 页面结构可能已变更")
        return json.loads(m.group(1))

    @staticmethod
    def _extract_params_for_car(car_info: dict, properties: list) -> dict:
        series = car_info.get("series_name", "")
        year = car_info.get("car_year", "")
        car_name = car_info.get("car_name", "")
        full_model = (
            f"{series} {year}款 {car_name}" if year else f"{series} {car_name}"
        ).strip()

        basic_info = {
            "车型": full_model,
            "品牌": car_info.get("brand_name", ""),
            "年份": year,
            "官方指导价": car_info.get("official_price", ""),
            "经销商报价": car_info.get("dealer_price", ""),
        }

        info_map: dict = {}
        for key, val in car_info.get("info", {}).items():
            if isinstance(val, dict):
                v = val.get("value", "")
                u = val.get("unit", "")
                icon_type = val.get("icon_type", None)
                if icon_type == 3:
                    info_map[key] = "-"
                elif v != "" and v is not None:
                    info_map[key] = f"{v}{u}" if u else str(v)
                else:
                    info_map[key] = "-"
            elif isinstance(val, list):
                info_map[key] = ", ".join(str(x) for x in val) if val else "-"
            else:
                info_map[key] = str(val) if val not in (None, "") else "-"

        params: list[dict] = [
            {
                "category": "基本信息",
                "name": "车型名称",
                "value": full_model,
                "key": "model_name",
            }
        ]
        current_category = "基本信息"
        for prop in properties:
            if prop.get("type") == 0:
                current_category = prop.get("text", current_category)
                continue
            key = prop.get("key", "")
            name = prop.get("text", "")
            value = info_map.get(key, "-")
            params.append(
                {
                    "category": current_category,
                    "name": name,
                    "value": value,
                    "key": key,
                }
            )

        return {
            "model_name": full_model,
            "basic_info": basic_info,
            "params": params,
        }

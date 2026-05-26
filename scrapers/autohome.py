"""汽车之家参数抓取器。

URL 支持两种格式:
- 单车型: https://www.autohome.com.cn/config/spec/{specid}.html
- 车系页 (含多个车型): https://www.autohome.com.cn/config/series/{seriesid}.html

数据源: car.autohome.com.cn (注意是 car. 不是 www.)
返回的 SSR HTML 中包含 paramtypeitems / configtypeitems JSON, 但部分中文文字
被 <span class='hs_kw{N}_{group}'></span> 占位 (CSS ::before content 替换)。
解密方法: 用 py_mini_racer (V8) 执行页内嵌的混淆解码 JS,
捕获 insertRule 调用拿到 CSS 规则, 解析出 class -> 文字 的映射, 再替换 span。

注意:
- 同一页面有多个 group (configvC/configlr/optionXX 等), 每个 group 独立映射, 互不通用。
- 解码器 JS 调用 `this[...]` 取 window, V8 严格模式下 this=undefined,
  需要把 `this[` 文本替换为 `globalThis[`。
- 一次请求会运行 ~3 个解码块 (param/config/option), 总耗时数秒。
"""

from __future__ import annotations

import json
import re

import requests

from .base import BaseScraper

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_URL_SPEC = "https://car.autohome.com.cn/config/spec/{}.html"
_URL_SERIES = "https://car.autohome.com.cn/config/series/{}.html"

_RE_SCRIPT = re.compile(r"<script[^>]*>([\s\S]*?)</script>")
_RE_RULE = re.compile(
    r'\.hs_kw(\d+)_(\w+)::before\s*\{\s*content:\s*"([^"]*)"'
)
_RE_SPAN = re.compile(
    r"<span\s+class=['\"](hs_kw\d+_\w+)['\"]\s*>\s*</span>"
)
_RE_SPEC_IDS = re.compile(r"var\s+specIDs\s*=\s*\[([\d,\s]+)\]")
_RE_PATH_SPEC = re.compile(r"/spec/(\d+)\.html")
_RE_PATH_SERIES = re.compile(r"/series/(\d+)\.html")

_DECODER_SHIM = """
var __capturedRules = [];
var document = {
  createElement: function(tag) {
    return {
      sheet: {
        insertRule: function(rule, idx) { __capturedRules.push(rule); }
      }
    };
  },
  head: { appendChild: function(){} },
  getElementsByTagName: function() { return [{ appendChild: function(){} }]; },
  querySelectorAll: function() { return []; }
};
var window = globalThis;
"""


class AutohomeScraper(BaseScraper):
    name = "autohome"
    host_patterns = ["autohome.com.cn", "autohome.com"]

    def parse_ids(self, url: str) -> list[str]:
        m = _RE_PATH_SPEC.search(url)
        if m:
            return [f"spec:{m.group(1)}"]
        m = _RE_PATH_SERIES.search(url)
        if m:
            return [f"series:{m.group(1)}"]
        raise ValueError(f"无法识别汽车之家 URL: {url} (支持 /config/spec/{{id}}.html 或 /config/series/{{id}}.html)")

    def fetch(self, token: str) -> list[dict]:
        kind, _, ident = token.partition(":")
        if kind == "spec":
            url = _URL_SPEC.format(ident)
        elif kind == "series":
            url = _URL_SERIES.format(ident)
        else:
            raise ValueError(f"未知 token: {token}")

        html = self._fetch_html(url)
        mappings = self._build_class_mappings(html)
        param_types = self._extract_json_after(html, '"paramtypeitems":')
        config_types = self._extract_json_after(html, '"configtypeitems":')

        if param_types is None:
            raise ValueError("未在页面中找到 paramtypeitems 数据, 页面结构可能已变更")

        # 收集所有 specid（保持页面顺序）
        spec_ids = self._collect_spec_ids(html, param_types)
        if kind == "spec":
            spec_ids = [int(ident)] if int(ident) in spec_ids else spec_ids[:1] or [int(ident)]

        results = []
        for sid in spec_ids:
            params = self._build_params_for_spec(sid, param_types, config_types or [], mappings)
            model_name = self._model_name_for_spec(sid, params)
            results.append({
                "model_name": model_name,
                "basic_info": {"车型": model_name, "specid": sid},
                "params": params,
            })
        return results

    # --- HTTP ---

    @staticmethod
    def _fetch_html(url: str) -> str:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text

    # --- Decoder ---

    @staticmethod
    def _build_class_mappings(html: str) -> dict[str, str]:
        """运行页面内嵌的混淆解码 JS, 得到 hs_kw{N}_{group} -> 中文 的映射。"""
        from py_mini_racer import MiniRacer

        mappings: dict[str, str] = {}
        for body in _RE_SCRIPT.findall(html):
            if "$InsertRuleRun$" not in body or "function $FillDicData$" not in body:
                continue
            patched = body.replace("return this[", "return globalThis[")
            ctx = MiniRacer()
            try:
                ctx.eval(_DECODER_SHIM + "\n" + patched)
                rules = json.loads(ctx.eval("JSON.stringify(__capturedRules)"))
            except Exception:
                continue
            for rule in rules:
                m = _RE_RULE.match(rule)
                if m:
                    mappings[f"hs_kw{m.group(1)}_{m.group(2)}"] = m.group(3)
        return mappings

    @classmethod
    def _decode(cls, s: str, mappings: dict[str, str]) -> str:
        if not isinstance(s, str) or "hs_kw" not in s:
            return s
        return _RE_SPAN.sub(lambda m: mappings.get(m.group(1), ""), s)

    # --- JSON extraction ---

    @staticmethod
    def _extract_json_after(haystack: str, marker: str) -> list | None:
        """在 haystack 中找到 marker 后第一个 [...], 平衡括号取出, JSON parse 返回。"""
        i = haystack.find(marker)
        if i < 0:
            return None
        i = haystack.find("[", i)
        if i < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(haystack)):
            c = haystack[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        raw = haystack[i:j + 1]
                        return json.loads(raw.replace("\\'", "'"))
        return None

    # --- Spec ID collection ---

    @staticmethod
    def _collect_spec_ids(html: str, param_types: list) -> list[int]:
        m = _RE_SPEC_IDS.search(html)
        if m:
            return [int(s) for s in m.group(1).split(",") if s.strip()]
        seen, ordered = set(), []
        for cat in param_types:
            for item in cat.get("paramitems", []):
                for v in item.get("valueitems", []):
                    sid = v.get("specid")
                    if isinstance(sid, int) and sid not in seen:
                        seen.add(sid)
                        ordered.append(sid)
        return ordered

    # --- Per-spec params assembly ---

    @classmethod
    def _build_params_for_spec(
        cls,
        specid: int,
        param_types: list,
        config_types: list,
        mappings: dict[str, str],
    ) -> list[dict]:
        out: list[dict] = []
        for groups, item_key in ((param_types, "paramitems"), (config_types, "configitems")):
            for cat in groups:
                cat_name = cls._decode(cat.get("name", ""), mappings)
                for item in cat.get(item_key, []):
                    name = cls._decode(item.get("name", ""), mappings)
                    value = "-"
                    for v in item.get("valueitems", []):
                        if v.get("specid") == specid:
                            value = cls._decode(str(v.get("value", "")), mappings) or "-"
                            break
                    out.append({
                        "category": cat_name,
                        "name": name,
                        "value": value,
                        "key": str(item.get("id", "")),
                    })
        return out

    @staticmethod
    def _model_name_for_spec(specid: int, params: list[dict]) -> str:
        # 第一行通常是"车型名称"
        for p in params:
            if "车型" in (p.get("name") or ""):
                v = p.get("value") or ""
                if v and v != "-":
                    return v
        return f"specid_{specid}"

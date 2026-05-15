"""
懂车帝车辆参数抓取脚本
用法:
    python dongchedi_scraper.py 254067              # 单个车型ID（默认输出CSV）
    python dongchedi_scraper.py 254067 --json       # 同时输出JSON
    python dongchedi_scraper.py 254067 --no-csv     # 不输出CSV（仅控制台）
"""

import requests
import json
import re
import sys
import csv
import os
from io import StringIO

BASE_URL = "https://www.dongchedi.com/auto/params-carIds-{}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.dongchedi.com/",
}


def fetch_page(car_id: str) -> str:
    url = BASE_URL.format(car_id)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_next_data(html: str) -> dict:
    match = re.search(r'id="__NEXT_DATA__"[^>]*>(.+?)</script>', html)
    if not match:
        raise ValueError("未找到 __NEXT_DATA__ 数据，页面结构可能已变更")
    return json.loads(match.group(1))


def extract_params(data: dict) -> list[dict]:
    """从 __NEXT_DATA__ JSON 中提取所有参数，返回列表"""
    raw = data["props"]["pageProps"]["rawData"]
    properties = raw["properties"]
    car_info = raw["car_info"][0] if raw.get("car_info") else {}

    # 组装完整车型名称: "长安启源Q05 2026款 405 Air"
    series = car_info.get("series_name", "")
    year = car_info.get("car_year", "")
    car_name = car_info.get("car_name", "")
    full_model = f"{series} {year}款 {car_name}" if year else f"{series} {car_name}"

    # 提取基本信息
    basic_info = {
        "车型": full_model,
        "品牌": car_info.get("brand_name", ""),
        "年份": year,
        "官方指导价": car_info.get("official_price", ""),
        "经销商报价": car_info.get("dealer_price", ""),
    }

    # 构建 key -> value 的映射
    info_map = {}
    for key, val in car_info.get("info", {}).items():
        if isinstance(val, dict):
            # 某些值为对象，需要提取 value / unit 字段
            v = val.get("value", "")
            u = val.get("unit", "")
            icon_type = val.get("icon_type", None)
            if icon_type == 3:  # 无数据标记
                info_map[key] = "-"
            elif v:
                info_map[key] = f"{v}{u}" if u else str(v)
            else:
                info_map[key] = list(val.keys())  # 回退：显示所有key
        elif isinstance(val, list):
            info_map[key] = ", ".join(str(x) for x in val)
        else:
            info_map[key] = str(val) if val else "-"

    # 通过 properties 元数据组装最终结果
    results = [{
        "类别": "基本信息",
        "参数名": "车型名称",
        "参数值": full_model,
        "key": "model_name",
    }]
    current_category = ""
    for prop in properties:
        if prop["type"] == 0:
            current_category = prop["text"]
            continue

        key = prop["key"]
        name = prop["text"]
        raw_value = info_map.get(key)

        if raw_value is None:
            value = "-"
        elif isinstance(raw_value, list):
            value = ", ".join(raw_value)
        else:
            value = raw_value

        results.append({
            "类别": current_category,
            "参数名": name,
            "参数值": value,
            "key": key,
        })

    return results, basic_info


def save_csv(results: list[dict], filename: str):
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["类别", "参数名", "参数值"])
        writer.writeheader()
        for r in results:
            writer.writerow({"类别": r["类别"], "参数名": r["参数名"], "参数值": r["参数值"]})
    print(f"CSV 已保存至: {filename}")


def save_json(results: list[dict], basic_info: dict, filename: str):
    output = {
        "basic_info": basic_info,
        "params": {r["类别"]: {} for r in results},
    }
    for r in results:
        output["params"][r["类别"]][r["参数名"]] = r["参数值"]
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"JSON 已保存至: {filename}")


def print_params(results: list[dict], basic_info: dict):
    print(f"\n{'='*60}")
    print(f"车型: {basic_info['车型']}")
    print(f"年份: {basic_info['年份']}")
    print(f"指导价: {basic_info['官方指导价']}")
    print(f"经销商价: {basic_info['经销商报价']}")
    print(f"{'='*60}")

    last_cat = None
    for r in results:
        if r["类别"] != last_cat:
            last_cat = r["类别"]
            print(f"\n  [{r['类别']}]")
        print(f"    {r['参数名']}: {r['参数值']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("示例: python dongchedi_scraper.py 254067")
        sys.exit(1)

    args = sys.argv[1:]
    output_csv = "--no-csv" not in args
    output_json = "--json" in args
    car_ids = [a for a in args if not a.startswith("--")]

    if not car_ids:
        print("错误: 请提供至少一个车型ID")
        sys.exit(1)

    for car_id in car_ids:
        print(f"\n正在抓取车型 ID: {car_id} ...")
        try:
            html = fetch_page(car_id)
            data = extract_next_data(html)
            params, basic_info = extract_params(data)
            print_params(params, basic_info)

            name_slug = basic_info["车型"].replace(" ", "_").replace("/", "-")
            if output_csv:
                save_csv(params, f"dongchedi_{car_id}_{name_slug}.csv")
            if output_json:
                save_json(params, basic_info, f"dongchedi_{car_id}_{name_slug}.json")
        except Exception as e:
            print(f"  抓取失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

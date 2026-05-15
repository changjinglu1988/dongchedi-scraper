import re
import io
from flask import Flask, render_template, request, send_file
from openpyxl import Workbook

from dongchedi_scraper import fetch_page, extract_next_data, extract_params

app = Flask(__name__)


def parse_car_id(url: str) -> str:
    """从懂车帝URL中提取车型ID"""
    m = re.search(r"carIds-(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{5,})", url)
    if m:
        return m.group(1)
    raise ValueError(f"无法识别URL中的车型ID：{url}")


def scrape_one(url: str) -> tuple[str, list[dict]]:
    """抓取单个车型，返回 (车型名称, 参数列表)"""
    car_id = parse_car_id(url)
    html = fetch_page(car_id)
    data = extract_next_data(html)
    params, basic_info = extract_params(data)
    return basic_info["车型"], params


def sanitize_sheet_name(name: str) -> str:
    """清理工作表名称，Excel 工作表名最长31字符，不能包含特殊字符"""
    name = re.sub(r'[\\/*?:\[\]]', '', name)
    return name[:31]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def scrape():
    text = request.form.get("urls", "").strip()
    if not text:
        return "请输入至少一个懂车帝车型参数页链接", 400

    urls = [u.strip() for u in text.splitlines() if u.strip()]
    if not urls:
        return "未识别到有效链接", 400

    wb = Workbook()
    # 删除默认空工作表
    wb.remove(wb.active)
    failed = []

    for url in urls:
        try:
            model_name, params = scrape_one(url)
        except Exception as e:
            failed.append(f"{url} -> {e}")
            continue

        sheet_name = sanitize_sheet_name(model_name)
        ws = wb.create_sheet(title=sheet_name)

        # 写入表头
        ws.append(["类别", "参数名", "参数值"])
        for r in params:
            ws.append([r["类别"], r["参数名"], r["参数值"]])

        # 调整列宽
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 32
        ws.column_dimensions["C"].width = 30

    if not wb.sheetnames:
        return f"所有链接抓取失败：\n" + "\n".join(failed), 500

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    result_name = f"dongchedi_{len(wb.sheetnames)}cars.xlsx"
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=result_name,
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

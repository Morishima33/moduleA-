"""第四版矩阵下载同步中英文标签，Excel/CSV保留原始精度及原≤−8标记。"""

import csv
from pathlib import Path

from .matrix_exports import validate_matrix
from .trial_presentation import score_label, highlighted, LEGEND


def export_workbook(view, directory):
    """依同一矩阵输出原值与显示值两页，不计算或更换对接评分。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    validate_matrix(view)
    folder = Path(directory)
    table = view["table"]
    headers = ["成分中文", "Compound (English)"] + [r["symbol"] for r in table["columns"]]
    rows = [
        [r["name_zh"], r.get("name_en", "")]
        + [c["score"] if c["score"] is not None else "NA" for c in line]
        for r, line in zip(table["rows"], table["cells"])
    ]
    workbook = Workbook()
    raw = workbook.active
    raw.title = "原始评分"
    display = workbook.create_sheet("中英矩阵")
    for sheet in (raw, display):
        sheet.append(headers)
        sheet.freeze_panes = "C2"
        sheet.column_dimensions["A"].width = 19
        sheet.column_dimensions["B"].width = 46
        for j in range(3, len(headers) + 1):
            sheet.column_dimensions[get_column_letter(j)].width = 11
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="0F5E6E")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, (row, line) in enumerate(zip(rows, table["cells"]), 2):
        raw.append(row)
        display.append(row[:2] + [score_label(c["score"], mark=True) for c in line])
        for sheet in (raw, display):
            for cell in sheet[i]:
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            for j, item in enumerate(line, 3):
                sheet.cell(i, j).fill = PatternFill("solid", fgColor=item["color"].lstrip("#"))
                sheet.cell(i, j).font = Font(color=item["text_color"].lstrip("#"))
    raw.append(["单位", "kcal/mol；保留Vina原始精度"])
    display.append(["标记说明", LEGEND])
    path = folder / "A06_02_中英15×15结合能矩阵.xlsx"
    workbook.save(path)
    csv_path = folder / "A06_02_中英15×15结合能矩阵.csv"
    with csv_path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    return {"xlsx": path, "csv": csv_path}

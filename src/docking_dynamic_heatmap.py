# A06动态结合能热图；受体为行、成分为列，不在图内显示质量等级。
import hashlib  # 为来源结果和图件生成可追溯指纹。
import json  # 保存图件元数据。
import math  # 只允许有限的真实结合能进入色标。
from pathlib import Path  # 使用明确的研究包路径。
import textwrap  # 将较长成分名称分行，避免列标题重叠。

from contracts import require  # 复用项目统一阻断规则。
from docking_contract import validate_generic_result  # 图件只能读取已通过契约检查的A06事实。
from docking_formal import _heat_color  # SVG和PNG继续使用项目唯一红蓝颜色函数。
from storage import now, read_json, write_json  # 使用统一时间和不可覆盖写入。


SCHEMA_VERSION = "A06.dynamic_heatmap.1"  # 首个支持任意矩阵及NA的热图元数据版本。
NA_COLOR = "#D9DDE1"  # 失败或未运行组合使用中性灰色，不进入色标范围。


def _sha256(path):  # 计算完整文件指纹。
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()  # 使用原始字节确保跨电脑一致。


def _rgb(value, minimum, maximum):  # 将生产颜色字符串转换为Pillow颜色。
    text = _heat_color(value, minimum, maximum)  # 调用统一连续色带。
    return tuple(int(part) for part in text[4:-1].split(","))  # 解析rgb三通道。


def _font(image_font, size, bold=False):  # 固定中文字体并在缺失时明确停止。
    path = Path("C:/Windows/Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc")  # Windows项目使用微软雅黑。
    require(path.is_file(), "未找到微软雅黑字体，不能生成中文热图")  # 不输出乱码图。
    return image_font.truetype(str(path), size=size)  # 返回实际字体对象。


def _matrix(generic):  # 将组合明细转为受体行、成分列的动态矩阵。
    compounds = generic["compounds"]  # 成分顺序来自已批准A03_SELECT。
    receptors = generic["receptors"]  # 受体顺序来自PPI筛查窗口。
    scores = {(row["compound_id"], row["target"]): float(row["score_kcal_mol"]) for row in generic["completed_pairs"]}  # 只索引真实完成项。
    rows = []  # 每行对应一个受体。
    for receptor in receptors:  # 保持PPI顺序，不按结合能重新排序。
        rows.append({"target": receptor["target"], "values": [scores.get((compound["compound_id"], receptor["target"])) for compound in compounds]})  # 失败项保持None。
    return compounds, receptors, rows  # 返回绘图和元数据共同使用的结构。



def _display_matrix(generic):  # 只删除全无评分的行列，不影响其他成功组合。
    used_compounds = {row['compound_id'] for row in generic['completed_pairs']}  # 找出至少有一组成功的成分。
    used_targets = {row['target'] for row in generic['completed_pairs']}  # 找出至少有一组成功的受体。
    display = dict(generic, compounds=[row for row in generic['compounds'] if row['compound_id'] in used_compounds], receptors=[row for row in generic['receptors'] if row['target'] in used_targets])  # 保持原有顺序。
    return _matrix(display)  # 单对失败仍为None，不删除整行或列。


def _write_png(path, generic):  # 绘制高清PNG并返回色标范围。
    dependency = Path(__file__).resolve().parents[1] / "environments" / "docking_packages"  # 使用项目固定Pillow环境。
    import sys  # 仅为隔离依赖添加项目路径。
    if str(dependency) not in sys.path:  # 避免重复加入。
        sys.path.insert(0, str(dependency))  # 不依赖用户全局环境。
    from PIL import Image, ImageDraw, ImageFont  # 在固定路径生效后加载绘图工具。
    compounds, receptors, rows = _display_matrix(generic)  # 建立动态矩阵。
    finite = [value for row in rows for value in row["values"] if value is not None and math.isfinite(value)]  # NA不进入颜色范围。
    require(finite, "没有可绘制的真实结合能")  # 全部失败时不生成假热图。
    minimum, maximum = min(finite), max(finite)  # 色标只描述本次观察范围。
    midpoint = (minimum + maximum) / 2  # 中点不是阈值或零值。
    cell_w, cell_h = 230, 108  # 七列与十行保持报告可读。
    label_w, top_h, bar_w = 330, 300, 210  # 为受体、长成分名和色标留出空间。
    width = label_w + cell_w * len(compounds) + bar_w  # 根据成分数动态计算画布宽度。
    height = top_h + cell_h * len(receptors) + 150  # 根据受体数动态计算画布高度。
    canvas = Image.new("RGB", (width, height), "white")  # 白底适合Word和打印。
    draw = ImageDraw.Draw(canvas)  # 创建绘图接口。
    draw.text((55, 35), f"分子对接结合能热图（{len(receptors)}个受体×{len(compounds)}个成分）", fill="#18354A", font=_font(ImageFont, 48, True))  # 图题只说明对象数。
    draw.text((55, 103), "Vina affinity（kcal/mol）；红色越深表示数值越负，NA表示未形成有效评分，不参与色标", fill="#526B7A", font=_font(ImageFont, 25))  # 明确颜色和NA。
    label_font = _font(ImageFont, 25)  # 受体和成分使用相同层级。
    value_font = _font(ImageFont, 24, True)  # 格内数值加粗便于复核。
    for column, compound in enumerate(compounds):  # 绘制成分列标题。
        name = str(compound.get("name") or compound["compound_id"])  # 缺名称时仍有稳定编号。
        label = "\n".join(textwrap.wrap(name, width=18, break_long_words=True, break_on_hyphens=False)[:3] + [compound["compound_id"]])  # 长名称最多三行并追加稳定编号。
        x = label_w + column * cell_w + cell_w / 2  # 计算列中心。
        for line_index, line in enumerate(label.split("\n")):  # 两行避免标题过长。
            box = draw.textbbox((0, 0), line, font=label_font)  # 计算文字宽度。
            draw.text((x - (box[2] - box[0]) / 2, 172 + line_index * 34), line, fill="#203342", font=label_font)  # 居中写入。
    for row_index, row in enumerate(rows):  # 逐个受体绘制一行。
        y = top_h + row_index * cell_h  # 计算行起点。
        draw.text((55, y + 36), row["target"], fill="#203342", font=label_font)  # 不显示A/B/C或符号等级。
        for column_index, value in enumerate(row["values"]):  # 绘制真实评分或NA。
            x = label_w + column_index * cell_w  # 计算格子左边界。
            if value is None:  # 单对缺失显示NA但不填灰色。
                box = draw.textbbox((0, 0), 'NA', font=value_font)  # 使用与数值相同的字体。
                draw.text((x + (cell_w - (box[2] - box[0])) / 2, y + 38), 'NA', fill='#203342', font=value_font)  # 白底居中提示缺失。
                continue  # 不为缺失格生成评分色块。
            else:  # 完成组合使用连续红蓝颜色。
                fill = _rgb(value, minimum, maximum)  # 颜色与数值单调对应。
                label = f"{value:.3f}"  # 保留三位小数。
                ratio = 0.5 if maximum == minimum else (value - minimum) / (maximum - minimum)  # 仅用于文字对比度。
                text_color = "#203342" if abs(ratio - 0.5) < 0.28 else "white"  # 深色格使用白字。
            draw.rectangle((x, y, x + cell_w, y + cell_h), fill=fill, outline="white", width=3)  # 白线分隔矩阵。
            box = draw.textbbox((0, 0), label, font=value_font)  # 计算数值尺寸。
            draw.text((x + (cell_w - (box[2] - box[0])) / 2, y + 38), label, fill=text_color, font=value_font)  # 居中写入。
    bar_x = label_w + cell_w * len(compounds) + 58  # 色标放在矩阵右侧。
    bar_y, bar_h = top_h, cell_h * len(receptors)  # 色标覆盖矩阵全高。
    for pixel in range(bar_h):  # 逐像素生成平滑色带。
        ratio = pixel / max(1, bar_h - 1)  # 顶部较不负、底部更负。
        value = maximum - ratio * (maximum - minimum)  # 映射回真实值。
        draw.line((bar_x, bar_y + pixel, bar_x + 42, bar_y + pixel), fill=_rgb(value, minimum, maximum), width=1)  # 使用统一颜色函数。
    note_font = _font(ImageFont, 22)  # 色标和页脚使用较小字号。
    draw.text((bar_x - 6, bar_y - 38), "结合能", fill="#203342", font=note_font)  # 标注色标含义。
    draw.text((bar_x + 52, bar_y - 8), f"{maximum:.3f}", fill="#203342", font=note_font)  # 顶部较不负值。
    draw.text((bar_x + 52, bar_y + bar_h / 2 - 12), f"{midpoint:.3f}", fill="#203342", font=note_font)  # 中间观察值。
    draw.text((bar_x + 52, bar_y + bar_h - 23), f"{minimum:.3f}", fill="#203342", font=note_font)  # 底部最负值。
    draw.text((55, height - 92), "颜色只表示本批原始Vina评分的相对位置，不代表统一有效阈值或体内疗效。", fill="#526B7A", font=note_font)  # 保留科学边界。
    canvas.save(path, format="PNG", dpi=(300, 300), optimize=True)  # 输出高清位图。
    return minimum, midpoint, maximum  # 元数据保存同一范围。


def _write_svg(path, generic, minimum, maximum):  # 绘制可编辑SVG并保持同一矩阵方向。
    from html import escape  # 防止名称破坏XML。
    compounds, receptors, rows = _display_matrix(generic)  # 读取相同数据。
    cell_w, cell_h, label_w, top_h, bar_w = 210, 72, 260, 240, 170  # SVG为长名称增加列宽和顶部空间。
    width = label_w + cell_w * len(compounds) + bar_w  # 动态宽度。
    height = top_h + cell_h * len(receptors) + 100  # 动态高度。
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>']  # 建立白底SVG。
    lines.append(f'<text x="30" y="42" font-family="Microsoft YaHei" font-size="30" font-weight="700" fill="#18354A">分子对接结合能热图（{len(receptors)}个受体×{len(compounds)}个成分）</text>')  # 写入图题。
    lines.append('<text x="30" y="78" font-family="Microsoft YaHei" font-size="16" fill="#526B7A">红色越深表示数值越负；NA表示未形成有效评分，不参与色标</text>')  # 写入颜色说明。
    for column, compound in enumerate(compounds):  # 绘制列标题。
        x = label_w + column * cell_w + cell_w / 2  # 计算列中心。
        name_lines = textwrap.wrap(str(compound.get("name") or compound["compound_id"]), width=18, break_long_words=True, break_on_hyphens=False)[:3]  # 长名称使用可编辑多行文字。
        for line_index, label in enumerate(name_lines):  # 每行保持同一水平层级。
            lines.append(f'<text x="{x}" y="{140 + line_index * 22}" text-anchor="middle" font-family="Microsoft YaHei" font-size="15">{escape(label)}</text>')  # 显示成分名分行。
        lines.append(f'<text x="{x}" y="{140 + len(name_lines) * 22}" text-anchor="middle" font-family="Arial" font-size="13">{escape(compound["compound_id"])}</text>')  # 显示稳定编号。
    for row_index, row in enumerate(rows):  # 绘制受体行与评分格。
        y = top_h + row_index * cell_h  # 行起点。
        lines.append(f'<text x="30" y="{y + 44}" font-family="Arial" font-size="17">{escape(row["target"])}</text>')  # 不显示质量分级。
        for column_index, value in enumerate(row["values"]):  # 逐格写入。
            x = label_w + column_index * cell_w  # 格子左边界。
            if value is None:  # 仅白底显示NA，不画灰色方格。
                lines.append(f'<text x="{x + cell_w / 2}" y="{y + 44}" text-anchor="middle" font-family="Arial" font-size="17" font-weight="700" fill="#203342">NA</text>')  # 与PNG相同位置和语义。
                continue  # 缺失不参与颜色范围。
            fill = _heat_color(value, minimum, maximum)  # 只为真实评分着色。
            label = f"{value:.3f}"  # 显示真实原始评分。
            ratio = 0.5 if value is None or maximum == minimum else (value - minimum) / (maximum - minimum)  # 选择对比文字色。
            color = "#203342" if value is None or abs(ratio - 0.5) < 0.28 else "white"  # 提高可读性。
            lines.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="white" stroke-width="2"/>')  # 绘制色块。
            lines.append(f'<text x="{x + cell_w / 2}" y="{y + 44}" text-anchor="middle" font-family="Arial" font-size="17" font-weight="700" fill="{color}">{label}</text>')  # 绘制数值。
    bar_x = label_w + cell_w * len(compounds) + 28  # 色标放在矩阵右侧。
    bar_height = cell_h * len(receptors)  # 色标高度与矩阵一致。
    for index in range(240):  # 细分色块使SVG渐变平滑并与PNG同源。
        ratio = index / 239  # 顶部为较不负值，底部为最负值。
        value = maximum + ratio * (minimum - maximum)  # 同一数值映射。
        fill = _heat_color(value, minimum, maximum)  # 不使用不同SVG配色算法。
        lines.append(f'<rect x="{bar_x}" y="{top_h + index * bar_height / 240}" width="24" height="{bar_height / 240 + 0.2}" fill="{fill}"/>')  # 保存可编辑色标。
    for ratio, value in ((0, maximum), (0.5, (minimum + maximum) / 2), (1, minimum)):  # 三个观察刻度。
        lines.append(f'<text x="{bar_x + 32}" y="{top_h + ratio * bar_height + 5}" font-family="Arial" font-size="13">{value:.3f}</text>')  # 数值不表示阈值。
    lines.append(f'<text x="{bar_x}" y="{top_h - 20}" font-family="Arial" font-size="13">kcal/mol</text>')  # 标明真实评分单位。
    lines.append(f'<text x="30" y="{height - 30}" font-family="Microsoft YaHei" font-size="14" fill="#526B7A">颜色仅描述本批Vina评分的相对位置，不代表统一阈值或体内疗效。</text>')  # 科学边界。
    lines.append('</svg>')  # 结束文档。
    with path.open("x", encoding="utf-8", newline="\n") as stream:  # 禁止覆盖历史图件。
        stream.write("\n".join(lines))  # 一次写入完整SVG。


def export(result_path, output_dir, stem):  # 从A06通用事实生成两种图件和元数据。
    result_path = Path(result_path).resolve()  # 固定来源文件。
    output_dir = Path(output_dir).resolve()  # 固定输出目录。
    result = read_json(result_path)  # 读取标准A06结果或直接通用事实。
    generic = result.get("tables", {}).get("generic_docking", result)  # 同时支持工作流结果和独立事实包。
    validate_generic_result(generic)  # 图件生成前复核全部组合。
    require(generic["outcome"] in {"success", "partial"}, "有效空A06不生成热图")  # 空结果不画空矩阵。
    svg_path, png_path, metadata_path = (output_dir / f"{stem}.{suffix}" for suffix in ("svg", "png", "json"))  # 三个文件使用同一版本名。
    require(not any(path.exists() for path in (svg_path, png_path, metadata_path)), "禁止覆盖历史热图版本")  # 保留旧图可追溯。
    output_dir.mkdir(parents=True, exist_ok=True)  # 创建当前版本目录。
    from docking_grouped_heatmap import omission_text  # 图下说明仍完整保留失败组合。
    minimum, midpoint, maximum = _write_png(png_path, generic)  # 恢复原矩阵样式，单对缺失留空。
    _write_svg(svg_path, generic, minimum, maximum)  # 同一行列投影和数值范围。
    compounds, receptors, rows = _matrix(generic)  # 保存实际维度和NA数量。
    metadata = {"schema_version": SCHEMA_VERSION, "created_at": now(), "source_result": {"path": result_path.as_posix(), "bytes": result_path.stat().st_size, "sha256": _sha256(result_path)}, "orientation": "receptors_as_rows_compounds_as_columns", "receptor_order": [row["target"] for row in receptors], "compound_order": [row["compound_id"] for row in compounds], "dimensions": {"receptors": len(receptors), "compounds": len(compounds), "planned_pairs": len(receptors) * len(compounds), "na_cells": sum(value is None for row in rows for value in row["values"])}, "palette": {"minimum_more_negative": "#B2182B", "midpoint_light_red": "#EFA9AE", "transition_light_blue": "#A4C7E0", "maximum_less_negative": "#2166AC", "missing": NA_COLOR}, "range_kcal_mol": {"minimum": minimum, "midpoint": midpoint, "maximum": maximum}, "quality_labels_in_heatmap": False, "scientific_boundary": "raw_vina_scores_relative_visualization_only; NA_excluded_from_color_range; no_universal_threshold", "files": [{"path": svg_path.name, "bytes": svg_path.stat().st_size, "sha256": _sha256(svg_path), "role": "heatmap_svg"}, {"path": png_path.name, "bytes": png_path.stat().st_size, "sha256": _sha256(png_path), "role": "heatmap_png"}]}  # 元数据固定全部显示规则。
    shown_compounds, shown_receptors, shown_rows = _display_matrix(generic)  # 原始维度与显示维度分别留存。
    metadata.update(display_kind='aligned_matrix_without_all_missing_axes', displayed_receptor_order=[row['target'] for row in shown_receptors], displayed_compound_order=[row['compound_id'] for row in shown_compounds], display_dimensions={'receptors': len(shown_receptors), 'compounds': len(shown_compounds)}, displayed_pairs=[{'target': row['target'], 'compound_id': row['compound_id'], 'score_kcal_mol': row['score_kcal_mol']} for row in generic['completed_pairs']], omitted_pairs=generic.get('failed_pairs', []), omission_explanation=omission_text(generic), displayed_missing_cells=sum(value is None for row in shown_rows for value in row['values']))  # 保留可核对的一格空白及23组原始失败记录。
    metadata['palette']['missing'] = None  # NA格没有灰色填充。
    metadata['missing_display'] = 'NA_text_on_white_background'  # 用户确认的单个缺失格表示方法。
    write_json(metadata_path, metadata)  # 不可覆盖保存。
    return metadata  # 供网页和报告绑定。


if __name__ == "__main__":  # 提供可重复命令行入口。
    import argparse  # 解析明确路径。
    parser = argparse.ArgumentParser(description="生成受体为行、成分为列的动态A06热图")  # 说明用途。
    parser.add_argument("--result", required=True)  # A06结果路径。
    parser.add_argument("--output-dir", required=True)  # 图件输出目录。
    parser.add_argument("--stem", required=True)  # 版本化文件名。
    arguments = parser.parse_args()  # 读取调用参数。
    print(json.dumps(export(arguments.result, arguments.output_dir, arguments.stem), ensure_ascii=False, indent=2))  # 输出小型索引。

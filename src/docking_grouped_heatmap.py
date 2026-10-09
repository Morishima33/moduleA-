# 有效组合分组热图：只画成功组合，失败记录转入图下文字，不生成空格。
from pathlib import Path  # 定位图件和项目字体。
from html import escape  # 保持SVG文字安全。
import textwrap  # 折行成分名称和图下注释。
from docking_formal import _heat_color  # 沿用用户确认的平滑红蓝色带。
from contracts import require  # 防止不存在有效组合时画假图。


def current_display(workflow, result):  # 网页只采用绑定当前A06的数据展示修订。
    from storage import read_json, verified_file  # 统一归属和指纹核验。
    study = workflow.location(result['study_id'])  # 当前独立研究。
    pointer = study / 'governance' / 'A06_figure_index.json'  # 唯一图件展示指针。
    if not pointer.is_file():  # 历史研究使用原绑定图件。
        return None  # 不扫描文件名猜图。
    index = read_json(pointer)  # 显式展示版本。
    if index['source_a06_run'] != result['run_id']:  # 科学结果已变动时旧展示失效。
        return None  # 新A06使用自身图件。
    require(index['schema_version'] == 'A06.figure.index.1' and index['study_id'] == result['study_id'], '图件展示归属不一致')  # 不跨研究显示。
    source_hashes = {record['sha256'] for record in result['files'] + result.get('sources', []) if record['role'] == 'generic_docking_candidate'}  # A06唯一事实来源。
    metadata_path = verified_file(study, index['metadata'])  # 新图元数据不可被静默篡改。
    metadata = read_json(metadata_path)  # 同源生成规则。
    require(metadata['source_result']['sha256'] in source_hashes, '图件修订不是当前A06数据')  # 拒绝同维度不同结果。
    record = next(row for row in metadata['files'] if row['role'] == 'heatmap_png')  # 不猜图片名称。
    return metadata, verified_file(metadata_path.parent, record)  # 返回已核验的图片与说明。


def groups(generic):  # 按PPI受体顺序及原成分顺序排列真实有效组合。
    scores = {(row['target'], row['compound_id']): row for row in generic['completed_pairs']}  # 只索引成功结果。
    result = []  # 返回变长分组而不是带缺口矩阵。
    for receptor in generic['receptors']:  # 原PPI顺序不变。
        pairs = [dict(scores[(receptor['target'], compound['compound_id'])], name=compound.get('name') or compound['compound_id']) for compound in generic['compounds'] if (receptor['target'], compound['compound_id']) in scores]  # 每个色块保留明确身份。
        if pairs:  # 全部失败的受体不占图面一行。
            result.append({'target': receptor['target'], 'pairs': pairs})  # 不产生空值。
    return result  # 未展示组合另有全量原始记录。


def omission_text(generic):  # 将每一个未展示组合明确写入一段可复核文字。
    failed = generic.get('failed_pairs', [])  # 读取原始失败事实，不新增失败。
    if not failed:  # 完整结果不制造排除说明。
        return ''  # 没有未展示项。
    grouped = {}  # 同一原因合并说明，组合不丢失。
    for row in failed:  # 每个失败组合只出现一次。
        reason = str(row.get('reason') or '原始记录未提供具体原因，需查阅运行日志')  # 不猜失败原因。
        reason = reason.replace('相关组合为NA。', '未形成有效评分。')  # 使用中文说明替代图内代码。
        grouped.setdefault(reason, []).append(row['target'] + '—' + row['compound_id'])  # 精确保留成分编号。
    sections = ['、'.join(pairs) + '：' + reason.rstrip('。') for reason, pairs in grouped.items()]  # 一段文字明确每组及其原因。
    return f"本图仅展示{len(generic['completed_pairs'])}组有效评分；原计划{len(generic['planned_pairs'])}组，以下{len(failed)}组未展示：" + '；'.join(sections) + '。未展示不等于无结合或无效，原始资料和失败日志完整保留。'  # 避免视觉排除被解释为生物学排除。


def draw(png_path, svg_path, generic, font_loader):  # 同时生成高清位图和可编辑SVG。
    import sys  # 加载项目固定Pillow环境。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'environments' / 'docking_packages'))  # 不下载绘图依赖。
    from PIL import Image, ImageDraw, ImageFont  # 使用已有固定库。
    rows = groups(generic)  # 无空格分组。
    require(rows, '没有可绘制的有效对接组合')  # 全失败不画空图。
    values = [float(pair['score_kcal_mol']) for row in rows for pair in row['pairs']]  # 仅真实评分进入色标。
    low, high = min(values), max(values)  # 不新增评分阈值。
    count = max(len(row['pairs']) for row in rows)  # 行宽由实际最大成功数决定。
    tile_w, tile_h, gap, left, top = 300, 154, 10, 250, 170  # 每格写身份和数值，不使用共同列标题。
    width = left + count * (tile_w + gap) + 60  # 动态画布宽度。
    row_step = tile_h + 20  # 分组留有细小间距。
    body_end = top + len(rows) * row_step  # 矩阵后放色标和说明。
    note = omission_text(generic)  # 失败事实放在图下。
    font = font_loader(ImageFont, 23)  # 固定中文可读字体。
    large = font_loader(ImageFont, 36, True)  # 评分为主要阅读对象。
    small = font_loader(ImageFont, 20)  # 稳定成分编号。
    def wrap_measured(text, available):  # 按实际字体宽度折行，不截断说明。
        lines, line = [], ''  # 支持中文和英文混排。
        for character in text:  # 每一个字都保留。
            candidate = line + character  # 尝试当前行。
            if line and font.getlength(candidate) > available:  # 防止长英文原因横向溢出。
                lines.append(line)  # 完成上一行。
                line = character  # 开始下一行。
            else:  # 当前行仍能容纳。
                line = candidate  # 继续拼接。
        if line:  # 收尾。
            lines.append(line)  # 不丢尾部文字。
        return lines  # PNG/SVG使用相同折行。
    notes = wrap_measured(note, width - 100) if note else []  # 图下完整一段说明。
    height = body_end + 175 + len(notes) * 33  # 文字多少决定高度，不裁切。
    canvas = Image.new('RGB', (width, height), 'white')  # 学术白底。
    painter = ImageDraw.Draw(canvas)  # 位图绘制接口。
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>']  # 可编辑矢量图。
    def text(x, y, label, face=font, color='#203342', size=23, bold=False):  # 两图同位置同文字。
        painter.text((x, y), label, fill=color, font=face)  # 固定实际字体。
        svg.append(f'<text x="{x}" y="{y + size}" font-family="Microsoft YaHei" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(label)}</text>')  # 保持文字可编辑。
    text(40, 24, f"有效分子对接组合热图（{len(values)}组）", font_loader(ImageFont, 44, True), size=44, bold=True)  # 不称为完整10×7矩阵。
    text(40, 89, '按受体分组；每个色块单独标明成分。数值越负颜色越红，未得到有效评分的组合不绘制。')  # 说明压缩排列的语义。
    for row_index, row in enumerate(rows):  # 按PPI顺序绘制分组。
        y = top + row_index * row_step  # 当前受体行。
        text(40, y + 36, row['target'], font_loader(ImageFont, 29, True), size=29, bold=True)  # 受体标签。
        text(40, y + 83, str(len(row['pairs'])) + '组有效结果', small, size=20)  # 防止误认为每行组合数相同。
        for column, pair in enumerate(row['pairs']):  # 只画真实存在的色块。
            x = left + column * (tile_w + gap)  # 有效组合紧邻排列。
            score = float(pair['score_kcal_mol'])  # 原分数不改变。
            color = _heat_color(score, low, high)  # 沿用平滑红蓝渐变。
            rgb = tuple(int(item) for item in color[4:-1].split(','))  # Pillow使用实际三通道。
            painter.rectangle((x, y, x + tile_w, y + tile_h), fill=rgb)  # 没有灰色或空值方格。
            svg.append(f'<rect data-target="{escape(row["target"])}" data-compound="{escape(pair["compound_id"])}" x="{x}" y="{y}" width="{tile_w}" height="{tile_h}" fill="{color}"/>')  # 色块身份可机器核查。
            ratio = 0.5 if high == low else (score - low) / (high - low)  # 只用于字体对比度。
            ink = '#203342' if abs(ratio - 0.5) < 0.28 else 'white'  # 深色格用白字。
            name_lines = textwrap.wrap(pair['name'], width=21, break_on_hyphens=False)  # 完整名称折行。
            label = name_lines[:2]  # 图中简称，完整名称在数据与编号映射中保留。
            for index, line in enumerate(label):  # 两行成分名称。
                text(x + 14, y + 10 + index * 26, line, small, ink, 20)  # 标明各色块自己的成分。
            text(x + 14, y + 65, pair['compound_id'], small, ink, 20)  # 稳定身份编号。
            text(x + 14, y + 96, f'{score:.3f}', large, ink, 36, True)  # 三位小数原始Vina分数。
    bar_x, bar_y, bar_w = left, body_end + 12, count * (tile_w + gap) - gap  # 水平色标避免末行视觉空格。
    for pixel in range(bar_w):  # 平滑渐变不使用白色中点。
        value = low + (high - low) * pixel / max(1, bar_w - 1)  # 左红右蓝。
        color = _heat_color(value, low, high)  # 与格子使用同一映射。
        rgb = tuple(int(item) for item in color[4:-1].split(','))  # 同一色彩空间。
        painter.line((bar_x + pixel, bar_y, bar_x + pixel, bar_y + 24), fill=rgb)  # 位图逐像素色标。
        svg.append(f'<rect x="{bar_x + pixel}" y="{bar_y}" width="1" height="24" fill="{color}"/>')  # 矢量色标同源。
    text(40, bar_y, 'kcal/mol', small, size=20)  # 明确单位。
    text(bar_x, bar_y + 32, f'{low:.3f}', small, size=20)  # 最负值。
    text(bar_x + bar_w / 2 - 40, bar_y + 32, f'{(low + high) / 2:.3f}', small, size=20)  # 观察范围中点。
    text(bar_x + bar_w - 80, bar_y + 32, f'{high:.3f}', small, size=20)  # 较不负值。
    text(40, body_end + 88, '颜色仅表示本批Vina评分的相对位置，不等同于治疗效果或实验验证。', small, '#526B7A', 20)  # 科学边界。
    for index, line in enumerate(notes):  # 失败原因出现在图下而非占据灰格。
        text(40, body_end + 135 + index * 33, line)  # 保留完整叙述。
    svg.append('</svg>')  # 结束矢量文档。
    canvas.save(png_path, format='PNG', dpi=(300, 300), optimize=True)  # 高清报告用图片。
    with Path(svg_path).open('x', encoding='utf-8') as stream:  # 不覆盖旧图。
        stream.write('\n'.join(svg))  # 一次写入。
    return low, (low + high) / 2, high  # 元数据保存相同范围。

# 三库成分候选扩展；复用原TCMSP计算，不修改现有运行。
import csv  # 读取明确字段的原始表。
import gzip  # 读取BATMAN官方压缩关系表。
import json  # 读取已有官方化学结构快照。
import hashlib  # 为稳定化学身份生成编号。
import io  # 解析固定原始字节。
import re  # 校验结构键与来源编号。
from collections import defaultdict  # 保留多个来源及药味关系。
from pathlib import Path  # 定位项目内归档资料。
import openpyxl  # 只读读取HERB导出表。
from components import select_rows, analyze  # 复用已验收TCMSP规则。
from contracts import require  # 沿用现有可读错误。

VERSION = "A01.multisource.import.2"  # 参数化导入版本；不改旧版。
KEY_PATTERN = re.compile(r"[A-Z]{14}-[A-Z]{10}-[A-Z]")  # 仅接受完整InChIKey。

def text(value):  # 清理缺失标记而不改变科学含义。
    value = str(value or "").strip()  # 去除外部空白。
    return "" if value in ("NA", "N/A", "None", "nan") else value  # 缺失不补零。

def catalog(path):  # 读取全量HERB化学身份表。
    with Path(path).open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))  # 保留原字段。
    require(rows and {"Ingredient_id", "InChIKey", "TCMSP_id", "PubChem_id"} <= rows[0].keys(), "HERB身份表缺少必要字段")  # 不猜列名。
    index = {r["Ingredient_id"]: r for r in rows}  # 使用明确HERB编号。
    require(len(index) == len(rows), "HERB成分编号重复")  # 重复身份需要核查。
    return index  # 返回固定身份索引。

def make_record(source, source_id, name, herb, source_ref, identity=None):  # 三库使用同一来源记录结构。
    identity = identity or {}  # 没有结构时保留独立待核记录。
    key = text(identity.get("InChIKey"))  # 不以名称生成结构键。
    require(not key or KEY_PATTERN.fullmatch(key), "InChIKey格式不合格：" + source_id)  # 损坏结构键不能合并。
    return {"source": source, "source_id": source_id, "name": text(name), "herb": herb, "source_ref": source_ref, "inchikey": key, "formula": text(identity.get("Molecular_formula")), "identity_basis": "HERB完整结构键" if key else "来源编号保留；结构待核"}  # 原始来源不被主编号替代。

def herb_records(raw, identities, herb_files):  # 读取当前研究已确认药味导出。
    records = []  # 保留每条药味与成分关系。
    for herb, name in herb_files.items():  # 不从文件名猜药味归属。
        path = (raw / name).resolve()
        require(path.is_relative_to(raw.resolve()), "HERB导出路径超出来源目录")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)  # 不改动原工作簿。
        try:  # 任何异常都关闭工作簿。
            require(len(book.worksheets) == 1, "HERB导出工作表不唯一")  # 不任取工作表。
            values = list(book.worksheets[0].values)  # 保留原始行号。
            require(values and values[0][0:2] == ("Ingredient id", "Ingredient name"), "HERB导出表头不匹配")  # 拒绝错列。
            for line, row in enumerate(values[1:], 2):  # 表头计入来源行号。
                require(row[0] in identities, "HERB编号未对应全量表")  # 不仅按名称匹配。
                identity = identities[row[0]]  # 使用明确对应记录。
                require(text(row[1]).lower() == text(identity["Ingredient_name"]).lower(), "HERB成分名称冲突")  # 冲突不能静默合并。
                records.append(make_record("HERB", row[0], row[1], herb, name + ":" + str(line), identity))  # 保留全部药味关系。
        finally:  # 释放文件句柄。
            book.close()  # 不保存或重写导出表。
    return records  # 返回未去重来源记录。

def tcmsp_records(root, identities, herbs):  # 扩展当前TCMSP结果而非重写其科学内核。
    rows, source = select_rows(root, herbs)  # 保留现有指纹核验。
    summary, tables, anomalies = analyze(rows, herbs)  # 保留OB和DL条件。
    bridges = defaultdict(list)  # 显式TCMSP编号到HERB身份的交叉引用。
    for identity in identities.values():  # 不用模糊名称桥接。
        for mid in re.findall(r"MOL\d+", identity["TCMSP_id"]):  # 保留多值交叉引用。
            bridges[mid].append(identity)  # 多重映射不能任取一条。
    components = {r["compound_id"]: r for r in tables["components"]}  # 仅使用已通过筛选的成分。
    records = []  # 输出药味与来源身份。
    for row in tables["herb_components"]:  # 共享成分保持多个药味。
        cid = row["compound_id"]  # 不改变原TCMSP编号。
        matches = bridges[cid]  # 不猜未收录身份。
        identity = matches[0] if len(matches) == 1 else {}  # 多重对应作为待核而不合并。
        records.append(make_record("TCMSP", cid, components[cid]["name"], row["herb"], "tcmsp_snapshot.tsv:" + row["source_lines"], identity))  # 来源行号完整保留。
    return records, tables, source  # 原靶点表另行交给现有标准化流程。

def deduplicate(records, herbs):  # 按用户确认的完整化学身份保守去重。
    formulas = defaultdict(set)  # 检查同结构键的分子式冲突。
    for r in records:  # 先核对再合并。
        if r["inchikey"] and r["formula"]:  # 缺失不当作冲突值。
            formulas[r["inchikey"]].add(r["formula"])  # 分子式冲突需要人工处理。
    conflicts = {key for key, values in formulas.items() if len(values) > 1}  # 不覆盖冲突身份。
    groups, memberships, source_rows = {}, set(), []  # 主表、药味关系和来源表分别保留。
    for r in records:  # 每条原始记录均有去向。
        usable = bool(r["inchikey"] and r["inchikey"] not in conflicts)  # 冲突结构不能自动合并。
        identity = r["inchikey"] if usable else r["source"] + ":" + r["source_id"]  # 未核实记录保持来源隔离。
        cid = "CHEM_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]  # 编号稳定且不使用易变名称。
        groups.setdefault(cid, {"compound_id": cid, "name": r["name"], "inchikey": r["inchikey"] if usable else "", "identity_status": "结构键分组" if usable else "结构待核"})  # 不把待核条目称作已确认物质。
        memberships.add((r["herb"], cid))  # 去重后仍保留所有药味归属。
        source_rows.append(dict(r, compound_id=cid))  # 每个新编号可回到原始来源。
    components = [groups[k] for k in sorted(groups)]  # 固定输出顺序便于复算。
    for row in components:  # 为现有A03接口补足药味展示字段。
        row["herbs"] = "、".join(h for h in herbs if (h, row["compound_id"]) in memberships)  # 不丢失共享成分。
    member_rows = [{"herb": h, "compound_id": cid} for h, cid in sorted(memberships)]  # 保持现有成员关系字段。
    return components, member_rows, source_rows, sorted(conflicts)  # 异常作为独立审核项目。

def batman_known(path):  # 只读取用户批准的已有关系文件。
    raw = gzip.decompress(Path(path).read_bytes())  # 固定归档字节供复算。
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")  # 不读取预测评分表。
    require({"PubChem_CID", "IUPAC_name", "known_target_proteins"} <= set(reader.fieldnames or []), "BATMAN已有关系表头错误")  # 错文件不得当作零关系。
    return list(reader)  # 保留原数字编号及名称用于后续核查。


def batman_records(raw, identities, herb_names, pubchem_evidence=None):  # 全部BATMAN成分入候选池，不做ADME淘汰。
    names = dict(herb_names)  # 调用方按当前药味明确绑定官方拼音条目。
    require(bool(names) and all(names.values()), "请明确绑定BATMAN药味条目")
    index = defaultdict(list)  # HERB提供的明确PubChem交叉引用。
    for row in identities.values():  # 不猜测编号偏移或模糊名称。
        for cid in re.findall(r"\d+", text(row["PubChem_id"])):  # 保留多值交叉引用。
            index[cid].append(row)  # 身份不唯一时停止自动合并。
    official = {}  # 复用有来源指纹的官方PubChem属性，不把实时失败当作零结果。
    evidence_path = Path(pubchem_evidence) if pubchem_evidence else None
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path else {"sources": []}  # 明确绑定既有查询快照。
    for item in evidence["sources"]:  # 只读取来源清单指定文件。
        path = (evidence_path.parent / item["copied_to"]).resolve()
        require(path.is_relative_to(evidence_path.parent.resolve()), "PubChem快照路径超出来源目录")  # 不按修改日期猜最新文件。
        require(hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], "PubChem快照指纹改变")  # 禁止未核对数据参与合并。
        properties = json.loads(path.read_text(encoding="utf-8"))["PropertyTable"]["Properties"]  # 官方结构字段。
        require(len(properties) == 1, "PubChem属性身份多值")  # 不任意选择一个结构。
        value = properties[0]  # 已归档的唯一化学身份。
        official[str(value["CID"])] = value  # 完整CID不做偏移转换。
    records, counts, pending = [], {}, []  # 待核事项与候选成分分开。
    normalize = lambda value: re.sub(r"\s+", "", value).lower()  # 只忽略大小写和空白，不改变立体信息。
    with (raw / "BATMAN_herb_browse.txt").open(encoding="utf-8-sig") as stream:  # 使用完整归档总表。
        reader = csv.DictReader(stream, delimiter="\t")  # 不依赖筛选过的靶点查询接口。
        require({"Pinyin.Name", "Chinese.Name", "Latin.Name", "Ingredients"} <= set(reader.fieldnames or []), "BATMAN成分总表字段缺失")  # 错文件不能继续。
        for line, row in enumerate(reader, 2):  # 保存真实来源行号。
            if row["Pinyin.Name"] not in names:  # 防风花、叶等相近条目不混入。
                continue  # 其他药味不属于本次处方。
            herb = names[row["Pinyin.Name"]]  # 药味通过准确拼音条目绑定。
            require(row["Chinese.Name"] == herb and herb not in counts, "BATMAN药味身份冲突或多条同名记录")  # 不按第一条匹配。
            entries = row["Ingredients"].split("|")  # 保留原始成分枚举。
            counts[herb] = len(entries)  # 不将共享成分直接相加。
            for item in entries:  # 每个成分均保留，不以靶点缺失筛除。
                match = re.search(r"\((\d+)\)$", item)  # 只解析官方标明的尾部编号。
                require(match is not None, "BATMAN成分编号格式改变")  # 不猜数字位置。
                cid, name = match.group(1), item[:match.start()]  # 原始编号不加减或替换。
                candidates = index[cid]  # 明确命名空间的交叉引用。
                agreed = [r for r in candidates if normalize(name) in {normalize(x) for x in [r["Ingredient_name"]] + r["Ingredient_alias_name"].split(";")}]  # 同时要求原名或别名精确对应。
                keys = {text(r["InChIKey"]) for r in agreed if text(r["InChIKey"])}  # 同一编号的结构不能相互冲突。
                identity = agreed[0] if agreed and len(keys) == 1 else {}  # 不明确时保留独立结构待核条目。
                if cid in official:  # 已有官方属性能补齐同一CID的名称和结构核对。
                    value = official[cid]  # 只使用经指纹验证的归档快照。
                    require(normalize(name) == normalize(value["IUPACName"]), "BATMAN与PubChem名称冲突")  # 不用相似名称强行合并。
                    require(not keys or keys == {value["InChIKey"]}, "HERB与PubChem结构键冲突")  # 冲突须人工决定。
                    identity = {"InChIKey": value["InChIKey"], "Molecular_formula": value["InChI"].split("/")[1]}  # 保留完整立体结构键与官方分子式。
                records.append(make_record("BATMAN", cid, name, herb, "BATMAN_herb_browse.txt:" + str(line), identity))  # 保留完整药味来源。
                if not identity:  # 不能把未核实记录算作已确认结构。
                    pending.append({"source_id": cid, "herb": herb, "name": name, "reason": "未明确对应结构" if not candidates else "编号对应但名称或结构尚待核实"})  # 待核记录供用户查看。
    require(set(counts) == set(names.values()), "BATMAN未匹配完整处方")  # 缺药味不能宣称三库齐备。
    return records, counts, pending  # 不发布生产运行。

"""固定官方来源三库采集；原响应、分页和失败留存，统一交给上传解析器。"""
import csv
import hashlib
import html
import io
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from contracts import require
from storage import now, read_json, write_json

HERB_API = "http://herb.ac.cn/chedi/api/"
BATMAN = "http://batman2.cloudna.cn/downloadApiFile/data/browser/"
TCMSP = "https://old.tcmsp-e.com/"
HOSTS = {"herb.ac.cn", "batman2.cloudna.cn", "old.tcmsp-e.com", "rest.uniprot.org"}


class Fetcher:
    """同目录固定请求键断点复用；不同研究不自动借用资料。"""
    def __init__(self, folder, opener, sleeper):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.opener, self.sleeper = opener, sleeper

    def get(self, url, payload=None):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.hostname in HOSTS and parsed.scheme in ("http", "https") and not parsed.username and not parsed.password,
                "采集来源不在固定官方名单")
        body = json.dumps(payload, sort_keys=True).encode() if payload is not None else None
        token = hashlib.sha256(url.encode() + (body or b"")).hexdigest()
        path = self.folder / (token + ".bin")
        index = self.folder / (token + ".json")
        if index.exists():
            record = read_json(index)
            raw = path.read_bytes()
            require(record["url"] == url and record["payload"] == payload and record["sha256"] == hashlib.sha256(raw).hexdigest(), "缓存原件或请求指纹改变")
            return raw
        for attempt in range(2):
            try:
                self.sleeper(0.5)
                request = urllib.request.Request(url, data=body, headers={"User-Agent": "ModuleA/1.0", "Content-Type": "application/json"})
                with self.opener(request, timeout=25) as response:
                    require(urllib.parse.urlsplit(response.geturl()).hostname in HOSTS, "官方请求重定向到不支持的主机")
                    raw = response.read(64 * 1024 * 1024 + 1)
                    require(response.status == 200 and len(raw) <= 64 * 1024 * 1024, "官方响应失败或超出容量，未截断采用")
                    length = response.headers.get("Content-Length")
                    require(not length or len(raw) == int(length), "官方响应下载不完整")
                path.write_bytes(raw)
                write_json(index, {"url": url, "payload": payload, "retrieved_at": now(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
                return raw
            except Exception as error:
                failure = self.folder / (token + "_failure_" + str(attempt) + "_" + str(time.time_ns()))
                if isinstance(error, urllib.error.HTTPError):
                    failure.with_suffix(".bin").write_bytes(error.read(8 * 1024 * 1024))
                write_json(failure.with_suffix(".json"), {"url": url, "payload": payload, "error": str(error), "at": now()})
                if attempt:
                    raise

    def herb(self, func, **values):
        return json.loads(self.get(HERB_API, dict(func_name=func, **values)))


def _table(rows):
    """仅生成包装表，不改变原响应；原字节另存并一起归档。"""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def _value(value):
    return str(value.get("title", "")) if isinstance(value, dict) else str(value or "")


def _herb(fetch, herbs, progress):
    """完整药味详情列出全部成分，再读取每个成分的已有关系，不触发预测。"""
    import openpyxl
    files, counts, bindings, identities, compounds = {}, {}, {}, {}, {}
    for number, herb in enumerate(herbs):
        search = fetch.herb("search_api", label="Herb", keyword=herb)
        rows = search.get("res_data")
        require(isinstance(rows, list) and rows and rows[0][:3] == ["Herb id", "Herb pinyin name", "Herb Chinese name"], "HERB药味搜索结构改变")
        matches = [r for r in rows[1:] if len(r) > 2 and r[2] == herb]
        require(len(matches) == 1, "HERB未找到唯一精确药味：" + herb)
        identifier = _value(matches[0][0])
        require(re.fullmatch(r"HERB\d+", identifier), "HERB药味编号无效")
        detail = fetch.herb("detail_api", label="Herb", v=identifier, key_id=identifier)
        summary = detail.get("summary", [])
        require(len(summary) == 2 and summary[1][0] == identifier and summary[1][2] == herb, "HERB药味详情身份不符")
        ingredients = detail.get("herb_ingredient")
        require(ingredients and ingredients[0][:2] == ["Ingredient id", "Ingredient name"], "HERB完整成分列表未取得")
        ids = [_value(r[0]) for r in ingredients[1:]]
        require(len(ids) == len(set(ids)) and all(re.fullmatch(r"HBIN\d+", v) for v in ids), "HERB成分清单重复或编号异常")
        require(ids, "HERB药味成分清单为空，须人工核对是否为官方完整零结果")
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["Ingredient id", "Ingredient name"])
        for row in ingredients[1:]:
            cid = _value(row[0])
            compounds[cid] = row[1]
            sheet.append([cid, row[1]])
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        filename = "herb_" + str(number + 1) + ".xlsx"
        bindings[herb] = filename
        files[filename] = stream.getvalue()
        counts[herb] = len(ids)
    # 官方分页必须收齐；同一编号重复、总量漂移均拒绝宣布完整。
    target_rows, page, total = [], 1, None
    while True:
        result = fetch.herb("browse_api", label="Target", page=page, page_size=1000)
        require(type(result.get("total_num")) is int and result["total_num"] >= 0 and result.get("browse_data"), "HERB靶点分页缺少总数")
        require(total is None or total == result["total_num"], "HERB靶点分页期间总量改变")
        total = result["total_num"]
        batch = result["browse_data"][1:]
        require(batch or len(target_rows) == total, "HERB靶点分页提前结束")
        target_rows.extend(batch)
        if len(target_rows) >= total:
            require(len(target_rows) == total, "HERB靶点分页数量超出声明")
            break
        page += 1
        require(page <= 1000, "HERB分页超过可核验范围")
    require(len({_value(r[0]) for r in target_rows}) == total, "HERB靶点分页重复，不能冒充全量")
    files["HERB_target_browse_page001.json"] = json.dumps({"total_num": total, "browse_data": [["Target id", "Gene name", "Gene alias"]] + target_rows}, ensure_ascii=False).encode()
    for i, (cid, name) in enumerate(sorted(compounds.items()), 1):
        if progress:
            progress(f"HERB已有关系 {i}/{len(compounds)}")
        detail = fetch.herb("detail_api", label="Ingredient", v=cid, key_id=cid)
        summary = detail.get("summary", [])
        require(len(summary) == 2 and summary[1][0] == cid, "HERB成分身份冲突")
        values = dict(zip(summary[0], summary[1]))
        require(values.get("Ingredient name") == name, "HERB清单与详情成分名不一致")
        targets = detail.get("ingredient_target")
        require(targets and targets[0] == ["Target id", "Target name", "Database sources"], "HERB已有关系表不完整")
        files["HERB_existing_details/" + cid + ".json"] = json.dumps(detail, ensure_ascii=False).encode()
        # 官方详情没有完整结构键时留空，不能用名称或缺立体信息的SMILES猜结构。
        key = _value(values.get("InChIKey", ""))
        require(not key or re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", key), "HERB结构键不完整")
        identities[cid] = [cid, name, "", key, _value(values.get("Molecule formula")), _value(values.get("TCMSP id")), _value(values.get("PubChem id"))]
    files["HERB_ingredient_info_v2.txt"] = _table([["Ingredient_id", "Ingredient_name", "Ingredient_alias_name", "InChIKey", "Molecular_formula", "TCMSP_id", "PubChem_id"]] + list(identities.values()))
    return files, counts, {"herb_files": bindings}


def _batman(fetch, herbs, progress):
    """采用官方全量下载的known表；未取得完整下载则失败，不取预测结果。"""
    raw = fetch.get(BATMAN + "herb_browse.txt")
    known = fetch.get(BATMAN + "known_browse_by_ingredients.txt.gz")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t"))
    require(rows and {"Pinyin.Name", "Chinese.Name", "Latin.Name", "Ingredients"} <= rows[0].keys(), "BATMAN药味总表结构改变")
    bindings, counts = {}, {}
    for herb in herbs:
        matches = [r for r in rows if r["Chinese.Name"] == herb]
        require(len(matches) == 1, "BATMAN未找到唯一精确药味：" + herb)
        row = matches[0]
        require(row["Ingredients"] and row["Ingredients"] != "NA", "BATMAN成分清单缺失，不能作零结果")
        counts[herb] = len(row["Ingredients"].split("|"))
        bindings[row["Pinyin.Name"]] = herb
    from .multisource import batman_known
    check = fetch.folder / "known_validation.gz"
    check.write_bytes(known)
    batman_known(check)
    return {"BATMAN_herb_browse.txt": raw, "BATMAN_known_browse_by_ingredients.txt.gz": known}, counts, {"herb_names": bindings}


def _arrays(raw):
    """只解析网页显式JSON数组；不执行任何脚本，不猜列或分页。"""
    text = raw.decode("utf-8")
    arrays = []
    for match in re.finditer(r"\bdata\s*:\s*(?=\[)", text):
        value, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        if isinstance(value, list):
            arrays.append(value)
    return arrays


def _human_target(fetch, name):
    """官方人类精确蛋白名唯一映射才采用，不能按第一条或高相似名称匹配。"""
    query = '(protein_name:"' + name.replace('"', '') + '") AND (organism_id:9606) AND (reviewed:true)'
    url = "https://rest.uniprot.org/uniprotkb/search?" + urllib.parse.urlencode({"query": query, "format": "json", "size": 500})
    data = json.loads(fetch.get(url))
    require(isinstance(data.get("results"), list), "UniProt映射响应不完整")
    require(len(data["results"]) < 500, "UniProt候选未完整取得，不能按前页判断唯一身份")
    rows = []
    for row in data["results"]:
        desc = row.get("proteinDescription", {})
        names = [desc.get("recommendedName", {}).get("fullName", {}).get("value", "")]
        names += [x.get("fullName", {}).get("value", "") for x in desc.get("alternativeNames", [])]
        genes = [x.get("geneName", {}).get("value") for x in row.get("genes", []) if x.get("geneName", {}).get("value")]
        if name.casefold() in {n.casefold() for n in names} and row.get("organism", {}).get("taxonId") == 9606 and len(genes) == 1:
            rows.append((row["primaryAccession"], genes[0], "Homo sapiens (Human)"))
    return rows[0] if len(rows) == 1 else ("", "", "")


def _tcmsp(fetch, herbs, progress):
    """原官方页面JSON含完整药味成分与关系；身份缺口保留为待核验。"""
    page = fetch.get(TCMSP + "tcmsp.php").decode("utf-8")
    token = re.search(r'name="token"\s+value="([A-Za-z0-9]+)"', page)
    require(token is not None, "TCMSP官方入口需登录或页面已改变，请使用原始文件上传")
    output, counts = [], {}
    target_cache = {}
    for herb in herbs:
        search = fetch.get(TCMSP + "tcmspsearch.php?" + urllib.parse.urlencode({"qs": "herb_all_name", "q": herb, "token": token[1]}))
        choices = [r for group in _arrays(search) for r in group if isinstance(r, dict) and r.get("herb_cn_name") == herb]
        require(len(choices) == 1 and choices[0].get("herb_en_name"), "TCMSP未找到唯一精确药味：" + herb)
        raw = fetch.get(TCMSP + "tcmspsearch.php?" + urllib.parse.urlencode({"qr": choices[0]["herb_en_name"], "qsr": "herb_en_name", "token": token[1]}))
        arrays = _arrays(raw)
        components = [r for group in arrays for r in group if isinstance(r, dict) and {"MOL_ID", "ob", "dl"} <= r.keys()]
        relations = [r for group in arrays for r in group if isinstance(r, dict) and {"MOL_ID", "target_ID", "target_name"} <= r.keys()]
        require(components and relations, "TCMSP完整成分或靶点表未取得，不能宣称完整零结果")
        require(len({r["MOL_ID"] for r in components}) == len(components), "TCMSP成分表重复或分页异常")
        by_compound = {}
        for row in relations:
            by_compound.setdefault(row["MOL_ID"], []).append(row)
        start = len(output)
        for comp in components:
            cid = comp["MOL_ID"]
            require(re.fullmatch(r"MOL\d+", cid), "TCMSP分子编号异常")
            for rel in by_compound.get(cid, [{}]):
                tid, name = rel.get("target_ID", ""), rel.get("target_name", "")
                identity = ("", "", "")
                from components import number
                qualified = number(comp["ob"]) is not None and number(comp["dl"]) is not None and number(comp["ob"]) >= 30 and number(comp["dl"]) >= .18
                if tid and name and qualified:
                    if progress:
                        progress("TCMSP核对原始靶点：" + name)
                    if (tid, name) not in target_cache:
                        target_raw = fetch.get(TCMSP + "target.php?" + urllib.parse.urlencode({"qt": tid}))
                        require(" ".join(name.split()) in " ".join(html.unescape(re.sub(r"<[^>]+>", " ", target_raw.decode("utf-8"))).split()), "TCMSP靶点详情身份不一致")
                        target_cache[tid, name] = _human_target(fetch, name)
                    identity = target_cache[tid, name]
                output.append([herb, cid, comp["molecule_name"], comp["ob"], comp["dl"], *identity, tid, name])
        counts[herb] = len(output) - start
    files = {"references/tcmsp_snapshot.tsv": _table([["Chinesename", "MOLID", "moleculename", "ob", "dl", "UniProtAC", "GeneNames", "Organism", "raw_target_id", "raw_target_name"]] + output)}
    return files, counts, {"encoding": "utf-8-sig"}


def acquire(database, herbs, folder, progress=None, opener=urllib.request.urlopen, sleeper=time.sleep):
    """返回stage兼容资料包；成功包与失败轨迹留存，数量由真实原件决定。"""
    require(database in ("TCMSP", "HERB", "BATMAN") and isinstance(herbs, list) and herbs and len(set(herbs)) == len(herbs), "采集数据库或药味清单无效")
    folder = Path(folder)
    package_index = folder / "package_index.json"
    if package_index.exists():
        saved = read_json(package_index)
        require(saved["database"] == database and saved["herbs"] == herbs, "旧来源包不属于本次药味与数据库")
        for record in saved["files"]:
            path = (folder / record["path"]).resolve()
            require(path.is_relative_to(folder.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], "已保存来源原件指纹改变")
        data = (folder / "source.zip").read_bytes()
        return dict(saved["source"], data=data)
    fetch = Fetcher(folder / "original_requests", opener, sleeper)
    files, counts, meta = {"TCMSP": _tcmsp, "HERB": _herb, "BATMAN": _batman}[database](fetch, herbs, progress)
    complete = {h: {"status": "complete", "records": counts[h], "basis": "original_requests中完整官方响应及固定请求指纹；完整药味清单逐项解析"} for h in herbs}
    files["modulea_source.json"] = json.dumps(dict(version="A01.source_package.1", database=database, herbs=herbs, completeness=complete, **meta), ensure_ascii=False).encode()
    for path in fetch.folder.iterdir():
        if path.is_file():
            files["original_requests/" + path.name] = path.read_bytes()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    data = stream.getvalue()
    require(len(data) <= 16 * 1024 * 1024, "完整来源包超过16MiB上传限制，未截断采用；请按原始资料上传规范处理")
    with (folder / "source.zip").open("xb") as stream:
        stream.write(data)
    source = {"database": database, "format": "source_zip", "name": database + "_official.zip", "data": data,
            "encoding": "utf-8-sig", "query": "、".join(herbs), "retrieved_at": now(), "version": "A01.acquisition.1；以原响应固定",
            "source_url": {"TCMSP": TCMSP, "HERB": HERB_API, "BATMAN": BATMAN}[database], "coverage": complete}
    records = [{"path": p.relative_to(folder).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in [folder / "source.zip", *sorted(fetch.folder.iterdir())] if p.is_file()]
    write_json(package_index, {"database": database, "herbs": herbs, "files": records,
                               "source": {k:v for k,v in source.items() if k != "data"}})
    return source

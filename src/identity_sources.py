# 官方人类基因与历史编号核对；原始证据与未解歧记录全部保留。
import csv  # 按原列名解析官方表。
import gzip  # 解压官方原始快照。
import hashlib  # 校验文件和证据包。
import io  # 在内存解析已校验字节。
import json  # 读取固定来源清单。
from collections import defaultdict  # 保留一对多关系。
from contracts import require  # 失败使用项目统一错误。

class IdentityEvidence:  # 一个对象对应一组固定官方证据。
    def __init__(self, gene_raw, history_raw, query_raw=b"{}"):  # 输入已归档原字节。
        self.digest = hashlib.sha256(gene_raw + history_raw + query_raw).hexdigest()  # 不混淆不同证据组合。
        self.lookup_status = {}  # 按实际请求编号保存成功或失败，不混淆缺缓存。
        self.lookups, self.archives, self.proteins, self.query_status, self.xrefs = {}, {}, {}, {}, {}  # 官方查询原文的索引。
        for query in json.loads(query_raw.decode("utf-8")).get("queries", []):  # 不在复算时联网。
            url, status = query["url"], query["status"]  # 区分失败与成功空结果。
            self.query_status[url] = status  # 查询错误不伪装查无记录。
            if url.endswith("/lookup/id"):  # 记录这批每个编号的请求状态。
                self.lookup_status.update({identifier:status for identifier in (query.get("payload") or {}).get("ids", [])})  # 失败也留痕。
            if status != "ok":  # 失败证据不能提供身份。
                continue  # 状态仍可展示。
            text = query["response_text"]  # 实际官方响应。
            require(hashlib.sha256(text.encode("utf-8")).hexdigest() == query["response_sha256"], "身份查询原响应指纹错误")  # 检测人为改写响应。
            data = json.loads(text)  # 仅解析成功原文。
            if url.endswith("/lookup/id"):  # 当前Ensembl身份。
                self.lookups.update(data)  # 未命中保留null。
            elif url.endswith("/archive/id"):  # 官方历史关系。
                self.archives.update({x["id"]: x for x in data if "id" in x})  # 不根据相似度选择替代。
            elif "/xrefs/id/" in url:  # 官方精确跨库编号链接。
                identifier = url.split("/xrefs/id/", 1)[1].split("?", 1)[0]  # 保留查询的原编号。
                self.xrefs[identifier] = data  # 完整查询可补足先前过滤查询。
            elif "rest.uniprot.org/uniprotkb/" in url:  # 当前或失活蛋白条目。
                self.proteins[data["primaryAccession"]] = data  # 保存完整物种及拆分依据。
        self.genes, self.names, self.ids, self.history = {}, defaultdict(set), defaultdict(set), defaultdict(set)  # 名称、编号和历史分别索引。
        for line, row in enumerate(csv.DictReader(io.StringIO(gzip.decompress(gene_raw).decode("utf-8")), delimiter="\t"), 2):  # NCBI当前人类表。
            if row["#tax_id"] != "9606":  # 官方文件也含其他分类编号，按实际物种筛选。
                continue  # 仅采用用户批准的人类9606记录。
            gid = row["GeneID"]  # 明确NCBI编号。
            require(gid not in self.genes, "NCBI快照含重复编号")  # 不任取重复记录。
            self.genes[gid] = dict(row, source_line=line)  # 保存类型及原始定位。
            for name in [row["Symbol"], row["Symbol_from_nomenclature_authority"], *row["Synonyms"].split("|")]:  # 只用符号和官方别名，不模糊匹配描述。
                if name and name != "-":  # 缺失不成为候选。
                    self.names[name].add(gid)  # 一对多不任取第一条。
            self.ids["NCBIGene:" + gid].add(gid)  # 主编号带命名空间。
            self.ids["GeneID:" + gid].add(gid)  # 明确支持的同义前缀。
            self.ids["LOC" + gid].add(gid)  # 仅在该编号真实存在时形成候选。
            for cross in row["dbXrefs"].split("|"):  # 保存官方跨库编号。
                self.ids[cross].add(gid)  # 不删编号版本。
                if cross.startswith("Ensembl:"):  # Ensembl编号可以独立输入。
                    self.ids[cross.removeprefix("Ensembl:")].add(gid)  # 明确前缀转换。
        for line, row in enumerate(csv.DictReader(io.StringIO(history_raw.decode("utf-8")), delimiter="\t"), 2):  # 人类历史表保留原行序。
            require(row["#tax_id"] == "9606", "历史快照含其他物种")  # 仅核对人类。
            self.history[row["Discontinued_GeneID"]].add(row["GeneID"])  # 撤销无替代的减号也保留。
            if row["Discontinued_Symbol"] != "-":  # 可由旧名进入历史链。
                self.names[row["Discontinued_Symbol"]].add(row["Discontinued_GeneID"])  # 后续必须核对替代链。
        require(bool(self.genes), "NCBI人类快照为空")  # 不把获取失败当零基因。

    def current(self, gid, seen=None):  # 沿历史链找现行编号。
        seen = set() if seen is None else set(seen)  # 各分支独立检查循环。
        if gid in seen or gid == "-":  # 环或撤销无替代不能猜测。
            return set()  # 保留未解决状态。
        if gid in self.genes:  # 现行编号停止追溯。
            return {gid}  # 不改变已有编号。
        seen.add(gid)  # 防止错误历史链无限循环。
        return set().union(*(self.current(x, seen) for x in self.history.get(gid, set())))  # 多替代全部保留。

    def resolve(self, found, mapper):  # 只有完整一致的证据才形成统一HGNC身份。
        symbol, raw_id = found["raw_symbol"], found["raw_id"]  # 原输入永不改写。
        if found["raw_uniprot"]:  # NCBI名称不能证明蛋白编号已正确对应。
            return found  # UniProt历史一对多留给专门核对。
        evidence = []  # 各实际输入字段分别核对。
        if symbol:  # 名称可从当前和历史表找到候选。
            candidates = self.names.get(symbol, set()) | self.ids.get(symbol, set())  # LOC和明确Ensembl也支持。
            evidence.append(set().union(*(self.current(x) for x in candidates)))  # 历史替换不丢多值。
        if raw_id.startswith(("NCBIGene:", "GeneID:", "ENSG", "HGNC:")):  # 不把TTD等编号冒充GeneID。
            candidates = self.ids.get(raw_id, set())  # 明确编号优先交叉检查。
            if raw_id.startswith(("NCBIGene:", "GeneID:")):  # 历史编号可能已不在当前表。
                candidates = candidates | {raw_id.split(":", 1)[1]}  # 仅查询历史链，不直接确认。
            evidence.append(set().union(*(self.current(x) for x in candidates)))  # 所有提供的编号都必须查实。
        union = set().union(*evidence) if evidence else set()  # 保留全部NCBI候选。
        found["ncbi_candidate_ids"] = "|".join(sorted(union))  # 查询到多个候选也留痕。
        if not evidence or any(len(x) != 1 for x in evidence) or len(union) != 1:  # 不用另一个字段掩盖冲突或缺失。
            if raw_id.startswith(("NCBIGene:", "GeneID:")):  # 防止旧算法忽略明确NCBI冲突。
                found.update(status="ambiguous_or_conflicting", target_id="", symbol="", mapping_method="ncbi_identity_conflict")  # 主集合不能误收。
            return found  # 未确认不编造身份。
        gid = next(iter(union))  # 此处已证实唯一。
        row = self.genes[gid]  # 对应官方当前记录。
        found.update(ncbi_gene_id=gid, ncbi_symbol=row["Symbol"], gene_type=row["type_of_gene"], ncbi_source_line=row["source_line"], verification_url="https://www.ncbi.nlm.nih.gov/gene/" + gid)  # 网页和报告可追溯。
        hids = {x.removeprefix("HGNC:") for x in row["dbXrefs"].split("|") if x.startswith("HGNC:HGNC:")}  # 官方双前缀按字段定义转换。
        indexed = mapper.index[("entrez_id", gid)]  # HGNC自身提供的NCBI交叉索引。
        if hids and indexed and hids != indexed:  # 两个官方来源冲突不强行选择。
            found.update(status="ambiguous_or_conflicting", target_id="", symbol="", mapping_method="official_crossref_conflict")  # 留作重点复核。
            return found  # 不自动裁决。
        hids = hids or indexed  # 缺失不是反证，但必须有明确官方链接。
        if row["type_of_gene"] == "biological-region":  # 区域真实存在但不是单个基因。
            found.update(status="non_gene_object", target_id="", symbol="", mapping_method="ncbi_biological_region")  # 不冒充蛋白靶点。
        elif len(hids) == 1 and next(iter(hids)) in mapper.records:  # 只能接入现行批准的HGNC身份。
            hid = next(iter(hids))  # 唯一跨库关系。
            prior = set(filter(None, found["candidate_ids"].split("|")))  # 原HGNC冲突仍需交叉判断。
            if prior and hid not in prior:  # 官方新链接与原输入不一致。
                found.update(status="ambiguous_or_conflicting", target_id="", symbol="", mapping_method="official_crossref_conflict")  # 不任取任一来源。
            else:  # 唯一且无反证才进入统一集合。
                found.update(mapper.records[hid], status="matched", mapping_method="ncbi_current_or_history_crossref")  # 保留原名和历史来源。
        elif not hids:  # 查实记录不等于能接入HGNC。
            found.update(status="identity_verified_no_hgnc", target_id="", symbol="", mapping_method="ncbi_verified_no_hgnc")  # 另表保留，不叫无效基因。
        return found  # 非编码基因不因类型自动删除。

    def resolve_queries(self, found, mapper):  # 仅消费已归档的官方查询，不即时漂移。
        accession = found["raw_uniprot"]  # 蛋白证据优先检查失活或拆分。
        if accession:  # 不让名称掩盖错误蛋白编号。
            protein = self.proteins.get(accession)  # 本包未查询者明确未查询。
            found["query_status"] = "已查询" if protein else "本证据包未查实该蛋白编号"  # 不把缺缓存当查无记录。
            if protein and protein.get("inactiveReason"):  # 历史拆分或合并须保留原信息。
                reason = protein["inactiveReason"]  # 官方历史类型。
                targets = reason.get("mergeDemergeTo", [])  # 保留全部现行条目。
                found["query_note"] = reason.get("inactiveReasonType", "") + ": " + "|".join(targets)  # 解释不能自动确认的原因。
                found["verification_url"] = "https://www.uniprot.org/uniprotkb/" + accession + "/history"  # 用户可以直接核对。
                hids = {x["id"] for target in targets for x in self.proteins.get(target, {}).get("uniProtKBCrossReferences", []) if x.get("database") == "HGNC" and self.proteins.get(target, {}).get("organism", {}).get("taxonId") == 9606}  # 明确人类候选，不能全部纳入。
                found["candidate_ids"] = "|".join(sorted(set(filter(None, found["candidate_ids"].split("|"))) | hids))  # 候选用于影响评估。
            return found  # 当前不自动裁决蛋白历史一对多。
        values = [x for x in (found["raw_symbol"], found["raw_id"]) if x.startswith("ENSG")]  # 标识类型明确。
        if not values or found["status"] == "matched":  # 已由一致证据确认者无需降级。
            return found  # 不改正常结果。
        if len(set(values)) != 1:  # 两个字段出现不同编号。
            return found  # 不选择其一。
        identifier = values[0]  # 当前待查编号。
        info = self.lookups.get(identifier)  # 只用精确官方查询结果。
        history = self.archives.get(identifier, {})  # 历史状态作为补充证据。
        found["query_status"] = "查询失败，需重试" if self.lookup_status.get(identifier) == "query_failed" else ("已查询" if identifier in self.lookups or self.lookup_status.get(identifier) == "ok" else "本证据包未查询该编号")  # 无缓存不能假装查无记录。
        found["query_note"] = "Ensembl历史状态：" + str(history.get("is_current", "未返回"))  # 原历史返回保留在来源包。
        if not info or info.get("species") != "homo_sapiens" or info.get("object_type") != "Gene" or info.get("id") != identifier:  # 限于现行明确人类基因。
            return found  # 转录本、失活编号及物种不符不能强行纳入。
        if found["raw_symbol"] and found["raw_symbol"] != identifier:  # 不能用编号覆盖不一致的原始名称。
            if found["raw_symbol"] != info.get("display_name"):  # 未证明名称一致时保留。
                return found  # 不伪造对应。
        found.update(gene_type=info.get("biotype", ""), verification_url="https://www.ensembl.org/Homo_sapiens/Gene/Summary?g=" + identifier, ensembl_gene_id=identifier)  # 查实但不一定能接入HGNC。
        candidates = set(mapper.index[("ensembl_gene_id", identifier)])  # HGNC原表的精确交叉编号。
        links = self.xrefs.get(identifier, [])  # 官方查询跨库编号。
        explicit = {x["primary_id"] for x in links if x.get("dbname") == "HGNC"}  # 只取明确HGNC来源。
        ncbi = {x["primary_id"] for x in links if x.get("dbname") == "EntrezGene"}  # NCBI主编号，不取其他推测链接。
        linked = [mapper.index[("entrez_id", gid)] for gid in ncbi]  # 每个明确编号都须可核对。
        if any(len(ids) != 1 for ids in linked):  # 一个稳定编号没有查实就不忽略。
            return found  # 保留冲突供复核。
        candidates |= explicit | set().union(*linked)  # 所有官方证据必须指向同一身份。
        prior = set(filter(None, found["candidate_ids"].split("|")))  # 保留原名称的候选。
        if candidates and (not candidates <= mapper.records.keys() or (prior and not candidates <= prior)):  # 不覆盖原名称反证或撤销HGNC。
            found.update(status="ambiguous_or_conflicting", target_id="", symbol="", mapping_method="official_crossref_conflict")  # 官方冲突仍需处理。
            return found  # 不强行匹配。
        if len(candidates) > 1:  # 多个官方身份保持未决。
            found.update(status="ambiguous_or_conflicting", target_id="", symbol="", mapping_method="official_crossref_conflict")  # 不选择第一个。
            return found  # 不扩成多个靶点。
        if len(candidates) == 1:  # 唯一HGNC链接。
            found.update(mapper.records[next(iter(candidates))], status="matched", mapping_method="ensembl_verified_hgnc_id")  # 不凭显示名称猜对应。
        elif not candidates and not prior:  # 真实基因、没有明确HGNC链接或原名称冲突。
            found.update(status="identity_verified_no_hgnc", mapping_method="ensembl_verified_no_hgnc")  # 单独保留而非当无效。
        return found  # 不把possible_replacement相似度当确定替代。

def load_supplement(root):  # 固定版本避免随查询时间漂移。
    specs = [("ncbi_human_gene_info_20260913.gz", "ncbi_human_gene_info_20260913.json"), ("ncbi_human_gene_history_20260913.tsv", "ncbi_human_gene_history_20260913.json"), ("identity_queries_20260913_v3.json", "identity_queries_20260913_v3_manifest.json")]  # 已归档证据。
    blobs, metas = [], []  # 同一包供A01/A02复用。
    for filename, manifest in specs:  # 两份资料均必须校验。
        meta = json.loads((root / "references" / manifest).read_text(encoding="utf-8"))  # 不猜最新版。
        raw = (root / "references" / filename).read_bytes()  # 读取固定字节。
        require(len(raw) == meta["bytes"] and hashlib.sha256(raw).hexdigest() == meta["sha256"], "NCBI证据文件指纹不一致")  # 损坏不继续。
        blobs.append(raw)  # 只解析已核验字节。
        metas.append(dict(meta, filename=filename))  # 发布时保留文件及来源。
    return IdentityEvidence(*blobs), metas  # 与HGNC快照共同构成可重复依据。

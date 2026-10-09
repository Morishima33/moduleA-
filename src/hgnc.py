# 人类基因身份核对：原始字段与候选身份同时保留，不自动裁决歧义。
import csv  # 读取官方完整快照。
import hashlib  # 固定实际映射版本。
import io  # 从已核验字节解析。
import json  # 读取来源清单。
from collections import defaultdict  # 为同名多基因保留完整集合。
from contracts import require  # 使用统一校验错误。

class HgncMap:  # 一个实例固定使用一份HGNC快照。
    def __init__(self, raw, rule="HGNC.resolve.3", supplement=None):  # 可由归档文件或测试字节构造。
        self.rule, self.supplement = rule, supplement  # 固定算法版本及补充证据。
        self.digest = hashlib.sha256(raw).hexdigest()  # 映射版本绑定原字节。
        self.records, self.index = {}, defaultdict(set)  # 分开保存身份和索引。
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")  # 保留大小写与精确字段。
        fields = ("hgnc_id", "symbol", "prev_symbol", "alias_symbol", "ensembl_gene_id", "uniprot_ids")  # 只使用明确身份字段。
        require(set(fields) | {"status"} <= set(reader.fieldnames or []), "HGNC快照缺少必要字段")  # 不猜列。
        for line, row in enumerate(reader, 2):  # 官方文件原始行号。
            if row["status"] != "Approved":  # 撤销条目不直接当作有效身份。
                continue  # 后续无法匹配时明确报告。
            hid = row["hgnc_id"]  # HGNC稳定编号。
            require(hid not in self.records, "HGNC快照出现重复编号")  # 不任取第一条。
            self.records[hid] = {"target_id": hid, "symbol": row["symbol"], "mapping_line": line}  # 来源可定位。
            for value in row.get("entrez_id", "").split("|"):  # NCBI编号独立索引，不猜裸数字。
                if value.strip():  # 空编号不入表。
                    self.index[("entrez_id", value.strip())].add(hid)  # 保留多重映射。
            for field in fields:  # 别名、旧名和稳定编号分别索引。
                for value in row[field].split("|"):  # 只按官方多值分隔符拆分。
                    if value.strip():  # 空字段不形成候选身份。
                        self.index[(field, value.strip())].add(hid)  # 同一别名可以指向多个编号。
        require(bool(self.records), "HGNC快照没有有效条目")  # 失败不当作空结果。

    def _legacy(self, symbol, stable_id="", uniprot=""):  # 返回身份核对结果，不修改输入记录。
        symbol, stable_id, uniprot = (str(x or "").strip() for x in (symbol, stable_id, uniprot))  # 仅清理外部空白。
        evidence = []  # 每个输入字段各自给出候选。
        if symbol:  # 原始名称按原大小写核对。
            matches = set().union(*(self.index[(field, symbol)] for field in ("symbol", "prev_symbol", "alias_symbol")))  # 保留标准名与别名冲突。
            evidence.append(("symbol", matches))  # 无匹配也留存。
        if stable_id.startswith("HGNC:") or stable_id.startswith("ENSG"):  # 其他库自身条目号不冒充基因ID。
            field = "hgnc_id" if stable_id.startswith("HGNC:") else "ensembl_gene_id"  # 明确编号体系。
            evidence.append((field, self.index[(field, stable_id)]))  # 不截断版本或猜测编号。
        if uniprot:  # A01有明确的UniProt accession时交叉检查。
            evidence.append(("uniprot_ids", self.index[("uniprot_ids", uniprot)]))  # 不把蛋白名称当accession。
        candidates = set().union(*(ids for _, ids in evidence)) if evidence else set()  # 所有可能身份。
        resolved = bool(evidence) and all(len(ids) == 1 for _, ids in evidence) and len(candidates) == 1  # 仅唯一且相互一致自动通过。
        approved = self.index[("symbol", symbol)] if symbol else set()  # 现行标准名独立于旧别名。
        stable = [ids for field, ids in evidence if field != "symbol"]  # 只用明确稳定编号交叉验证。
        corroborated = len(approved) == 1 and bool(stable) and all(ids == approved for ids in stable)  # 所有提供的稳定编号必须唯一且一致。
        chosen = approved if corroborated else candidates  # 保留全部候选用于溯源，但明确选择依据。
        method = "approved_symbol_and_stable_id" if corroborated else ("unique_consistent" if resolved else "unresolved")  # 记录实际应用的规则。
        resolved = resolved or corroborated  # 仅新增用户已批准的消歧条件。
        status = "matched" if resolved else ("unmapped" if not candidates else "ambiguous_or_conflicting")  # 问题明确分组。
        target = self.records[next(iter(chosen))] if resolved else {}  # 歧义不选择第一项。
        return {"raw_symbol": symbol, "raw_id": stable_id, "raw_uniprot": uniprot, "status": status, "target_id": target.get("target_id", ""), "symbol": target.get("symbol", ""), "mapping_line": target.get("mapping_line", ""), "candidate_ids": "|".join(sorted(candidates)), "mapping_snapshot": self.digest, "mapping_rule": "HGNC.resolve.2", "mapping_method": method}  # 返回可追溯的扁平记录。

    def resolve(self, symbol, stable_id="", uniprot=""):  # 新旧版本显式分开，历史结果可复算。
        found = self._legacy(symbol, stable_id, uniprot)  # 首先执行原有严格核对。
        if self.rule == "HGNC.resolve.2":  # 不改变历史版本含义。
            return found  # 原字段和原算法完全保留。
        require(self.rule == "HGNC.resolve.3", "不支持的身份映射规则")  # 未知版本不能默认运行。
        found["mapping_rule"] = self.rule  # 新结果绑定新规则。
        found["evidence_snapshot"] = self.supplement.digest if self.supplement else ""  # 补充来源单独追溯。
        approved = self.index[("symbol", found["raw_symbol"])]  # 现行标准名精确核对。
        typed = found["raw_id"].startswith(("HGNC:", "ENSG", "NCBIGene:", "GeneID:")) or bool(found["raw_uniprot"])  # 数据库自身条目号不作基因编号。
        if len(approved) == 1 and not typed:  # 用户批准：无稳定编号反证时现行标准名优先。
            found.update(self.records[next(iter(approved))], status="matched", mapping_method="approved_symbol_priority")  # 不丢弃原候选集合。
        if self.supplement and (found["status"] != "matched" or found["raw_id"].startswith(("NCBIGene:", "GeneID:"))):  # 不忽略明确NCBI编号冲突。
            found = self.supplement.resolve(found, self)  # 本地官方证据分层核对，不依赖实时网络。
        if self.supplement and found["status"] != "matched":  # 官方历史查询用于解释剩余问题。
            found = self.supplement.resolve_queries(found, self)  # 不借此自动裁决一对多。
        return found  # 正常和异常都带版本与依据。

def load_snapshot(root):  # 仅加载明确固定版本，禁止按修改时间猜最新版。
    meta = json.loads((root / "references/hgnc_complete_set_20260913.json").read_text(encoding="utf-8"))  # 固定来源清单。
    raw = (root / "references/hgnc_complete_set_20260913.tsv").read_bytes()  # 固定文件位置。
    require(len(raw) == meta["bytes"] and hashlib.sha256(raw).hexdigest() == meta["sha256"], "HGNC文件与来源指纹不一致")  # 变动时停止。
    from identity_sources import load_supplement  # 补充证据按固定清单读取。
    supplement, evidence_meta = load_supplement(root)  # 文件缺失或指纹错误须明确失败。
    meta["identity_evidence"] = evidence_meta  # 发布时归档同一证据包。
    return HgncMap(raw, supplement=supplement), meta  # A01/A02共用同一对象与指纹。

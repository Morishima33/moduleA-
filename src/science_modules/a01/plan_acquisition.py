"""新方案来源获取：TCMSP查询及筛选使用相同OB/DL，同研究绑定独立缓存。"""

import html
import re
from pathlib import Path
from types import FunctionType
import urllib.parse

from contracts import fingerprint, require, safe_id
from storage import read_json, within, write_json, write_lock
from . import acquisition as legacy
from .plan_screening import screening_parameters

VERSION = "A01.plan_acquisition.1"


def _tcmsp(fetch, herbs, progress, parameters):
    """沿用官方完整表和唯一人类映射，按本方案门槛决定需补查的原始靶点。"""
    from components import number
    page = fetch.get(legacy.TCMSP + "tcmsp.php").decode("utf-8")
    token = re.search(r'name="token"\s+value="([A-Za-z0-9]+)"', page)
    require(token is not None, "TCMSP官方入口需登录或页面已改变，请使用原始文件上传")
    output, counts, target_cache = [], {}, {}
    for herb in herbs:
        search = fetch.get(legacy.TCMSP + "tcmspsearch.php?" + urllib.parse.urlencode({"qs": "herb_all_name", "q": herb, "token": token[1]}))
        choices = [r for group in legacy._arrays(search) for r in group if isinstance(r, dict) and r.get("herb_cn_name") == herb]
        require(len(choices) == 1 and choices[0].get("herb_en_name"), "TCMSP未找到唯一精确药味：" + herb)
        raw = fetch.get(legacy.TCMSP + "tcmspsearch.php?" + urllib.parse.urlencode({"qr": choices[0]["herb_en_name"], "qsr": "herb_en_name", "token": token[1]}))
        arrays = legacy._arrays(raw)
        compounds = [r for group in arrays for r in group if isinstance(r, dict) and {"MOL_ID", "ob", "dl"} <= r.keys()]
        relations = [r for group in arrays for r in group if isinstance(r, dict) and {"MOL_ID", "target_ID", "target_name"} <= r.keys()]
        require(compounds and relations, "TCMSP完整成分或靶点表未取得，不能宣称完整零结果")
        require(len({r["MOL_ID"] for r in compounds}) == len(compounds), "TCMSP成分表重复或分页异常")
        by_compound = {}
        for relation in relations:
            by_compound.setdefault(relation["MOL_ID"], []).append(relation)
        start = len(output)
        for compound in compounds:
            cid = compound["MOL_ID"]
            require(re.fullmatch(r"MOL\d+", cid), "TCMSP分子编号异常")
            ob, dl = number(compound["ob"]), number(compound["dl"])
            qualified = ob is not None and dl is not None and ob >= parameters["ob_min"] and dl >= parameters["dl_min"]
            for relation in by_compound.get(cid, [{}]):
                tid, name = relation.get("target_ID", ""), relation.get("target_name", "")
                identity = ("", "", "")
                if tid and name and qualified:
                    if progress:
                        progress("TCMSP按方案核对原始靶点：" + name)
                    if (tid, name) not in target_cache:
                        raw_target = fetch.get(legacy.TCMSP + "target.php?" + urllib.parse.urlencode({"qt": tid}))
                        target_text = html.unescape(re.sub(r"<[^>]+>", " ", raw_target.decode("utf-8")))
                        require(" ".join(name.split()) in " ".join(target_text.split()), "TCMSP靶点详情身份不一致")
                        target_cache[tid, name] = legacy._human_target(fetch, name)
                    identity = target_cache[tid, name]
                output.append([herb, cid, compound["molecule_name"], compound["ob"], compound["dl"], *identity, tid, name])
        counts[herb] = len(output) - start
    files = {"references/tcmsp_snapshot.tsv": legacy._table([
        ["Chinesename", "MOLID", "moleculename", "ob", "dl", "UniProtAC", "GeneNames", "Organism", "raw_target_id", "raw_target_name"], *output])}
    return files, counts, {"encoding": "utf-8-sig", "screening_parameters": parameters, "acquisition_protocol": VERSION}


def acquire_for_plan(database, herbs, folder, binding, plan, progress=None, opener=None, sleeper=None):
    """调用原包装及请求校验器；缓存绑定研究、输入和相关门槛，不跨研究借用。"""
    parameters = screening_parameters(plan)
    require(database in ("TCMSP", "HERB", "BATMAN"), "采集数据库无效")
    require(isinstance(herbs, list) and herbs and all(isinstance(h, str) and h.strip() and len(h) <= 2000 for h in herbs)
            and len(herbs) == len(set(herbs)), "采集药味清单无效")
    require(isinstance(binding, dict) and set(binding) == {"study_id", "a00_run", "a01_run"}, "来源获取缺少本研究输入绑定")
    safe_id(binding["study_id"], "study")
    safe_id(binding["a00_run"], "run")
    require(isinstance(binding["a01_run"], str), "A01来源版本格式无效")
    if binding["a01_run"]:
        safe_id(binding["a01_run"], "run")
    context = {"schema_version": VERSION, "binding": binding, "database": database, "herbs": herbs,
               "screening_parameters": parameters if database == "TCMSP" else None}
    key = fingerprint(context)
    home = Path(folder).resolve()
    work = within(home, "plan_source_" + key)
    work.mkdir(parents=True, exist_ok=True)
    with write_lock(work):
        record = work / "plan_source_binding.json"
        if record.exists():
            require(read_json(record) == context, "来源缓存研究或参数绑定改变")
        else:
            write_json(record, context)
        # 只绑定这一次调用的TCMSP采集器，旧采集函数和HERB/BATMAN规则均保持。
        def collect(fetch, names, report):
            return _tcmsp(fetch, names, report, parameters)
        namespace = dict(vars(legacy), _tcmsp=collect)
        acquire = FunctionType(legacy.acquire.__code__, namespace, legacy.acquire.__name__, legacy.acquire.__defaults__, legacy.acquire.__closure__)
        result = acquire(database, herbs, work, progress=progress,
                         opener=opener or legacy.urllib.request.urlopen, sleeper=sleeper or legacy.time.sleep)
        return dict(result, version=VERSION, analysis_plan_source={"binding_hash": key, **context})

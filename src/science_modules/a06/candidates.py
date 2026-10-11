"""按已确认A04第二轮名单生成两梯队，不重新计算网络指标。"""
from copy import deepcopy
import math
import re
from contracts import require
from science_modules.a04.selection import boundary_top, ranked

VERSION = "A06.candidate_groups.1"
RULE = "A组＝Degree第二轮前十∩BC＋CC第二轮前十五；B组＝Degree第二轮前十五去除A组。各窗口保留边界并列，重复优先A。"
NOTE = "A/B为本项目对接候选证据分组，不代表临床证据等级；结构质控须独立核查。"

# 每份表只能包含唯一HGNC身份及完整网络的有效指标。
def checked(rows):
    require(isinstance(rows,list),"缺少A04第二轮名单")
    seen=set()
    for row in rows:
        identity=row.get("target_id")
        require(isinstance(identity,str) and re.fullmatch(r"HGNC:[0-9]+",identity),"候选缺少有效HGNC编号")
        require(identity not in seen,"候选HGNC身份重复")
        seen.add(identity)
        require(isinstance(row.get("symbol"),str) and row["symbol"].strip(),"候选基因名缺失")
        for key in ("degree","bc","cc"):
            value=row.get(key)
            require(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0,"候选指标缺失或无效："+key)
    return deepcopy(rows)

# HGNC相交；第十五个位置的并列全部保留，不以竞争名次补名额。
def build(tables):
    degree=ranked(checked(tables.get("degree_round2")),"degree",True)
    top10=boundary_top(degree,10,"degree")
    archived_top=checked(tables.get("degree_top10"))
    require({r["target_id"] for r in top10}=={r["target_id"] for r in archived_top},"第二轮Degree前十与归档不一致")
    by_id={r["target_id"]:r for r in degree}
    require(all(all(r[k]==by_id[r["target_id"]][k] for k in ("degree","bc","cc")) for r in archived_top),"归档Degree指标不一致")
    bc_top=checked(tables.get("bc_cc_top15"))
    require(all(all(r[k]==by_id[r["target_id"]][k] for k in ("degree","bc","cc")) for r in bc_top if r["target_id"] in by_id),"两分支指标不一致")
    a_ids={r["target_id"] for r in top10}&{r["target_id"] for r in bc_top}
    top15=boundary_top(degree,15,"degree")
    a=[dict(r,evidence_group="A") for r in top10 if r["target_id"] in a_ids]
    b=[dict(r,evidence_group="B") for r in top15 if r["target_id"] not in a_ids]
    return {"schema_version":VERSION,"rule_zh":RULE,"note_zh":NOTE,"degree_top15":top15,"group_a":a,"group_b":b,
            "counts":{"degree_top10":len(top10),"bc_cc_top15":len(bc_top),"degree_top15":len(top15),"a":len(a),"b":len(b)}}

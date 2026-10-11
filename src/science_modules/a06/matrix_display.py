"""同批对接结果的展示裁切；不计算结合能，不复用不匹配的历史结果。"""
from copy import deepcopy
from contracts import require
from .two_pass import validate_result

VERSION="A06.matrix.display.1"

# 展示配置来自研究决定，重复、越界或空维度均不能悄悄补足。
def check_display(config,compounds,receptors):
    require(config.get("version")==VERSION,"矩阵展示规则版本不匹配")
    cids=[r["compound_id"] for r in compounds];tids=[r["target_id"] for r in receptors]
    require(len(cids)==len(set(cids)) and len(tids)==len(set(tids)),"完整候选名单有重复")
    for key,pool in (("heatmap_compounds",cids),("table_compounds",cids),("heatmap_targets",tids),("table_targets",tids)):
        rows=config.get(key)
        require(isinstance(rows,list) and rows and len(rows)==len(set(rows)) and set(rows)<=set(pool),"展示名单重复、空或超出完整范围："+key)
    require(set(config["heatmap_compounds"])<=set(config["table_compounds"]) and set(config["heatmap_targets"])<=set(config["table_targets"]),"热图须来自同一表格对象集合")
    return True

# 固定单蓝渐变；上下界来自同批完整结果，恒值仍使用统一中间色。
def blue(score,low,high):
    fraction=(high-score)/(high-low) if high!=low else .5
    light=(239,246,255);dark=(8,81,156)
    return "#"+"".join(f"{round(a+(b-a)*fraction):02x}" for a,b in zip(light,dark))

# 全矩阵结果先通过科学结果契约，再裁切两个视图；原行和版本保持。
def matrix_view(config,compounds,receptors,packet=None,prep=None,root=None,expected_source=None):
    check_display(config,compounds,receptors)
    cmap={r["compound_id"]:r for r in compounds};rmap={r["target_id"]:r for r in receptors}
    out={"ready":False,"status_zh":"待计算：本轮无已核验的真实评分","full_pair_count":len(compounds)*len(receptors),"score_range":None,"result_version":None}
    pairs={}
    quality={}
    if packet is not None:
        require(prep is not None and expected_source and prep.get("source_key")==expected_source,"矩阵准备来源与当前批准来源不同")
        require([r["compound_id"] for r in prep["compounds"]]==list(cmap) and {r["target_id"] for r in prep["receptors"]}==set(rmap),"结果范围与本轮完整名单不符")
        validate_result(packet,prep,root)
        pairs={(r["compound_id"],r["target_id"]):r for r in packet["pairs"]}
        scores=[r["score"] for r in packet["pairs"] if r["state"]=="completed"]
        low,high=(min(scores),max(scores)) if scores else (None,None)
        out.update(ready=True,status_zh="本轮同源Top-1结果；NA保留",score_range=[low,high],result_version=packet["input_key"])
        quality={r["target_id"]:r.get("quality","NA") for r in prep["receptors"]}
    for name in ("heatmap","table"):
        cs=config[name+"_compounds"];ts=config[name+"_targets"]
        view={"rows":[deepcopy(cmap[c]) for c in cs],"columns":[{**deepcopy(rmap[t]),"quality_zh":quality.get(t,"待质控")} for t in ts],"cells":[]}
        if packet is not None:
            for c in cs:
                line=[]
                for t in ts:
                    r=pairs[(c,t)]
                    line.append({"compound_id":c,"target_id":t,"state":r["state"],"score":r.get("score"),"reason_zh":r.get("reason_zh",""),"color":blue(r["score"],low,high) if r["state"]=="completed" else "#DCE1E5","text_color":"#FFFFFF" if r["state"]=="completed" and high!=low and (high-r["score"])/(high-low)>.6 else "#10253C"})
                view["cells"].append(line)
        out[name]=view
    return out

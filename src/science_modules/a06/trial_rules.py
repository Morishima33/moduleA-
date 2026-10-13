"""独立全覆盖试算规则；不修改严格质控、科学批准或历史评分。"""

import hashlib
import itertools
import json
import math

VERSION = "A06.full_coverage_trial.1"
VINA = {
    "scoring": "vina",
    "exhaustiveness": 8,
    "num_modes": 9,
    "energy_range": 3,
    "seed": 1,
    "version": "1.2.7",
}
PALETTE = {"weak": "#A7D5E5", "strong": "#B7326B", "NA": "#DCE1E5"}


def fingerprint(value):
    """所有准备、区域和缓存均按实际输入生成指纹。"""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def inside(point, box):
    """检查一个原子是否在搜索盒中，包括盒边界。"""
    return all(
        abs(p - c) <= s / 2 + 1e-7 for p, c, s in zip(point, box["center"], box["size"])
    )


def partitions(points, width=30.0, step=15.0, padding=5.0):
    """覆盖重原子包络及外围，移除无蛋白原子的空盒，验证全体原子覆盖。"""
    if not points or not all(
        len(p) == 3 and all(math.isfinite(v) for v in p) for p in points
    ):
        raise ValueError("分区需要真实有限重原子坐标")
    if not 0 < step <= width or padding < 0:
        raise ValueError("分区步长或外扩值非法")
    axes = []
    for axis in range(3):
        low = min(p[axis] for p in points) - padding
        high = max(p[axis] for p in points) + padding
        count = max(1, math.ceil((high - low - width) / step) + 1)
        axes.append([low + width / 2 + i * step for i in range(count)])
    boxes = []
    for center in itertools.product(*axes):
        box = {"center": list(center), "size": [width] * 3}
        if any(inside(p, box) for p in points):
            box["region_id"] = f"region_{len(boxes) + 1:04d}"
            boxes.append(box)
    if not all(any(inside(p, b) for b in boxes) for p in points):
        raise ValueError("搜索分区未覆盖全部蛋白重原子")
    return boxes


def choose_score(regions, mode):
    """固定位点只接受唯一预选区域；预测或盲搜取有效区域Top-1最低值。"""
    if mode not in {"fixed_site", "predicted_sites", "partitioned_blind"}:
        raise ValueError("未知评分来源")
    if mode == "fixed_site" and len(regions) > 1:
        raise ValueError("固定位点不能按成分评分更换区域")
    valid = [
        r
        for r in regions
        if r.get("state") == "completed"
        and isinstance(r.get("score"), (int, float))
        and not isinstance(r["score"], bool)
        and math.isfinite(r["score"])
    ]
    if not valid:
        return None
    return min(valid, key=lambda r: (r["score"], r["region_id"]))


def validate_matrix(packet):
    """十五项与十五受体的225个唯一组合不得因失败减少。"""
    compounds = [c["compound_id"] for c in packet["compounds"]]
    targets = [r["target_id"] for r in packet["receptors"]]
    if (
        len(compounds) != 15
        or len(set(compounds)) != 15
        or len(targets) != 15
        or len(set(targets)) != 15
    ):
        raise ValueError("试算范围必须为已确认的15×15")
    expected = set(itertools.product(compounds, targets))
    actual = [(p["compound_id"], p["target_id"]) for p in packet["pairs"]]
    if len(actual) != 225 or set(actual) != expected:
        raise ValueError("试算组合有缺失、重复或额外对象")
    for p in packet["pairs"]:
        best = choose_score(p.get("regions", []), p["mode"])
        if p["state"] == "completed":
            if (
                best is None
                or p["score"] != best["score"]
                or p["selected_region_id"] != best["region_id"]
            ):
                raise ValueError("评分与实际区域Top-1不一致")
        elif p["state"] == "NA":
            if p.get("score") is not None or not p.get("reason_zh"):
                raise ValueError("NA须无评分且记录原因")
        else:
            raise ValueError("完成包不能包含待计算格")
    return True

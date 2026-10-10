"""身份应用测试使用独立虚构研究与官方响应格式夹具，不引用真实病例。"""

from pathlib import Path
import hashlib
import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from modulea.core.identity_workflow import IdentityWorkflow
from science_modules.a04 import flow_v3, identity_flow
from storage import read_json

RAW = b"hgnc_id\tsymbol\tprev_symbol\tuniprot_ids\tensembl_gene_id\nHGNC:1\tTESTA\tOLDA\tTEST_UNIPROT\tTEST_ENSEMBL\nHGNC:2\tTESTB0\tOLDB\tTEST_UP2\tTEST_EN2\n"
SHA = hashlib.sha256(RAW).hexdigest()
TARGETS = [{"target_id": "HGNC:1", "symbol": "TESTA"}] + [
    {"target_id": f"HGNC:{i + 2}", "symbol": f"TESTB{i}"} for i in range(7)
]


# 各测试明确注入合成快照指纹；生产实现仍固定真实官方快照。
@contextmanager
def synthetic_snapshot():
    with ExitStack() as stack:
        stack.enter_context(patch("ppi_identity.SNAPSHOT", SHA))
        stack.enter_context(patch("ppi_flow.SNAPSHOT", SHA))
        stack.enter_context(patch("science_modules.a04.identity_flow.SNAPSHOT", SHA))
        stack.enter_context(patch("science_modules.a04.flow_v3.SNAPSHOT", SHA))
        yield


# STRING名称返回旧名但同一稳定蛋白编号，补查两种编号均一致才可派生现名。
def official_response(method, params, conflict=False, empty=False):
    if method == "network":
        data = [
            {
                "stringId_A": "9606.TEST0",
                "stringId_B": f"9606.TEST{i}",
                "ncbiTaxonId": 9606,
                "score": 0.95,
            }
            for i in range(1, 8)
            if "9606.TEST0" in params["identifiers"].split("\r")
            and f"9606.TEST{i}" in params["identifiers"].split("\r")
        ]
    elif params["identifiers"] in ("TEST_UNIPROT", "TEST_ENSEMBL", "TEST_UP2", "TEST_EN2"):
        data = (
            []
            if empty
            else [
                {
                    "queryIndex": 0,
                    "queryItem": params["identifiers"],
                    "ncbiTaxonId": 9606,
                    "preferredName": "OLDB"
                    if params["identifiers"] in ("TEST_UP2", "TEST_EN2")
                    else "OLDA",
                    "stringId": "9606.TEST1"
                    if params["identifiers"] in ("TEST_UP2", "TEST_EN2")
                    else "9606.TEST0",
                }
            ]
        )
    else:
        data = [
            {
                "queryIndex": i,
                "queryItem": row["symbol"],
                "ncbiTaxonId": 9606,
                "preferredName": "OLDA" if i == 0 else row["symbol"],
                "stringId": "9606.CONFLICT" if i == 0 and conflict else f"9606.TEST{i}",
            }
            for i, row in enumerate(TARGETS)
        ]
    return {
        "url": "https://version-12-0.string-db.org/api/json/" + method,
        "params": params,
        "retrieved_at": "2026-10-10T00:00:00+00:00",
        "response_text": json.dumps(data),
    }


# 初始名称不一致且无稳定编号证据，必须真实处于待核验，不能事先已通过。
def seed(root, two_issues=False):
    root = Path(root)
    w = IdentityWorkflow(root, {"A04": identity_flow.validator(root)})
    sid = w.create(
        {
            "formula": "虚构测试方",
            "herbs": "虚构测试药",
            "disease": "虚构测试病",
            "disease_scope": "仅测试",
            "operator": "模拟测试",
            "species": 9606,
            "analysis_purpose": "workflow_test",
        },
        kind="contract_test",
    )
    w.review(sid, w.load(sid)["current"]["A00"], "approved", "模拟测试", "合成输入")
    for mid in ("A01", "A02", "A03"):
        run = w.begin(sid, mid, {}, {}, "合成输入")
        w.finish(
            sid,
            run["run_id"],
            {"analysis_purpose": "workflow_test"},
            {"intersection_targets": TARGETS} if mid == "A03" else {},
        )
        w.review(sid, run["run_id"], "approved", "模拟测试", "合成输入")
    a03 = w.load(sid)["current"]["A03"]
    mapping = official_response(
        "get_string_ids",
        {
            "identifiers": "\r".join(r["symbol"] for r in TARGETS),
            "species": 9606,
            "echo_query": 1,
            "caller_identity": "ModuleA",
        },
    )
    if two_issues:
        records = json.loads(mapping["response_text"])
        records[1]["preferredName"] = "OLDB"
        mapping["response_text"] = json.dumps(records)
    from ppi_flow import mapped_ids

    initial_ids = mapped_ids(TARGETS, json.loads(mapping["response_text"]))
    network = official_response(
        "network",
        {
            "identifiers": "\r".join(initial_ids),
            "species": 9606,
            "required_score": 900,
            "network_type": "functional",
            "add_nodes": 0,
            "caller_identity": "ModuleA",
        },
    )
    network["response_text"] = "[]"
    result = flow_v3.run_ppi(
        w,
        sid,
        a03,
        "",
        "合成名称身份问题",
        {
            "schema_version": "A04.source.1",
            "string_version": "12.0",
            "mapping": mapping,
            "network": network,
        },
    )
    path = root / "references/hgnc_complete_set_20260913.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(RAW)
    payload = {
        "expected_a03": a03,
        "expected_a04": result["run_id"],
        "expected_decision_id": None,
        "reviewer": "模拟核验人",
        "note": "仅合成测试：两类官方编号一致时应用，不批准模块",
        "check_ids": ["HGNC:1"],
        "omit_ids": [],
        "confirmed": True,
        "decision_id": "decision_" + "1" * 32,
    }
    return w, sid, payload

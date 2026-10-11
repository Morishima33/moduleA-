"""虚构研究验证两梯队边界、身份、留存及真实HTTP后台链，不调用科学网络。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import threading
import time
import json
import sys
from uuid import uuid4
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from modulea.core.docking_workflow import DockingWorkflow, candidate_context
from modulea.config import Settings
from modulea.api.server import create_server
from science_modules.a06.candidates import build
from science_modules.a04.selection import ranked, boundary_top
from contracts import ContractError
from storage import read_json

# 模拟第十、第十五位置并列，真实身份按HGNC而非显示名称。
def tables():
    degrees=[30,29,28,27,26,25,24,23,22,21,21,20,19,18,17,17,16]
    rows=[{"target_id":"HGNC:"+str(i),"symbol":"TEST"+str(i),"degree":d,"bc":100-i,"cc":0.5} for i,d in enumerate(degrees,1)]
    ordered=ranked(rows,"degree",True)
    return {"degree_round2":ordered,"degree_top10":boundary_top(ordered,10,"degree"),"bc_cc_top15":[deepcopy(rows[i]) for i in (0,2,10,16)]}

# 使用生产Workflow建立独立契约研究，全部审批明确标为测试。
def fixture(root):
    flow=DockingWorkflow(root)
    sid=flow.create({"formula":"虚构方","herbs":"虚构药","disease":"虚构病","disease_scope":"契约测试","operator":"测试","species":9606,"analysis_purpose":"workflow_test"},kind="contract_test")
    flow.review(sid,flow.load(sid)["current"]["A00"],"approved","测试","不作为科研结论")
    for mid in ("A01","A02","A03","A04"):
        run=flow.begin(sid,mid,{},{},"虚构上游")
        flow.finish(sid,run["run_id"],{"docking_candidate_source_pending":True} if mid=="A04" else {},tables() if mid=="A04" else {},[],"success")
        flow.review(sid,run["run_id"],"approved","测试","虚构契约")
    return flow,sid

class CandidateTests(unittest.TestCase):
    def test_current_source_notice_uses_archive_only(self):
        from modulea.api.views import apply_candidate_context
        parts={"focus":[{"title_zh":"对接候选来源待确认"},{"title_zh":"其他事项"}],"special":{"ppi_dual":{"network_note_zh":"圆形图；对接候选另行确认。"}}}
        original=deepcopy(parts)
        apply_candidate_context(parts,None)
        self.assertEqual(parts,original)
        apply_candidate_context(parts,{"data":{"group_id":"已核验分组"}})
        self.assertEqual(parts["focus"],[{"title_zh":"其他事项"}])
        self.assertIn("结构质控",parts["special"]["ppi_dual"]["network_note_zh"])

    def test_ties_identity_and_precedence(self):
        source=tables(); original=deepcopy(source)
        # 名称变化不影响同一HGNC相交。
        source["bc_cc_top15"][0]["symbol"]="ALIASTEST"
        data=build(source)
        self.assertEqual(data["counts"],{"degree_top10":11,"bc_cc_top15":4,"degree_top15":16,"a":3,"b":13})
        self.assertEqual({r["target_id"] for r in data["group_a"]},{"HGNC:1","HGNC:3","HGNC:11"})
        self.assertFalse({r["target_id"] for r in data["group_a"]}&{r["target_id"] for r in data["group_b"]})
        self.assertNotIn("qc_status",data["group_a"][0])
        source["bc_cc_top15"][0]["symbol"]=original["bc_cc_top15"][0]["symbol"]
        self.assertEqual(source,original)

    def test_all_tied_and_empty_intersection_keep_real_counts(self):
        source=tables()
        for row in source["degree_round2"]: row["degree"]=30
        source["degree_top10"]=deepcopy(source["degree_round2"])
        source["bc_cc_top15"]=deepcopy(source["degree_round2"])
        data=build(source)
        self.assertEqual(data["counts"]["a"],17)
        self.assertEqual(data["counts"]["b"],0)
        source["bc_cc_top15"]=[]
        data=build(source)
        self.assertEqual(data["counts"]["a"],0)
        self.assertEqual(data["counts"]["b"],17)

    def test_empty_and_small_actual_counts(self):
        self.assertEqual(build({"degree_round2":[],"degree_top10":[],"bc_cc_top15":[]})["counts"]["a"],0)
        small={k:v[:2] for k,v in tables().items()}
        small["bc_cc_top15"]=[]
        self.assertEqual(build(small)["counts"]["b"],2)

    def test_invalid_metrics_or_archive_not_silently_used(self):
        for mutate in ("duplicate","metric","archive"):
            source=tables()
            if mutate=="duplicate": source["degree_round2"].append(deepcopy(source["degree_round2"][0]))
            if mutate=="metric": source["degree_round2"][0]["bc"]=float("nan")
            if mutate=="archive": source["degree_top10"].pop()
            with self.assertRaises(ContractError): build(source)

    def test_versioned_archive_retry_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,sid=fixture(Path(tmp)); before=flow.load(sid)
            binding=flow.candidate_binding(before); request={**binding,"group_id":"group_"+uuid4().hex,"reason":"测试"}
            data=flow.generate_candidates(sid,request)
            self.assertEqual(flow.generate_candidates(sid,request),data)
            after=flow.load(sid)
            self.assertEqual(len(after["docking_candidate_records"]),1)
            for key in ("runs","current","reviews"): self.assertEqual(after[key],before[key])
            self.assertEqual(candidate_context(flow,after)["data"],data)
            self.assertIsNone(candidate_context(flow,after,True))
            self.assertIsNotNone(candidate_context(flow,after,busy=True)["data"])
            self.assertFalse(candidate_context(flow,after,busy=True)["enabled"])
            with self.assertRaises(ContractError): flow.generate_candidates(sid,{**request,"reason":"改写重试"})
            # A04重签后旧分组失效，不能因为运行号相同就沿用。
            a04=after["current"]["A04"]
            flow.review(sid,a04,"approved","测试","再次复核",binding["expected_a04_review"])
            self.assertIsNone(candidate_context(flow,flow.load(sid))["data"])
            with self.assertRaises(ContractError): flow.generate_candidates(sid,request)

    def test_trash_and_cross_study_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,sid=fixture(Path(tmp)); binding=flow.candidate_binding(flow.load(sid))
            _,other=fixture(Path(tmp))
            req={**binding,"group_id":"group_"+uuid4().hex,"reason":"测试"}
            with self.assertRaises(ContractError): flow.generate_candidates(other,req)
            manifest=flow.load(sid);manifest["trashed"]=True;flow.save(manifest)
            with self.assertRaises(ContractError): flow.generate_candidates(sid,req)

    def test_continue_stops_at_new_structure_gate_without_old_prep(self):
        from unittest.mock import patch, Mock
        from types import SimpleNamespace
        from modulea.tasks.worker import run_continue
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);flow,sid=fixture(root)
            a05=flow.begin(sid,"A05",{},{},"虚构富集")
            flow.finish(sid,a05["run_id"],{}, {},[],"success")
            flow.review(sid,a05["run_id"],"approved","测试","虚构")
            request={**flow.candidate_binding(flow.load(sid)),"group_id":"group_"+uuid4().hex,"reason":"测试"}
            flow.generate_candidates(sid,request)
            with patch("modulea.tasks.worker.full_workflow",return_value=flow), patch("science_modules.a05.compact_flow.run_enrichment") as enrichment, patch("auto_continue.continue_after_review") as old_continue:
                result=run_continue(Settings(data_root=root),{"task_id":"测试任务","study_id":sid},SimpleNamespace(update=Mock()))
            self.assertIn("两梯队候选已归档",result)
            self.assertIn("未启动A06",result)
            enrichment.assert_not_called();old_continue.assert_not_called()
            self.assertNotIn("A06_PREP",flow.load(sid)["current"])

    def test_http_background_archive_and_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);flow,sid=fixture(root)
            settings=Settings(data_root=root,runtime_dir=root/"runtime",science_python=sys.executable)
            server,app=create_server(settings,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base="http://127.0.0.1:"+str(server.server_port)
            def call(path,body=None,token=True):
                headers={"Origin":base}
                if token: headers["X-ModuleA-Token"]=app.token
                if body is not None: headers["Content-Type"]="application/json"
                with urlopen(Request(base+"/api/v1"+path,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=30) as res:
                    return res.status,json.load(res)
            endpoint="/studies/"+sid+"/modules/A04"
            try:
                _,view=call(endpoint);info=view["docking_candidates"]
                payload={k:info[k] for k in ("expected_a03","expected_a04","expected_a04_review")};payload["reason"]="测试真实后台链"
                with self.assertRaises(HTTPError) as denial: call(endpoint+"/actions/docking_candidates",payload,False)
                self.assertEqual(denial.exception.code,403)
                with self.assertRaises(HTTPError) as denial: call(endpoint+"/actions/docking_candidates",{**payload,"expected_a04":"run_"+uuid4().hex})
                self.assertEqual(denial.exception.code,409)
                status,response=call(endpoint+"/actions/docking_candidates",payload)
                self.assertEqual(status,202)
                tid=response["task"]["task_id"]
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    _,task=call("/tasks/"+tid)
                    if task["state"] not in ("queued","running"): break
                    time.sleep(.1)
                self.assertEqual(task["state"],"succeeded",task)
                _,view=call(endpoint);groups=view["docking_candidates"]["data"]
                self.assertEqual(groups["counts"]["a"],3)
                _,prep=call("/studies/"+sid+"/modules/A06_PREP")
                self.assertEqual(prep["docking_candidates"]["data"],groups)
                _,download=call("/studies/"+sid+"/docking_candidates/"+groups["group_id"])
                self.assertEqual(download["group_a"],groups["group_a"])
                with self.assertRaises(HTTPError) as denial: call("/studies/"+sid+"/docking_candidates/group_"+uuid4().hex)
                self.assertEqual(denial.exception.code,404)
                self.assertNotIn("A06",read_json(root/"studies"/sid/"manifest.json")["current"])
            finally:
                server.shutdown();server.server_close();thread.join()

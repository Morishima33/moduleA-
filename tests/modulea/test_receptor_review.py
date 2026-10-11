"""受体摘要留存、上游失效与身份冲突保护：全部使用隔离虚构研究。"""
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from contracts import ContractError
from storage import read_json,verified_file
from tests.modulea.test_two_pass import fixture
from science_modules.a06.plan_adapter import source_context
from modulea.core.two_pass_workflow import preparation_context

# 合成摘要只有官方链接形式，没有真实结构或科学评分。
def packet(f,sid):
    m=f.load(sid);c=source_context(f,sid,m)
    rows=[{**r,"uniprot":"P12345","identity_url":"https://www.uniprot.org/uniprotkb/P12345/entry","current_qc_zh":"尚未准备或质控","candidates":[{"url":"https://www.rcsb.org/structure/1ABC","target_chains":[{"chains":["A"],"length":10}],"ligands":[]}],"historical":None} for r in c["receptors"]]
    return {"schema_version":"A06.receptor_review.1","study_id":sid,"source_key":c["source_key"],"execution_allowed":False,"approval":None,"note_zh":"虚构资料，不计算","receptors":rows,"compounds":[{**r,"identity_prechecked":True,"source_3d_evidence":[]} for r in c["compounds"]],"evidence":[{"url":"https://data.rcsb.org/graphql","response":{"virtual":True}}],"historical_result_file":m["runs"][m["current"]["A00"]]["result_file"]}

class ReceptorReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.f,self.sid=fixture(Path(self.tmp.name));self.p=packet(self.f,self.sid)
    def tearDown(self):self.tmp.cleanup()
    def test_append_preserves_runs_and_reviews_and_never_executes(self):
        before=self.f.load(self.sid);d=self.f.save_receptor_review(self.sid,self.p);after=self.f.load(self.sid)
        for key in ("current","runs","reviews"):self.assertEqual(before[key],after[key])
        self.assertFalse(d["execution_allowed"]);self.assertIsNone(d["approval"])
        self.assertEqual(preparation_context(self.f,after)["metadata_review"]["review_id"],d["review_id"])
        self.assertEqual(read_json(verified_file(self.f.location(self.sid),after["receptor_review_records"][-1]))["receptors"],self.p["receptors"])
    def test_rejects_conflict_other_study_stale_scope_and_execution(self):
        cases=[]
        for key,value in (("study_id","study_other"),("source_key","old"),("execution_allowed",True),("approval","approved")):
            p=deepcopy(self.p);p[key]=value;cases.append(p)
        for change in ("missing","grade","identity","qc","history","source"):
            p=deepcopy(self.p)
            if change=="missing":p["receptors"].pop()
            if change=="grade":p["receptors"][0]["candidate_grade"]="B"
            if change=="identity":p["compounds"][0]["identity_prechecked"]=False
            if change=="qc":p["receptors"][0]["current_qc_zh"]="严格质控通过"
            if change=="history":p["receptors"][0]["historical"]={"current_passed":True}
            if change=="source":p["evidence"][0]["url"]="https://untrusted.invalid/api"
            cases.append(p)
        for p in cases:
            with self.subTest(payload=p):
                with self.assertRaises(ContractError):self.f.save_receptor_review(self.sid,p)
        self.assertNotIn("receptor_review_records",self.f.load(self.sid))
    def test_new_review_invalidates_old_metadata_and_trash_is_readonly(self):
        self.f.save_receptor_review(self.sid,self.p);m=self.f.load(self.sid)
        self.f.review(self.sid,m["current"]["A03_SELECT"],"approved","隔离复核","重签测试",expected_review=self.f.latest_review(m,self.f.run(m,m["current"]["A03_SELECT"])["artifact_id"])["review_id"])
        self.assertIsNone(preparation_context(self.f,self.f.load(self.sid))["metadata_review"])
        with self.assertRaises(ContractError):self.f.save_receptor_review(self.sid,self.p)
        self.f.set_trashed(self.sid,True,"测试","回收站只读")
        with self.assertRaises(ContractError):self.f.save_receptor_review(self.sid,packet(self.f,self.sid))
    def test_tamper_fails_loudly(self):
        self.f.save_receptor_review(self.sid,self.p);m=self.f.load(self.sid);record=m["receptor_review_records"][-1]
        (self.f.location(self.sid)/record["path"]).write_text("{}",encoding="utf-8")
        with self.assertRaises(ContractError):preparation_context(self.f,m)

if __name__=="__main__":unittest.main()

# PPI边界与网页验收只使用虚构数据。
import sys  # 引用项目。
import json  # 构造官方响应。
import tempfile  # 隔离研究。
import unittest  # 验证算法边界。
from pathlib import Path  # 固定位置。
from unittest.mock import patch  # 只替代网络。
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))  # 不引用旧项目。
from ppi import calculate  # 实际计算。
from ppi_flow import fetch,evaluate  # 实际来源解释。
from contracts import ContractError  # 检验阻断。

class PpiTests(unittest.TestCase):  # 两个星形分量可手算。
    def data(self):  # 两星形、一个孤立、一个未识别。
        t=[{"target_id":"HGNC:"+str(i+1),"symbol":"G"+str(i)} for i in range(12)]  # 虚构基因。
        m=[{"queryIndex":i,"ncbiTaxonId":9606,"preferredName":"G"+str(i),"stringId":"9606.p"+str(i)} for i in range(11)]  # 第12项未识别。
        e=[{"stringId_A":"9606.p"+str(c),"stringId_B":"9606.p"+str(j),"ncbiTaxonId":9606,"score":0.9} for c in (0,5) for j in range(c+1,c+5)]  # 八条边。
        return t,m,e  # 可独立复算。
    def test_components_rounds(self):  # 全分量、原网指标及严格不等号。
        s,t=calculate(*self.data())  # 实际函数。
        self.assertEqual([s[k] for k in ("参与节点数","孤立节点数","身份待核验数")],[10,1,1])  # 未识别不能当孤立。
        self.assertTrue(s["handoff_blocked"])  # 未授权自动排除。
        self.assertEqual(len(t["round1"]),2)  # 两星中心均入选。
        self.assertEqual(t["round2"],[])  # BC严格大于中位数，同分不通过。
        self.assertEqual(t["round1"][0]["bc"],6)  # 未归一化BC手算。
        self.assertAlmostEqual(t["round1"][0]["cc"],4/9)  # 全十节点WF修正。
    def test_empty_duplicate_external(self):  # 不凑数、不引入邻居。
        self.assertEqual(calculate([],[],[])[0]["参与节点数"],0)  # 空集正常。
        t,m,e=self.data()  # 固定来源。
        self.assertEqual(calculate(t,m,e+e)[0]["合格边数"],8)  # 重复不加Degree。
        with self.assertRaises(ContractError):  # 扩展节点必须拒绝。
            calculate(t,m,e+[dict(e[0],stringId_B="9606.extra")])  # 不静默截去。
        with self.assertRaises(ContractError):  # 分数尺度不能猜。
            calculate(t,m,[dict(e[0],score=900)])  # 官方JSON尺度为0至1。
    def test_single_node(self):  # 防止API单节点自动加邻居。
        t,m,e=self.data()  # 一个节点即可手算。
        def fake(method,params):  # 不访问真实服务器。
            self.assertEqual(method,"get_string_ids")  # 不得请求network扩展。
            return {"url":"https://version-12-0.string-db.org/api/json/"+method,"params":params,"retrieved_at":"test","response_text":json.dumps(m[:1])}  # 完整测试响应。
        with patch("ppi_flow.request",fake):  # 计算保持真实。
            b=fetch(t[:1])  # 生产获取入口。
        self.assertEqual(evaluate(t[:1],b,"workflow_test")[0]["孤立节点数"],1)  # 孤立正确保留。
    def test_identity_evidence_and_scope(self):  # 旧名恢复、已批准缺口及未知问题分开。
        import copy  # 构造损坏来源而不改原件。
        from ppi_identity import context, SCOPE  # 授权绑定生产规则。
        root=Path(__file__).resolve().parents[1]  # 仅读固定证据，不操作研究。
        raw=context(root,SCOPE["study_id"],SCOPE["a03_run"])  # 校验官方快照。
        self.assertIsNone(context(root,"other-study",SCOPE["a03_run"]))  # 不跨研究自动排除。
        self.assertIsNone(context(root,SCOPE["study_id"],"other-run"))  # 不跨上游自动排除。
        targets=[{"target_id":"HGNC:125","symbol":"ACP3"},{"target_id":"HGNC:12680","symbol":"VEGFA"},{"target_id":"HGNC:5525","symbol":"IGHG1"}]  # 三种已知问题。
        def row(index,name,sid,query):  # 合成官方格式。
            return {"queryIndex":index,"queryItem":query,"ncbiTaxonId":9606,"preferredName":name,"stringId":sid}  # 身份字段完整。
        def fake(method,params):  # 成功空结果与旧名一致结果。
            q=params["identifiers"]  # 每次查询明确编号。
            rows=[row(0,"ACPP","9606.acp","ACP3"),row(1,"COL18A1","9606.wrong","VEGFA")] if "\r" in q else ([row(0,"ACPP","9606.acp",q)] if q in ("P15309","ENSG00000014257") else [])  # 不把错误基因入网。
            return {"url":"https://version-12-0.string-db.org/api/json/"+method,"params":params,"retrieved_at":"test","response_text":json.dumps(rows)}  # 模拟成功响应。
        with patch("ppi_flow.request",fake),patch("ppi_flow.time.sleep"):  # 不联网或等待。
            bundle=fetch(targets,raw)  # 真实新版来源构造。
        summary,tables=evaluate(targets,bundle,"workflow_test",raw)  # 原数据独立复算。
        self.assertEqual(summary["本次PPI暂不采用数"],2)  # 明确缺口。
        self.assertEqual(summary["已识别数"],1)  # ACP3已恢复。
        self.assertEqual(summary["孤立节点数"],1)  # 排除两项不伪造Degree零。
        self.assertFalse(summary["handoff_blocked"])  # 只有批准缺口才解除身份阻断。
        self.assertEqual(tables["identity_adjustments"][0]["returned"],"ACPP")  # 旧名仍可追溯。
        self.assertIn("COL18A1",bundle["mapping"]["response_text"])  # 原始错误响应未被篡改。
        bad=copy.deepcopy(bundle)  # 错误授权不得接受。
        bad["identity_evidence"]["authorization"]["study_id"]="other"  # 模拟跨研究伪用。
        with self.assertRaises(ContractError):  # 不依赖来源包自我授权。
            evaluate(targets,bad,"workflow_test",raw)  # 验证拒绝。
        bad=copy.deepcopy(bundle)  # 一份补查缺失不能当空结果。
        bad["identity_evidence"]["queries"].pop()  # 移除必需证据。
        with self.assertRaises(ContractError):  # 完整性门控。
            evaluate(targets,bad,"workflow_test",raw)  # 不放行。
        bad=copy.deepcopy(bundle)  # 两个稳定编号冲突仍待处理。
        bad["identity_evidence"]["queries"][1]["source"]["response_text"]=json.dumps([row(0,"ACPP","9606.other","ENSG00000014257")])  # 不同蛋白编号。
        with self.assertRaises(ContractError):  # 身份改变后旧网络不可套用。
            evaluate(targets,bad,"workflow_test",raw)  # 拒绝冲突来源。

    def test_rhinitis_scope_is_independent(self):  # 新研究复用通用规则但不继承COPD专属授权。
        from ppi_identity import context, RHINITIS_SCOPE  # 使用当前研究明确批准的独立范围。
        root=Path(__file__).resolve().parents[1]  # 只读同一固定HGNC证据。
        raw=context(root,RHINITIS_SCOPE["study_id"],RHINITIS_SCOPE["a03_run"])  # 研究和A03必须同时匹配。
        targets=[{"target_id":"HGNC:125","symbol":"ACP3"},{"target_id":"HGNC:12680","symbol":"VEGFA"}]  # 本次实际两项问题。
        def row(index,name,sid,query):  # 构造STRING标准返回字段。
            return {"queryIndex":index,"queryItem":query,"ncbiTaxonId":9606,"preferredName":name,"stringId":sid}  # 身份字段完整。
        def fake(method,params):  # ACP3稳定编号一致，VEGFA稳定编号均为空。
            q=params["identifiers"]  # 原名称批量请求与稳定编号单项请求分开。
            rows=[row(0,"ACPP","9606.acp","ACP3"),row(1,"COL18A1","9606.wrong","VEGFA")] if "\r" in q else ([row(0,"ACPP","9606.acp",q)] if q in ("P15309","ENSG00000014257") else [])  # 不接受错误VEGFA替代。
            return {"url":"https://version-12-0.string-db.org/api/json/"+method,"params":params,"retrieved_at":"test","response_text":json.dumps(rows)}  # 模拟完整官方响应。
        with patch("ppi_flow.request",fake),patch("ppi_flow.time.sleep"):  # 不访问外网或等待。
            bundle=fetch(targets,raw,RHINITIS_SCOPE)  # 使用本研究独立授权生成来源包。
        summary,tables=evaluate(targets,bundle,"workflow_test",raw,RHINITIS_SCOPE)  # 同一授权独立复算。
        self.assertEqual(summary["本次PPI暂不采用数"],1)  # 仅VEGFA退出本次PPI。
        self.assertEqual(tables["identity_adjustments"][0]["target_id"],"HGNC:125")  # ACP3按稳定编号接入。
        self.assertEqual(tables["ppi_exclusions"][0]["target_id"],"HGNC:12680")  # VEGFA不被COL18A1替代。

    def test_web_archive(self):  # 实际网页提交和磁盘复读。
        import threading,urllib.request,urllib.parse,re  # 真实HTTP表单。
        from web import create_server  # 同用户入口。
        from workflow import Workflow  # 重新打开研究。
        from test_intersection_flow import setup_study  # 仅虚构上游。
        from intersection_flow import run_intersection  # 真实交集归档。
        with tempfile.TemporaryDirectory() as folder:  # 不写用户研究。
            root=Path(folder)  # 临时项目。
            f,sid=setup_study(root)  # 合成已复核A01/A02。
            a=run_intersection(f,sid,f.load(sid)["current"],"测试")  # 真实A03。
            f.review(sid,a["run_id"],"approved","测试","合成交集")  # 只签测试。
            target=a["tables"]["intersection_targets"][0]  # 单个虚构身份。
            def fake(method,params):  # 仅替代外网。
                return {"url":"https://version-12-0.string-db.org/api/json/"+method,"params":params,"retrieved_at":"test","response_text":json.dumps([{"queryIndex":0,"ncbiTaxonId":9606,"preferredName":target["symbol"],"stringId":"9606.synthetic"}])}  # 原响应格式。
            server=create_server(root,0)  # 临时端口。
            thread=threading.Thread(target=server.serve_forever,daemon=True)  # 后台运行。
            thread.start()  # 开始接收请求。
            try:  # 失败也清理。
                base="http://127.0.0.1:"+str(server.server_port)  # 不访问用户服务。
                html=urllib.request.urlopen(base+"/study?study="+sid).read().decode()  # 实际页面。
                self.assertIn("获取STRING并运行PPI两轮分析",html)  # 已接入而非占位。
                token=re.search(r'name="token" value="([^"]+)"',html).group(1)  # 页面令牌。
                data={"token":token,"study":sid,"expected_a03":a["run_id"],"expected_a04":"","reason":"隔离网页测试"}  # 版本明确。
                with patch("ppi_flow.request",fake):  # 不改变计算器。
                    html=urllib.request.urlopen(base+"/ppi",urllib.parse.urlencode(data).encode()).read().decode()  # 真实POST。
                self.assertIn("第一轮主候选数",html)  # 结果确实显示。
                fresh=Workflow(root)  # 模拟重启。
                m=fresh.load(sid)  # 读取新指针。
                x=fresh.result(m,m["current"]["A04"])  # 检查关联文件完整性。
                self.assertEqual(x["outcome"],"empty")  # 单节点无边。
                self.assertFalse(fresh.approved(m,x["run_id"]))  # 没有代签。
            finally:  # 不遗留后台进程。
                server.shutdown()  # 结束服务。
                server.server_close()  # 释放端口。
                thread.join(timeout=3)  # 回收线程。

if __name__=="__main__":  # 单独验收入口。
    unittest.main(verbosity=2)  # 如实报告。

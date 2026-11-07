"""基础层证据只读视图：使用明确合成结构与文件，不联网、不执行科学工具。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contracts import ContractError, fingerprint
from storage import file_record, write_json


def atom(serial, x, kind="C"):
    """生成列宽明确的合成PDBQT原子，仅验证文件关联与原始构象。"""
    return f"ATOM  {serial:5d}  C   LIG A   1    {x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00     0.000 {kind}"


class EvidenceFixture:
    """最小归档读者；只含本测试研究与实际写出的合成原件。"""

    def __init__(self, home):
        self.home = home
        self.root = home.parent.parent
        self.sid = "study_" + "a" * 32
        self.prep_id, self.score_id = "run_" + "b" * 32, "run_" + "c" * 32
        self.batch = {"path": "batch.json", "bytes": 1, "sha256": "b" * 64}
        self.fixed = {"compounds": [{"compound_id": "C1", "name": "本批成分"}],
                      "receptors": [{"target_id": "HGNC:1", "symbol": "本批受体"}], "input_key": "original"}
        self.ligand = self.save("inputs/ligand.pdbqt", atom(1, 0) + "\n", "prepared_ligand")
        self.receptor = self.save("inputs/receptor.pdbqt", atom(9, 1) + "\n", "receptor")
        self.binary = self.save("runs/A06/" + self.score_id + "/system_scoring/software/vina.exe", "not-an-executable", "scoring_vina")
        self.config = {"version": "A06.system_scoring.2", "cpu_per_pair": 1,
                       "vina_parameters": {"scoring": "vina", "exhaustiveness": 8, "num_modes": 2,
                                           "energy_range_kcal_mol": 3, "seed": 1}}
        self.box = {"center": [0, 0, 0], "size": [10, 10, 10]}
        self.evidence = {"structure_id": "TEST", "identity": {"chains": ["A"], "uniprot": "P00001"},
                         "reference": {"reference_code": "LIG", "reference_chain": "A", "reference_sequence": "1"},
                         "box": self.box, "receptor": self.receptor, "receptor_ready": True,
                         "top1_rmsd": 1.1, "pocket_complete": True, "environment_resolved": True,
                         "environment_audit": {"missing_pocket_atoms": [], "adjacent_unobserved_residues": [],
                                               "box_environment": [], "pocket_complete": True, "environment_resolved": True}}
        self.trace = {"candidate": {"spec": {"pdb_id": "TEST", "chains": ["A"], "pocket": "reference"}},
                      "evidence": self.evidence, "assessment": {"state": "ready", "quality": "严格", "reason_zh": "原核验通过"}}
        self.prepared = {"schema_version": "A06.system_qualification.2", "study_id": self.sid, "input_key": "original",
                         "configuration": {"version": "A06.system_qualification.2"}, "human_review_written": False,
                         "compounds": [{"compound_id": "C1", "state": "ready", "files": [self.ligand]}],
                         "receptors": [{"target_id": "HGNC:1", "symbol": "本批受体", "state": "ready", "quality": "严格",
                                        "reason_zh": "原核验通过", "attempts": [self.trace], "system_qualified_attempt": self.trace}]}
        self.prep_fact = self.json("prep/fact.json", self.prepared)
        self.fixed_ref = self.json("fixed.json", {"study_id": self.sid, "stage": "A06_INPUT",
                                                  "binding": {"batch_file": self.batch}, "payload": self.fixed})
        self.prep_run = {"study_id": self.sid, "run_id": self.prep_id, "module_id": "A06_PREP", "batch_file": self.batch,
                         "config": self.prepared["configuration"], "inputs": {"system_input_ref": self.fixed_ref}}
        self.prep_result = {"study_id": self.sid, "run_id": self.prep_id, "tables": {"preparation_packet": [self.prep_fact]}}
        self.prep_run_ref = self.json("runs/A06_PREP/" + self.prep_id + "/run.json", self.prep_run)
        self.prep_result_ref = self.json("runs/A06_PREP/" + self.prep_id + "/result.json", self.prep_result)
        self.run = {"study_id": self.sid, "run_id": self.score_id, "module_id": "A06", "batch_file": self.batch,
                    "config": self.config, "parent_runs": {"A06_PREP": self.prep_id},
                    "inputs": {"system_input_ref": self.prep_run["inputs"]["system_input_ref"],
                               "preparation_run": self.prep_run_ref, "preparation_result": self.prep_result_ref}}
        self.run_ref = self.json("runs/A06/" + self.score_id + "/run.json", self.run)
        self.folder = f"runs/A06/{self.score_id}/system_scoring/scores/pair_000001/attempt_test"
        raw = "MODEL 1\nREMARK VINA RESULT: -7.125 0 0\n" + atom(1, 0.1) + "\nENDMDL\n"
        raw += "MODEL 2\nREMARK VINA RESULT: -20.0 1 1\n" + atom(1, 0.2) + "\nENDMDL\n"
        self.pose = self.save(self.folder + "/poses.pdbqt", raw, "scoring_pose")
        args = [str(self.home / self.binary["path"]), "--receptor", str(self.home / self.receptor["path"]),
                "--ligand", str(self.home / self.ligand["path"])]
        for name in ("center", "size"):
            for axis, value in zip("xyz", self.box[name]):
                args += ["--" + name + "_" + axis, str(value)]
        for flag, key in (("scoring", "scoring"), ("exhaustiveness", "exhaustiveness"), ("num_modes", "num_modes"),
                          ("energy_range", "energy_range_kcal_mol"), ("seed", "seed")):
            args += ["--" + flag, str(self.config["vina_parameters"][key])]
        args += ["--cpu", "1", "--out", str(self.home / self.pose["path"])]
        self.command = {"arguments": args, "configuration": self.config, "ligand": self.ligand,
                        "receptor": self.receptor, "box": self.box, "executable": self.binary}
        self.command_ref = self.json(self.folder + "/command.json", self.command)
        self.execution = {"state": "completed", "score": -7.125, "mode_count": 2, "top_mode": 1,
                          "returncode": 0, "failure_kind": None, "reason_zh": "", "pose": self.pose,
                          "files": [self.command_ref, self.pose]}
        self.execution_ref = self.json(self.folder + "/execution.json", self.execution)
        self.pair = {"compound_id": "C1", "target_id": "HGNC:1", "state": "completed", "score": -7.125,
                     "quality": "严格", "input_key": "original", "reason_zh": "", "execution": self.execution_ref}
        self.score_packet = {"study_id": self.sid, "run_id": self.score_id, "schema_version": self.config["version"],
                             "configuration": self.config, "inputs": self.run["inputs"], "binary": self.binary,
                             "pairs": [self.pair], "files": [self.command_ref, self.pose, self.execution_ref]}
        self.score_ref = self.json(f"runs/A06/{self.score_id}/system_scoring/packets/packet_test.json", self.score_packet)
        self.result = {"study_id": self.sid, "run_id": self.score_id,
                       "summary": {"science_version": self.config["version"], "input_key": "original"},
                       "tables": {"scoring_packet": [self.score_ref], "plan_scoring_pairs": [dict(self.pair, execution_path=self.execution_ref["path"])]}}
        self.manifest = {"study_id": self.sid, "runs": {self.prep_id: {"run_file": self.prep_run_ref, "result_file": self.prep_result_ref},
                                                       self.score_id: {"run_file": self.run_ref, "result_file": self.json("score_result.json", self.result)}}}
        self.files = [self.pose, self.ligand, self.receptor, self.command_ref, self.execution_ref]

    def save(self, name, text, role="evidence"):
        """写入测试独立目录，并按实际字节建立文件引用。"""
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return file_record(self.home, path, role)

    def json(self, name, value):
        """保存明确合成的归档JSON，测试篡改也必须产生新真实指纹。"""
        path = self.home / name
        write_json(path, value, replace=True)
        return file_record(self.home, path, "evidence")

    def location(self, sid):
        """拒绝借用其他测试研究的原件。"""
        assert sid == self.sid
        return self.home

    def load(self, sid):
        """只读返回本测试已登记的manifest，不写入研究索引。"""
        assert sid == self.sid
        return self.manifest

    def run(self, manifest, rid):
        """仅提供测试中真实登记的两个运行。"""
        return self.prep_run if rid == self.prep_id else self.run

    def result(self, manifest, rid):
        """只读原准备结果。"""
        assert rid == self.prep_id
        return self.prep_result

    def refresh(self):
        """更新被测试者明确篡改的JSON指纹，使断言不只依赖文件损坏检测。"""
        self.execution_ref = self.json(self.folder + "/execution.json", self.execution)
        self.pair["execution"] = self.execution_ref
        self.score_ref = self.json(f"runs/A06/{self.score_id}/system_scoring/packets/packet_test.json", self.score_packet)
        self.result["tables"]["scoring_packet"] = [self.score_ref]
        self.result["tables"]["plan_scoring_pairs"] = [dict(self.pair, execution_path=self.execution_ref["path"])]


class FoundationEvidenceTests(unittest.TestCase):
    """显示层必须读同一份实际文件，不能按第二姿势或其他批次补齐。"""

    def setUp(self):
        self.temp = TemporaryDirectory(prefix="foundation_evidence_")
        self.addCleanup(self.temp.cleanup)
        self.case = EvidenceFixture(Path(self.temp.name) / "study")

    def build(self):
        """通过预定公开只读helper读取，不安装或运行任何科学库。"""
        from modulea.core.foundation_evidence import build
        c = self.case
        return build(c, c.manifest, c.run, c.result, c.fixed,
                     [dict(ref, key=f"{c.score_id}.{i}") for i, ref in enumerate(c.files)])

    def test_original_top1_and_files_are_read_only_and_second_pose_is_not_selected(self):
        c = self.case
        before = fingerprint([c.manifest, c.result, c.prepared])
        value = self.build()
        self.assertEqual(value["integrity"], "verified")
        self.assertEqual(value["scores"][0]["score"], -7.125)
        self.assertEqual(value["scores"][0]["top_mode"], 1)
        self.assertEqual(value["scores"][0]["pose_sha256"], c.pose["sha256"])
        self.assertEqual(value["scores"][0]["box"], c.box)
        self.assertTrue(value["scores"][0]["downloads"][0]["url"].startswith("/api/v1/studies/" + c.sid + "/files/"))
        self.assertEqual(value["preparation"][0]["reference"], c.evidence["reference"])
        self.assertEqual(value["preparation"][0]["chains"], ["A"])
        self.assertEqual(fingerprint([c.manifest, c.result, c.prepared]), before)

    def test_edited_display_score_is_rejected_even_when_packet_score_is_edited_too(self):
        c = self.case
        c.pair["score"] = -20.0
        c.refresh()
        with self.assertRaisesRegex(ContractError, "Top-1|评分"):
            self.build()

    def test_changed_pose_bytes_cannot_keep_download_link(self):
        c = self.case
        (c.home / c.pose["path"]).write_text("different coordinates", encoding="utf-8")
        with self.assertRaises(ContractError):
            self.build()

    def test_changed_command_box_is_rejected_with_fresh_file_hash(self):
        c = self.case
        c.command["arguments"][c.command["arguments"].index("--size_x") + 1] = "20"
        c.execution["files"][0] = c.json(c.folder + "/command.json", c.command)
        c.refresh()
        with self.assertRaisesRegex(ContractError, "参数|命令|搜索盒"):
            self.build()

    def test_unknown_environment_is_not_presented_as_an_empty_successful_check(self):
        c = self.case
        c.evidence.pop("environment_audit")
        c.evidence.update(pocket_complete=False, environment_resolved=False)
        c.prepared["receptors"][0].update(state="NA", quality="待核查", reason_zh="原准备未完成")
        c.prep_result["tables"]["preparation_packet"] = [c.json("prep/fact.json", c.prepared)]
        c.run["module_id"] = "A06_PREP"
        c.run["run_id"] = c.prep_id
        c.run["config"] = c.prep_run["config"]
        c.result = dict(c.prep_result, summary={"input_key": "original"})
        value = self.build()
        self.assertIsNone(value["preparation"][0]["pocket_complete"])
        self.assertIsNone(value["preparation"][0]["environment_resolved"])
        self.assertIsNone(value["preparation"][0]["environment_components"])
        self.assertEqual(value["preparation"][0]["reason_zh"], "原准备未完成")

    def test_foreign_preparation_or_packet_is_rejected(self):
        c = self.case
        c.prepared["study_id"] = "study_" + "d" * 32
        c.prep_result["tables"]["preparation_packet"] = [c.json("prep/fact.json", c.prepared)]
        with self.assertRaises(ContractError):
            self.build()

    def test_contact_chains_require_archived_basis_and_never_default_to_target_chain(self):
        self.assertIsNone(self.build()['preparation'][0]['reference_contacts'])
        c = self.case
        def save_preparation():
            c.prep_result['tables']['preparation_packet'] = [c.json('prep/fact.json', c.prepared)]
            ref = c.json(c.prep_result_ref['path'], c.prep_result)
            c.manifest['runs'][c.prep_id]['result_file'] = ref
            c.run['inputs']['preparation_result'] = ref
            c.refresh()
        c.evidence['reference_contacts'] = {'chains':['B'],'basis_zh':'明确合成原核查，保留其依据'}
        save_preparation()
        self.assertEqual(self.build()['preparation'][0]['reference_contacts']['chains'], ['B'])
        c.evidence['reference_contacts'].pop('basis_zh')
        save_preparation()
        with self.assertRaisesRegex(ContractError, '接触链'):
            self.build()

    def test_missing_result_index_does_not_invent_a_download_permission(self):
        self.case.files = []
        value = self.build()
        self.assertEqual(value["scores"][0]["downloads"], [])

    def test_missing_execution_from_successful_pair_is_an_explicit_integrity_error(self):
        c = self.case
        c.pair["execution"] = None
        c.score_ref = c.json(f"runs/A06/{c.score_id}/system_scoring/packets/packet_test.json", c.score_packet)
        c.result["tables"]["scoring_packet"] = [c.score_ref]
        with self.assertRaises(ContractError):
            self.build()

    def test_legacy_fixture_without_an_archived_packet_adds_no_evidence(self):
        self.case.result["tables"].pop("scoring_packet")
        self.assertIsNone(self.build())

    def test_top1_download_preserves_exact_original_bytes_and_provenance(self):
        from hashlib import sha256
        import json
        from types import SimpleNamespace
        from modulea.api.foundation_evidence import top1, context
        c = self.case
        source = (c.home / c.pose["path"]).read_bytes()
        before = {p: sha256(p.read_bytes()).hexdigest() for p in c.home.rglob("*") if p.is_file()}
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: c))
        query = {"expected_input_key": ["original"], "expected_pose_sha256": [c.pose["sha256"]]}
        req = SimpleNamespace(query=query, query1=lambda name: query[name][0])
        response = top1(app, req, c.sid, c.score_id, "1")
        self.assertEqual(response[0], "download")
        self.assertEqual(response[1], source[:source.index(b"MODEL 2")])
        self.assertNotIn(b"MODEL 2", response[1])
        metadata = json.loads(context(app, req, c.sid, c.score_id, "1")[1])
        self.assertEqual(metadata["source_pose_sha256"], sha256(source).hexdigest())
        self.assertEqual(metadata["top1_sha256"], sha256(response[1]).hexdigest())
        self.assertEqual(metadata["score"], -7.125)
        self.assertEqual(metadata["box"], c.box)
        self.assertEqual(before, {p: sha256(p.read_bytes()).hexdigest() for p in c.home.rglob("*") if p.is_file()})

    def test_top1_download_rejects_stale_binding_and_path_or_pose_overrides(self):
        from types import SimpleNamespace
        from modulea.api.foundation_evidence import top1
        from modulea.api.errors import ApiError
        c = self.case
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: c))
        for query, expected in (({"expected_input_key": ["other"], "expected_pose_sha256": [c.pose["sha256"]]}, 409),
                                ({"expected_input_key": ["original"], "expected_pose_sha256": [c.pose["sha256"]], "pose": ["2"]}, 422),
                                ({"expected_input_key": ["original"], "expected_pose_sha256": [c.pose["sha256"]], "path": ["../other"]}, 422)):
            req = SimpleNamespace(query=query, query1=lambda name: query[name][0])
            with self.assertRaises(ApiError) as caught:
                top1(app, req, c.sid, c.score_id, "1")
            self.assertEqual(caught.exception.status, expected)

    def test_http_routes_download_exact_top1_and_reject_extra_parameters(self):
        from hashlib import sha256
        import json,threading
        from urllib.request import urlopen
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        from modulea.config import Settings
        from modulea.api.server import create_server
        c=self.case
        server,app=create_server(Settings(data_root=c.root,runtime_dir=c.home/'runtime'),0)
        app.kernel.read_workflow=lambda:c
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_address[1]}/api/v1/studies/{c.sid}/runs/{c.score_id}/foundation/pairs/1/'
        query=urlencode({'expected_input_key':'original','expected_pose_sha256':c.pose['sha256']})
        try:
            with urlopen(base+'top1.pdbqt?'+query) as response:
                raw=response.read();self.assertIn('attachment',response.headers['Content-Disposition'])
            with urlopen(base+'context.json?'+query) as response:context=json.load(response)
            self.assertEqual(context['top1_sha256'],sha256(raw).hexdigest())
            self.assertEqual(context['source_pose_sha256'],c.pose['sha256'])
            self.assertNotIn(b'MODEL 2',raw)
            with self.assertRaises(HTTPError) as rejected:urlopen(base+'top1.pdbqt?'+query+'&pose=2')
            self.assertEqual(rejected.exception.code,422)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

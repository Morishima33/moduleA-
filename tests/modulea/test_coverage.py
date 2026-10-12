"""第二版A06覆盖隔离回归：技术资格、主要五、采用确认和旧版本委托。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from science_modules.a06.coverage_engine import eligible, candidate_pool
from science_modules.a06.coverage_flow import reports, confirm_packet, counts, validator
from science_modules.a06.two_pass import confidence


def packet():
    """虚构结构只用于纯契约自测，不冒充真实评分或来源。"""
    rows = []
    for i in range(7):
        quality = "严格" if i < 3 else "探索" if i < 6 else "待补／无法计算"
        rows.append(
            {
                "target_id": "HGNC:" + str(i + 1),
                "symbol": "虚构" + str(i),
                "candidate_grade": "A" if i < 2 else "B",
                "ppi_order": i + 1,
                "eligible": i < 6,
                "quality_zh": quality,
                "status_zh": "待采纳",
                "reason_zh": "隔离原因",
                "pdb_id": "1ABC",
                "adopted": False,
                "selected": {"spec": {"pocket": "reference"}, "top1_rmsd": 1.0}
                if i < 6
                else None,
                "attempts": [
                    {"round": 1, "reason_zh": "第一遍隔离记录"},
                    {"round": 2, "reason_zh": "第二遍隔离记录"},
                ],
            }
        )
    context = {
        "analysis_purpose": "workflow_test",
        "receptors": rows,
        "compounds": [{"compound_id": "C1"}, {"compound_id": "C2"}],
    }
    return {
        "context": context,
        "source_key": "virtual",
        "receptors": rows,
        "counts": counts(rows),
        "compounds": [
            {
                "compound_id": "C1",
                "name_zh": "虚构成分1",
                "state": "ready",
                "reason_zh": "",
            },
            {
                "compound_id": "C2",
                "name_zh": "虚构成分2",
                "state": "NA",
                "reason_zh": "无三维",
            },
        ],
        "confirmation": None,
    }


class CoverageRulesTests(TestCase):
    """边界不为提高覆盖数量而改变，未确认技术候选不下传。"""

    def test_unconfirmed_no_handoff_and_full_pairs(self):
        p = packet()
        s, t = reports(p)
        self.assertTrue(s["handoff_blocked"])
        self.assertEqual(s["具备准备输入组合数"], 0)
        self.assertEqual(len(t["planned_pairs"]), 14)
        self.assertEqual(s["实际批量评分数"], 0)

    def test_exploration_does_not_fill_main_five(self):
        p = packet()
        d = {
            "selected_target_ids": [
                r["target_id"] for r in p["receptors"] if r["eligible"]
            ],
            "reviewer": "隔离核验",
            "note": "核对位点",
            "confirmed": True,
        }
        q = confirm_packet(p, d)
        s, t = reports(q)
        self.assertFalse(s["handoff_blocked"])
        self.assertFalse(s["主要结果条件满足"])
        self.assertEqual(s["主要受体数"], 0)
        self.assertEqual(s["具备准备输入组合数"], 6)
        self.assertFalse(any(r["adopted"] for r in p["receptors"]))

    def test_boundary_rmsd_and_environment(self):
        e = {
            "receptor_ready": True,
            "pocket_complete": True,
            "environment_resolved": True,
            "top1_rmsd": 2.0,
        }
        spec = {"pocket": "reference"}
        self.assertTrue(eligible(e, spec))
        for bad in (
            {**e, "top1_rmsd": 2.000001},
            {**e, "environment_resolved": False},
            {**e, "pocket_complete": False},
            {**e, "top1_rmsd": True},
        ):
            self.assertFalse(eligible(bad, spec))

    def test_pocket_and_af_threshold(self):
        spec = {"pocket": "p2rank", "source_type": "alphafold"}
        e = {
            "receptor_ready": True,
            "pocket_complete": True,
            "environment_resolved": True,
            "confidence_facts": {"passed": True},
            "pocket": {"rank": 1, "runs": [{"x": 1}, {"x": 1}]},
        }
        self.assertTrue(eligible(e, spec))
        e["pocket"]["runs"][1] = {"x": 2}
        self.assertFalse(eligible(e, spec))
        data = {"plddt": [70, 90], "pae": [[0, 10], [10, 0]], "pocket_indices": [0, 1]}
        self.assertTrue(confidence(data)["passed"])
        data["pae"][1][0] = 10.01
        self.assertFalse(confidence(data)["passed"])

    def test_unresolved_not_adoptable_and_old_delegation(self):
        p = packet()
        with self.assertRaises(ValueError):
            confirm_packet(p, {"selected_target_ids": ["HGNC:7"]})
        old = Mock()
        validator(Path("."), old)(
            {"config": {"version": "historical"}}, {}, {}, [], "success"
        )
        old.assert_called_once()

    def test_failed_structure_not_candidate(self):
        meta = {
            "candidates": [
                {
                    "pdb_id": "1ABC",
                    "target_chains": [{"length": 200, "mutation_count": 0}],
                },
                {
                    "pdb_id": "2ABC",
                    "target_chains": [{"length": 200, "mutation_count": 1}],
                },
                {
                    "pdb_id": "3ABC",
                    "target_chains": [{"length": 12, "mutation_count": 0}],
                },
            ]
        }
        self.assertEqual(
            candidate_pool(meta, {"pdb_id": "1ABC", "pocket": "reference"}, {"1ABC"}),
            [],
        )

    def test_number_adjacency_not_damage_and_missing_blocks(self):
        import gemmi
        from science_modules.a06.coverage_geometry import audit

        st = gemmi.read_pdb_string(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \nEND\n"
        )
        st.setup_entities()
        block = st.make_mmcif_document().sole_block()
        block.set_mmcif_category(
            "_pdbx_unobs_or_zero_occ_residues.",
            {"auth_asym_id": ["A"], "auth_seq_id": ["2"], "auth_comp_id": ["ALA"]},
        )
        e = audit(
            block.as_string(),
            {"chains": ["A"], "altloc": None},
            {"center": [0, 0, 0], "size": [10, 10, 10]},
            [("A", "1")],
        )
        self.assertFalse(e["pocket_complete"])
        self.assertEqual(e["adjacent_unobserved_residues"], e["unobserved_residues"])
        self.assertIn("需完整独立结构对照", e["unobserved_residues"][0]["reason_zh"])

    def test_only_official_non_native_expression_tag_can_be_omitted(self):
        import gemmi
        from science_modules.a06.coverage_geometry import audit

        st = gemmi.read_pdb_string(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \nEND\n"
        )
        st.setup_entities()
        block = st.make_mmcif_document().sole_block()
        block.set_mmcif_category(
            "_pdbx_unobs_or_zero_occ_residues.",
            {"auth_asym_id": ["A"], "auth_seq_id": ["2"], "auth_comp_id": ["GLY"]},
        )
        details = {
            "pdbx_pdb_strand_id": ["A"],
            "pdbx_auth_seq_num": ["2"],
            "mon_id": ["GLY"],
            "details": ["expression tag"],
            "pdbx_seq_db_seq_num": [None],
            "pdbx_seq_db_accession_code": ["P00001"],
        }
        block.set_mmcif_category("_struct_ref_seq_dif.", details)
        spec = {"chains": ["A"], "altloc": None, "uniprot": "P00001"}
        box = {"center": [0, 0, 0], "size": [10, 10, 10]}

        def evidence():
            return audit(block.as_string(), spec, box, [("A", "1")])

        self.assertTrue(evidence()["pocket_complete"])
        self.assertEqual(len(evidence()["expression_tag_evidence"]), 1)
        details["pdbx_seq_db_seq_num"] = ["2"]
        block.set_mmcif_category("_struct_ref_seq_dif.", details)
        self.assertFalse(evidence()["pocket_complete"])
        details["pdbx_seq_db_seq_num"] = [None]
        details["pdbx_seq_db_accession_code"] = ["OTHER"]
        block.set_mmcif_category("_struct_ref_seq_dif.", details)
        self.assertFalse(evidence()["pocket_complete"])


class CoverageWorkflowTests(TestCase):
    """单个隔离研究验证完整保存／确认生命周期，不用真实研究签名。"""

    def test_save_refresh_stale_and_confirm_without_approval(self):
        from tests.modulea.test_source_review import source_fixture
        from tests.modulea.test_two_pass import filled
        from modulea.core.coverage_workflow import CoverageWorkflow
        from science_modules.a06.coverage_engine import CONFIG
        from storage import write_json, file_record
        from uuid import uuid4

        with TemporaryDirectory() as temp:
            root = Path(temp)
            old, sid, ctx, source = source_fixture(root)
            w = CoverageWorkflow(root, old.validators)
            w.validators["A06_PREP"] = Mock()
            saved_source = w.save_source_review(sid, source)
            plan = filled(ctx)
            saved_plan = w.save_two_pass(
                sid,
                {
                    "expected_source": ctx["source_key"],
                    "expected_source_review_id": saved_source["review_id"],
                    "expected_plan_id": None,
                    "plan_id": "plan_" + uuid4().hex,
                    "confirmed_target_ids": [r["target_id"] for r in ctx["receptors"]],
                    "reviewer": "隔离核验",
                    "note": "虚构方案",
                    "confirmed": True,
                    "plan": plan,
                },
            )
            before = w.load(sid)
            rows = []
            for i, target in enumerate(ctx["receptors"]):
                spec = plan["receptors"][i]["first"]
                evidence = {
                    "spec": spec,
                    "round": 1,
                    "top1_rmsd": 1.0,
                    "reason_zh": "虚构准备证据",
                }
                rows.append(
                    {
                        **target,
                        "eligible": i == 0,
                        "quality_zh": "严格" if i == 0 else "待补／无法计算",
                        "status_zh": "待采纳",
                        "reason_zh": "隔离测试",
                        "pdb_id": "1ABC",
                        "adopted": False,
                        "selected": evidence if i == 0 else None,
                        "attempts": [evidence],
                    }
                )
            p = {
                "schema_version": "A06.coverage.execution.4",
                "study_id": sid,
                "campaign_id": "campaign_virtual",
                "source_key": ctx["source_key"],
                "plan_id": saved_plan["plan_id"],
                "source_review_id": saved_source["review_id"],
                "context": ctx,
                "receptors": rows,
                "compounds": [
                    {**c, "state": "ready", "name_zh": c["name"], "reason_zh": ""}
                    for c in ctx["compounds"]
                ],
                "files": [],
                "counts": counts(rows),
                "confirmation": None,
            }
            run = w.begin(sid, "A06_PREP", {}, CONFIG, "隔离虚构技术核查")
            p["run_id"] = run["run_id"]
            path = (
                w.location(sid)
                / "runs/A06_PREP"
                / run["run_id"]
                / "coverage/packet.json"
            )
            write_json(path, p)
            record = file_record(w.location(sid), path, "coverage_packet")
            summary, tables = reports(p)
            tables["coverage_packet"] = [record]
            w.finish(sid, run["run_id"], summary, tables, attachments=[record])
            info = w.coverage_info(w.load(sid))
            req = {
                "expected_run": info["expected_run"],
                "expected_source": info["expected_source"],
                "campaign_id": info["campaign_id"],
                "expected_decision_id": None,
                "selected_target_ids": [rows[0]["target_id"]],
                "reviewer": "",
                "note": "",
                "confirmed": False,
            }
            w.save_coverage_selection(sid, req)
            refreshed = w.coverage_info(w.load(sid))
            self.assertEqual(
                refreshed["draft"]["selected_target_ids"], req["selected_target_ids"]
            )
            self.assertFalse(refreshed["confirmed"])
            after = w.load(sid)
            for name in (
                "expected_run",
                "expected_source",
                "campaign_id",
                "expected_decision_id",
            ):
                with self.assertRaises(ValueError):
                    w.validate_coverage_selection(sid, {**req, name: "过期"})
            with self.assertRaises(ValueError):
                w.validate_coverage_selection(
                    sid,
                    {
                        **req,
                        "expected_decision_id": refreshed["expected_decision_id"],
                        "selected_target_ids": [rows[-1]["target_id"]],
                    },
                )
            with self.assertRaises(ValueError):
                w.validate_coverage_selection(
                    sid, {**req, "batch_docking_allowed": True}
                )
            self.assertEqual(after, w.load(sid))
            final = {
                **req,
                "expected_decision_id": refreshed["expected_decision_id"],
                "reviewer": "隔离核验人",
                "note": "核对全部结构与位点",
                "confirmed": True,
            }
            w.save_coverage_selection(sid, final)
            confirmed = w.coverage_info(w.load(sid))
            self.assertTrue(confirmed["confirmed"])
            m = w.load(sid)
            self.assertEqual(before["reviews"], m["reviews"])
            self.assertFalse(w.approved(m, m["current"]["A06_PREP"]))
            self.assertNotIn("A06", m["current"])
            self.assertFalse(confirmed["batch_docking_allowed"])
            with self.assertRaises(ValueError):
                w.save_coverage_selection(sid, final)


class CoverageGeometryTests(TestCase):
    """独立完整实验对照必须同时满足身份映射、非退化空间拟合和缺失位置安全余量。"""

    def structures(self, gap_x=30):
        import gemmi

        def document(extra):
            lines = []
            for i, (x, y, z) in enumerate(((0, 0, 0), (2, 0, 0), (0, 2, 0)), 1):
                lines.append(
                    f"ATOM  {i:5d}  CA  ALA A{i:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C  "
                )
            if extra:
                lines.append(
                    f"ATOM      4  CA  ALA A  10    {gap_x:8.3f}{0:8.3f}{0:8.3f}  1.00 20.00           C  "
                )
            st = gemmi.read_pdb_string("\n".join(lines) + "\nEND\n")
            st.setup_entities()
            b = st.make_mmcif_document().sole_block()
            b.set_mmcif_category(
                "_struct_ref_seq.",
                {
                    "pdbx_strand_id": ["A"],
                    "pdbx_db_accession": ["P00001"],
                    "pdbx_auth_seq_align_beg": ["1"],
                    "pdbx_auth_seq_align_end": ["30"],
                    "db_align_beg": ["1"],
                    "db_align_end": ["30"],
                },
            )
            return b.as_string()

        return document(False), document(True)

    def test_complete_control_resolves_remote_gap(self):
        from science_modules.a06.coverage_geometry import compare_missing

        spec = {"uniprot": "P00001", "chains": ["A"], "altloc": None}
        env = {
            "pocket_residues": [("A", "1"), ("A", "2"), ("A", "3")],
            "unobserved_residues": [{"chain": "A", "sequence": "10"}],
            "missing_pocket_atoms": [],
        }
        left, right = self.structures()
        reviews = compare_missing(
            left, spec, env, {"spec": dict(spec, pdb_id="2ABC"), "file": {}}, right
        )
        self.assertEqual(len(reviews), 1)
        self.assertGreater(reviews[0]["minimum_distance_A"], 5)
        self.assertEqual(reviews[0]["canonical_position"], 10)
        self.assertEqual(reviews[0]["pocket_mapping_count"], 3)

    def test_close_or_unmapped_gap_not_resolved(self):
        from science_modules.a06.coverage_geometry import compare_missing

        spec = {"uniprot": "P00001", "chains": ["A"], "altloc": None}
        env = {
            "pocket_residues": [("A", "1"), ("A", "2"), ("A", "3")],
            "unobserved_residues": [{"chain": "A", "sequence": "10"}],
            "missing_pocket_atoms": [],
        }
        left, right = self.structures(3)
        self.assertEqual(
            compare_missing(
                left, spec, env, {"spec": dict(spec, pdb_id="2ABC"), "file": {}}, right
            ),
            [],
        )
        env["unobserved_residues"][0]["sequence"] = "99"
        self.assertEqual(
            compare_missing(
                left, spec, env, {"spec": dict(spec, pdb_id="2ABC"), "file": {}}, right
            ),
            [],
        )


class CoverageCalculationGateTests(TestCase):
    """通用继续动作也不能越过本轮仍关闭的批量计算关口。"""

    def test_continue_stops_before_any_scientific_handoff(self):
        from modulea.tasks.worker import run_continue

        settings = Mock()
        manager = Mock()
        for version in ("A06.coverage.execution.4", "A06.coverage.confirmed.4"):
            workflow = Mock()
            workflow.load.return_value = {"current": {"A06_PREP": "run_isolated"}}
            workflow.run.return_value = {"config": {"version": version}}
            with patch("modulea.tasks.worker.full_workflow", return_value=workflow):
                text = run_continue(
                    settings,
                    {"task_id": "task_isolated", "study_id": "study_isolated"},
                    manager,
                )
            self.assertIn("未启动计算", text)
            workflow.result.assert_not_called()
            workflow.begin.assert_not_called()


class CoverageFinalAuditTests(TestCase):
    """最终审计再核对原位点与必要金属，不以模型置信度取代环境。"""

    def test_alphafold_cannot_bypass_original_required_metal(self):
        import gemmi
        from storage import file_record
        from science_modules.a06.coverage_final_audit import audit_choice

        with TemporaryDirectory() as folder:
            root = Path(folder)
            st = gemmi.read_pdb_string(
                "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \n"
                "HETATM    2 ZN    ZN A   2       1.000   0.000   0.000  1.00 20.00          ZN  \n"
                "HETATM    3  C1  LIG B  99       0.500   0.000   0.000  1.00 20.00           C  \nEND\n"
            )
            st.setup_entities()
            block = st.make_mmcif_document().sole_block()
            block.set_mmcif_category(
                "_struct_ref_seq.",
                {
                    "pdbx_strand_id": ["A"],
                    "pdbx_db_accession": ["P00001"],
                    "pdbx_auth_seq_align_beg": ["1"],
                    "pdbx_auth_seq_align_end": ["30"],
                    "db_align_beg": ["1"],
                    "db_align_end": ["30"],
                },
            )
            source = root / "original.cif"
            source.write_text(block.as_string(), encoding="utf-8")
            record = file_record(root, source, "source")
            spec = {
                "pdb_id": "1ABC",
                "uniprot": "P00001",
                "source_type": "experimental",
                "chains": ["A"],
                "altloc": None,
                "pocket": "reference",
                "reference_code": "LIG",
                "reference_chain": "B",
                "reference_sequence": "99",
            }
            chosen = {
                "spec": {"source_type": "alphafold", "pocket": "p2rank"},
                "receptor_ready": True,
                "pocket_complete": True,
                "environment_resolved": True,
                "confidence_facts": {"passed": True},
                "files": [],
                "pocket": {"rank": 1, "runs": [{"rank": 1}, {"rank": 1}]},
            }
            row = {
                "selected": chosen,
                "attempts": [
                    {"spec": spec, "box": {"center": [0, 0, 0], "size": [10, 10, 10]}}
                ],
            }
            # 此单元测试验证最终审计对已核实必要环境的执行；原件几何另有独立测试。
            environment = {
                "pocket_residues": [("A", "1")],
                "retained_cofactors": [("A", "ZN", "2")],
                "retained_partner_chains": [],
                "unresolved_environment": [],
            }
            with patch(
                "science_modules.a06.coverage_geometry.audit", return_value=environment
            ):
                with self.assertRaisesRegex(ValueError, "必要伙伴"):
                    audit_choice(root, row, {"first": spec}, record)

"""参数校验、重算依赖与复用键的固定预期测试，不访问真实研究或网络。"""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from contracts import ContractError
from science_modules.analysis_protocol import affected_stages, checked_plan, compile_plan, parameter_catalog, stage_fingerprint


class AnalysisProtocolTests(unittest.TestCase):
    """验证用户已确认的参数、保护项和独立分支，而非仅比较实现返回值。"""

    def plan(self, **values):
        return compile_plan({"mode": "personalized", "parameters": values})

    def test_defaults_and_catalog_do_not_allow_external_mutation(self):
        plan = compile_plan({"mode": "standard"})
        self.assertEqual(plan["parameters"]["a06.component_count"], 15)
        self.assertEqual(plan["parameters"]["a06.receptor_count"], 15)
        self.assertEqual(plan["parameters"]["a04.mode"], "dual_ab")
        self.assertEqual(plan["parameters"]["a04.required_score"], .90)
        self.assertTrue(plan["fixed"]["keep_boundary_ties"])
        catalog = parameter_catalog()
        self.assertFalse(catalog["execution_ready"])
        catalog["fixed"]["species"] = 10090
        catalog["parameters"]["a01.ob_min"]["default"] = 99
        self.assertEqual(compile_plan({"mode": "standard"}), plan)

    def test_invalid_types_ranges_unknown_fields_and_fixed_rules_are_rejected(self):
        bad = [{"a01.ob_min": True}, {"a01.ob_min": 101}, {"a01.dl_min": -1},
               {"a05.min_term_size": 1.5}, {"a06.seed": 0}, {"a06.num_modes": False},
               {"a06.exhaustiveness": 0}, {"a06.energy_range": float("nan")},
               {"a06.box_padding": float("inf")}, {"a06.redocking_rmsd_max": 0}, {"a01.dl_min": 10 ** 400},
               {"a04.required_score": .9001}, {"a04.mode": "all"},
               {"species": 10090}, {"vina_version": "latest"}, {"a06.receptor_count": 16}]
        for values in bad:
            with self.subTest(values=values), self.assertRaises(ContractError):
                self.plan(**values)
        for spec in [{"mode": "standard", "parameters": {"a01.ob_min": 40}},
                     {"mode": "personalized", "hidden": True}, {"mode": "unknown"}]:
            with self.subTest(spec=spec), self.assertRaises(ContractError):
                compile_plan(spec)

    def test_cross_parameter_checks_and_nonblocking_warnings(self):
        for values in [{"a05.min_term_size": 600}, {"a04.degree_main_window": 20, "a04.degree_pool_window": 15}]:
            with self.assertRaises(ContractError):
                self.plan(**values)
        self.assertEqual(self.plan(**{"a06.receptor_count": 25})["warnings"][0]["code"], "POOL_SMALLER_THAN_TARGET")
        relaxed = self.plan(**{"a06.redocking_rmsd_max": 3})
        self.assertEqual(relaxed["fixed"]["default_strict_rmsd_A"], 2)
        self.assertIn("CUSTOM_RMSD", [r["code"] for r in relaxed["warnings"]])
        disabled = self.plan(**{"a05.include_go": False, "a05.include_kegg": False})
        self.assertEqual(disabled["warnings"][0]["code"], "ENRICHMENT_DISABLED")

    def test_changed_ob_keeps_disease_and_changed_string_keeps_enrichment(self):
        baseline = self.plan()
        ob = affected_stages(baseline, self.plan(**{"a01.ob_min": 40}))
        self.assertIn("A01", ob["stages"])
        self.assertIn("A03", ob["stages"])
        self.assertIn("A06_SCORING", ob["stages"])
        self.assertNotIn("A02", ob["stages"])
        string = affected_stages(baseline, self.plan(**{"a04.required_score": .70}))
        self.assertIn("A04_NETWORK", string["stages"])
        self.assertIn("A06_SCORING", string["stages"])
        self.assertNotIn("A05_STATISTICS", string["stages"])
        self.assertNotIn("A01", string["stages"])

    def test_plot_and_significance_changes_do_not_repeat_statistics_or_docking(self):
        baseline = self.plan()
        plotted = affected_stages(baseline, self.plan(**{"a05.kegg_plot_top": 25}))
        self.assertEqual(plotted["stages"], ["A05_DISPLAY", "A07"])
        filtered = affected_stages(baseline, self.plan(**{"a05.adjusted_p_max": .01}))
        self.assertEqual(filtered["stages"], ["A05_FILTER", "A05_DISPLAY", "A07"])
        changed_size = affected_stages(baseline, self.plan(**{"a05.max_term_size": 600}))
        self.assertIn("A05_STATISTICS", changed_size["stages"])
        self.assertNotIn("A06_SCORING", changed_size["stages"])

    def test_component_count_changes_only_docking_selection_branch(self):
        changed = affected_stages(self.plan(), self.plan(**{"a06.component_count": 25}))
        self.assertIn("A03_SELECT", changed["stages"])
        self.assertIn("A06_PREPARATION", changed["stages"])
        self.assertNotIn("A03", changed["stages"])
        self.assertNotIn("A04_NETWORK", changed["stages"])
        self.assertNotIn("A05_STATISTICS", changed["stages"])

    def test_fingerprints_bind_input_tools_and_relevant_parameters(self):
        inputs, tools = {"ligand": "a" * 64, "receptor": "b" * 64}, {"vina": "1.2.7", "environment": "fixture"}
        baseline = self.plan()
        key = stage_fingerprint(baseline, "A06_SCORING", inputs, tools)
        displayed = self.plan(**{"a05.go_plot_top": 25})
        self.assertEqual(stage_fingerprint(displayed, "A06_SCORING", inputs, tools), key)
        seeded = self.plan(**{"a06.seed": 2})
        self.assertNotEqual(stage_fingerprint(seeded, "A06_SCORING", inputs, tools), key)
        self.assertNotEqual(stage_fingerprint(baseline, "A06_SCORING", dict(inputs, ligand="c" * 64), tools), key)
        self.assertNotEqual(stage_fingerprint(baseline, "A06_SCORING", inputs, dict(tools, environment="other")), key)
        self.assertNotEqual(stage_fingerprint(displayed, "A07", inputs, tools), stage_fingerprint(baseline, "A07", inputs, tools))
        with self.assertRaises(ContractError):
            stage_fingerprint(baseline, "A06_SCORING", {"ligand": "unverified"}, tools)

    def test_compiled_plan_tampering_is_rejected_including_boolean_alias(self):
        for change in [lambda p: p["fixed"].update(species=10090),
                       lambda p: p["fixed"].update(keep_boundary_ties=1),
                       lambda p: p.update(parameter_hash="f" * 64),
                       lambda p: p["fixed"].update(bad=float("nan")),
                       lambda p: p["parameters"].update({"a06.seed": 2})]:
            plan = deepcopy(self.plan())
            change(plan)
            with self.assertRaises(ContractError):
                checked_plan(plan)

    def test_mode_only_change_updates_report_without_scientific_recalculation(self):
        result = affected_stages(compile_plan({"mode": "standard"}), self.plan())
        self.assertEqual(result["stages"], ["A07"])
        self.assertEqual(result["changed_parameters"], [])

    def test_javascript_json_number_roundtrip_preserves_valid_plan(self):
        plan = self.plan()
        def javascript_numbers(value):
            if isinstance(value, dict):
                return {k: javascript_numbers(v) for k, v in value.items()}
            if isinstance(value, list):
                return [javascript_numbers(v) for v in value]
            return int(value) if type(value) is float and value.is_integer() else value
        self.assertEqual(checked_plan(javascript_numbers(plan)), plan)


if __name__ == "__main__":
    unittest.main()

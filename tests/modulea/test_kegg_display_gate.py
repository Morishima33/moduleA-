"""KEGG仅在范围已应用后展示；不改统计、人工决定或其他模块。"""
import unittest
from copy import deepcopy
from modulea.core.enrichment_workflow import kegg_display_status
from modulea.api.views import hide_pending_kegg

class KeggDisplayGateTests(unittest.TestCase):
    def test_proposed_is_not_confirmed_and_both_tables_are_hidden(self):
        info=kegg_display_status({"exclusions_confirmed":False},None,"run_a")
        self.assertFalse(info["kegg_ready"])
        special={"enrichment_graphs":{"go":{"url":"go"},"kegg":{"url":"old"}},"enrichment_display_tables":{"bp_top15":[1],"kegg_p_top10":[2],"kegg_count_top10":[3],"kegg_excluded":[]}}
        hide_pending_kegg(special,info)
        self.assertEqual(special["enrichment_graphs"],{"go":{"url":"go"}})
        self.assertEqual(special["enrichment_display_tables"],{"bp_top15":[1],"kegg_excluded":[]})

    def test_saved_unapplied_decision_or_busy_hides_previous_confirmed_graph(self):
        meta={"exclusions_confirmed":True,"decision_id":"older"}
        decision={"decision_id":"new","a05_run":"run_a"}
        self.assertFalse(kegg_display_status(meta,decision,"run_a")["kegg_ready"])
        self.assertFalse(kegg_display_status(meta,None,"run_a",busy=True)["kegg_ready"])

    def test_applied_zero_exclusions_and_revised_layout_preserve_valid_scope(self):
        meta={"exclusions_confirmed":True,"decision_id":"new"}
        decision={"decision_id":"new","a05_run":"run_old"}
        self.assertTrue(kegg_display_status(meta,decision,"run_a")["kegg_ready"])
        meta["decision_id"]=None
        self.assertTrue(kegg_display_status(meta,decision,"run_a")["kegg_ready"])

    def test_historical_confirmed_scope_remains_readonly_and_unconfirmed_history_hidden(self):
        d={"decision_id":"new","a05_run":"run_a"}
        self.assertTrue(kegg_display_status({"exclusions_confirmed":True},d,"run_a",historical=True,busy=True)["kegg_ready"])
        self.assertFalse(kegg_display_status({"exclusions_confirmed":False},d,"run_a",historical=True)["kegg_ready"])

    def test_other_modules_and_confirmed_payload_unchanged(self):
        special={"enrichment_graphs":{"kegg":{"url":"confirmed"}},"enrichment_display_tables":{"kegg_p_top10":[1]}}
        before=deepcopy(special)
        hide_pending_kegg(special,None);self.assertEqual(special,before)
        hide_pending_kegg(special,{"kegg_ready":True});self.assertEqual(special,before)

if __name__=="__main__":unittest.main()

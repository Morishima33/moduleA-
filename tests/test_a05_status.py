"""A05等待确认文案来自归档指标；不改变状态码、复核资格或其他模块。"""
import unittest
from modulea.core.status import map_state

class A05StatusTests(unittest.TestCase):
    def raw(self,**fields):
        return {"state":"awaiting_review","result":{"outcome":"success","summary":{"handoff_blocked":True,"display_version":"A05.display.2","display_exclusions_confirmed":False,"display_layout_confirmed":False,"display_missing_translation_count":0,"身份待核验数":0,**fields}}}
    def test_ready_data_waits_for_scope_and_layout_not_missing_data(self):
        s=map_state("A05",self.raw())
        self.assertEqual(s.code,"waiting");self.assertEqual(s.label_zh,"等待确认")
        self.assertIn("KEGG展示范围确认",s.reason_zh);self.assertIn("图表版式确认",s.reason_zh)
        self.assertTrue(s.handoff_blocked and s.can_review)
        self.assertEqual(s.raw_state,"awaiting_review")
    def test_missing_identity_and_chinese_remain_explicit(self):
        s=map_state("A05",self.raw(display_missing_translation_count=2,**{"身份待核验数":1}))
        self.assertEqual(s.label_zh,"等待身份核验");self.assertIn("2个条目中文核译",s.reason_zh);self.assertIn("1项身份核验",s.reason_zh)
    def test_other_modules_old_versions_and_unblocked_review_unchanged(self):
        self.assertEqual(map_state("A04",self.raw()).label_zh,"等待资料")
        old=self.raw();old["result"]["summary"].pop("display_version")
        self.assertEqual(map_state("A05",old).label_zh,"等待资料")
        self.assertEqual(map_state("A05",self.raw(handoff_blocked=False)).code,"review")

if __name__=="__main__":unittest.main(verbosity=2)

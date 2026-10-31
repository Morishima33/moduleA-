"""系统三库显示采用本版实际来源；不能从旧上传空清单误报缺库或放行待核。"""
from copy import deepcopy
import unittest
from modulea.presenters.sources import present_a01


class SystemComponentDisplayTests(unittest.TestCase):
    def sample(self):
        """虚构数量与归档协议，测试不读真实名单或改变状态。"""
        return {'summary':{'候选成分分组数':5,'结构键分组数':0,'结构待核分组数':5,
            '标准化基因数':7,'component_source_profile':'A01.system_publication.1',
            'source_binding_protocol':'A01.system_source_binding.1','handoff_blocked':True,
            '完整性待核项数':0,'未决身份组数':2},'tables':{}}

    def test_bound_source_marker_and_actual_blocker_counts_without_mutation(self):
        result=self.sample();before=deepcopy(result);view=present_a01(result,{})
        self.assertEqual(view.special['system_component_publication']['source_binding_protocol'],'A01.system_source_binding.1')
        blocker=view.focus[0];self.assertEqual(blocker['blocks'],['A03'])
        self.assertIn('完整性待核 0 项',blocker['body_zh']);self.assertIn('身份未决 2 组',blocker['body_zh'])
        self.assertIn('未决项不自动采用',blocker['body_zh']);self.assertEqual(result,before)

    def test_missing_or_other_protocol_cannot_claim_system_bound_sources(self):
        for profile,protocol in [('A01.multisource.collect.1','A01.system_source_binding.1'),
                                 ('A01.plan_publication.1','A01.system_source_binding.1'),
                                 ('A01.system_publication.1',None)]:
            with self.subTest(profile=profile,protocol=protocol):
                result=self.sample();result['summary'].update(component_source_profile=profile,source_binding_protocol=protocol)
                self.assertNotIn('system_component_publication',present_a01(result,{}).special)

    def test_missing_counts_do_not_invent_zero_and_unblocked_result_adds_no_blocker(self):
        result=self.sample();del result['summary']['完整性待核项数'];del result['summary']['未决身份组数']
        self.assertNotIn('0 项',present_a01(result,{}).focus[0]['body_zh'])
        self.assertNotIn('0 组',present_a01(result,{}).focus[0]['body_zh'])
        result['summary']['handoff_blocked']=False
        self.assertFalse(any(row['blocks'] for row in present_a01(result,{}).focus))

    def test_legacy_blocker_keeps_original_operation_message(self):
        result=self.sample();result['summary']['component_source_profile']='A01.multisource.collect.1'
        view=present_a01(result,{})
        self.assertEqual(view.focus[0]['body_zh'],'三库完整性待核 0 项，身份未决 2 组。请在本页资料区核对并保存处理；当前A02保持。')
        self.assertNotIn('system_component_publication',view.special)


if __name__=='__main__':unittest.main()

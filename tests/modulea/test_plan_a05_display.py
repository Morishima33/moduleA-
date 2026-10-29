"""A05新方案展示独立模型：真实数量、全量译名、分类待判断及原统计保持。"""
from copy import deepcopy
import unittest
from contracts import ContractError,fingerprint
from science_modules.analysis_protocol import compile_plan
from science_modules.a05.plan_display import build,make_source


def fixture(parameters=None,count=30):
    """纯模型测试的显著表为显式合成数据，不冒充实际R来源。"""
    plan=compile_plan({'mode':'personalized','parameters':parameters or {}})
    tables={};lexicon={}
    for offset,group in enumerate(('BP','CC','MF','KEGG')):
        included=plan['parameters']['a05.include_kegg' if group=='KEGG' else 'a05.include_go']
        rows=[]
        for index in range(count if included else 0):
            tid=f'hsa{index+1:05}' if group=='KEGG' else f'GO:{offset*1000+index+1:07}'
            name=f'Synthetic {group} term {index+1}'
            rows.append({'ID':tid,'Description':name,'Count':index+1,'p.adjust':.001+index*.00001,
                         'RichFactor':.1,'geneID':'1/2'})
            lexicon[tid]={'english':name,'zh':f'合成{group}条目{index+1}','source':'显式合成核译测试'}
        tables[group.lower()+'_significant']=rows
    base={'module_id':'A05','study_id':'study_synthetic','run_id':'run_synthetic',
          'summary':{'protocol_version':'A05.plan_enrichment.1','analysis_parameter_hash':plan['parameter_hash']},'tables':tables}
    catalog={'schema_version':'explicit_synthetic','pathways':{f'{index+1:05}':[{'category':'Cellular Processes','subcategory':'Synthetic','name':f'Synthetic KEGG term {index+1}'}] for index in range(count)}}
    source=make_source(base,plan,{},catalog=catalog,lexicon=lexicon)
    return base,plan,source


def decision(**changes):
    """明确展示决定不含人工A05批准。"""
    return dict({'excluded_ids':[],'uncertain_decisions':[],'translations':[],'confirmed':True},**changes)


class PlanA05DisplayTests(unittest.TestCase):
    def test_standard_dynamic_counts_and_count_ranking_share_scope(self):
        base,plan,source=fixture();before=fingerprint(base);value=build(base,plan,source)
        self.assertEqual(len(value['tables']['bp_display']),15);self.assertEqual(len(value['tables']['bp_plan_top']),15)
        self.assertEqual(len(value['tables']['kegg_display']),15);self.assertEqual(len(value['tables']['kegg_plan_top']),10)
        self.assertEqual(value['tables']['kegg_plan_count_top'][0]['Count'],30)
        self.assertFalse(value['ready_for_display']);self.assertFalse(value['scientific_approval'])
        self.assertEqual(fingerprint(base),before);self.assertTrue(build(base,plan,source,decision())['ready_for_display'])

    def test_go_twentyfive_translation_snapshot_is_not_legacy_fifteen(self):
        base,plan,source=fixture({'a05.go_plot_top':25,'a05.go_table_top':25,'a05.include_kegg':False})
        value=build(base,plan,source,decision())
        for group in ('bp','cc','mf'):
            self.assertEqual(len(value['tables'][group+'_plan_top']),25)
            self.assertTrue(all(r['translation_status']=='checked' for r in value['tables'][group+'_display']))
        self.assertEqual(len(source['translations']),90)
        self.assertIsNone(value['groups'][-1]['significant_count']);self.assertIsNone(value['groups'][-1]['plot_count'])
        self.assertEqual(value['tables']['kegg_catalog'],[]);self.assertEqual(value['missing_translations'],[])

    def test_missing_or_changed_english_stays_pending_and_cannot_approve(self):
        base,plan,source=fixture(count=2)
        source['translations']['GO:0000001']['english']='Different old English'
        value=build(base,plan,source,decision())
        row=value['tables']['bp_plan_top'][0];self.assertEqual(row['Description'],'Synthetic BP term 1')
        self.assertEqual(row['description_zh'],'');self.assertIn(row['ID'],value['missing_translations'])
        self.assertFalse(value['ready_for_display'])
        override={'ID':row['ID'],'english':row['Description'],'zh':'本研究明确核译','reason':'合成核译依据'}
        updated=build(base,plan,source,decision(translations=[override]))
        self.assertTrue(updated['ready_for_display']);self.assertEqual(updated['tables']['bp_plan_top'][0]['translation_source'],'本研究明确核译')
        for change in ({'english':'wrong'},{'reason':''},{'ID':'GO:unknown'}):
            with self.subTest(change=change),self.assertRaises(ContractError):build(base,plan,source,decision(translations=[dict(override,**change)]))

    def test_official_disease_proposal_is_not_automatically_excluded(self):
        base,plan,source=fixture(count=3)
        # 独立合成分类：疾病身份已核验且仅精确本病同名可保留，其他疾病只是拟排除。
        from science_modules.a05 import screening
        source['catalog']['pathways']['00001']=[{'category':'Human Diseases','subcategory':'Synthetic','name':'Another disease'}]
        source['identity']={'mesh_id':'D123456','verified':True,'names':['this disease']}
        source['assessments']=screening.assess(base['tables']['kegg_significant'],source['catalog'],source['identity'])
        before=fingerprint(base);value=build(base,plan,source)
        row=value['tables']['kegg_catalog'][0]
        self.assertTrue(row['proposed_exclusion']);self.assertFalse(row['excluded']);self.assertEqual(len(value['tables']['kegg_display']),3)
        confirmed=build(base,plan,source,decision(excluded_ids=['hsa00001']))
        self.assertEqual(confirmed['excluded_ids'],['hsa00001'])
        self.assertEqual(len(confirmed['tables']['kegg_display']),2)
        self.assertEqual({r['ID'] for r in confirmed['tables']['kegg_plan_count_top']},{'hsa00002','hsa00003'})
        self.assertEqual(fingerprint(base),before);self.assertEqual(len(base['tables']['kegg_significant']),3)

    def test_unknown_classification_can_be_explicitly_deferred_with_reason(self):
        base,plan,source=fixture(count=2)
        from science_modules.a05 import screening
        del source['catalog']['pathways']['00001']
        source['assessments']=screening.assess(base['tables']['kegg_significant'],source['catalog'],source['identity'])
        value=build(base,plan,source,decision());self.assertFalse(value['ready_for_display']);self.assertEqual(value['unresolved_classifications'],['hsa00001'])
        record={'ID':'hsa00001','decision':'defer','reason':'分类材料待补，展示暂不纳入，原统计保持'}
        deferred=build(base,plan,source,decision(uncertain_decisions=[record]))
        self.assertEqual(deferred['excluded_ids'],[]);self.assertEqual(deferred['deferred_ids'],['hsa00001'])
        self.assertEqual(len(deferred['tables']['kegg_display']),1);self.assertEqual(len(deferred['tables']['kegg_deferred']),1)
        self.assertTrue(deferred['ready_for_display']);self.assertFalse(deferred['scientific_approval'])
        with self.assertRaises(ContractError):build(base,plan,source,decision(excluded_ids=['hsa00001']))
        with self.assertRaises(ContractError):build(base,plan,source,decision(uncertain_decisions=[dict(record,reason='')]))

    def test_foreign_source_parameter_and_decision_injections_are_rejected(self):
        base,plan,source=fixture(count=2)
        changed=deepcopy(base);changed['tables']['bp_significant'][0]['Count']=999
        with self.assertRaises(ContractError):build(changed,plan,source)
        newplan=compile_plan({'mode':'personalized','parameters':{'a05.go_table_top':25}})
        with self.assertRaises(ContractError):build(base,newplan,source)
        for changes in ({'approved':True},{'confirmed':False},{'excluded_ids':['hsa99999']},{'excluded_ids':['hsa00001','hsa00001']}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):build(base,plan,source,dict(decision(),**changes))
        bad=deepcopy(source);bad['assessments']['hsa00001']['classification_status']='exclude'
        with self.assertRaises(ContractError):build(base,plan,bad)


if __name__=='__main__':unittest.main()

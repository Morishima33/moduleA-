"""展示包保留原集合/统计/NA的边界回归；合成输入只写独立临时目录，不生成Word。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import shutil
import unittest

from contracts import ContractError, fingerprint
from science_modules import presentation_revision as presentation
from science_modules.a05 import screening
from science_modules.a07 import plan_facts_v2, plan_figures_v2
from tests.modulea.test_plan_a05_display import fixture as enrichment_fixture
from tests.modulea.test_plan_report_facts import packet


def fixture():
    """显式合成三族GO和KEGG；附录含待分类项，2×2评分含NA及工具失败。"""
    base,plan,source=enrichment_fixture(count=3)
    del source['catalog']['pathways']['00003']
    source['assessments']=screening.assess(base['tables']['kegg_significant'],source['catalog'],source['identity'])
    for entry in source['translations'].values():
        entry['translation_basis']='本测试显式合成译名依据'
    lexicon=deepcopy(source['translations'])
    enrichment=plan_facts_v2.automatic_enrichment(base,plan,source)
    sid='study_synthetic';runs={'A03':'run_a03','A04':'run_a04','A05':base['run_id'],'A06':'run_a06'}
    a03={'module_id':'A03','study_id':sid,'run_id':runs['A03'],
         'summary':{'仅方剂靶点数':2,'交集靶点数':3,'仅疾病靶点数':4}}
    network={'tables':{'mapping':[{'target_id':key,'symbol':'GENE_'+key} for key in ('A','B','C')],
                       'edges':[{'source':'A','target':'B','combined_score':0.9},
                                {'source':'B','target':'C','combined_score':0.8}]}}
    selected={'degree_round2':[{'target_id':key} for key in ('A','B')]}
    raw=packet();raw.update(study_id=sid,run_id=runs['A06'])
    raw['compounds'][0]['name']='实际合成成分One'
    raw['compounds'][1]['name']='实际合成成分Two'
    docking=plan_facts_v2.docking(raw,{'version':'explicit_synthetic'})
    payload={'schema_version':'A07.plan_payload.2','study_id':sid,'run_ids':runs,'plan':plan,
             'counts':{'a01_genes':5,'a02_genes':7,'intersection':3},
             'sources':[{'name':'显式合成原始来源','run_id':'run_a04'}],
             'network':{'network_run_id':runs['A04'],'selection':selected,
                        'main':plan_figures_v2.network_scope(network,selected),
                        'overview':plan_figures_v2.network_scope(network,selected,overview=True)},
             'enrichment':enrichment,'docking':docking,'figures':[],'figure_source':None}
    return payload,a03,lexicon


class PresentationRevisionTests(unittest.TestCase):
    """图件只生成一次，独立测试通过隔离拷贝校验真实字节和故障门控。"""

    @classmethod
    def setUpClass(cls):
        cls.seed=TemporaryDirectory(prefix='presentation_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.payload,cls.a03,cls.lexicon=fixture()
        before=fingerprint([cls.payload,cls.a03,cls.lexicon])
        cls.folder=Path(cls.seed.name)/'new_bundle'
        cls.manifest=presentation.build_bundle(cls.payload,cls.a03,cls.folder,lexicon=cls.lexicon)
        cls.inputs_unchanged=before==fingerprint([cls.payload,cls.a03,cls.lexicon])

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='presentation_case_');self.addCleanup(self.temp.cleanup)
        self.target=Path(self.temp.name)/'bundle';shutil.copytree(self.folder,self.target)
        self.value=deepcopy(self.manifest)

    def validate(self,payload=None,a03=None,lexicon=None):
        """所有验证仍按独立原事实输入，不从被修改的展示索引回读事实。"""
        return presentation.validate_bundle(payload or self.payload,a03 or self.a03,self.target,self.value,
                                            lexicon=self.lexicon if lexicon is None else lexicon)

    def test_success_preserves_inputs_and_exports_only_display_files(self):
        self.assertTrue(self.inputs_unchanged)
        self.assertTrue(self.validate())
        self.assertFalse(self.value['word_generated']);self.assertFalse(self.value['human_review_written'])
        self.assertFalse(self.value['statistics_changed'])
        self.assertEqual(len(self.value['figures']),8)
        self.assertEqual({p.suffix for p in self.target.rglob('*') if p.is_file()},{'.png','.svg','.csv','.json'})
        json.dumps(self.value,ensure_ascii=False,allow_nan=False)

    def test_main_ppi_is_degree_second_round_and_full_graph_is_separate(self):
        self.assertEqual(self.value['counts']['degree_round2'],{'nodes':2,'edges':1,'isolates':0})
        self.assertEqual(self.value['counts']['full_network_overview'],{'nodes':3,'edges':2,'isolates':0})
        self.assertEqual([row['target_id'] for row in self.value['tables']['ppi_degree_round2_nodes']],['A','B'])
        figures=[row for row in self.value['figures'] if row['module']=='A04']
        self.assertEqual([row['role'] for row in figures],['degree_round2','full_network_overview'])
        self.assertNotEqual(figures[0]['scope_hash'],figures[1]['scope_hash'])

    def test_csv_keeps_raw_precision_missing_state_reason_and_input_order(self):
        with (self.target/'tables/a06_pairs.csv').open(encoding='utf-8-sig',newline='') as handle:
            rows=list(csv.DictReader(handle))
        self.assertEqual([row['compound_id'] for row in rows],['c1','c1','c2','c2'])
        self.assertEqual([row['score'] for row in rows],['-8.001','NA','-7.999','NA'])
        self.assertEqual([row['state'] for row in rows],['completed','NA','completed','failed'])
        self.assertEqual(rows[1]['reason_zh'],'固定身份未通过')
        self.assertEqual(rows[3]['reason_zh'],'工具输出不完整')
        data=json.loads((self.target/'presentation_data.json').read_text(encoding='utf-8'))
        self.assertEqual(data['tables']['a05_bp_display'][0]['p.adjust'],0.001)
        self.assertEqual(data['tables']['a05_bp_display'][1]['p.adjust'],0.00101)

    def test_labels_are_actual_names_and_venn_uses_bound_counts(self):
        matrix=(self.target/'figures/docking/scores_1_1.svg').read_text(encoding='utf-8')
        self.assertIn('实际合成成分One',matrix);self.assertIn('>T1<',matrix)
        self.assertIn('>NA<',matrix);self.assertNotIn('>0.00<',matrix)
        venn=(self.target/'figures/intersection.svg').read_text(encoding='utf-8')
        self.assertIn('>3<',venn);self.assertIn('方剂靶点 T = 5',venn);self.assertIn('疾病靶点 D = 7',venn)
        self.assertIn('面积仅示意',venn)

    def test_translation_audit_covers_appendix_with_ids_original_and_evidence(self):
        self.assertEqual(self.value['counts']['translation_terms'],12)
        self.assertEqual(self.value['counts']['translation_rows'],25)
        audit={row['ID']:row for row in self.value['translation_audit']}
        row=audit['hsa00003'];self.assertIn('kegg_deferred',row['tables'])
        self.assertEqual(row['english'],'Synthetic KEGG term 3')
        self.assertEqual(row['chinese'],'合成KEGG条目3')
        self.assertTrue(row['source']);self.assertTrue(row['translation_basis'])

    def test_unknown_or_changed_appendix_translation_blocks_before_creation(self):
        for change in ('missing','english','basis','placeholder','different_zh'):
            lexicon=deepcopy(self.lexicon)
            if change=='missing':del lexicon['hsa00003']
            elif change=='english':lexicon['hsa00003']['english']='Another term'
            elif change=='basis':lexicon['hsa00003']['translation_basis']=''
            elif change=='placeholder':lexicon['hsa00003']['zh']='中文待核译'
            else:lexicon['hsa00003']['zh']='不匹配已归档译名'
            target=Path(self.temp.name)/('blocked_'+change)
            with self.subTest(change=change),self.assertRaises(ContractError):
                presentation.build_bundle(self.payload,self.a03,target,lexicon=lexicon)
            self.assertFalse(target.exists())

    def test_caption_placeholder_and_missing_appendix_row_translation_block(self):
        for change in ('text','appendix'):
            payload=deepcopy(self.payload)
            if change=='text':payload['note_zh']='说明：译名待补'
            else:
                payload['enrichment']['tables']['kegg_deferred'][0]['chinese']=''
                payload['enrichment']['tables']['kegg_deferred'][0]['description_zh']=''
            with self.subTest(change=change),self.assertRaises(ContractError):self.validate(payload=payload)

    def test_table_and_image_translation_aliases_must_all_match_same_evidence(self):
        for key in ('chinese','description_zh','english','label','translation_source','translation_status'):
            payload=deepcopy(self.payload)
            payload['enrichment']['tables']['bp_display'][0][key]='伪造可见文字'
            with self.subTest(key=key),self.assertRaises(ContractError):self.validate(payload=payload)

    def test_wrong_counts_run_network_scope_and_receptor_matrix_are_rejected(self):
        for change in ('count','run','network','edge','matrix','group'):
            payload=deepcopy(self.payload)
            if change=='count':payload['counts']['intersection']=2
            elif change=='run':payload['run_ids']['A03']='other_run'
            elif change=='network':payload['network']['main']['nodes'].append(payload['network']['overview']['nodes'][-1])
            elif change=='edge':payload['network']['main']['edges']=[]
            elif change=='matrix':payload['docking']['matrix'][0]['cells'][1]['score']=0
            else:payload['enrichment']['groups'][0]['included']=False
            with self.subTest(change=change),self.assertRaises(ContractError):self.validate(payload=payload)

    def test_existing_output_is_not_overwritten(self):
        before={p.relative_to(self.target):sha256(p.read_bytes()).hexdigest() for p in self.target.rglob('*') if p.is_file()}
        with self.assertRaises(ContractError):presentation.build_bundle(self.payload,self.a03,self.target,lexicon=self.lexicon)
        self.assertEqual(before,{p.relative_to(self.target):sha256(p.read_bytes()).hexdigest() for p in self.target.rglob('*') if p.is_file()})

    def test_file_corruption_is_rejected(self):
        (self.target/'figures/intersection.svg').write_text('<svg>corrupt</svg>',encoding='utf-8')
        with self.assertRaises(ContractError):self.validate()

    def test_self_signed_na_zero_or_changed_reason_csv_is_still_rejected(self):
        path=self.target/'tables/a06_pairs.csv'
        raw=path.read_bytes().replace(b',NA,NA,',b',NA,0,')
        self.assertNotEqual(raw,path.read_bytes());path.write_bytes(raw)
        ref=next(row for row in self.value['files'] if row['path']=='tables/a06_pairs.csv')
        ref.update(bytes=len(raw),sha256=sha256(raw).hexdigest())
        with self.assertRaises(ContractError):self.validate()

    def test_forged_roles_scopes_names_paths_or_missing_download_block(self):
        original=deepcopy(self.value)
        for change in ('role','scope','caption','path','missing','extra'):
            self.value=deepcopy(original)
            if change=='role':self.value['figures'][1]['role']='full_network_overview'
            elif change=='scope':self.value['figures'][1]['scope_hash']=self.value['figures'][2]['scope_hash']
            elif change=='caption':self.value['figures'][0]['caption']='新一批结果'
            elif change=='path':self.value['figures'][0]['files']['png']='../old.png'
            elif change=='missing':self.value['files'].pop()
            else:self.value['files'].append(dict(self.value['files'][0],path='unrelated.png'))
            with self.subTest(change=change),self.assertRaises(ContractError):self.validate()

    def test_all_na_preparation_has_own_module_and_never_invents_scores(self):
        payload=deepcopy(self.payload);raw=packet();pairs=raw.pop('pairs')
        raw.update(study_id=payload['study_id'],run_id='run_prep',
                   planned_pairs=[dict(row,state='NA',score=None,reason_zh='合成固定对象准备失败') for row in pairs])
        payload['run_ids']['A06_PREP']='run_prep';payload['run_ids'].pop('A06')
        payload['docking']=plan_facts_v2.docking(raw,{},preparation_only=True)
        target=Path(self.temp.name)/'prep'
        value=presentation.build_bundle(payload,self.a03,target,lexicon=self.lexicon)
        self.assertEqual(value['figures'][-1]['module'],'A06_PREP')
        self.assertEqual(value['counts']['docking']['NA'],4)
        self.assertEqual(value['counts']['docking']['scored'],0)
        self.assertIn('本批无可用评分',(target/value['figures'][-1]['files']['svg']).read_text(encoding='utf-8'))


if __name__=='__main__':
    unittest.main()

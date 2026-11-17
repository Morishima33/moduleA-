"""真实合成R及公开展示决定验证A05模块投影，不伪造回执/validator或修改实际研究。"""
from copy import deepcopy
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,SkipTest
from unittest.mock import patch
from uuid import uuid4

from storage import file_record,write_json,read_json,verified_file
from modulea.api.module_display_read import project
from modulea.core import display_revisions,plan_a05,plan_a05_display
from modulea.api.server import App
from modulea.config import Settings
from tests.modulea.plan_report_fixture import prepare
from tests.modulea.test_plan_a05 import RSCRIPT,source


def install_translatable_synthetic_source(root,plan):
    """术语名沿产品词典，仅基因集使用既有明确合成fixture，不冒充官方注释。"""
    from science_modules.a05.display import LEXICON
    from science_modules.a05.plan_flow import legacy,groups
    lexicon=json.loads(LEXICON.read_text('utf-8'));value=source(plan)
    go=[key for key,entry in lexicon.items() if key.startswith('GO:') and entry.get('english') and entry.get('zh')
        and not entry.get('source_obsolete')][:4]
    kegg=[key for key,entry in lexicon.items() if key.startswith('hsa') and entry.get('english') and entry.get('zh')][:4]
    assert len(go)==len(kegg)==4
    for group,terms in value['annotations'].items():
        for row,tid in zip(terms,kegg if group=='KEGG' else go):
            row.update(id=tid,description=lexicon[tid]['english'])
    terms=value['annotations']['KEGG']
    value['kegg_sources']={'names':{'response_text':''.join(r['id']+'\t'+r['description']+'\n' for r in terms)},
        'links':{'response_text':''.join('hsa:'+gene+'\tpath:'+r['id']+'\n' for r in terms for gene in r['genes'])}}
    value['annotations']['KEGG']=legacy.kegg_terms(value['kegg_sources'])
    raw=gzip.compress(json.dumps(value,ensure_ascii=False).encode('utf-8'),mtime=0)
    path=root/'references'/('fixture_'+sha256(raw).hexdigest()+'.json.gz');path.write_bytes(raw)
    write_json(root/'environments'/('A05_plan_sources_'+'_'.join(groups(plan))+'.json'),
        file_record(root,path,'annotation_source'),replace=True)


class ModuleDisplayA05PublicTests(TestCase):
    def test_later_public_a05_decision_blocks_prior_module_projection_with_same_scientific_runs(self):
        if not RSCRIPT.is_file():raise SkipTest('需已配置现有Rscript；完整公开A05保护未验证')
        if len(display_revisions._fonts())!=2:raise SkipTest('需现有中文字体；完整公开A05图件未验证')
        with TemporaryDirectory(prefix='a05_module_public_') as directory:
            root=Path(directory);w,sid,draft,_=prepare(root,empty=False,multiple_targets=True)
            w.review(sid,w.load(sid)['current']['A03'],'approved','明确合成复核','仅隔离A05基线')
            install_translatable_synthetic_source(root,draft['plan']);info=plan_a05.info(w,sid)
            with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(RSCRIPT)}):
                w.publish_analysis_plan_a05(sid,{key:info[key] for key in plan_a05.FIELDS-{'reason'}}|
                    {'reason':'明确合成R统计，仅验证独立决定不得被模块投影忽略'})
            rid=w.load(sid)['current']['A05']
            w.review(sid,rid,'approved','明确合成复核','仅隔离已实际R复算的A05')
            info=w.analysis_plan_display_revision_info(sid);self.assertTrue(info['enabled'],info)
            receipt=w.publish_analysis_plan_display_revision(sid,{'request_id':'displayreq_'+uuid4().hex,
                'expected_input_hash':info['expected_input_hash'],'author':'明确合成展示测试',
                'note':'原统计和本批词典的真实图件归档，不生成Word','confirmed':True})
            # 公开begin仅登记未发表的并行分支，A05来源及父链保持不变。
            w.begin(sid,'A04',{}, {'version':'A04.plan_network.1'},'仅合成无关下游未发表')
            manifest=w.load(sid);value=project(w,manifest,'A05')
            self.assertIsNotNone(value,'实际A05图件应在独立决定前适用')
            self.assertEqual(value['record']['revision_id'],receipt['revision_id'])
            self.assertTrue(value['record']['figures']);self.assertFalse(value['record']['matches_input'])
            app=App(Settings(data_root=root,runtime_dir=root/'http_runtime'))
            page=app._json_read(sid,app.views.module,sid,'A05')
            self.assertEqual(page['display_revision']['module_current']['record']['revision_id'],receipt['revision_id'])
            def request():
                current=plan_a05_display.info(w,sid)
                return {key:current[key] for key in ('expected_a05','expected_display_id','expected_input_hash')}|{
                    'request_id':'a05displayreq_'+uuid4().hex,'author':'明确合成范围测试',
                    'note':'仅隔离独立范围决定，不是用户科研批准','confirmed':True}
            w.prepare_analysis_plan_a05_display(sid,request())
            self.assertIsNotNone(project(w,w.load(sid),'A05'),'仅准备资料尚未确认决定，应保持原适用投影')
            current=plan_a05_display.info(w,sid)['current'];home=w.location(sid)
            original=read_json(verified_file(home,current['source']))
            choices=[{'ID':tid,'decision':'defer','reason':'明确合成暂缓'} for tid,row in original['assessments'].items()
                if row['classification_status']=='uncertain']
            before={key:deepcopy(w.load(sid)[key]) for key in ('current','runs','reviews')}
            decision=w.confirm_analysis_plan_a05_display(sid,request()|{
                'excluded_ids':[],'uncertain_decisions':choices,'translations':[]})
            self.assertTrue(decision['decision'])
            self.assertEqual(before,{key:w.load(sid)[key] for key in before})
            self.assertTrue(w.active(w.load(sid),rid),'范围决定不应假冒科学运行失效')
            self.assertEqual(display_revisions.read_record(w,w.load(sid),manifest[display_revisions.INDEX][-1])['revision_id'],
                receipt['revision_id'],'旧原件仍应可读；只是不能作为当前范围的适用图件')
            self.assertIsNone(project(w,w.load(sid),'A05'),'旧图不能忽略后来明确的独立范围决定')
            page=app._json_read(sid,app.views.module,sid,'A05')
            self.assertIsNone(page['display_revision'],'实际当前模块入口不能继续返回旧范围投影')
            self.assertEqual(app.tasks.list(sid),[],'读取不应产生后台科研任务或批准')
            self.assertEqual(w.load(sid)[display_revisions.INDEX][-1]['path'],manifest[display_revisions.INDEX][-1]['path'])
            self.assertFalse(list(home.rglob('*.docx')))

"""已有展示按未变模块只读核验；整包来源及科研门槛保持。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from contracts import require
from ..core import display_revisions as core
from ..core.read_evidence import read_call
from ..core.system_validation import same_binding_after_first_approval
from .display_revisions import _current,_counts


def _json(workflow,manifest,reference):
    """复用原已列入单请求证据范围的严格JSON读取器。"""
    return read_call(core._json,workflow,manifest,reference)


def _scope(workflow,manifest,source,module_id):
    """从原运行父链取闭包；当前编号和登记必须逐项相同，不凭名称或数量猜测。"""
    runs={};visiting=set()
    def visit(module,rid):
        if module in visiting:raise ValueError('展示原来源父链存在循环')
        if module in runs:return runs[module]==rid
        if source['run_ids'].get(module)!=rid or manifest['current'].get(module)!=rid:return False
        expected=source['run_files'].get(rid)
        if not expected or not expected.get('result_file') or manifest['runs'].get(rid)!=expected:return False
        run=workflow.run(manifest,rid)
        if run['study_id']!=manifest['study_id'] or run['module_id']!=module:return False
        if workflow.result(manifest,rid) is None or not workflow.active(manifest,rid):return False
        visiting.add(module)
        if not all(visit(parent,parent_id) for parent,parent_id in run['parent_runs'].items()):return False
        visiting.remove(module);runs[module]=rid
        return True
    rid=source['run_ids'].get(module_id)
    if not rid or not visit(module_id,rid):return None
    plan=source['plan_file']
    if plan not in manifest.get('analysis_plan_records',[]):return None
    if workflow.run(manifest,rid)['inputs'].get('analysis_plan_file')!=plan:return None
    _json(workflow,manifest,plan)
    return runs


def _reviews(workflow,manifest,references,runs):
    """限定本模块闭包的原人工记录；沿已有首次通过兼容，不忽略后来的暂存或退回。"""
    selected=[];latest={}
    artifacts={workflow.run(manifest,rid)['artifact_id']:rid for rid in runs.values()}
    for ref in references:
        value=_json(workflow,manifest,ref)
        if value.get('run_id') in runs.values() or value.get('artifact_id') in artifacts:
            require(artifacts.get(value.get('artifact_id'))==value.get('run_id'),
                '展示来源人工意见的运行与产物归属不同')
            selected.append(ref);latest[value['artifact_id']]=value
    return selected,all(value.get('decision')=='approved' for value in latest.values())


def _a05_basis(workflow,manifest,source):
    """独立展示决定及原核译来源必须保持；不能用默认词典或不变run掩盖新决定。"""
    rid=source['run_ids']['A05']
    for ref in manifest.get('analysis_plan_a05_display_records',[]):
        value=_json(workflow,manifest,ref)
        if value.get('a05_run_id')==rid and value.get('decision'):return False
    basis=source.get('a05_basis')
    if not basis:return False
    if basis['kind']=='archived_report_source':
        payload=_json(workflow,manifest,basis['payload_file'])
        if payload.get('run_ids',{}).get('A05')!=rid or payload.get('plan_source')!=source['plan_file']:return False
        require(payload.get('source_evidence')==basis['evidence'],'原A05核译来源与归档报告不同')
        for ref in basis['evidence'].values():_json(workflow,manifest,ref)
        return True
    if basis['kind']=='repository_initial_source':
        root=Path(__file__).resolve().parents[2]/'science_modules/a05'
        return (sha256((root/'kegg_classification.json').read_bytes()).hexdigest()==basis['catalog_sha256']
            and sha256((root/'term_translations.json').read_bytes()).hexdigest()==basis['lexicon_sha256'])
    return False


def _record(workflow,manifest,item,module_id,runs):
    """格式沿原API，返回前严格裁剪模块、数量及下载，不把旧A06或整包混入当前页面。"""
    value=_current(workflow,manifest['study_id'],dict(item,matches_input=False))
    value['source_run_ids']=deepcopy(runs)
    value['figures']=[row for row in value['figures'] if row['module_id']==module_id]
    value['tables']=[row for row in value['tables'] if row['module_id']==module_id]
    bundle=_json(workflow,manifest,item['bundle_file']);counts=bundle['counts']
    keys={'A03':('a03',),'A04':('degree_round2','full_network_overview'),'A05':('translation_terms','translation_rows')}[module_id]
    value['counts']=_counts({key:counts[key] for key in keys if key in counts})
    if module_id!='A05':
        value['counts']=[row for row in value['counts'] if row['label_zh']!='核译独立条目／展示记录']
        value['translation_coverage']={'required':0,'verified':0,'missing':[]}
    downloads={row['url']:row for group in (*value['figures'],*value['tables']) for row in group['downloads']}
    value['downloads']=list(downloads.values())
    if not value['figures'] and not value['tables']:return None
    return value


def project(workflow,manifest,module_id):
    """只返回可证明与本模块当前来源一致的归档展示，不生成图件或签署。"""
    if module_id not in ('A03','A04','A05') or manifest.get('trashed'):return None
    for reference in reversed(manifest.get(core.INDEX,[])):
        item=read_call(core.read_record,workflow,manifest,reference)
        request=read_call(core.read_request,workflow,manifest,item['request_file']);source=request['binding']['source']
        runs=_scope(workflow,manifest,source,module_id)
        if runs is None:continue
        old_reviews,old_allowed=_reviews(workflow,manifest,source['reviews'],runs)
        current_reviews,current_allowed=_reviews(workflow,manifest,manifest.get('reviews',[]),runs)
        if not old_allowed or not current_allowed:return None
        if not read_call(same_binding_after_first_approval,workflow,manifest,
            {'run_ids':runs,'reviews':old_reviews},{'run_ids':runs,'reviews':current_reviews}):return None
        if module_id=='A05' and not _a05_basis(workflow,manifest,source):return None
        record=_record(workflow,manifest,item,module_id,runs)
        if record is None:continue
        return {'module_id':module_id,
            'note_zh':'本模块及其上游来源未变，沿用已登记图表与核译；不代表新A06已完成或科研复核通过。',
            'record':record}
    return None

"""新版A05分类与双语展示模型；只派生已落盘统计，不执行R、不改ORA/BH或批准。"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from contracts import fingerprint,require
from science_modules.analysis_protocol import checked_plan
from . import screening
from .display import english,translate,LEXICON

VERSION='A05.plan_display.1'
SOURCE_VERSION='A05.plan_display_source.1'
GROUPS=('BP','CC','MF','KEGG')


def significant(base):
    """只读四族完整显著表，不把未纳入类别当作已完成的零显著统计。"""
    require(base.get('module_id')=='A05' and base.get('summary',{}).get('protocol_version')=='A05.plan_enrichment.1',
            '仅支持实际新版A05统计，不套用旧固定参数结果')
    return {group:base['tables'][group.lower()+'_significant'] for group in GROUPS}


def make_source(base,plan,intake,*,catalog=None,lexicon=None):
    """固定本批全显著范围与原英文，GO前25及Count排名前移不会漏存译名来源。"""
    plan=checked_plan(plan);rows=significant(base)
    require(base['summary'].get('analysis_parameter_hash')==plan['parameter_hash'],'展示方案与实际统计参数不一致')
    catalog_raw=screening.CATALOG.read_bytes() if catalog is None else None
    lexicon_raw=LEXICON.read_bytes() if lexicon is None else None
    catalog=json.loads(catalog_raw.decode('utf8')) if catalog_raw is not None else deepcopy(catalog)
    lexicon=json.loads(lexicon_raw.decode('utf8')) if lexicon_raw is not None else deepcopy(lexicon)
    require(isinstance(catalog,dict) and isinstance(catalog.get('pathways'),dict) and isinstance(lexicon,dict),'分类或译名资料格式无效')
    ids={row['ID'] for values in rows.values() for row in values}
    identity=screening.disease_identity(intake)
    return {'schema_version':SOURCE_VERSION,'statistical_result_hash':fingerprint(base),'parameter_hash':plan['parameter_hash'],
            'catalog':catalog,'catalog_sha256':hashlib.sha256(catalog_raw).hexdigest() if catalog_raw is not None else fingerprint(catalog),
            'catalog_kind':'repository_snapshot' if catalog_raw is not None else 'explicit_fixture',
            'lexicon_sha256':hashlib.sha256(lexicon_raw).hexdigest() if lexicon_raw is not None else fingerprint(lexicon),
            'lexicon_kind':'repository_snapshot' if lexicon_raw is not None else 'explicit_fixture',
            'translations':{key:deepcopy(lexicon.get(key,{})) for key in sorted(ids)},'identity':identity,
            'classification_version':screening.VERSION,'assessments':screening.assess(rows['KEGG'],catalog,identity)}


def check_source(base,plan,source):
    """历史重放只用归档快照，不读取后来更新的全局分类和译名词典。"""
    plan=checked_plan(plan);rows=significant(base)
    require(source.get('schema_version')==SOURCE_VERSION and source.get('classification_version')==screening.VERSION,'展示来源版本不支持')
    require(source['statistical_result_hash']==fingerprint(base) and source['parameter_hash']==plan['parameter_hash']
            and base['summary']['analysis_parameter_hash']==plan['parameter_hash'],'展示来源、统计或方案已改变')
    ids={row['ID'] for values in rows.values() for row in values}
    require(set(source['translations'])==ids,'译名快照未覆盖本次完整显著集合')
    require(source['assessments']==screening.assess(rows['KEGG'],source['catalog'],source['identity']),'KEGG分类与归档目录或本病身份不一致')
    return plan,rows


def decision_values(rows,source,decision):
    """逐项登记展示范围与核译依据；未知项可明确暂缓，不能偷偷当保留/排除。"""
    if decision is None:return set(),{},deepcopy(source['translations']),False
    require(isinstance(decision,dict) and set(decision)=={'excluded_ids','uncertain_decisions','translations','confirmed'},'展示决定字段不完整或有未支持选项')
    require(decision['confirmed'] is True,'展示决定必须明确确认')
    excluded=decision['excluded_ids'];uncertain=decision['uncertain_decisions'];overrides=decision['translations']
    require(isinstance(excluded,list) and all(isinstance(t,str) for t in excluded) and len(excluded)==len(set(excluded)), '展示排除编号必须唯一')
    all_kegg={row['ID'] for row in rows['KEGG']}
    require(set(excluded)<=all_kegg,'排除项不属于本次完整显著KEGG集合')
    require(isinstance(uncertain,list) and isinstance(overrides,list),'待判断与核译决定须为列表')
    choices={}
    for item in uncertain:
        require(isinstance(item,dict) and set(item)=={'ID','decision','reason'},'待判断决定字段无效')
        tid=item['ID'];require(isinstance(tid,str) and tid in all_kegg and tid not in choices,'待判断编号未知或重复')
        require(source['assessments'][tid]['classification_status']=='uncertain','仅对实际待判断条目登记分类决定')
        require(item['decision'] in ('retain','exclude','defer') and isinstance(item['reason'],str) and 0<len(item['reason'].strip())<=2000,'待判断条目须明确保留/排除/暂缓和依据')
        choices[tid]=dict(item)
    for tid in excluded:
        if source['assessments'][tid]['classification_status']=='uncertain':
            require(tid in choices and choices[tid]['decision']=='exclude','待判断排除须有逐项明确依据')
    for tid,item in choices.items():
        require((item['decision']=='exclude')==(tid in excluded),'待判断决定与排除清单不一致')
    originals={row['ID']:row for values in rows.values() for row in values};translations=deepcopy(source['translations']);seen=set()
    for item in overrides:
        require(isinstance(item,dict) and set(item)=={'ID','english','zh','reason'},'核译决定字段无效')
        tid=item['ID'];require(isinstance(tid,str) and tid in originals and tid not in seen,'核译编号未知或重复')
        require(item['english']==english(originals[tid]),'核译英文必须与本次稳定编号的原文完全一致')
        require(all(isinstance(item[key],str) and 0<len(item[key].strip())<=2000 for key in ('zh','reason')),'中文核译和依据不能为空或超长')
        translations[tid]={'english':item['english'],'zh':item['zh'].strip(),'source':'本研究明确核译',
                           'translation_basis':item['reason'].strip()};seen.add(tid)
    return set(excluded),choices,translations,True


def build(base,plan,source,decision=None):
    """按本方案图/表独立数量派生展示，原统计始终完整保留在原结果文件。"""
    plan,rows=check_source(base,plan,source);p=plan['parameters']
    excluded,choices,translations,confirmed=decision_values(rows,source,decision)
    output={};states=[];required=[]
    deferred={tid for tid,row in choices.items() if row['decision']=='defer'}
    uncertain={tid for tid,row in source['assessments'].items() if row['classification_status']=='uncertain'}
    unresolved=sorted(uncertain-set(choices))
    for group in GROUPS:
        values=rows[group];included=p['a05.include_kegg' if group=='KEGG' else 'a05.include_go']
        require(included or not values,'未纳入类别不能出现显著结果')
        require(len({row['ID'] for row in values})==len(values),'显著表编号重复')
        require(all(math.isfinite(float(row['p.adjust'])) and 0<=float(row['p.adjust'])<p['a05.adjusted_p_max'] for row in values),'显著条目不符合本批严格BH阈值')
        ordered=sorted(values,key=lambda row:(float(row['p.adjust']),row['ID']))
        bilingual=[dict(translate(row,translations),english=english(row)) for row in ordered]
        kept=[row for row in bilingual if group!='KEGG' or row['ID'] not in excluded|deferred]
        graph_top=p['a05.kegg_plot_top' if group=='KEGG' else 'a05.go_plot_top']
        table_top=p['a05.kegg_table_top' if group=='KEGG' else 'a05.go_table_top']
        key=group.lower();output[key+'_display']=kept[:graph_top];output[key+'_plan_top']=kept[:table_top]
        required.extend(output[key+'_display']+output[key+'_plan_top'])
        if group=='KEGG':
            output['kegg_plan_count_top']=sorted(kept,key=lambda row:(-int(row['Count']),float(row['p.adjust']),row['ID']))[:table_top]
            required.extend(output['kegg_plan_count_top'])
            output['kegg_catalog']=[dict(row,**source['assessments'][row['ID']],proposed_exclusion=source['assessments'][row['ID']]['classification_status']=='exclude',
                excluded=row['ID'] in excluded,deferred=row['ID'] in deferred,decision=choices.get(row['ID'])) for row in bilingual]
            output['kegg_excluded']=[row for row in bilingual if row['ID'] in excluded]
            output['kegg_deferred']=[row for row in bilingual if row['ID'] in deferred]
        states.append({'group':group,'included':included,'significant_count':len(values) if included else None,
                       'retained_count':len(kept) if included else None,'plot_count':len(output[key+'_display']) if included else None,
                       'table_count':len(output[key+'_plan_top']) if included else None})
    missing=sorted({row['ID'] for row in required if row['translation_status']!='checked'})
    return {'schema_version':VERSION,'parameter_hash':plan['parameter_hash'],'tables':output,'groups':states,
            'missing_translations':missing,'unresolved_classifications':unresolved,'excluded_ids':sorted(excluded),'deferred_ids':sorted(deferred),
            'decisions_confirmed':confirmed,'ready_for_display':bool(confirmed and not missing and not unresolved),
            'scientific_approval':False,'statistics_changed':False,
            'note_zh':'分类与核译决定仅影响展示；完整显著统计、BH校正和A05人工复核保持原记录，富集不证明通路激活、抑制或疗效。'}

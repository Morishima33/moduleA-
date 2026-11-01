"""只读整理系统A01待核原件与原官方响应；不做科学映射、联网或决定。"""
import csv
import hashlib
import io
import json
import urllib.parse
from copy import deepcopy
from pathlib import PurePosixPath
from contracts import fingerprint,require
from storage import verified_file
from . import system_component_sources as sources

VERSION='A01.identity_evidence_view.1'
IDENTITY_LABELS={'unmapped':'原符号未匹配到人类基因','ambiguous_or_conflicting':'存在多个候选或身份冲突'}


def snapshot(m):
    """导出只绑定当前运行、来源及明确人工意见，拒绝刷新后的旧下载链接。"""
    return {'study_id':m['study_id'],'current':m['current'],'reviews':m.get('reviews',[]),
            'source_binding':m.get(sources.CURRENT),'trashed':bool(m.get('trashed')),
            'runs':{rid:m['runs'][rid] for rid in m['current'].values()}}


def read_bytes(home,ref):
    """解析/下载针对同一已核验字节，不能在核验后换入其他内容。"""
    raw=verified_file(home,ref).read_bytes()
    require(len(raw)==ref['bytes'] and hashlib.sha256(raw).hexdigest()==ref['sha256'],'核对原件指纹已改变')
    return raw


def build_units(result,slots,read,add_file):
    """仅按原字段分组和列出原文，不把查询返回候选转成已采用身份。"""
    issues=result['tables'].get('identity_decisions',[]);units={};named=set();missing=0;other=0
    tc=slots['TCMSP'];refs={ref['path']:ref for slot in slots.values() for ref in slot['files']}
    snapshot_ref=next((ref for ref in tc['files'] if ref['path']==tc['folder']+'/references/tcmsp_snapshot.tsv'),None)
    require(snapshot_ref is not None,'本版TCMSP原表未登记')
    table={line:row for line,row in enumerate(csv.DictReader(io.StringIO(read(snapshot_ref).decode('utf-8-sig')),delimiter='\t'),2)}
    snapshot_index=add_file(snapshot_ref,'TCMSP原始关系表')
    for issue in issues:
        key=issue['issue_key'];require(isinstance(key,str) and len(key)==64,'待核记录缺少原问题指纹')
        if 'source_line' in issue:
            line=issue['source_line'];require(type(line) is int and line in table,'TCMSP待核源行不在原表')
            row=table[line]
            require(row['MOLID']==issue['compound_id'] and row['Chinesename']==issue['herb']
                    and row['Organism']==issue['organism'],'TCMSP待核记录与原表行不一致')
            tid,name=row.get('raw_target_id',''),row.get('raw_target_name','')
            unit_key=('TCMSP',name) if tid and name else ('TCMSP_missing_target',key)
            if tid and name:named.add(name)
            else:missing+=1
            if unit_key not in units:
                unit={'database':'TCMSP','kind':'protein_query' if tid and name else 'source_without_target',
                      'raw_name':name,'raw_target_ids':[],'original_reason_zh':issue['reason'],
                      'records':[],'file_indices':[snapshot_index],'response_state':'not_applicable',
                      'response_records':None,'protein_candidates':[]}
                if tid and name:
                    query='(protein_name:"'+name.replace('"','')+'") AND (organism_id:9606) AND (reviewed:true)'
                    url='https://rest.uniprot.org/uniprotkb/search?'+urllib.parse.urlencode({'query':query,'format':'json','size':500})
                    token=hashlib.sha256(url.encode()).hexdigest();base=tc['folder']+'/original_requests/'+token
                    index,body=refs.get(base+'.json'),refs.get(base+'.bin')
                    require(bool(index)==bool(body),'原官方查询索引和原文不完整')
                    unit.update(query=query,original_url=url,response_state='not_archived')
                    if index:
                        request=json.loads(read(index));raw=read(body)
                        require(request['url']==url and request['payload'] is None and request['bytes']==len(raw)
                                and request['sha256']==hashlib.sha256(raw).hexdigest(),'原查询与响应指纹不同')
                        data=json.loads(raw);require(isinstance(data.get('results'),list),'原官方响应结构无法核对')
                        unit.update(response_state='archived_success',response_records=len(data['results']))
                        unit['protein_candidates']=[{
                            'accession':protein.get('primaryAccession',''),
                            'recommended_name':protein.get('proteinDescription',{}).get('recommendedName',{}).get('fullName',{}).get('value',''),
                            'alternative_names':[n.get('fullName',{}).get('value','') for n in protein.get('proteinDescription',{}).get('alternativeNames',[])],
                            'taxid':protein.get('organism',{}).get('taxonId'),
                            'genes':[g['geneName']['value'] for g in protein.get('genes',[]) if 'geneName' in g],
                        } for protein in data['results']]
                        unit['file_indices'] += [add_file(index,'原UniProt请求记录'),add_file(body,'原UniProt响应')]
                units[unit_key]=unit
            unit=units[unit_key]
            if tid and tid not in unit['raw_target_ids']:unit['raw_target_ids'].append(tid)
            unit['records'].append(deepcopy(issue))
        else:
            db=issue['database'];require(db in slots,'待核记录来源不在本版三库中');other+=1
            rawref=issue.get('source_ref','');name=rawref.split(':',1)[0]
            require(name.startswith('raw/') and '..' not in PurePosixPath(name).parts,'原来源引用格式错误')
            target=slots[db]['folder']+'/'+name.removeprefix('raw/');ref=refs.get(target)
            require(ref is not None,'待核关系原件不在本版来源索引')
            read(ref)
            unit_key=(db,issue.get('raw_symbol',''),issue.get('raw_target_id',''),rawref)
            units.setdefault(unit_key,{'database':db,'kind':'source_identity','raw_name':issue.get('raw_symbol',''),
                'raw_target_ids':[issue['raw_target_id']] if issue.get('raw_target_id') else [],
                'original_reason_zh':IDENTITY_LABELS.get(issue.get('identity_status'),'原记录状态：'+str(issue.get('identity_status','未注明'))),'records':[],
                'file_indices':[add_file(ref,'原来源关系文件')],'response_state':'not_applicable',
                'response_records':None,'protein_candidates':[]})['records'].append(deepcopy(issue))
    values=list(units.values())
    for unit in values:
        unit['unit_id']=fingerprint({'database':unit['database'],'kind':unit['kind'],'records':unit['records']})
        unit['record_count']=len(unit['records'])
    return values,{'source_rows':len(issues),'protein_query_groups':len(named),'source_without_target_rows':missing,
                   'other_identity_rows':other,'display_groups':len(values)}


def info(workflow,sid):
    """标准库读取当前A01及已绑定原件，结束时重核状态；不写文件或调用科学验证器。"""
    m=workflow.load(sid);rid=m['current'].get('A01');base={'schema_version':VERSION,'supported':False,'read_only':True,
        'study_id':sid,'expected_a01':rid,'expected_input_hash':fingerprint(snapshot(m)),
        'message_zh':'仅支持本版系统三库结果；本页不确认身份、不自动排除或批准。','units':[],'files':[],'stats':None}
    if not rid:return base
    run=workflow.run(m,rid);result=workflow.result(m,rid)
    if not result or run['config'].get('version')!='A01.system_publication.1':return base
    require(run['study_id']==sid and run['module_id']=='A01','A01运行归属不正确')
    home=workflow.location(sid);ref=run['inputs']['system_source_binding']
    binding=sources.read_record(workflow,m,ref)
    require(binding['study_id']==sid and run['inputs']['staging_file']==ref
            and binding['plan_file']==run['inputs']['analysis_plan_file']
            and binding['a00_run_id']==run['parent_runs']['A00'],'A01原件绑定与本版结果不同')
    files=[];positions={};checked={}
    def read(item):
        key=fingerprint(item)
        if key not in checked:checked[key]=read_bytes(home,item)
        return checked[key]
    def add_file(item,label):
        read(item);key=fingerprint(item)
        if key not in positions:
            positions[key]=len(files);files.append({'index':len(files),'label_zh':label,'file':deepcopy(item)})
        return positions[key]
    units,stats=build_units(result,{row['database']:row for row in binding['datasets']},read,add_file)
    require(fingerprint(snapshot(workflow.load(sid)))==base['expected_input_hash'],'核对期间研究版本已改变，请刷新')
    return dict(base,supported=True,units=units,stats=stats,files=files,
                message_zh='本页只整理本版待核原记录与已归档官方原文；返回条目数不代表可采用身份数，原有待核和复核状态保持。')


def export_csv(value):
    """每个原问题一行，分组不合并或丢弃issue_key及原字段。"""
    out=io.StringIO(newline='');writer=csv.writer(out)
    writer.writerow(['study_id','a01_run_id','input_hash','unit_id','database','raw_name','original_record_json'])
    for unit in value['units']:
        for row in unit['records']:writer.writerow([value['study_id'],value['expected_a01'],value['expected_input_hash'],unit['unit_id'],unit['database'],unit['raw_name'],json.dumps(row,ensure_ascii=False)])
    return out.getvalue().encode('utf-8-sig')

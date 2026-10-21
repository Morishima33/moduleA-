"""第三版来源：新策略绑定下复用同研究原件，追加共晶候选清单，不升级旧授权。"""
from collections import defaultdict
from copy import deepcopy
import json
import re
import urllib.error
from urllib.parse import quote, urlsplit
from contracts import require, fingerprint
from storage import file_record, verified_file, write_json, read_json, new_id, now
from .automatic_sources import Fetcher as OriginalFetcher, compound_source, connected_reference
from .automatic_rules import binding as original_binding
from .reference_rules import POLICY, VERSION


class Fetcher(OriginalFetcher):
    """每次失败独立归档；只重试网络、限流和服务器暂时错误。"""
    def get(self, url, suffix="json"):
        require(urlsplit(url).scheme == "https" and urlsplit(url).hostname in {
            "pubchem.ncbi.nlm.nih.gov","rest.genenames.org","rest.uniprot.org",
            "files.rcsb.org","data.rcsb.org","search.rcsb.org","alphafold.ebi.ac.uk"}, "只允许官方无凭据来源")
        require(not urlsplit(url).username and not urlsplit(url).password, "来源URL不能携带凭据")
        for attempt in range(POLICY["network_attempts"]):
            try:
                return super().get(url, suffix)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if isinstance(error, urllib.error.HTTPError) and error.code not in (408,429,500,502,503,504):
                    raise
                if attempt == POLICY["network_attempts"] - 1:
                    raise
                __import__('time').sleep(attempt+1)


def conformer(cif, chains):
    """选择完整一致的原始构象；并列固定排序，仅归入探索，不混合原子。"""
    import gemmi
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(cif).sole_block())
    require(len(st) == 1, "多模型来源未明确选择")
    groups = defaultdict(dict)
    for chain in st[0]:
        if chain.name not in chains:
            continue
        for residue in chain:
            for atom in residue:
                if atom.has_altloc():
                    groups[(chain.name,str(residue.seqid),atom.name)][atom.altloc] = atom.occ
    if not groups:
        return None, {"selection":None,"tie":False,"reason_zh":"原件没有替代构象"}
    common = set.intersection(*(set(row) for row in groups.values()))
    require(common, "没有覆盖全部替代原子的同一构象，保留待补")
    scores = {key:sum(row[key] for row in groups.values()) for key in common}
    require(all(__import__('math').isfinite(x) and x >= 0 for x in scores.values()), "占有率无效")
    ordered = sorted(scores,key=lambda key:(-scores[key],key))
    selected = ordered[0]
    tie = sum(value == scores[selected] for value in scores.values()) > 1
    return selected, {"selection":selected,"tie":tie,"occupancy_scores":scores,"reason_zh":"选择覆盖全部替代原子的最高总占有率构象；并列按字母固定，仅探索"}


def sequence_scope(cif, spec, official):
    """逐个实际蛋白残基与官方序列核对；截短不冒充全长，冲突不按计数猜测。"""
    import gemmi
    from .coverage_geometry import canonical_map
    require(official["primaryAccession"] == spec["uniprot"] and official["organism"]["taxonId"] == 9606, "官方人类UniProt身份不符")
    block = gemmi.cif.read_string(cif).sole_block()
    structure = gemmi.make_structure_from_block(block)
    require(len(structure) == 1, "多模型不能自动合并")
    sequence = official["sequence"]["value"]
    mapping = canonical_map(block,spec)
    modeled, unresolved = [], []
    for chain in structure[0]:
        if chain.name not in spec["chains"]:
            continue
        for residue in chain:
            if residue.entity_type != gemmi.EntityType.Polymer:
                continue
            index = mapping.get((chain.name,str(residue.seqid)))
            aa = gemmi.find_tabulated_residue(residue.name).one_letter_code
            require(index is not None and 1 <= index <= len(sequence), "存在不能映射至目标UniProt的已解析残基，包括未核定标签")
            require(aa and aa.upper() == sequence[index-1] and aa.isupper(), "实际坐标存在序列突变或非标准残基，不自动采用")
            modeled.append(index)
    require(modeled and len(modeled) == len(set(modeled)), "残基映射为空或重复")
    dif = block.get_mmcif_category("_struct_ref_seq_dif.")
    differences = [{k:v[i] for k,v in dif.items()} for i in range(len(dif.get("details",[]))) if dif.get("pdbx_pdb_strand_id",[""]*len(dif.get("details",[])))[i] in spec["chains"]]
    require(not any(re.search(r"mutation|conflict",str(row.get("details","")),re.I) for row in differences), "原件声明突变或冲突，不能作为无突变对象")
    return {"matched":True,"mapped_positions":sorted(modeled),"official_length":len(sequence),
        "full_length":set(modeled)==set(range(1,len(sequence)+1)),"differences":differences,
        "reason_zh":"实际坐标残基逐一匹配官方人类序列；缺失及功能域范围另行保留，不推定口袋完整"}


def pages(uniprot, fetch, progress):
    """完整分页，检测服务异常重复页；不以空网络响应当作查无结构。"""
    start, seen = 0, set()
    while True:
        query={"query":{"type":"terminal","service":"text","parameters":{"attribute":"rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession","operator":"exact_match","value":uniprot}},"return_type":"polymer_entity","request_options":{"paginate":{"start":start,"rows":POLICY["page_size"]},"sort":[{"sort_by":"rcsb_entry_info.resolution_combined","direction":"asc"}]}}
        response,_=fetch.get("https://search.rcsb.org/rcsbsearch/v2/query?json="+quote(json.dumps(query),safe=""))
        rows=response.get("result_set",[])
        total=response.get("total_count",0)
        require(isinstance(total,int) and total >= 0,"官方结构总数字段异常")
        require(rows or start >= total, "官方分页提前为空，检索未完整结束")
        progress(f"补查实验结构：第{start+1}项 / 官方共{total}项")
        for row in rows:
            key=row["identifier"]
            require(key not in seen,"官方分页重复，不能假装完成检索")
            seen.add(key)
            yield key
        start += len(rows)
        if start >= total:
            break


def experimental_candidates(row, uniprot, official, fetch, progress, skip=()):
    """逐实体、逐作者链核查；准备失败时可从同一来源继续寻找独立PDB。"""
    from docking_audit import receptor_identity
    from docking_receptor import inspect_structure
    rejected, tried, exhausted = [], 0, False
    try:
        for key in pages(uniprot,fetch,progress):
            pdb,eid=key.split('_')
            if pdb in skip:
                continue
            try:
                entity,_=fetch.get(f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb}/{eid}")
                chains=sorted(entity.get("rcsb_polymer_entity_container_identifiers",{}).get("auth_asym_ids",[]))
                require(chains,"实体没有作者链")
                text, record = None, None
                for chain in chains:
                    try:
                        require(re.fullmatch(r"[A-Za-z0-9]",chain),"作者链不适合现有准备工具")
                        identity=receptor_identity(entity,uniprot,chain)
                        require(identity["pdb_id"]==pdb and str(identity["entity_id"])==eid,"结构实体编号不符")
                        if text is None:
                            _,record=fetch.get(f"https://files.rcsb.org/download/{pdb}.cif","cif")
                            text=verified_file(fetch.root,record).read_text('utf-8')
                        alt,choice=conformer(text,[chain])
                        spec={"source_type":"experimental","pdb_id":pdb,"chains":[chain],"uniprot":uniprot,"pocket":"p2rank","altloc":alt}
                        scope=sequence_scope(text,spec,official)
                        inspection=inspect_structure(text,pdb,[chain])
                        tried+=1
                        yield {"spec":spec,"identity":[identity],"cif":record,"conformer":choice,"inspection":inspection,"sequence_scope":scope,"official_sequence":official}
                        break
                    except (ValueError,KeyError,TypeError) as error:
                        rejected.append({"candidate":key,"chain":chain,"reason_zh":str(error)})
            except Exception as error:
                rejected.append({"candidate":key,"reason_zh":str(error)})
        exhausted=True
    finally:
        path=fetch.folder/(new_id('inspection')+'.json')
        write_json(path,{"target_id":row['target_id'],"yielded":tried,"rejected":rejected,"exhausted":exhausted})
        fetch.records.append(file_record(fetch.root,path,'structure_rejections'))


def published_model(row, uniprot, official, fetch):
    """只读取已发布模型、完整序列、逐残基pLDDT和PAE；不运行预测模型。"""
    import gemmi
    rows,metadata_record=fetch.get('https://alphafold.ebi.ac.uk/api/prediction/'+uniprot)
    require(isinstance(rows,list),"预测模型元数据异常")
    rows=[r for r in rows if r.get('uniprotAccession')==uniprot]
    require(len(rows)==1,"没有唯一已发布模型，不能任意拼接片段")
    info=rows[0]
    _,record=fetch.get(info['cifUrl'],'cif')
    pae,pae_record=fetch.get(info['paeDocUrl'])
    text=verified_file(fetch.root,record).read_text('utf-8')
    st=gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    require(len(st)==1 and len(st[0])==1,"预测模型不是明确单模型单链")
    chain=st[0][0]
    residues=[r for r in chain if r.entity_type==gemmi.EntityType.Polymer]
    start,end=info['uniprotStart'],info['uniprotEnd']
    require(official['primaryAccession']==uniprot and official['organism']['taxonId']==9606,"预测模型目标身份不符")
    seq=''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in residues)
    require(seq==official['sequence']['value'][start-1:end] and len(seq)==end-start+1,"预测模型序列不能逐残基匹配")
    scores=[next(a.b_iso for a in r if a.name=='CA') for r in residues]
    matrix=pae[0]['predicted_aligned_error']
    require(len(matrix)==len(scores) and all(len(r)==len(scores) for r in matrix),"PAE范围不完整")
    spec={"source_type":"alphafold","uniprot":uniprot,"chains":[chain.name],"model_id":info['entryId'],"sequence_start":start,"sequence_end":end,"pocket":"p2rank","altloc":None}
    return {"spec":spec,"cif":record,"identity":[{"identity_check":"matched","uniprot":uniprot}],"conformer":{"selection":None},"sequence_scope":{"matched":True,"full_length":start==1 and end==len(official['sequence']['value'])},"official_sequence":official,
        "confidence":{"plddt":scores,"pae":matrix},"pae_file":pae_record,"model_metadata":info,"model_metadata_file":metadata_record,"scope_zh":"已发布预测模型，仅探索；置信度仍待实际区域核验"}


def receptor_sources(row, fetch, progress):
    """先取同身份实验候选；完整检索无可用对象时连接已发布模型备选。"""
    hgnc,_=fetch.get('https://rest.genenames.org/fetch/hgnc_id/'+quote(row['target_id'],safe=''))
    docs=hgnc.get('response',{}).get('docs',[])
    require(len(docs)==1 and docs[0].get('hgnc_id')==row['target_id'] and docs[0].get('status')=='Approved',"HGNC身份未唯一核实")
    ids=docs[0].get('uniprot_ids',[])
    require(len(ids)==1,"HGNC没有唯一UniProt身份")
    uniprot=ids[0]
    official,official_record=fetch.get('https://rest.uniprot.org/uniprotkb/'+uniprot+'.json')
    candidates=[]
    iterator=experimental_candidates(row,uniprot,official,fetch,progress)
    try:
        for candidate in iterator:
            candidates.append(candidate)
            if len(candidates)>=POLICY['structures_per_target']:
                break
    finally:
        iterator.close()
    if not candidates:
        progress('实验来源未接上，连接已发布预测模型：'+row['symbol'])
        candidates.append(published_model(row,uniprot,official,fetch))
    candidates=[dict(c,official_sequence_file=official_record) for c in candidates]
    return {**row,'state':'connected','identity_matched':True,'uniprot':uniprot,'official_sequence':official,'official_sequence_file':official_record,'candidates':candidates,'reason_zh':'连接不等于质控通过；准备失败将继续独立替代来源和探索路线'}


def connect(workflow, sid, payload, progress):
    """复用同研究同批准的成功原件，只补查异常；新策略连接与授权独立留存。"""
    manifest,bound=workflow.automatic_binding(sid,payload['expected_binding'])
    existing=workflow.automatic_record(manifest,payload['connection_id'])
    if existing:
        return existing
    candidate_binding=workflow.candidate_binding(manifest)
    if workflow.candidate_record(manifest,candidate_binding)[0] is None:
        workflow.generate_candidates(sid,{**candidate_binding,'group_id':new_id('group'),'reason':'补齐连接沿用当前已批准A04名单'})
    from .plan_adapter import source_context
    manifest=workflow.load(sid);context=source_context(workflow,sid,manifest)
    require(all(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',r['compound_id']) for r in context['compounds']),"成分编号不能用于安全目录")
    root=workflow.location(sid)
    fetch=Fetcher(root,root/'raw/A06_automatic'/payload['connection_id']/new_id('attempt'))
    reusable=None
    old_key=fingerprint(original_binding(workflow,manifest))
    from .automatic_coverage_rules import binding as coverage_binding
    coverage_key=fingerprint(coverage_binding(workflow,manifest))
    for row in reversed(manifest.get('automatic_connections',[])):
        if row['binding'] not in (payload['expected_binding'],old_key,coverage_key):
            continue
        old=read_json(verified_file(root,row['packet']))
        require(old['study_id']==sid,"连接资料跨研究")
        for f in row['files']:
            verified_file(root,f)
        reusable=old
        fetch.records.extend(row['files']);fetch.records.append(row['packet'])
        break
    compounds,receptors,exceptions=[],[],[]
    for kind,rows,output in (('compound',context['compounds'],compounds),('receptor',context['receptors'],receptors)):
        for row in rows:
            progress('连接补齐：'+row.get('name',row.get('symbol','')))
            identity=row.get('compound_id',row.get('target_id'))
            previous=next((r for r in (reusable or {}).get('compounds' if kind=='compound' else 'receptors',[]) if r.get('compound_id',r.get('target_id'))==identity and r['state']=='connected'),None)
            try:
                if previous:
                    output.append(dict(deepcopy(previous),reused_connection=(reusable or {})['id']))
                else:
                    output.append(compound_source(row,fetch) if kind=='compound' else receptor_sources(row,fetch,progress))
            except Exception as error:
                state='failed' if isinstance(error,(OSError,urllib.error.URLError)) else 'unavailable'
                output.append(dict(row,state=state,reason_zh=str(error),candidates=[]))
                exceptions.append({'id':identity,'kind':kind,'name':row.get('name',row.get('symbol')),'state':state,'reason_zh':str(error)})
    files=list({r['path']:r for r in fetch.records}.values())
    packet={'schema_version':VERSION,'id':payload['connection_id'],'study_id':sid,'binding':fingerprint(bound),'context':context,'created_at':now(),'policy':POLICY,'compounds':compounds,'receptors':receptors,'exceptions':exceptions,'files':files,
        'counts':{'compounds':len(compounds),'receptors':len(receptors),'pairs':len(compounds)*len(receptors)},'summary':{'connected_compounds':sum(r['state']=='connected' for r in compounds),'connected_receptors':sum(r['state']=='connected' for r in receptors),'exceptions':len(exceptions)},
        'objects':[{'id':r.get('compound_id',r.get('target_id')),'kind':kind,'name':r.get('name',r.get('symbol')),'state':r['state'],'reason_zh':r.get('reason_zh',''),'structures':[c['spec'] for c in r.get('candidates',[])],'cid':r.get('cid')} for kind,rows in (('compound',compounds),('receptor',receptors)) for r in rows]}
    from .reference_candidates import discover
    packet['reference_candidates']=discover(root,packet)
    return workflow.save_automatic_connection(sid,payload['expected_binding'],packet,files)

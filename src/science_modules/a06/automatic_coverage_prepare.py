"""自动补救编排：严格共晶不放宽，有限修补、替代结构及预测模型仅单列探索。"""
from copy import deepcopy
from pathlib import Path
from contracts import require
from storage import verified_file, file_record, write_json, new_id
from .automatic_coverage_sources import Fetcher, experimental_candidates, published_model, sequence_scope


def region_confidence(origin, region, protein):
    """逐区域读取实际映射残基的置信度，不用全蛋白平均值替代。"""
    from .two_pass import confidence
    from .trial_prepare import _pdb_atoms
    from .quality_engine import inside_box
    import gemmi
    st=gemmi.make_structure_from_block(gemmi.cif.read_string(origin['cif_text']).sole_block())
    mapping={(c.name,str(r.seqid)):i for c in st[0] for i,r in enumerate([r for r in c if r.entity_type==gemmi.EntityType.Polymer])}
    from docking_p2rank import _residue_keys
    if region.get('prediction'):
        keys=_residue_keys(region['prediction']['residue_ids'])
    else:
        keys={(a['chain'],a['residue']) for a in _pdb_atoms(protein) if inside_box(a['xyz'],region)}
    require(keys and all(k in mapping for k in keys),'预测区域残基不能完整映射到模型')
    return confidence(dict(origin['confidence'],pocket_indices=sorted({mapping[k] for k in keys})))


def heavy_atoms(text):
    """以同一作者链、残基和原子名验证原重原子坐标保持。"""
    values={}
    for line in text.splitlines():
        if line.startswith(('ATOM  ','HETATM')) and line[76:78].strip() not in ('H','D'):
            key=(line[21],line[22:27].strip(),line[12:16].strip())
            require(key not in values,'存在未消除的替代构象原子')
            values[key]=[float(line[i:i+8]) for i in (30,38,46)]
    return values


def check_exploration(root, origin, prepared):
    """从归档原件重核修补、完整区域、必要环境和预测置信度；不执行科学工具。"""
    from .coverage_geometry import audit
    from .trial_prepare import prediction_rows, regions_from_predictions, coordinates
    from .trial_rules import partitions
    from .automatic_coverage_sources import sequence_scope
    from docking_p2rank import _residue_keys
    source=verified_file(root,origin['cif']).read_text('utf-8')
    spec=origin['spec']
    require(spec==prepared['spec'] and prepared['source']==origin['cif'],'补救准备结构与原件不一致')
    from storage import read_json
    require(read_json(verified_file(root,origin['official_sequence_file']))==origin['official_sequence'],'官方序列与归档原件不一致')
    import gemmi
    from docking_top10_execute import _protein_pdb
    converted=verified_file(root,prepared['original_conversion'])
    require(converted.read_text('ascii')==gemmi.make_structure_from_block(gemmi.cif.read_string(source).sole_block()).make_pdb_string(),'原坐标转换不是同一官方原件')
    require(_protein_pdb(converted,spec['chains'],spec.get('altloc'))==verified_file(root,prepared['repair_input']).read_text('ascii'),'有限修补输入不是所选原始链及构象')
    if spec['source_type']=='experimental':
        require(sequence_scope(source,spec,origin['official_sequence'])==origin['sequence_scope'],'实际序列映射依据不一致')
    else:
        import gemmi
        from storage import read_json
        st=gemmi.make_structure_from_block(gemmi.cif.read_string(source).sole_block())
        residues=[r for c in st[0] for r in c if r.entity_type==gemmi.EntityType.Polymer]
        require(len(st)==1 and len(st[0])==1,'预测来源多模型或多链')
        expected=origin['official_sequence']
        require(origin['model_metadata'] in read_json(verified_file(root,origin['model_metadata_file'])),'模型元数据与原始来源不一致')
        require(expected['primaryAccession']==spec['uniprot'] and expected['organism']['taxonId']==9606,'预测来源目标身份不符')
        sequence=''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in residues)
        require(sequence==expected['sequence']['value'][spec['sequence_start']-1:spec['sequence_end']],'预测坐标序列与目标不一致')
        scores=[next(a.b_iso for a in r if a.name=='CA') for r in residues]
        require(scores==origin['confidence']['plddt'] and read_json(verified_file(root,origin['pae_file']))[0]['predicted_aligned_error']==origin['confidence']['pae'],'预测置信度与原件不一致')
    before=heavy_atoms(verified_file(root,prepared['repair_input']).read_text('ascii'))
    repaired=verified_file(root,prepared['repair_output']).read_text('ascii')
    after=heavy_atoms(repaired)
    require(before and all(k in after and after[k]==v for k,v in before.items()),'有限修补改变原已解析重原子')
    added={k:v for k,v in after.items() if k not in before}
    require(not any(k[2] in ('N','CA','C','O','OXT') for k in added),'有限修补新增主链，禁止采用')
    proof={(r['chain'],r['residue'],r['atom']):r['xyz'] for r in prepared['repair']['added_atoms']}
    require(proof==added and prepared['repair']['original_coordinates_unchanged'] is True,'修补声明与实际坐标不一致')
    if spec['pocket']=='reference':
        from docking_top10_execute import _box_from_lines
        reference=verified_file(root,prepared['reference_coordinates']).read_text('ascii')
        regions=[dict(_box_from_lines(reference),region_id='fixed_site')]
        mode='fixed_site'
    else:
        files=prepared['prediction_files']
        require(len(files)==2,'缺少两次完整预测表')
        rows=[prediction_rows(verified_file(root,r)) for r in files]
        require(rows[0]==rows[1],'两次完整预测不一致')
        regions,_=regions_from_predictions(repaired,rows[0])
        mode='predicted_sites'
        if not regions:
            regions=partitions(coordinates(verified_file(root,prepared['receptor']).read_text('ascii')))
            mode='partitioned_blind'
    require(mode==prepared['mode'],'搜索路线与原始预测不一致')
    usable, rejected=[],[]
    for region in regions:
        try:
            pocket_keys=_residue_keys(region['prediction']['residue_ids']) if region.get('prediction') else None
            environment=audit(source,spec,region,pocket_keys)
            require(environment['environment_resolved'],'必要伙伴、金属或未知伴随组分尚未解决')
            require(not environment['retained_cofactors'] and not environment['retained_partner_chains'],'本次蛋白单体准备不能丢弃必要金属或组装伙伴，转入独立候选')
            require(not environment['unobserved_residues'],'原件有未解决的主链/残基缺失，不以侧链修补代替')
            missing=environment['missing_pocket_atoms']
            require(all((r['chain'],r['sequence'],r['atom']) in added for r in missing),'口袋缺原子未在实际修补输出中补齐')
            region=dict(region,environment=environment)
            if spec['source_type']=='alphafold':
                facts=region_confidence(dict(origin,cif_text=source),region,repaired)
                require(facts['passed'],'预测模型该区域未达到80／70／10置信度')
                region['confidence']=facts
            usable.append(region)
        except ValueError as error:
            rejected.append({'region_id':region['region_id'],'reason_zh':str(error)})
    require(usable,'所有预定区域均未通过环境、完整性或预测置信度核验')
    return usable,rejected


def explore(root, row, origin, folder, tools, repair_packages, code):
    """复用已批准的有限侧链准备和全预测/盲搜函数，额外逐区域复核，不升格严格。"""
    from .trial_prepare import candidate
    require(repair_packages and Path(repair_packages).is_dir(),'未配置固定有限修补依赖目录，不能声称完成补救')
    if origin['spec']['source_type']=='experimental':
        text=verified_file(root,origin['cif']).read_text('utf-8')
        origin=dict(origin,sequence_scope=sequence_scope(text,origin['spec'],origin['official_sequence']))
    adapted={'spec':origin['spec'],'source_file':origin['cif'],'source_audit':{'identity':origin['identity']}}
    prepared=candidate(root,row,adapted,folder,tools,Path(repair_packages),code)
    prepared.update(repair_input=file_record(root,folder/'observed_protein.pdb','observed_input'),
        original_conversion=file_record(root,folder/'source_conversion.pdb','source_conversion'),
        repair_output=file_record(root,folder/'repaired_protein.pdb','repaired_output'),origin=origin,
        prediction_files=[file_record(root,p,'p2rank_prediction') for directory in sorted(folder.glob('p2rank_*')) for p in sorted(directory.rglob('*_predictions.csv'))])
    if origin['spec']['pocket']=='reference':
        prepared['reference_coordinates']=file_record(root,folder/'reference_coordinates.pdb','reference_coordinates')
    regions,rejected=check_exploration(root,origin,prepared)
    prepared.update(regions=regions,rejected_regions=rejected,quality='探索',reason_zh='独立补救探索：结构、修补及各区域证据已归档；不代表严格质控通过')
    return prepared


def prepare(workflow, sid, connection, row, folder, tools, repair_packages, code, authorization_id, progress):
    """先检查已连接候选，再分页补查，最后用已发布模型探索，所有失败留因。"""
    from .automatic_engine import preparation_source
    from .quality_engine import attempt
    from .automatic_rules import assess as original_assess
    root=workflow.location(sid)
    attempts=[]
    value=dict(row,state='NA',quality='未通过',reason_zh=row.get('reason_zh',''),attempts=attempts)
    if row['state']!='connected':
        value['state']='failed' if row['state']=='failed' else 'NA'
        return value
    uniprot=row.get('uniprot') or row['candidates'][0]['spec']['uniprot']
    fetch=Fetcher(root,folder/'supplemental_sources')
    official=row.get('official_sequence')
    official_record=row.get('official_sequence_file')
    known=set()
    serial=0
    def use(origin):
        """同一候选只执行一次；严格参考优先，其余只作为补救探索。"""
        nonlocal serial,official,official_record
        serial+=1
        spec=origin['spec']
        progress('结构补救：'+row['symbol']+' / '+spec.get('pdb_id',spec.get('model_id','')))
        trace={'candidate':origin}
        if spec['source_type']=='experimental':
            known.add(spec['pdb_id'])
        try:
            if spec['source_type']=='experimental' and spec['pocket']=='reference':
                adapted=dict(connection,receptors=[dict(row,candidates=[origin])])
                evidence=attempt(root,preparation_source(adapted),row,spec,1,folder/f'strict_{serial:04d}',tools,progress)
                result=original_assess(spec,evidence,authorization_id,row)
                trace['evidence']=evidence
                if result['state']=='ready' and result['quality']=='严格':
                    value.update(state='ready',quality='严格',selected_candidate=origin,evidence=evidence,regions=[dict(evidence['box'],region_id='fixed_site')],mode='fixed_site',receptor=evidence['receptor'],reason_zh=result['reason_zh'])
                    attempts.append(trace)
                    return True
            if official is None or official_record is None:
                official,official_record=fetch.get('https://rest.uniprot.org/uniprotkb/'+uniprot+'.json')
            origin=dict(origin,official_sequence=official,official_sequence_file=official_record)
            prepared=explore(root,row,origin,folder/f'exploration_{serial:04d}',tools,repair_packages,code)
            trace['prepared']=prepared
            value.update(prepared,selected_candidate=prepared['origin'],evidence=prepared,attempts=attempts)
            attempts.append(trace)
            return True
        except Exception as error:
            trace['reason_zh']=str(error)
            value['reason_zh']=str(error)
            attempts.append(trace)
            write_json(folder/f'failure_{serial:04d}.json',trace)
            return False
    for origin in row.get('candidates',[]):
        if use(origin):
            return value
    try:
        if official is None:
            official,_=fetch.get('https://rest.uniprot.org/uniprotkb/'+uniprot+'.json')
        iterator=experimental_candidates(row,uniprot,official,fetch,progress,known)
        try:
            for origin in iterator:
                if use(origin):
                    return value
        finally:
            close=getattr(iterator,'close',None)
            if close:
                close()
    except Exception as error:
        attempts.append({'reason_zh':'补充实验检索异常：'+str(error)})
    try:
        require(official is not None,'缺少官方序列，不能采用预测模型')
        origin=published_model(row,uniprot,official,fetch)
        if use(origin):
            return value
    except Exception as error:
        attempts.append({'reason_zh':'已发布预测模型补救失败：'+str(error)})
    value.update(state='NA',reason_zh='已完成本轮实验候选及预测模型补救；仍有未解决条件，详见逐项依据')
    write_json(folder/'final_failure.json',{'target_id':row['target_id'],'attempts':attempts})
    return value

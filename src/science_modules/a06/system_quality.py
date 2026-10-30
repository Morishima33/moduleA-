"""新系统资格的独立规则：真实结构证据与一次批次授权，不制造人工口袋确认。"""
from copy import deepcopy
from contracts import require
from .two_pass import confidence,pocket_key

VERSION='A06.system_quality.1'


def assess(spec,evidence,target,config):
    """严格参考保持原规则；预测路线只有全部证据明确时按新系统规则记为探索。"""
    from .plan_preparation_v2 import assess_plan_attempt
    if spec.get('pocket')=='reference':return assess_plan_attempt(spec,evidence,target,1,config)
    output={'round':2,'state':'failed','quality':'无法计算','source_type':spec.get('source_type'),
        'structure_id':spec.get('pdb_id',spec.get('model_id','')),'rmsd':None,'reason_zh':'资格证据尚未完整'}
    try:
        require(spec['pocket']=='p2rank' and spec['source_type'] in ('experimental','alphafold'),'系统探索只接受已归档实验或已发布预测模型')
        identity=evidence.get('identity',{})
        require(identity.get('target_id')==target['target_id'] and identity.get('uniprot')==spec['uniprot']
            and identity.get('species')==9606 and identity.get('polymer_type')=='Protein'
            and identity.get('sequence_matches') is True and identity.get('chains')==spec['chains'],'蛋白身份、物种或序列不符')
        require(evidence.get('structure_id')==output['structure_id'],'资格证据不属于所选结构')
        require(evidence.get('pocket_complete') is True and evidence.get('environment_resolved') is True,'口袋不完整或必要环境尚未解决')
        require(evidence.get('receptor_ready') is True,'受体尚未成功准备')
        pocket=evidence.get('pocket',{})
        require(pocket.get('rank')==1 and isinstance(pocket.get('runs'),list) and len(pocket['runs'])==2
            and pocket['runs'][0]==pocket['runs'][1] and pocket['runs'][0],'P2Rank首位口袋两次结果不一致或缺证据')
        require(evidence.get('predicted_pocket',{}).get('files') and evidence['predicted_pocket'].get('input_pdb'),
            '预测资格缺少两次原文件或实际输入结构')
        if spec['source_type']=='alphafold':
            data=evidence.get('confidence',{})
            require(identity.get('sequence_start')==spec['sequence_start'] and identity.get('sequence_end')==spec['sequence_end']
                and len(data.get('plddt',[]))==spec['sequence_end']-spec['sequence_start']+1,'模型序列范围与置信度记录不符')
            require(data.get('pocket_indices')==pocket.get('mapped_indices'),'置信度残基不属于首位预测口袋')
            output['confidence']=confidence(data);require(output['confidence']['passed'],'AlphaFold口袋置信度未达到项目探索阈值')
        return dict(output,state='ready',quality='探索',reason_zh='本批系统规则核验首位预测口袋两次一致；无可靠参考配体，RMSD不适用',
            system_decision={'schema_version':VERSION,'authority_kind':'system_validation','pocket_key':pocket_key(spec,pocket),
                'human_review_written':False,'basis_zh':'明确批次授权及实际结构/两次原始预测/口袋环境证据'})
    except (ValueError,KeyError,TypeError) as error:return dict(output,reason_zh=str(error))


def qualify(fact):
    """仅从原完整准备证据派生资格，不重做下载/预测/重对接，不更换对象。"""
    rows=deepcopy(fact['receptors']);decisions=[]
    for row in rows:
        original=next(r for r in fact['connection']['receptors'] if r['target_id']==row['target_id'])
        accepted=None;choices=[]
        for trace in row['attempts']:
            result=assess(trace['candidate']['spec'],trace['evidence'],original,fact['config'])
            choices.append({'candidate':deepcopy(trace['candidate']),'assessment':result})
            if result['state']=='ready' and accepted is None:accepted=(trace,result)
        if accepted:
            trace,result=accepted;row.update(state='ready',quality=result['quality'],reason_zh=result['reason_zh'])
            row['system_qualified_attempt']={'candidate':deepcopy(trace['candidate']),'evidence':deepcopy(trace['evidence']),
                'assessment':deepcopy(result)}
        else:row.update(state='NA',quality='待核查')
        row['system_qualification_attempts']=choices
        decisions.append({'target_id':row['target_id'],'state':row['state'],'quality':row['quality'],
            'reason_zh':row['reason_zh'],'attempt_count':len(choices),'human_review_written':False,'authority_kind':'system_validation'})
    return rows,decisions

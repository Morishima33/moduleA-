"""新方案PPI精确清单的稳定编号补查：旧名称规则冻结，失败与未决分开。"""
from copy import deepcopy
import json

from contracts import ContractError,fingerprint,require
import ppi_identity as original

VERSION='A04.plan_identity.1'
NOTICE='仅限本研究本批流程测试：PPI精确清单内仍未解决的身份暂不纳入本批网络；原身份、原文与原因保留，不改变A03交集或A05输入，不代表完整网络或正式研究结论。'


def queries(targets,raw,scope):
    """沿用冻结HGNC现名/旧名和全部UniProt/Ensembl稳定编号，不接受任意编号。"""
    require(isinstance(scope,dict) and set(scope)=={'study_id','a03_run','decision','check_ids','omit_ids'},'PPI补查范围字段错误')
    require(isinstance(scope['decision'],str) and scope['decision'].strip(),'PPI缺少明确限定决定')
    for key in ('check_ids','omit_ids'):
        require(isinstance(scope[key],list) and all(isinstance(v,str) for v in scope[key])
            and len(set(scope[key]))==len(scope[key]),'PPI身份范围重复或格式错误')
    require(scope['check_ids'] and set(scope['omit_ids'])<=set(scope['check_ids']),'PPI暂不采用超出补查范围')
    return original.queries(targets,raw,scope)


def checked_queries(targets,raw,scope,probes):
    """逐一校验完整官方成功响应；缺项、失败、错编号、错原文指纹不能作为空结果。"""
    expected=queries(targets,raw,scope)
    require(isinstance(probes,list) and len(probes)==len(expected),'PPI稳定编号补查缺失或多出查询')
    grouped={gid:[] for gid in scope['check_ids']}
    for spec,probe in zip(expected,probes):
        require(isinstance(probe,dict) and set(probe)=={'query','source'} and probe['query']==spec,'PPI补查顺序或编号不属于本清单')
        source=probe['source']
        require(isinstance(source,dict) and source.get('url')==original.BASE+'get_string_ids'
            and source.get('params')==original.params(spec['identifier']) and bool(source.get('retrieved_at'))
            and source.get('query_state')=='succeeded','PPI补查请求未成功完成，不能暂不采用掩盖网络失败')
        require(isinstance(source.get('response_text'),str) and source.get('response_sha256')==fingerprint(source['response_text']),
            'PPI补查原文指纹不一致')
        try:rows=json.loads(source['response_text'])
        except (TypeError,ValueError) as error:raise ContractError('PPI补查原文不是完整JSON') from error
        require(isinstance(rows,list),'PPI补查错误对象不能作为空结果')
        require(all(isinstance(row,dict) and str(row.get('queryIndex'))=='0' and row.get('queryItem')==spec['identifier']
            and isinstance(row.get('preferredName'),str) and isinstance(row.get('stringId'),str)
            and isinstance(row.get('ncbiTaxonId'),int) and not isinstance(row['ncbiTaxonId'],bool) for row in rows),
            'PPI补查响应编号或结构不属于本次请求')
        grouped[spec['target_id']].append(probe)
    return grouped


def resolve(targets,mapping,probes,raw,scope):
    """每项复用旧唯一身份算法；反证、缺稳定编号和多值不选择候选，仅按新限定清单留因。"""
    grouped=checked_queries(targets,raw,scope,probes)
    indices={row['target_id']:i for i,row in enumerate(targets)}
    require(len(indices)==len(targets),'PPI交集稳定身份重复')
    require(isinstance(mapping,list) and all(isinstance(row,dict) and isinstance(row.get('queryIndex'),int)
        and not isinstance(row['queryIndex'],bool) and 0<=row['queryIndex']<len(targets) for row in mapping),
        'PPI原名称映射包含越界或错误索引')
    original_issues=set()
    for index,target in enumerate(targets):
        matches=[row for row in mapping if row['queryIndex']==index]
        if not (len(matches)==1 and matches[0].get('ncbiTaxonId')==9606
                and matches[0].get('preferredName')==target['symbol'] and str(matches[0].get('stringId','')).startswith('9606.')):
            original_issues.add(target['target_id'])
    require(set(scope['check_ids'])==original_issues,'PPI精确清单与原完整身份问题不同，不能遗漏或扩展')
    corrected=deepcopy(mapping);adjustments=[];decisions=[]
    for gid in scope['check_ids']:
        index=indices[gid];target=targets[index];checks=grouped[gid]
        one_scope=dict(scope,check_ids=[gid],omit_ids=[gid] if gid in scope['omit_ids'] else [])
        evidence={'authorization':one_scope,'hgnc_sha256':original.SNAPSHOT,'queries':checks}
        reason='原HGNC没有可供本规则查询的稳定编号' if not checks else '全部稳定编号尚未获得唯一且名称一致的同一人类STRING身份'
        adopted=[]
        if checks:
            try:
                candidate,adopted,_=original.resolve(targets,corrected,evidence,raw,one_scope)
            except ContractError as error:
                require(str(error)=='名称与稳定编号相互冲突，须重新核对','PPI补查存在不能豁免的结构或证据错误：'+str(error))
                reason=str(error)
            else:
                if adopted:corrected=candidate;adjustments.extend(adopted)
        decisions.append(dict(target,action='resolved_by_exact_evidence' if adopted else 'temporarily_omitted' if gid in scope['omit_ids'] else 'unresolved',
            reason_zh='沿用原全部稳定编号唯一一致规则，原名称转换和原文保留' if adopted else reason,
            query_count=len(checks),authority_kind='explicit_bound_test_decision'))
    # 新接入项与原有效身份碰撞时，不合并基因、不删原有效项；新清单项回到未决。
    by_protein={}
    for row in corrected:
        index=row['queryIndex']
        if row.get('ncbiTaxonId')==9606 and row.get('preferredName')==targets[index]['symbol']:
            by_protein.setdefault(row['stringId'],set()).add(targets[index]['target_id'])
    collided={gid for gids in by_protein.values() if len(gids)>1 for gid in gids}&{row['target_id'] for row in adjustments}
    if collided:
        positions={indices[gid] for gid in collided}
        corrected=[row for row in corrected if row['queryIndex'] not in positions]
        corrected.extend(deepcopy(row) for row in mapping if row['queryIndex'] in positions)
        adjustments=[row for row in adjustments if row['target_id'] not in collided]
        for row in decisions:
            if row['target_id'] in collided:
                row.update(action='temporarily_omitted' if row['target_id'] in scope['omit_ids'] else 'unresolved',
                    reason_zh='补查身份与另一交集HGNC对应同一STRING蛋白，保留未决，不合并或选择替代')
    return corrected,adjustments,decisions

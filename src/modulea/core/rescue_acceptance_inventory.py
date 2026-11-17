"""同修订验收包共用来源成员计划；保留原路径/登记关系，不读取或改变科学结果。"""
from copy import deepcopy

from contracts import require
from .rescue_result_read import same_file


def registered_files(records):
    """只合并完全相同路径/长度/SHA的原件，清单保留每条原登记和索引。"""
    groups={}
    for index,record in enumerate(records):
        path=record['path']
        if path not in groups:groups[path]={'record':record,'registrations':[]}
        group=groups[path]
        require(same_file(group['record'],record),'同一归档路径存在冲突长度或指纹，验收资料已阻断')
        group['registrations'].append({'index':index,'record':deepcopy(record)})
    return list(groups.values())


def member_plan(result,presentation=None):
    """原小包与落盘完整包共享成员集合，不能为了容量丢弃原件或名称依据。"""
    registered=registered_files(result['files']);extra=[];presentation_groups=[]
    if presentation:
        record=presentation['record'];request=presentation['request'];source=presentation['binding']['source']
        refs=[record['file'],record['request_file'],*record['files'],request['catalog_file'],request['font_file'],
              *request['implementation_files'],*presentation['binding']['name_decisions'],*source['evidence'],source['scoring_packet']]
        refs.extend(ref for entry in source['basis']['run_files'].values() for ref in entry.values() if ref)
        presentation_groups=registered_files(refs)
        combined=registered_files(result['files']+refs)
        original_paths={group['record']['path'] for group in registered}
        extra=[group for group in combined if group['record']['path'] not in original_paths]
    return {'registered':registered,'extra':extra,'presentation_groups':presentation_groups,
            'registered_bytes':sum(group['record']['bytes'] for group in registered+extra)}


def file_entries(plan):
    """路径布局沿原验收ZIP，角色别名和重复登记逐项保留。"""
    return [{'name':prefix+group['record']['path'],'file':deepcopy(group['record']),
             'role':group['record'].get('role',role),'registrations':deepcopy(group['registrations'])}
            for prefix,groups,role in [('registered/',plan['registered'],'registered'),('presentation/',plan['extra'],'presentation')]
            for group in groups]


def presentation_files(plan):
    """共用文件按实际ZIP前缀建立映射，不能指向不存在的重复副本。"""
    original_paths={group['record']['path'] for group in plan['registered']}
    return [dict(deepcopy(group),zip_path=('registered/' if group['record']['path'] in original_paths else 'presentation/')+
                 group['record']['path']) for group in plan['presentation_groups']]

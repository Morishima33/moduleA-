"""系统三库原ZIP到科学输入：原解析和原方案算法复用，独立明确来源协议。"""
from copy import deepcopy
from pathlib import Path
import tempfile
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file
from . import uploads,plan_flow
from .system_acquisition import validate_record,validate_source

VERSION='A01.system_source_binding.1'
PUBLICATION='A01.system_publication.1'


def materialize(home,folder,request,record):
    """验证实际完整获取后解包原件；清单明确标记系统来源，不冒充人工上传。"""
    validate_record(home,request,record);folder.mkdir(parents=True,exist_ok=False)
    slots=[]
    for row in record['sources']:
        db=row['database'];destination=folder/db;destination.mkdir()
        uploads.unpack(verified_file(home,row['archive']).read_bytes(),destination,max_compressed=(64 if db=='HERB' and row['source'].get('analysis_plan_source') else 16)*1024*1024)
        uploads.validate_package(destination,db,record['herbs'])
        slots.append(dict(deepcopy(row['source']),folder=destination.relative_to(home).as_posix(),source_record=deepcopy(row['archive']),
            files=[file_record(home,p,'system_component_source') for p in sorted(destination.rglob('*')) if p.is_file()]))
    implementations=[]
    for code in (Path(__file__),Path(uploads.__file__)):
        target=folder/'implementations'/code.name;target.parent.mkdir(exist_ok=True);target.write_bytes(code.read_bytes())
        implementations.append(file_record(home,target,'system_source_binding_implementation'))
    return {'a00_run_id':request['binding']['a00'],'herbs':deepcopy(record['herbs']),'datasets':slots,'implementation_files':implementations}


def validate_binding(home,value,request,record):
    """逐库从原ZIP重建解析产物再逐字节比较，SHA自洽不能代替原件一致。"""
    validate_record(home,request,record)
    require(value['schema_version']==VERSION and value['version']==VERSION and value['a00_run_id']==request['binding']['a00']
        and value['herbs']==record['herbs'] and [r['database'] for r in value['datasets']]==list(uploads.DATABASES),
        '系统来源解包绑定不同')
    for slot,row in zip(value['datasets'],record['sources']):
        require(slot['source_record']==row['archive'] and all(slot[k]==v for k,v in row['source'].items()
            if k not in ('folder','files','source_record')),'系统来源原始元数据不同')
        directory=(home/slot['folder']).resolve();require(directory.is_relative_to(home.resolve()),'系统来源解包目录越界')
        with tempfile.TemporaryDirectory(prefix='system_binding_verify_') as temp:
            expected=Path(temp)
            uploads.unpack(verified_file(home,row['archive']).read_bytes(),expected,max_compressed=(64 if row['database']=='HERB' and row['source'].get('analysis_plan_source') else 16)*1024*1024)
            uploads.validate_package(expected,row['database'],record['herbs'])
            actual={verified_file(home,ref).relative_to(directory).as_posix():verified_file(home,ref).read_bytes() for ref in slot['files']}
            require(set(actual)=={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()},
                '系统来源解包目录出现未登记文件')
            desired={p.relative_to(expected).as_posix():p.read_bytes() for p in expected.rglob('*') if p.is_file()}
            require(actual==desired,'系统来源解析产物与原ZIP实际重建不同')
    for ref in value['implementation_files']:verified_file(home,ref)


def facts(home,inputs):
    """先独立核验系统原件链，再调用冻结原方案三库/HGNC事实算法。"""
    binding=read_json(verified_file(home,inputs['system_source_binding']))
    record=read_json(verified_file(home,binding['acquisition_record']));request=read_json(verified_file(home,record['request_file']))
    require(inputs['staging_file']==inputs['system_source_binding'] and binding['plan_file']==inputs['analysis_plan_file']
        and binding['study_id']==inputs['study_id'] and binding['a00_run_id']==inputs['bound_a00'],'科学三库输入不属于原来源及方案')
    validate_binding(home,binding,request,record)
    summary,tables,anomalies=plan_flow.facts(home,inputs)
    summary.update(component_source_profile=PUBLICATION,source_binding_protocol=VERSION)
    return summary,tables,anomalies


def configuration(plan):
    """科学参数沿用原函数，只有来源和科学发布版本显式新增。"""
    return dict(plan_flow.configuration(plan),version=PUBLICATION,source_binding_protocol=VERSION)


def validator(root,fallback):
    """新版本从实际原件复算，旧全部版本继续原校验器。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=PUBLICATION:return fallback(run,summary,tables,anomalies,outcome)
        home=Path(root)/'studies'/run['study_id'];_,plan=plan_flow.plan_record(home,run['inputs'])
        require(run['execution_protocol']=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
            and run['inputs']['bound_a00']==run['parent_runs']['A00'] and run['config']==configuration(plan),
            '系统三库科学版本、原依赖或配置不同')
        require((summary,tables,anomalies)==facts(home,run['inputs']) and outcome=='success','系统三库科学结果与原件复算不同')
    return check

"""只恢复同批已完整归档、因发布核查失败而未提交的准备原件；不重取来源。"""
import ast,hashlib
from pathlib import Path
from contracts import require
from storage import file_record,new_id,read_json,verified_file,write_json


def functions(raw,names):
    """比较参数/结果派生函数的语义，允许独立校验器修复，不能偷换科学配置。"""
    tree=ast.parse(raw.decode('utf8'))
    return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names}


def recover(workflow,m,batch,batch_ref,input_ref,packet,config,executable):
    """只读已登记失败事件中的完整事实；指纹/参数/科学实现不一致则阻断。"""
    home=workflow.location(m['study_id']);prefix='decisions/analysis_plans/system_batches/'+batch['batch_id']+'/acquisition/A06_PREP/'
    candidates=[];seen=set()
    for failure_ref in reversed(m.get('analysis_plan_system_batch_events',[])):
        failure=read_json(verified_file(home,failure_ref))
        if failure['batch_id']!=batch['batch_id'] or failure['stage']!='A06_PREP' or failure['state']!='failed':continue
        for ref in failure['files']:
            if ref['path'].startswith(prefix) and ref['path'].endswith('/packet.json') and ref['path'] not in seen:
                seen.add(ref['path']);candidates.append((ref,failure_ref))
    if not candidates:return None
    ref,failure_ref=candidates[0];fact=read_json(verified_file(home,ref))
    require(fact['schema_version']=='A06.system_preparation.1' and fact['study_id']==m['study_id']
        and fact['batch_file']==batch_ref and fact['system_input_ref']==input_ref and fact['input_key']==packet['input_key']
        and fact['config']==config,'原准备包与本批授权、名单或参数不同，不能恢复或静默重取')
    for source in fact['files']+fact['connection']['files']:verified_file(home,source)
    require(hashlib.sha256(executable.read_bytes()).hexdigest()==fact['vina_sha256']==fact['vina_binary']['sha256'],
        '恢复时固定工具版本已改变，不能沿用旧准备')
    src=Path(__file__).resolve().parents[2];folder=home/fact['attempt_path'];checked=[]
    for source in fact['files']:
        path=verified_file(home,source)
        try:relative=path.relative_to(folder/'code')
        except ValueError:continue
        current=src/relative
        require(current.is_file(),'原准备所需科学实现已缺失')
        if relative.as_posix()=='science_modules/a06/system_preparation.py':
            require(functions(path.read_bytes(),{'configuration','reports'})==functions(current.read_bytes(),{'configuration','reports'}),
                '原准备参数或结果派生规则已改变，不能恢复')
        else:require(current.read_bytes()==path.read_bytes(),'原准备科学实现已改变，不能恢复：'+relative.as_posix())
        checked.append(source)
    require(len(checked)>=16,'原准备缺少完整实际实现快照，不能靠状态标记恢复')
    from . import system_preparation
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'recoveries'/new_id('recovery')
    implementations=[]
    for source in (Path(__file__),Path(system_preparation.__file__)):
        target=folder/'implementation'/source.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
        implementations.append(file_record(home,target,'system_recovery_implementation'))
    value={'schema_version':'A06.system_preparation_recovery.1','study_id':m['study_id'],'batch_file':batch_ref,
        'system_input_ref':input_ref,'input_key':packet['input_key'],'preparation_fact':ref,'failure_event':failure_ref,
        'science_implementation_files':checked,'implementation_files':implementations,
        'network_requested':False,'new_preparation_executed':False,'human_review_written':False,
        'note_zh':'仅恢复已完整落盘的同批准备原件；当前实际生产规范重新复核，旧失败、下载、结构、位点和参数保留。'}
    path=folder/'recovery.json'
    write_json(path,value);return ref,file_record(home,path,'system_preparation_recovery')

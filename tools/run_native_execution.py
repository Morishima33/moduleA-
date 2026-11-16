"""原生A06只由当前预算worker隔离执行；本工具不安装依赖或自动接续旧批。"""
import argparse
import json
import os
from pathlib import Path
import sys

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'src'))


def main(argv=None):
    """完整核任务、配置与资源归属后调用公开Workflow，所有科学判断留在后台。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('execute',))
    for key in ('request-file','result-file','data-root','runtime-dir','tools-profile','font-regular','font-bold'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--study',required=True);parser.add_argument('--task-id',required=True)
    args=parser.parse_args(argv)
    from contracts import require
    from modulea.config import load_settings
    from modulea.core.kernel import full_workflow
    from modulea.core.bounded_evidence import digest_file
    from modulea.tasks.manager import TaskManager
    require(sys.flags.isolated,'原生执行必须由-I隔离科学Python运行')
    require(not args.result_file.exists() and not args.result_file.resolve().is_relative_to((args.data_root/'studies').resolve()),
            '回执须在研究外的新文件，禁止覆盖原件')
    value=json.loads(args.request_file.read_text('utf-8'))
    settings=load_settings(data_root=args.data_root,runtime_dir=args.runtime_dir,science_python=sys.executable,
        tools_profile=args.tools_profile,font_regular=args.font_regular,font_bold=args.font_bold)
    active=TaskManager(settings)._raw(args.task_id)
    require(active and active['state']=='running' and active['kind']=='native_a06' and active['study_id']==args.study
        and active['pid']==os.getppid() and active.get('resource_owner_pid')==active['pid']
        and json.loads(active['payload'])==value,'原生执行必须匹配原任务、父worker及计算位')
    require(set(value)=={'stage','request','profile_sha256'} and digest_file(args.tools_profile)[1]==value['profile_sha256'],
            '原生执行配置已改变')
    methods={'prepare':'execute_native_preparation','qualify':'qualify_native_preparation','score':'execute_native_scoring'}
    require(value['stage'] in methods,'原生执行阶段不同')
    w=full_workflow(args.data_root)
    result=getattr(w,methods[value['stage']])(args.study,value['request'],settings=settings,
        progress=lambda message:print('PROGRESS '+message,flush=True))
    with args.result_file.open('x',encoding='utf-8') as stream:
        json.dump({k:result[k] for k in ('run_id','summary','outcome')},stream,ensure_ascii=False,indent=2)
    require(result['outcome']=='success','全部可用组合失败，诊断已归档，不当作成功')


if __name__=='__main__':main()

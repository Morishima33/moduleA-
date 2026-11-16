"""明确选择有界worker I/O；只读预检与显式同运行恢复分开，不自动启动真实研究。"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE/'src'))


def main(argv=None):
    """工具与数据来自本机配置参数；七字段原请求不升级、不覆盖旧文件。"""
    parser = argparse.ArgumentParser(description='二版补救的独立有界I/O适配')
    parser.add_argument('action', choices=('inspect', 'resume', 'execute'))
    for name in ('request-file','result-file','data-root','tools-root','repair-packages'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--study',required=True)
    parser.add_argument('--expected-run-id',required=True)
    parser.add_argument('--authorize-adapter',action='store_true')
    parser.add_argument('--runtime-dir',type=Path)
    parser.add_argument('--task-id')
    args = parser.parse_args(argv)
    if args.action != 'inspect' and not args.authorize_adapter:
        parser.error('恢复必须明确提供--authorize-adapter；inspect只读，不会执行科学工具')
    if args.result_file.exists():parser.error('输出文件已存在，拒绝覆盖，请提供新文件名')
    if args.result_file.resolve().is_relative_to((args.data_root/'studies').resolve()):
        parser.error('输出核查清单必须位于studies研究目录之外')
    # 本入口保留旧Windows科学环境的严格激活方式；不在Mac伪造旧批恢复。
    if sys.flags.no_site:
        from docking_runtime import activate
        activate(args.tools_root)
        if sys.platform == 'win32':sys.path.append(str(Path(sys.executable).parents[1]/'Lib/site-packages'))
    from contracts import require
    from modulea.core.kernel import full_workflow
    from modulea.core.scoped_worker_io import VERSION, ScopedWorkerIO as WorkerIO
    from modulea.core.rescue_recovery import inventory, preflight
    from modulea.config import load_settings
    from modulea.tasks.manager import TaskManager
    require(struct.calcsize('P') == 8, '恢复需要64位科学Python；不修改原环境，请先核对原解释器架构')
    original_request = json.loads(args.request_file.read_text('utf-8'))
    body = original_request['request'] if original_request.get('schema_version') == 'A06.system_rescue.2' else original_request
    settings = load_settings(data_root=args.data_root,runtime_dir=args.runtime_dir,
        science_python=sys.executable,science_tools_root=args.tools_root,science_repair_packages=args.repair_packages)
    manager = None
    if args.action != 'inspect':
        manager = TaskManager(settings)
    if args.action == 'execute':
        from modulea.tasks.scoped_rescue_worker import budget_owns_current_process
        active = manager._raw(args.task_id) if args.task_id else None
        require(active and active['state'] == 'running' and active['kind'] == 'plan_rescue_worker_io_v2'
                and active['study_id'] == args.study and budget_owns_current_process(active, settings.runtime_dir)
                and active.get('resource_owner_pid') == active['pid']
                and json.loads(active['payload']) == {'request':body,'run_id':args.expected_run_id,'adapter_version':VERSION},
                '科学恢复必须由原任务管理器预算worker启动，拒绝直接并发执行')
    adapter = WorkerIO()
    try:
        workflow = adapter.wrap(adapter.bind(full_workflow)(args.data_root))
        _, run = preflight(adapter,workflow,args.study,args.expected_run_id,body,args.tools_root,args.repair_packages)
        value = inventory(adapter,workflow,args.study,run)
        if args.action == 'resume':
            task, created = manager.submit(args.study,'plan_rescue_worker_io_v2',body['author'],
                payload={'request':body,'run_id':args.expected_run_id,'adapter_version':VERSION})
            require(task['kind'] == 'plan_rescue_worker_io_v2', '本研究已有其他活动任务；未提交第二个计算')
            require(json.loads(manager._raw(task['task_id'])['payload']) ==
                    {'request':body,'run_id':args.expected_run_id,'adapter_version':VERSION},
                    '本研究已有不同的I/O恢复任务；未提交第二个计算')
            value = dict(value,task_id=task['task_id'],task_created=created,task_state=task['state'])
        if args.action == 'execute':
            record = workflow.register_worker_io(args.study,args.expected_run_id,body)
            adapter.activate_registration(workflow,args.study,record)
            print('PROGRESS 已核对原二版绑定，使用明确登记的'+VERSION,flush=True)
            result = workflow.execute_analysis_plan_receptor_rescue_v2(args.study,body,
                tools=args.tools_root,repair_packages=args.repair_packages,
                progress=lambda message: print('PROGRESS '+message,flush=True))
            adapter.guard(workflow,args.study)
            value = dict(value,result_run_id=result['run_id'],outcome=result['outcome'],
                         scientific_computation_performed=True,adapter_record=record)
        value['worker_io'] = VERSION
        value['io_statistics'] = dict(adapter.stats)
        with args.result_file.open('x',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
        print(json.dumps({'action':args.action,'run_id':run['run_id'],'output':str(args.result_file),
                          'worker_io':VERSION},ensure_ascii=False),flush=True)
    finally:
        adapter.close()


if __name__ == '__main__':main()

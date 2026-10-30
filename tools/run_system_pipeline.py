"""隔离科学进程执行已明确授权的统一系统批次，浏览器不能指定工具或文件路径。"""
import argparse,json,sys
from pathlib import Path
CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'src'))


def main():
    """固定环境由服务器给出，排队后先重核实际输入；不代签任何结果复核。"""
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    for name in ('request-file','result-file','data-root'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--tools-root',type=Path);parser.add_argument('--study',required=True);args=parser.parse_args()
    if args.tools_root:
        from docking_runtime import activate
        activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1]/'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    from modulea.core.system_pipeline import validate_request
    w=full_workflow(args.data_root);body=json.loads(args.request_file.read_text('utf8'));validate_request(w,args.study,body)
    result=w.execute_analysis_plan_system_pipeline(args.study,{'batch_id':body['batch_id']},tools=args.tools_root,
        progress=lambda message:print('PROGRESS '+message,flush=True))
    args.result_file.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
    print('已归档本批双报告，结论等待独立复核',flush=True)


if __name__=='__main__':main()

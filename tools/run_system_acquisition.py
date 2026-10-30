"""隔离科学进程处理明确三库原件获取；参数和来源来自原请求及固定服务器代码。"""
import argparse,json,sys
from pathlib import Path
CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'src'))


def main():
    """先复核排队请求再调用公开Workflow；不接收路径/门槛或网络地址覆盖。"""
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    for name in ('request-file','result-file','data-root'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--study',required=True);args=parser.parse_args()
    sys.path.append(str(Path(sys.executable).parents[1]/'Lib/site-packages'))
    from modulea.core.kernel import full_workflow
    from modulea.core.system_acquisition import validate_request
    w=full_workflow(args.data_root);body=json.loads(args.request_file.read_text('utf8'));validate_request(w,args.study,body)
    result=w.acquire_analysis_plan_system_a01_sources(args.study,body,progress=lambda message:print('PROGRESS '+message,flush=True))
    args.result_file.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
    print(result['message_zh'],flush=True)


if __name__=='__main__':main()

"""为本机原生工具生成明确版本/SHA清单；不下载、不安装、不改变已有环境。"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'src'))


def main(argv=None):
    """输入均为管理员配置的本机路径；未知包版本必须显式提供，不猜原批版本。"""
    parser=argparse.ArgumentParser(description='生成本机新平台科学工具清单')
    for key in ('python','vina','java','p2rank','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--package',action='append',required=True,help='发行版=精确版本；重复七次')
    args=parser.parse_args(argv)
    packages={}
    for entry in args.package:
        name,sep,version=entry.partition('=')
        if not sep or not name or not version:parser.error('package须为发行版=精确版本')
        if name in packages:parser.error('package不可重复')
        packages[name]=version
    def digest(path):
        """完整SHA绑定，输出清单不按mtime推断工具身份。"""
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    p2rank=args.p2rank.resolve()
    files={p.relative_to(p2rank).as_posix():digest(p)
        for directory in ('bin','config','models') for p in sorted((p2rank/directory).rglob('*')) if p.is_file()}
    script='import platform,json;print(json.dumps([platform.system(),platform.machine()]))'
    done=subprocess.run([str(args.python),'-I','-B','-c',script],capture_output=True,text=True,timeout=20,check=True)
    system,machine=json.loads(done.stdout)
    machine={'AMD64':'x86_64','aarch64':'arm64'}.get(machine,machine)
    value={'schema_version':'ModuleA.platform_tools.1','science_protocol':'A06.platform_execution.1',
        'system':system,'machine':machine,
        'vina':{'path':str(args.vina.resolve()),'version':'1.2.7','sha256':digest(args.vina)},
        'java':{'path':str(args.java.resolve()),'version':'19','sha256':digest(args.java)},
        'p2rank':{'path':str(p2rank),'version':'2.5','files':files},'packages':packages}
    with args.output.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    # 生成不代表通过；立即调用原预检并逐项核实际架构、版本与包导入。
    from modulea.config import Settings
    from modulea.platform_preflight import verify_profile
    settings=Settings(science_python=str(args.python),tools_profile=args.output)
    _,facts=verify_profile(settings)
    print(json.dumps({'profile':str(args.output),'system':system,'machine':machine,
                     'packages':packages,'verified_tools':list(facts['tools'])},ensure_ascii=False))


if __name__=='__main__':main()

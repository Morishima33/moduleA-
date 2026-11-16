"""实际Windows CMD入口需干净转发含空格/中文路径与参数，不访问真实服务。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase,skipUnless


@skipUnless(os.name=='nt','仅Windows实际CMD入口；Mac入口独立核查')
class WindowsCmdEntryTests(TestCase):
    def exercise(self,configured):
        """合成Python管理器只回显参数，不联网、创建任务或修改系统配置。"""
        with TemporaryDirectory(prefix='ModuleA 中文 空格 ') as temporary:
            root=Path(temporary);(root/'tools').mkdir()
            entry=root/'modulea.cmd';entry.write_bytes((Path(__file__).resolve().parents[2]/'modulea.cmd').read_bytes())
            (root/'tools/manage_service.py').write_text('import json,sys\nprint(json.dumps({"args":sys.argv[1:]},ensure_ascii=False))\n',encoding='utf-8')
            env=dict(os.environ,PYTHONUTF8='1')
            if configured:env['MODULEA_PYTHON']=sys.executable
            else:env.pop('MODULEA_PYTHON',None)
            command=[os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(entry),'status','--json']
            done=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
            self.assertEqual(done.returncode,0,done.stderr)
            self.assertEqual(done.stderr,'','入口不能产生注释被误当命令等错误')
            self.assertEqual(json.loads(done.stdout),{'args':['status','--json']})

    def test_configured_python_receives_arguments_without_cmd_errors(self):self.exercise(True)

    @skipUnless(shutil.which('py'),'未安装Windows py启动器，仅核显式解释器')
    def test_default_python_launcher_receives_arguments_without_cmd_errors(self):self.exercise(False)

"""Windows入口回归：启动分支只mock标准Start-Process，真实执行仅隔离临时CheckOnly。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import codecs
import json
import os
import shutil
import subprocess
import sys
import unittest


PROJECT=Path(__file__).resolve().parents[2]
LAUNCHER=PROJECT/'src/start_v2.ps1'
POWERSHELL=shutil.which('powershell.exe')
PWSH=shutil.which('pwsh.exe') or shutil.which('pwsh')

# 此虚构CLI仅输出明确测试状态，不监听端口，不加载生产服务，不接触真实研究。
FAKE_CLI=r'''
from pathlib import Path
import json,os,sys
root=Path(__file__).resolve().parents[2]
scenario=os.environ['LAUNCHER_TEST_SCENARIO']
marker=Path(os.environ['LAUNCHER_TEST_MARKER'])
calls=Path(os.environ['LAUNCHER_TEST_CALLS'])
with calls.open('a',encoding='utf-8') as stream:stream.write(json.dumps(sys.argv[1:])+'\n')
if scenario=='malformed':print('not JSON');raise SystemExit(4)
port=int(sys.argv[sys.argv.index('--port')+1])
expected={'project_root':str(root),'data_root':os.environ['MODULEA_DATA_ROOT'],
          'runtime_dir':os.environ['MODULEA_RUNTIME_DIR'],'static_dir':str(root/'static'),'code_signature':'a'*64}
state='running' if scenario=='reuse' or marker.exists() else 'not_running'
ready=state=='running';preflight=True
if sys.argv[2]=='stop':
 state='stop_rejected' if scenario=='stop_busy' else 'stopped';ready=False
 if marker.exists():marker.unlink()
elif scenario in ('mismatch','degraded','unreachable','access_denied','stopping','configuration_error'):
 state=scenario;ready=False
elif scenario=='preflight_false':state='not_running';ready=False;preflight=False
elif scenario=='process_exited':state='not_running';ready=False
actual=dict(expected) if ready else None
if scenario=='wrong_identity' and marker.exists():actual['data_root']='other'
if scenario=='changed_code' and marker.exists():expected['code_signature']='b'*64;actual=dict(expected)
value={'schema_version':'ModuleA.service_probe.1','state':state,'ready':ready,'preflight_ready':preflight,
       'expected':expected,'actual':actual,'url':'http://127.0.0.1:'+str(port),'reasons_zh':['明确合成状态：'+state]}
if state=='stop_rejected':value.update(http_status=409,reasons_zh=['有活跃任务，明确拒绝停止'])
print(json.dumps(value,ensure_ascii=False))
raise SystemExit(0 if ready or state=='stopped' else 3 if state=='not_running' else 4)
'''

# 覆盖cmdlet只用于隔离测试；记录生产参数但绝不创建服务或浏览器进程。
MOCK_PROCESS=r'''
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
function global:Start-Process {
    param($FilePath, [string[]]$ArgumentList, $WorkingDirectory, $WindowStyle,
          $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru)
    $entry=@{ file=$FilePath; arguments=@($ArgumentList); working_directory=$WorkingDirectory;
              window_style=$WindowStyle; stdout=$RedirectStandardOutput; stderr=$RedirectStandardError;
              pass_thru=[bool]$PassThru }
    ($entry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $env:LAUNCHER_TEST_CAPTURE -Encoding UTF8
    if (-not $PassThru) { return }
    [IO.File]::WriteAllText($RedirectStandardOutput,'explicit synthetic stdout')
    [IO.File]::WriteAllText($RedirectStandardError,'')
    [IO.File]::WriteAllText($env:LAUNCHER_TEST_MARKER,'mock process only')
    $handle=[PSCustomObject]@{ HasExited=($env:LAUNCHER_TEST_SCENARIO -eq 'process_exited'); ExitCode=12 }
    $handle | Add-Member -MemberType ScriptMethod -Name Refresh -Value {} -PassThru
}
'''


@unittest.skipUnless(os.name=='nt' and POWERSHELL,'需要WindowsPowerShell5验证本机启动入口')
class ServiceLauncherTests(unittest.TestCase):
    """虚构CLI与mock启动完全隔离；两件真实目录变量始终指向临时目录。"""

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='modulea_launcher_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'project'
        (self.project/'src/modulea').mkdir(parents=True)
        (self.project/'src/modulea/__init__.py').write_text('',encoding='utf-8')
        (self.project/'src/modulea/__main__.py').write_text(FAKE_CLI,encoding='utf-8')
        self.launcher=self.project/'src/start_v2.ps1';shutil.copyfile(LAUNCHER,self.launcher)
        self.data=self.root/'data';self.runtime=self.root/'runtime';self.data.mkdir()
        (self.data/'must_keep.bin').write_bytes(b'EXPLICIT_SYNTHETIC_DATA')
        self.marker=self.root/'mock_started';self.calls=self.root/'cli_calls.jsonl';self.capture=self.root/'captured_processes.jsonl'
        self.env=dict(os.environ,MODULEA_DATA_ROOT=str(self.data),MODULEA_RUNTIME_DIR=str(self.runtime),
                      LAUNCHER_TEST_MARKER=str(self.marker),LAUNCHER_TEST_CALLS=str(self.calls),
                      LAUNCHER_TEST_CAPTURE=str(self.capture),LAUNCHER_TEST_SCRIPT=str(self.launcher),
                      LAUNCHER_TEST_PYTHON=sys.executable)

    def invoke(self,scenario='reuse',flags=(),*,browser=False,shell=None,native_errors=False):
        """仅mock分支可进入常驻路径；测试进程不创建任何真实服务。"""
        script=MOCK_PROCESS
        if native_errors:script+='\n$PSNativeCommandUseErrorActionPreference=$true\n'
        script+='\n& $env:LAUNCHER_TEST_SCRIPT -Port 8780 -PythonPath $env:LAUNCHER_TEST_PYTHON '
        if not browser:script+='-NoBrowser '
        script+=' '.join(flags)
        env=dict(self.env,LAUNCHER_TEST_SCENARIO=scenario)
        result=subprocess.run([shell or POWERSHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',script],
                              cwd=self.root,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
        self.assertEqual((self.data/'must_keep.bin').read_bytes(),b'EXPLICIT_SYNTHETIC_DATA')
        return result

    def records(self):
        if not self.capture.exists():return []
        return [json.loads(line) for line in self.capture.read_text(encoding='utf-8-sig').splitlines() if line.strip()]

    def test_bom_ps5_ast_and_cmd_forwarding_keep_compatibility(self):
        self.assertTrue(LAUNCHER.read_bytes().startswith(codecs.BOM_UTF8))
        code="$t=$null; $e=$null; [Management.Automation.Language.Parser]::ParseFile($env:LAUNCHER_TEST_SCRIPT,[ref]$t,[ref]$e) | Out-Null; if($e.Count){$e;exit 1}"
        result=subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-Command',code],env=self.env,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        for name,flag in (('start_v2.cmd',''),('stop_v2.cmd','-Stop'),('restart_v2.cmd','-Restart')):
            text=(PROJECT/name).read_text(encoding='utf-8-sig')
            self.assertIn('%~dp0src\\start_v2.ps1',text);self.assertIn('%*',text)
            self.assertIn('exit /b %moduleaExitCode%',text)
            if flag:self.assertIn(flag,text)

    def test_matching_ready_instance_is_reused_without_new_process(self):
        result=self.invoke();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('已复用',result.stdout);self.assertEqual(self.records(),[])
        self.assertFalse(self.runtime.exists())

    def test_only_not_running_and_preflight_ready_uses_hidden_standard_process(self):
        result=self.invoke('start');self.assertEqual(result.returncode,0,result.stderr)
        calls=self.records();self.assertEqual(len(calls),1);entry=calls[0]
        self.assertEqual(entry['window_style'],'Hidden');self.assertTrue(entry['pass_thru'])
        self.assertEqual(entry['arguments'],['-B','-m','modulea','serve','--port','8780','--no-browser'])
        self.assertEqual(Path(entry['working_directory']),self.project)
        for key in ('stdout','stderr'):
            self.assertEqual(Path(entry[key]).parent,self.runtime/'service/logs');self.assertTrue(Path(entry[key]).is_file())
        self.assertIn('后台就绪',result.stdout)

    def test_mismatch_and_all_unready_states_never_start_or_change_port(self):
        for state in ('mismatch','degraded','unreachable','access_denied','stopping','configuration_error','preflight_false','malformed'):
            with self.subTest(state=state):
                result=self.invoke(state);self.assertNotEqual(result.returncode,0)
                self.assertEqual(self.records(),[]);self.assertFalse(self.marker.exists())

    def test_stop_and_restart_use_only_confirmed_safe_cli(self):
        result=self.invoke('start',('-Stop',));self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.records(),[])
        commands=[json.loads(line) for line in self.calls.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(commands[0],['service','stop','--port','8780','--json','--confirmed'])
        result=self.invoke('start',('-Restart',));self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(self.records()),1)

    def test_active_tasks_reject_stop_and_restart_without_process_operations(self):
        for flags in (('-Stop',),('-Restart',)):
            with self.subTest(flags=flags):
                result=self.invoke('stop_busy',flags);self.assertNotEqual(result.returncode,0)
                self.assertIn('活跃任务',result.stderr);self.assertEqual(self.records(),[])

    def test_service_identity_change_or_process_exit_cannot_claim_ready_or_open_browser(self):
        for state in ('wrong_identity','changed_code','process_exited'):
            with self.subTest(state=state):
                if self.marker.exists():self.marker.unlink()
                if self.capture.exists():self.capture.unlink()
                result=self.invoke(state,browser=True);self.assertNotEqual(result.returncode,0)
                self.assertEqual(len(self.records()),1);self.assertTrue(self.records()[0]['pass_thru'])
                self.assertIn('日志',result.stderr)

    def test_browser_opens_only_after_ready_and_log_names_never_overwrite(self):
        logs=self.runtime/'service/logs';logs.mkdir(parents=True)
        old=logs/'old.stdout.log';old.write_bytes(b'KEEP_OLD_LOG')
        for _ in range(2):
            if self.marker.exists():self.marker.unlink()
            result=self.invoke('start',browser=True);self.assertEqual(result.returncode,0,result.stderr)
        records=self.records();services=[row for row in records if row['pass_thru']]
        browsers=[row for row in records if not row['pass_thru']]
        self.assertEqual(len(services),2);self.assertEqual(len(browsers),2)
        self.assertNotEqual(services[0]['stdout'],services[1]['stdout'])
        self.assertTrue(all(row['file']=='http://127.0.0.1:8780' for row in browsers))
        self.assertEqual(old.read_bytes(),b'KEEP_OLD_LOG')

    def test_logs_directory_junction_is_rejected_before_any_start_or_external_write(self):
        service=self.runtime/'service';service.mkdir(parents=True)
        outside=self.root/'studies_like';outside.mkdir();(outside/'keep').write_bytes(b'KEEP')
        env=dict(self.env,LAUNCHER_TEST_LINK=str(service/'logs'),LAUNCHER_TEST_LINK_TARGET=str(outside))
        result=subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-Command',
            'New-Item -ItemType Junction -Path $env:LAUNCHER_TEST_LINK -Value $env:LAUNCHER_TEST_LINK_TARGET | Out-Null'],env=env,capture_output=True,timeout=10)
        if result.returncode:self.skipTest('当前账户不支持测试junction：'+str(result.stderr))
        result=self.invoke('start');self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.records(),[]);self.assertEqual({path.name for path in outside.iterdir()},{'keep'})
        self.assertIn('目录链接',result.stderr)

    @unittest.skipUnless(PWSH,'未安装PowerShell7，仅验证WindowsPowerShell5')
    def test_ps7_expected_native_exit_three_still_allows_valid_not_running_status(self):
        result=self.invoke('start',shell=PWSH,native_errors=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(self.records()),1)

    def test_real_check_only_uses_temp_data_runtime_and_leaves_no_service_marker(self):
        """仅原生产serve --check使用真实随机端口，立即关闭且不登记常驻。"""
        result=subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(LAUNCHER),
            '-Port','0','-NoBrowser','-CheckOnly','-PythonPath',sys.executable],cwd=self.root,env=self.env,
            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=25)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('没有启动常驻',result.stdout)
        self.assertEqual(list(self.runtime.rglob('service_*.json')),[])
        self.assertEqual((self.data/'must_keep.bin').read_bytes(),b'EXPLICIT_SYNTHETIC_DATA')


if __name__=='__main__':
    unittest.main()

"""新原生协议的真实实现文件必须影响工具签名，防止改源码后恢复旧对象。"""
from hashlib import sha256
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from contracts import ContractError,fingerprint
from science_modules.a06 import native_tools


class NativeSignatureTests(TestCase):
    def test_nested_python_tools_explicitly_enable_utf8(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);tools=native_tools.NativeTools.__new__(native_tools.NativeTools)
            tools.python='synthetic-python';tools.facts={'packages':{'pdbfixer':{'origin':str(root/'packages/pdbfixer/__init__.py')}}}
            commands=[]
            def capture(command,folder,*args,**kwargs):
                commands.append(command)
                if '-o' in command:Path(command[command.index('-o')+1]+'.pdbqt').write_bytes(b'synthetic')
                else:
                    for name in ('--output','--evidence'):Path(command[command.index(name)+1]).write_bytes(b'synthetic')
            tools.run=capture
            tools.prepare_receptor(root,'HEADER synthetic\n',{'center':[0,0,0],'size':[20,20,20]},'fixture',root)
            tools.repair_observed(root/'input.pdb',root/'output.pdb',root/'evidence.json',root)
            for command in commands:
                with self.subTest(command=command):self.assertEqual(command[1:5],['-I','-B','-X','utf8'])

    def test_flat_scientific_and_workflow_dependencies_invalidate_signature(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); code=Path(native_tools.__file__).resolve().parents[3]
            for origin in (code/'src').rglob('*'):
                if origin.is_file() and origin.suffix in ('.py','.R'):
                    target=root/origin.relative_to(code);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(origin,target)
            for name in ('repair_a06_trial.py','run_native_execution.py'):
                (root/'tools').mkdir(exist_ok=True);shutil.copyfile(code/'tools'/name,root/'tools'/name)
            tools=native_tools.NativeTools.__new__(native_tools.NativeTools)
            tools.vina=root/'vina';tools.java=root/'java/bin/java';tools.java.parent.mkdir(parents=True)
            tools.p2rank=root/'p2rank';tools.p2rank.mkdir()
            profile=root/'profile.json';profile.write_text('{}')
            font=root/'font.ttc';font.write_bytes(b'synthetic font never drawn')
            python=root/'python';python.write_bytes(b'synthetic python never executed');tools.python=str(python)
            for tool in (tools.vina,tools.java):tool.write_bytes(b'synthetic tool never executed')
            tools.settings=SimpleNamespace(tools_profile=profile,font_regular=font,font_bold=font)
            tools.facts={'profile':{'sha256':sha256(profile.read_bytes()).hexdigest()}}
            tools.profile={'packages':{},'system':'Windows','machine':'x86_64','p2rank':{'files':{}},
                'vina':{'sha256':sha256(tools.vina.read_bytes()).hexdigest()},
                'java':{'sha256':sha256(tools.java.read_bytes()).hexdigest()}}
            with patch.object(native_tools,'__file__',str(root/'src/science_modules/a06/native_tools.py')), \
                 patch.object(native_tools.subprocess,'run',return_value=CompletedProcess([],0,json.dumps([]),'')):
                previous=fingerprint(tools.signature())
                for name in ('docking_receptor.py','docking_ligand_flow.py','contracts.py','storage.py','workflow.py','modulea/core/analysis_plans.py'):
                    with self.subTest(dependency=name):
                        path=root/'src'/name
                        self.assertTrue(path.is_file(),'必须检查实际存在的执行依赖')
                        with path.open('a',encoding='utf-8') as stream:stream.write('\n# synthetic changed dependency\n')
                        current=fingerprint(tools.signature())
                        self.assertNotEqual(current,previous,'修改实际执行依赖必须使同批恢复签名改变')
                        previous=current
            # 绘图库等实际安装依赖未必列在七个结构包profile内，仍须绑定其真实文件。
            rendering=root/'pillow_render.py';rendering.write_bytes(b'synthetic rendering dependency')
            distribution=SimpleNamespace(files=[rendering],locate_file=lambda relative:relative,
                                         read_text=lambda _:None,metadata={'Name':'Pillow'})
            def inventory(command,**kwargs):
                output=io.StringIO()
                try:
                    with redirect_stdout(output):exec(command[-1],{})
                except Exception as error:return CompletedProcess(command,1,output.getvalue(),str(error))
                return CompletedProcess(command,0,output.getvalue(),'')
            with patch.object(native_tools,'__file__',str(root/'src/science_modules/a06/native_tools.py')), \
                 patch.object(native_tools.subprocess,'run',side_effect=inventory), \
                 patch.object(native_tools.importlib.metadata,'distributions',return_value=[distribution]):
                before=fingerprint(tools.signature())
                rendering.write_bytes(b'changed rendering dependency')
                self.assertNotEqual(fingerprint(tools.signature()),before,'未列入七包profile的实际绘图依赖也必须阻断同批恢复')
                # PEP660的非空RECORD可能只指向加载器，不能代表外部editable源码已被核验。
                distribution.read_text=lambda _:json.dumps({'dir_info':{'editable':True}})
                with self.assertRaises(ContractError) as blocked:tools.signature()
                self.assertIn('editable',str(blocked.exception))
                distribution.read_text=lambda _:None;distribution.files=None
                with self.assertRaises(ContractError) as blocked:tools.signature()
                self.assertIn('完整文件清单',str(blocked.exception))

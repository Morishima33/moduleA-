"""运行环境签名使用合成工具树；不运行Java、结构准备或真实研究。"""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError


class SystemRescueRuntimeTests(unittest.TestCase):
    def setUp(self):
        """伪造有效运行文件，只有Java发现分支替换外部命令。"""
        module = 'science_modules.a06.system_rescue_runtime'
        self.assertIsNotNone(importlib.util.find_spec(module), '缺少独立运行环境签名工具')
        self.runtime = importlib.import_module(module)
        self.real_interpreter = sys.executable
        temporary = tempfile.TemporaryDirectory(prefix='rescue_runtime_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tools, self.repair = self.root / 'tools', self.root / 'repair'
        self.java, self.python = self.root / 'actual java', self.root / 'python'
        artifacts = {
            'actual java/bin/java.exe': b'java',
            'actual java/release': b'JAVA_VERSION="19.0.2"',
            'actual java/bin/server/jvm.dll': b'jvm',
            'python/python.exe': b'python',
            'python/python313.dll': b'python-dll',
            'tools/environments/p2rank_2.5/prank.bat': b'prank',
            'tools/environments/p2rank_2.5/bin/p2rank.jar': b'program',
            'tools/environments/p2rank_2.5/bin/lib/dependency.jar': b'dependency',
            'tools/environments/p2rank_2.5/config/default.groovy': b'model="default"',
            'tools/environments/p2rank_2.5/models/default/model.zst': b'model',
            'tools/environments/p2rank_2.5/models/default/features.txt': b'features',
            'tools/environments/p2rank_2.5/models/_score_transform/default_ZscoreTpTransformer.json': b'{}',
            'tools/environments/docking_packages/meeko/__init__.py': b'# meeko',
            'tools/environments/docking_packages/meeko/data/residue_chem_templates.json': b'{}',
            'tools/environments/docking_packages/meeko-0.8.0.dist-info/METADATA': b'Version: 0.8.0',
            'tools/environments/docking_packages/gemmi/__init__.py': b'# gemmi',
            'tools/environments/docking_packages/gemmi/gemmi.pyd': b'gemmi-native',
            'tools/environments/docking_packages/gemmi-0.7.5.dist-info/METADATA': b'Version: 0.7.5',
            'repair/pdbfixer/pdbfixer.py': b'# fixer',
            'repair/pdbfixer/templates/ALA.pdb': b'ALA',
            'repair/pdbfixer-1.12.dist-info/METADATA': b'Version: 1.12',
            'repair/openmm/__init__.py': b'# openmm',
            'repair/openmm/_openmm.pyd': b'openmm-native',
            'repair/openmm/app/data/amber.xml': b'<forcefield/>',
            'repair/openmm-8.4.dist-info/METADATA': b'Version: 8.4',
            'repair/OpenMM.libs/lib/OpenMM.dll': b'openmm-dll',
            'repair/numpy/__init__.py': b'# repair numpy',
            'repair/numpy/core.pyd': b'numpy-native',
            'repair/numpy.libs/blas.dll': b'blas',
        }
        for relative, raw in artifacts.items():
            self.write(relative, raw)
        self.write('tools/environments/A06_python_runtime.json', json.dumps({
            'schema_version': 'A06.runtime.1',
            'packages': {'meeko': {'module': 'meeko', 'version': '0.8.0'},
                         'gemmi': {'module': 'gemmi', 'version': '0.7.5'}}
        }).encode('utf-8'))
        for replacement in (
                patch.object(self.runtime.sys, 'executable', str(self.python / 'python.exe')),
                patch.object(self.runtime.sys, 'prefix', str(self.python)),
                patch.object(self.runtime.sys, 'base_prefix', str(self.python)),
                patch.dict(os.environ, {'JAVA_HOME': str(self.java)})):
            replacement.start()
            self.addCleanup(replacement.stop)

    def write(self, relative, raw):
        """测试专用工具文件只写入本次临时目录。"""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def signature(self):
        """调用真实签名入口，不替换文件读取或散列。"""
        return self.runtime.signature(self.tools, self.repair)

    def test_existing_java_home_is_used_without_requiring_path_java(self):
        with patch.object(self.runtime.shutil, 'which', return_value=None):
            value = self.signature()
        self.assertEqual(value['java_home'], str(self.java.resolve()))
        self.assertEqual(value['python_executable'], str((self.python / 'python.exe').resolve()))

    def test_invalid_java_home_discovers_actual_home_from_java_properties(self):
        launcher = self.write('java shim/java.exe', b'shim')
        def properties(command, **kwargs):
            self.assertEqual(command, [str(launcher), '-XshowSettings:properties', '-version'])
            return subprocess.CompletedProcess(command, 0, '',
                'Property settings:\n    java.home = ' + str(self.java) + '\njava version "19.0.2"\n')
        with patch.dict(os.environ, {'JAVA_HOME': str(self.root / 'missing')}), \
                patch.object(self.runtime.shutil, 'which', return_value=str(launcher)), \
                patch.object(self.runtime.subprocess, 'run', side_effect=properties):
            before = dict(os.environ)
            value = self.signature()
            self.assertEqual(os.environ, before)
        self.assertEqual(value['java_home'], str(self.java.resolve()))

    def test_unset_java_home_uses_properties_and_matches_later_activation(self):
        result = subprocess.CompletedProcess([], 0, '', '    java.home = ' + str(self.java) + '\n')
        with patch.dict(os.environ), patch.object(self.runtime.shutil, 'which', return_value='java'), \
                patch.object(self.runtime.subprocess, 'run', return_value=result):
            os.environ.pop('JAVA_HOME', None)
            first = self.signature()
            active = self.runtime.activate(self.tools, self.repair)
            self.assertEqual(first, active)
            self.assertEqual(first, self.signature())

    def test_missing_or_failed_java_discovery_blocks_signature(self):
        with patch.dict(os.environ, {'JAVA_HOME': str(self.root / 'missing')}):
            with patch.object(self.runtime.shutil, 'which', return_value=None), self.assertRaises(ContractError):
                self.signature()
            for result in (subprocess.CompletedProcess([], 1, '', 'launch failed'),
                           subprocess.CompletedProcess([], 0, '', 'java version only'),
                           subprocess.CompletedProcess([], 0, '', 'java.home = ' + str(self.root / 'missing'))):
                with self.subTest(result=result.stderr), \
                        patch.object(self.runtime.shutil, 'which', return_value='java'), \
                        patch.object(self.runtime.subprocess, 'run', return_value=result), \
                        self.assertRaises(ContractError):
                    self.signature()

    def test_each_effective_binary_model_template_and_source_changes_signature(self):
        baseline = self.signature()
        paths = ('actual java/bin/java.exe', 'actual java/release', 'actual java/bin/server/jvm.dll',
                 'python/python.exe', 'python/python313.dll',
                 'tools/environments/p2rank_2.5/prank.bat',
                 'tools/environments/p2rank_2.5/bin/p2rank.jar',
                 'tools/environments/p2rank_2.5/bin/lib/dependency.jar',
                 'tools/environments/p2rank_2.5/config/default.groovy',
                 'tools/environments/p2rank_2.5/models/default/model.zst',
                 'tools/environments/p2rank_2.5/models/default/features.txt',
                 'tools/environments/p2rank_2.5/models/_score_transform/default_ZscoreTpTransformer.json',
                 'tools/environments/A06_python_runtime.json',
                 'tools/environments/docking_packages/meeko/__init__.py',
                 'tools/environments/docking_packages/meeko/data/residue_chem_templates.json',
                 'tools/environments/docking_packages/meeko-0.8.0.dist-info/METADATA',
                 'tools/environments/docking_packages/gemmi/gemmi.pyd',
                 'repair/pdbfixer/pdbfixer.py', 'repair/pdbfixer/templates/ALA.pdb',
                 'repair/pdbfixer-1.12.dist-info/METADATA', 'repair/openmm/_openmm.pyd',
                 'repair/openmm/app/data/amber.xml', 'repair/OpenMM.libs/lib/OpenMM.dll',
                 'repair/numpy/core.pyd', 'repair/numpy.libs/blas.dll')
        for relative in paths:
            with self.subTest(path=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + (b'\n' if path.suffix == '.json' else b'changed'))
                self.assertNotEqual(self.signature(), baseline, relative)
                path.write_bytes(original)

    def test_tests_docs_caches_and_pdbfixer_ui_assets_are_not_effective_inputs(self):
        baseline = self.signature()
        for relative in ('tools/environments/p2rank_2.5/test_data/example.pdb',
                         'tools/environments/p2rank_2.5/doc/README.md',
                         'repair/pdbfixer/tests/test.py', 'repair/pdbfixer/html/form.html',
                         'repair/pdbfixer/images/logo.png', 'repair/pdbfixer/__pycache__/fixer.pyc',
                         'tools/environments/docking_packages/meeko/tests/test_data/model.pyd',
                         'tools/environments/docking_packages/meeko/__pycache__/writer.pyc'):
            self.write(relative, b'unrelated')
        self.assertEqual(self.signature(), baseline)

    def test_unused_alphafold_prediction_model_does_not_slow_default_model_signature(self):
        baseline = self.signature()
        self.write('tools/environments/p2rank_2.5/models/alphafold/model.zst', b'unused predictive model')
        self.assertEqual(self.signature(), baseline)

    def test_missing_required_tool_model_or_preparation_dependency_blocks(self):
        for relative in ('tools/environments/p2rank_2.5/prank.bat',
                         'tools/environments/p2rank_2.5/bin/p2rank.jar',
                         'tools/environments/p2rank_2.5/config/default.groovy',
                         'tools/environments/p2rank_2.5/models/default/model.zst',
                         'tools/environments/A06_python_runtime.json',
                         'repair/pdbfixer/pdbfixer.py', 'repair/openmm/_openmm.pyd'):
            with self.subTest(path=relative):
                path = self.root / relative
                raw = path.read_bytes()
                path.unlink()
                with self.assertRaises(ContractError):
                    self.signature()
                path.write_bytes(raw)

    def test_activation_changes_only_process_java_home_and_returns_bound_signature(self):
        result = subprocess.CompletedProcess([], 0, '', 'java.home = ' + str(self.java) + '\n')
        with patch.dict(os.environ, {'JAVA_HOME': str(self.root / 'invalid'), 'RESCUE_SENTINEL': 'unchanged'}), \
                patch.object(self.runtime.shutil, 'which', return_value='java'), \
                patch.object(self.runtime.subprocess, 'run', return_value=result):
            before = dict(os.environ)
            value = self.runtime.activate(self.tools, self.repair)
            expected = dict(before, JAVA_HOME=str(self.java.resolve()))
            self.assertEqual(dict(os.environ), expected)
            self.assertEqual(value['java_home'], expected['JAVA_HOME'])
            self.assertEqual(value, self.signature())

    def test_real_child_activation_does_not_change_parent_environment(self):
        before = dict(os.environ)
        environment = dict(before, JAVA_HOME=' "' + str(self.java) + '" ',
                           RESCUE_TEST_TOOLS=str(self.tools), RESCUE_TEST_REPAIR=str(self.repair),
                           PYTHONUTF8='1', PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'src'))
        script = ('import json, os; '
                  'from science_modules.a06.system_rescue_runtime import activate; '
                  'value=activate(os.environ["RESCUE_TEST_TOOLS"],os.environ["RESCUE_TEST_REPAIR"]); '
                  'print(json.dumps({"home":os.environ["JAVA_HOME"],"same":os.environ["JAVA_HOME"]==value["java_home"]}))')
        result = subprocess.run([self.real_interpreter, '-B', '-c', script], env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'home': str(self.java.resolve()), 'same': True})
        self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main()

"""新适配器与冻结CLI的参数对照及失败证据检查；不运行科学工具。"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from science_modules.a06 import receptor_cli_paths as subject
import docking_top10_execute as legacy


class ReceptorCLIPathsTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.test-tmp'
        parent.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='receptor_cli_', dir=parent))
        self.tools = self.root / 'tools'
        (self.tools / 'environments' / 'docking_packages').mkdir(parents=True)
        self.folder = self.root / 'new'
        self.folder.mkdir()
        self.box = {'center': [1.25, -2.5, 3.75], 'size': [10.5, 11.25, 12.75]}
        self.text = 'ATOM      1  CA  ALA A   1       1.250  -2.500   3.750  1.00 10.00           C\nTER\nEND\n'

    def success(self, arguments, **kwargs):
        Path(arguments[arguments.index('-o') + 1] + '.pdbqt').write_text('RECEPTOR', encoding='ascii')
        return subprocess.CompletedProcess(arguments, 0, 'OK', '')

    def test_same_numeric_parameters_and_flags_as_frozen_cli(self):
        old_folder = self.root / 'legacy'
        old_folder.mkdir()
        before = hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest()
        with patch.object(legacy.subprocess, 'run', side_effect=self.success) as old_run:
            old = legacy._prepare_receptor_cli(self.tools, self.text, self.box, 'TEST', old_folder)
            old_args = old_run.call_args.args[0]
            old_environment = old_run.call_args.kwargs['env']['PYTHONPATH']
        with patch.object(subject.subprocess, 'run', side_effect=self.success) as new_run:
            new = subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)
            new_args = new_run.call_args.args[0]
            new_environment = new_run.call_args.kwargs['env']['PYTHONPATH']
        def normalized(arguments, folder):
            return [str(value).replace(str(folder), '<ATTEMPT>') for value in arguments]
        self.assertEqual(normalized(old_args, old_folder), normalized(new_args, self.folder))
        self.assertEqual(old_environment, new_environment)
        self.assertEqual(new.read_bytes(), old.read_bytes())
        self.assertEqual(before, hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest())
        receipt = json.loads((self.folder / 'receptors' / 'TEST_path_execution.json').read_text('utf-8'))
        self.assertEqual(receipt['protocol'], subject.VERSION)
        self.assertEqual(receipt['box'], self.box)
        self.assertEqual(receipt['returncode'], 0)
        self.assertEqual(receipt['input_sha256_before'], receipt['input_sha256_after'])

    def test_nonzero_exit_cannot_be_accepted_even_with_output_file(self):
        def fail(arguments, **kwargs):
            self.success(arguments, **kwargs)
            return subprocess.CompletedProcess(arguments, 2, '', 'TEMPLATE ERROR')
        with patch.object(subject.subprocess, 'run', side_effect=fail):
            with self.assertRaises(ValueError):
                subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)
        receipt = json.loads((self.folder / 'receptors' / 'TEST_path_execution.json').read_text('utf-8'))
        self.assertEqual(receipt['returncode'], 2)
        self.assertIn('TEMPLATE ERROR', (self.folder / 'receptors' / 'TEST_prepare_stderr.txt').read_text('utf-8'))

    def test_start_error_is_recorded_without_output_or_retry(self):
        with patch.object(subject.subprocess, 'run', side_effect=OSError('isolated start failure')) as run:
            with self.assertRaises(OSError):
                subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)
            self.assertEqual(run.call_count, 1)
        receipt = json.loads((self.folder / 'receptors' / 'TEST_path_execution.json').read_text('utf-8'))
        self.assertEqual(receipt['state'], 'failed_to_start')
        self.assertIn('isolated start failure', receipt['error_zh'])

    def test_repeat_same_attempt_never_overwrites_input_or_runs_again(self):
        with patch.object(subject.subprocess, 'run', side_effect=self.success) as run:
            subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)
            with self.assertRaises(FileExistsError):
                subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)
            self.assertEqual(run.call_count, 1)

    def test_child_modified_input_cannot_be_accepted(self):
        def corrupt(arguments, **kwargs):
            result = self.success(arguments, **kwargs)
            Path(arguments[arguments.index('--read_pdb') + 1]).write_text('CHANGED', encoding='ascii')
            return result
        with patch.object(subject.subprocess, 'run', side_effect=corrupt):
            with self.assertRaises(ValueError):
                subject.prepare(self.tools, self.text, self.box, 'TEST', self.folder)

    def test_invalid_filename_is_rejected_before_process_or_file_write(self):
        with patch.object(subject.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                subject.prepare(self.tools, self.text, self.box, '../escape', self.folder)
            run.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

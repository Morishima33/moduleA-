"""检查工具路径保持物理同一性，不能靠换文件或复制目录通过。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tool_process_paths as subject


class ToolPathsTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.test-tmp'
        parent.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='tool_paths_', dir=parent))
        self.input = self.root / 'input.pdb'
        self.input.write_text('ORIGINAL', encoding='ascii')

    def test_existing_short_input_is_same_file_and_unchanged(self):
        mapped = subject.existing(self.input)
        self.assertTrue(os.path.samefile(mapped, self.input))
        self.assertEqual(self.input.read_text('ascii'), 'ORIGINAL')

    def test_output_preserves_parent_and_exact_new_name(self):
        target = self.root / 'new_output.pdbqt'
        mapped = Path(subject.output(target))
        self.assertEqual(mapped.name, target.name)
        self.assertTrue(os.path.samefile(mapped.parent, self.root))
        self.assertFalse(target.exists())

    def test_missing_input_is_not_created(self):
        target = self.root / 'missing.pdb'
        with self.assertRaises(ValueError):
            subject.existing(target)
        self.assertFalse(target.exists())

    def test_missing_output_parent_is_not_created(self):
        target = self.root / 'missing_parent' / 'output.pdbqt'
        with self.assertRaises(ValueError):
            subject.output(target)
        self.assertFalse(target.parent.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows系统短名核查')
    def test_long_existing_directory_and_future_file_keep_physical_location(self):
        folder = self.root
        for i in range(5):
            folder = folder / ('long_component_' + str(i) + '_' + 'x' * 38)
        folder.mkdir(parents=True)
        self.assertGreater(len(str(folder)), 260)
        short = subject.existing(folder)
        self.assertLess(len(short), 240)
        self.assertTrue(os.path.samefile(short, folder))
        mapped = Path(subject.output(folder / 'same_name.pdbqt'))
        self.assertEqual(mapped.name, 'same_name.pdbqt')
        self.assertTrue(os.path.samefile(mapped.parent, folder))

    def test_short_name_failure_does_not_fall_back_to_different_directory(self):
        with patch.object(subject, 'WINDOWS', True), patch.object(subject, 'LIMIT', 1), \
                patch.object(subject, '_short_name', side_effect=ValueError('系统未提供短名')):
            with self.assertRaisesRegex(ValueError, '系统未提供短名'):
                subject.existing(self.input)

    def test_wrong_short_alias_is_rejected(self):
        other = self.root / 'other.pdb'
        other.write_text('OTHER', encoding='ascii')
        with patch.object(subject, 'WINDOWS', True), patch.object(subject, 'LIMIT', 100), \
                patch.object(subject, '_short_name', return_value=str(other)):
            # Force normalization without changing the actual operating system.
            with patch.object(subject, 'needs_short_name', return_value=True):
                with self.assertRaises(ValueError):
                    subject.existing(self.input)

    def test_output_name_cannot_escape_parent(self):
        for name in ('../outside', 'bad:name', 'bad/name', 'bad\\name', 'trailing.', 'trailing ', ''):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    subject.filename(name)

    def test_non_windows_path_does_not_call_native_short_name(self):
        with patch.object(subject, 'WINDOWS', False), patch.object(subject, '_short_name') as native:
            self.assertEqual(subject.existing(self.input), str(self.input.resolve()))
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()

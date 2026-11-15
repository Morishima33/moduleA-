"""跨路径迁移核验；登记、检查点和旧绝对路径保持，未登记残件不计成功。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from contracts import ContractError
from storage import file_record,write_json
from modulea.migration import inventory,verify


class MigrationIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='迁移 中文 ');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.source=self.root/'原数据';self.destination=self.root/'迁入 数据'
        self.sid='study_'+'e'*32;self.home=self.source/'studies'/self.sid;self.home.mkdir(parents=True)
        pose=self.home/'runs/A06/原始 构象.pdbqt';pose.parent.mkdir(parents=True);pose.write_bytes(b'MODEL 1\nENDMDL\n')
        self.pose=file_record(self.home,pose,'pose')
        packet=self.home/'checkpoint.json';write_json(packet,{'files':[self.pose],'original_command':'D:/旧工程/vina.exe'})
        write_json(self.home/'manifest.json',{'study_id':self.sid,'runs':{},'checkpoints':[file_record(self.home,packet,'checkpoint')]})

    def test_complete_migration_preserves_nested_originals_and_does_not_grant_resume(self):
        expected=inventory(self.source,self.sid)
        shutil.copytree(self.source,self.destination)
        value=verify(self.destination,expected)
        self.assertTrue(value['history_integrity_verified'])
        self.assertFalse(value['resume_allowed'])
        self.assertEqual(value['file_count'],2)
        migrated=self.destination/'studies'/self.sid/'checkpoint.json'
        self.assertIn('D:/旧工程/vina.exe',migrated.read_text('utf-8'))

    def test_corruption_missing_registered_input_and_modified_inventory_fail(self):
        expected=inventory(self.source,self.sid);shutil.copytree(self.source,self.destination)
        pose=self.destination/'studies'/self.sid/self.pose['path'];original=pose.read_bytes()
        pose.write_bytes(original.replace(b'1',b'2'))
        with self.assertRaises(ContractError):verify(self.destination,expected)
        pose.write_bytes(original);pose.unlink()
        with self.assertRaises((ContractError,OSError)):verify(self.destination,expected)
        changed=deepcopy(expected);changed['file_count']=99
        with self.assertRaises(ContractError):verify(self.source,changed)

    def test_unregistered_partial_file_is_not_counted_as_success_or_migrated_record(self):
        expected=inventory(self.source,self.sid)
        (self.home/'unregistered_top1.pdbqt').write_bytes(b'UNREGISTERED PARTIAL')
        self.assertEqual(inventory(self.source,self.sid),expected)


if __name__=='__main__':unittest.main()

"""完整验收包的有界落盘及逐成员指纹；只用合成文件，不改实际研究。"""
from hashlib import sha256
import importlib
import json
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
import tracemalloc
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import zipfile

from contracts import ContractError
from modulea.core.bounded_evidence import file_record


class AcceptanceArchiveIoTests(TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[2]/'src/modulea/core/acceptance_archive_io.py'
        self.assertTrue(path.is_file(),'缺少流式完整包写入与逐成员SHA复核')
        self.api=importlib.import_module('modulea.core.acceptance_archive_io')
        temp=TemporaryDirectory(prefix='完整包 流式 ');self.addCleanup(temp.cleanup)
        self.home=Path(temp.name);self.source=self.home/'raw/evidence.bin'
        self.source.parent.mkdir();self.source.write_bytes(b'original bytes\x00'*40)
        self.ref=file_record(self.home,self.source,'original')
        self.dest=self.home/'attempt/complete.zip';self.dest.parent.mkdir()
        self.metadata={'schema_version':'ModuleA.acceptance_archive.1','run_id':'run_synthetic',
                       'revision_id':'rescueview_synthetic','input_key':'fixed'}

    def entries(self):
        return [{'name':'registered/raw/evidence.bin','file':self.ref,'role':'original',
                 'registrations':[{'index':0,'record':self.ref},{'index':1,'record':dict(self.ref,role='alias')}]},
                {'name':'poses/pair_000001/top1.pdbqt','data':b'MODEL 1\nENDMDL\n','role':'top1'}]

    def build(self,entries=None,**options):
        return self.api.write_archive(self.home,self.dest,self.entries() if entries is None else entries,
                                      self.metadata,min_free_bytes=0,**options)

    def test_complete_file_and_top1_members_preserve_original_registration_and_sha(self):
        result=self.build()
        self.assertEqual(result['archive']['bytes'],self.dest.stat().st_size)
        with zipfile.ZipFile(self.dest) as archive:
            self.assertEqual(archive.read('registered/raw/evidence.bin'),self.source.read_bytes())
            self.assertEqual(archive.read('poses/pair_000001/top1.pdbqt'),b'MODEL 1\nENDMDL\n')
            metadata=json.loads(archive.read('验收目录与指纹.json'))
        self.assertEqual(metadata['revision_id'],self.metadata['revision_id'])
        self.assertEqual(len(metadata['files'][0]['registrations']),2)
        self.assertEqual(metadata['files'],result['inventory'])
        self.api.validate_archive(self.dest,result['inventory'],result['metadata'])

    def test_large_source_is_streamed_with_bounded_python_peak(self):
        block=bytes(range(256))*4096
        with self.source.open('wb') as stream:
            for _ in range(32):stream.write(block)
        self.ref=file_record(self.home,self.source,'original');del block
        tracemalloc.start()
        try:
            with patch.object(Path,'read_bytes',side_effect=AssertionError('不得整件read_bytes')):
                result=self.build()
                self.api.validate_archive(self.dest,result['inventory'],result['metadata'])
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,12*1024*1024,peak)
        self.assertEqual(result['inventory'][0]['bytes'],32*1024*1024)

    def test_source_changed_to_same_length_cannot_form_complete_package(self):
        raw=self.source.read_bytes();self.source.write_bytes(bytes([raw[0]^1])+raw[1:])
        with self.assertRaises(ContractError):self.build()

    def test_source_change_during_copy_cannot_be_hidden_by_restoring_mtime(self):
        raw=self.source.read_bytes();stamp=self.source.stat();mutated=[]
        def check():
            if self.dest.exists() and not mutated:
                mutated.append(True);self.source.write_bytes(bytes([raw[0]^1])+raw[1:])
                import os
                os.utime(self.source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaises(ContractError):self.build(check_task=check)
        self.assertTrue(mutated)

    def test_cancellation_keeps_unregistered_partial_and_does_not_overwrite_it(self):
        def check():
            if self.dest.exists():raise ContractError('合成取消，不能发表')
        with self.assertRaises(ContractError):self.build(check_task=check)
        self.assertTrue(self.dest.is_file());before=self.dest.read_bytes()
        with self.assertRaises((ContractError,FileExistsError)):self.build()
        self.assertEqual(self.dest.read_bytes(),before)

    def test_existing_archive_remains_byte_identical(self):
        result=self.build();before=self.dest.read_bytes()
        with self.assertRaises((ContractError,FileExistsError)):self.build()
        self.assertEqual(self.dest.read_bytes(),before)
        self.assertEqual(sha256(before).hexdigest(),result['archive']['sha256'])

    def test_unsafe_or_duplicate_members_reject_before_creating_file(self):
        cases=['../escape','/absolute','a\\b','C:drive','a/../b','./dot','a//b','a/']
        for name in cases:
            with self.subTest(name=name),self.assertRaises(ContractError):
                self.build([{'name':name,'data':b'x','role':'bad'}])
            self.assertFalse(self.dest.exists())
        for names in [('same','same'),('Case','case'),('验收目录与指纹.json','other')]:
            with self.subTest(names=names),self.assertRaises(ContractError):
                self.build([{'name':name,'data':b'x','role':'bad'} for name in names])
            self.assertFalse(self.dest.exists())

    def test_source_or_destination_outside_home_is_rejected(self):
        for entry in [dict(self.entries()[0],file=dict(self.ref,path='../foreign'))]:
            with self.assertRaises(ContractError):self.build([entry])
        with self.assertRaises(ContractError):
            self.api.write_archive(self.home,self.home.parent/'foreign.zip',self.entries(),self.metadata,min_free_bytes=0)

    def test_low_disk_fails_before_output_and_does_not_raise_byte_budget(self):
        with patch.object(self.api.shutil,'disk_usage',return_value=SimpleNamespace(free=0)),self.assertRaises(ContractError):self.build()
        self.assertFalse(self.dest.exists())

    def test_file_directory_prefix_collision_is_not_a_complete_extractable_package(self):
        for names in [('same','same/child'),('same/child','same'),('caf\u00e9','cafe\u0301')]:
            with self.subTest(names=names),self.assertRaises(ContractError):
                self.build([{'name':name,'data':b'x','role':'original'} for name in names])
            self.assertFalse(self.dest.exists())

    def test_source_growth_cannot_write_beyond_registered_member_length(self):
        changed=[]
        def check():
            if self.dest.exists() and not changed:
                changed.append(True);self.source.write_bytes(b'x'*(2*1024*1024))
        with self.assertRaises(ContractError):self.build(check_task=check)
        with zipfile.ZipFile(self.dest) as archive:
            self.assertLessEqual(archive.getinfo('registered/raw/evidence.bin').file_size,self.ref['bytes'])

    def test_repacked_metadata_cannot_change_revision_while_members_remain_valid(self):
        result=self.build();other=self.dest.with_name('wrong_metadata.zip')
        with zipfile.ZipFile(self.dest) as source,zipfile.ZipFile(other,'x',zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                raw=source.read(name)
                if name=='验收目录与指纹.json':raw=json.dumps(dict(result['metadata'],revision_id='foreign')).encode('utf8')
                target.writestr(name,raw)
        with self.assertRaises(ContractError):self.api.validate_archive(other,result['inventory'],result['metadata'])

    def test_windows_illegal_member_characters_reject_before_creating_file(self):
        for char in '<>"|?*'+''.join(chr(i) for i in range(1,32)):
            with self.subTest(char=repr(char)),self.assertRaises(ContractError):
                self.build([{'name':'unsafe'+char+'name','data':b'x','role':'original'}])
            self.assertFalse(self.dest.exists())

    def test_repacked_symlink_special_or_directory_type_cannot_pass_same_content_sha(self):
        result=self.build()
        for index,(name,mode,dos) in enumerate([
            ('registered/raw/evidence.bin',stat.S_IFLNK,0),('验收目录与指纹.json',stat.S_IFLNK,0),
            ('registered/raw/evidence.bin',stat.S_IFIFO,0),('registered/raw/evidence.bin',stat.S_IFDIR,0),
            ('registered/raw/evidence.bin',stat.S_IFREG,0x10)]):
            other=self.dest.with_name(f'wrong_type_{index}.zip')
            with zipfile.ZipFile(self.dest) as source,zipfile.ZipFile(other,'x',zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    raw=source.read(info.filename)
                    if info.filename==name:info.create_system=3;info.external_attr=((mode|0o600)<<16)|dos
                    target.writestr(info,raw)
            with self.subTest(name=name,mode=mode,dos=dos),self.assertRaises(ContractError):
                self.api.validate_archive(other,result['inventory'],result['metadata'])

    def test_repacked_wrong_member_with_valid_crc_cannot_pass_registered_inventory(self):
        result=self.build();other=self.dest.with_name('wrong.zip')
        with zipfile.ZipFile(self.dest) as source,zipfile.ZipFile(other,'x',zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                raw=source.read(name)
                target.writestr(name,bytes([raw[0]^1])+raw[1:] if name.endswith('evidence.bin') else raw)
        with self.assertRaises(ContractError):self.api.validate_archive(other,result['inventory'],result['metadata'])

    def test_valid_extra_member_or_changed_metadata_is_not_ignored(self):
        result=self.build()
        with zipfile.ZipFile(self.dest,'a') as archive:archive.writestr('unregistered.bin',b'extra')
        with self.assertRaises(ContractError):self.api.validate_archive(self.dest,result['inventory'],result['metadata'])
        with self.assertRaises(ContractError):self.api.validate_archive(self.dest,result['inventory'],dict(result['metadata'],revision_id='foreign'))

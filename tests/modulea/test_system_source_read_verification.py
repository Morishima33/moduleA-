"""大批来源只读核验与原科学入口对照；同大小/时间篡改、缺失及越界必须拒绝。"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contracts import ContractError
from storage import file_record
from modulea.core.read_archive import ReadArchive,verify_records


class SystemSourceReadVerificationTests(unittest.TestCase):
    def test_read_only_bulk_and_original_paths_both_reject_same_metadata_corruption(self):
        with tempfile.TemporaryDirectory(prefix='source_read_verification_') as temp:
            home=Path(temp);records=[]
            for number in range(70):
                p=home/'raw'/str(number);p.parent.mkdir(exist_ok=True);p.write_bytes(b'original');records.append(file_record(home,p,'source'))
            reader=ReadArchive();read_only=SimpleNamespace(verify_archives=reader.verify_all)
            verify_records(read_only,home,records);verify_records(object(),home,records)
            p=home/'raw/35';stat=p.stat();p.write_bytes(b'changed!');os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            for workflow in (read_only,object()):
                with self.subTest(read_only=workflow is read_only),self.assertRaises(ContractError):verify_records(workflow,home,records)

    def test_missing_and_outside_records_fail_without_skipping_other_files(self):
        with tempfile.TemporaryDirectory(prefix='source_read_bounds_') as temp:
            root=Path(temp);home=root/'study';home.mkdir();source=home/'valid';source.write_bytes(b'evidence')
            record=file_record(home,source,'source');outside=root/'outside';outside.write_bytes(b'other')
            reader=ReadArchive();read_only=SimpleNamespace(verify_archives=reader.verify_all)
            for workflow in (read_only,object()):
                with self.assertRaises(ContractError):verify_records(workflow,home,[record,dict(record,path='../outside')])
            source.unlink()
            for workflow in (read_only,object()):
                with self.assertRaises(ContractError):verify_records(workflow,home,[record])


if __name__=='__main__':unittest.main()

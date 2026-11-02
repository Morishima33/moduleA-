"""固定R环境对照旧/新脚本：仅修复中文常量，统计、背景与旧版本保持。"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock,patch

from science_modules.analysis_protocol import compile_plan
from science_modules.a05 import plan_flow as old,plan_flow_utf8 as new


class PlanA05UnicodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=old.SCRIPT.read_bytes();cls.old_version=old.VERSION
        cls.temp=tempfile.TemporaryDirectory(prefix='a05_unicode_');cls.addClassCleanup(cls.temp.cleanup)
        cls.root=Path(cls.temp.name)
        binary=Path(os.environ.get('MODULEA_RSCRIPT','D:/R/R-4.4.1/bin/x64/Rscript.exe'))
        if not binary.is_file():raise unittest.SkipTest('本地固定Rscript未安装，真实R编码对照未验证')
        terms=[{'id':'GO:0000001','description':'Synthetic hit','genes':['1','2','3']},
               {'id':'GO:0000002','description':'Synthetic too small','genes':['4']},
               {'id':'GO:0000003','description':'Synthetic no hit','genes':['4','5']}]
        cls.input={'genes':['1','2'],'annotations':{group:deepcopy(terms) for group in ('BP','CC','MF')},
                   'parameters':{'include_go':True,'include_kegg':False,'min_size':2,'max_size':3,'adjusted_p_lt':0.05}}
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(binary)}):
            cls.old_result,cls.old_log=old.r_call(cls.root,'analyze',cls.input)
            cls.new_result,cls.new_log=new.r_call(cls.root,'analyze',cls.input)

    def test_new_script_only_escapes_original_unicode_literals(self):
        restored=re.sub(r'\\u([0-9a-f]{4})',lambda match:chr(int(match[1],16)),new.SCRIPT.read_bytes().decode('utf8'))
        self.assertEqual(restored.encode('utf8'),self.before)
        self.assertEqual(old.SCRIPT.read_bytes(),self.before);self.assertEqual(old.VERSION,self.old_version)

    def test_actual_r_preserves_all_statistics_and_correctly_encodes_both_reasons(self):
        before=deepcopy(self.old_result);after=deepcopy(self.new_result)
        for group in ('BP','CC','MF'):
            reasons={row['ID']:row['reason'] for row in after[group]['skipped']}
            self.assertEqual(reasons,{'GO:0000002':'条目背景基因数不在本方案范围','GO:0000003':'有效输入无命中'})
            for value in (before,after):
                for row in value[group]['skipped']:row.pop('reason')
        self.assertEqual(before,after)
        self.assertEqual(old.SCRIPT.read_bytes(),self.before)

    def test_configuration_snapshots_both_versions_and_script_without_changing_parameters(self):
        plan=compile_plan({'mode':'standard'});old_config=old.configuration(plan);new_config=new.configuration(plan)
        self.assertEqual(new_config['version'],new.VERSION)
        self.assertEqual(new_config['text_encoding_rule'],'R.unicode_literals.1')
        for key,value in old_config.items():
            if key not in ('version','implementation_sha256'):self.assertEqual(new_config[key],value,key)
        for path in (Path(old.__file__),Path(new.__file__),old.SCRIPT,new.SCRIPT):
            self.assertEqual(new_config['implementation_sha256'][path.name],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(old.configuration(plan),old_config)

    def test_old_protocol_still_delegates_and_new_r_log_records_actual_script(self):
        fallback=Mock(return_value='original_validation')
        check=new.validator(self.root,fallback)
        self.assertEqual(check({'config':{'version':old.VERSION}},{},{},[],'success'),'original_validation')
        fallback.assert_called_once()
        self.assertIn(new.SCRIPT.name,self.new_log);self.assertIn(old.SCRIPT.name,self.old_log)


if __name__=='__main__':unittest.main()

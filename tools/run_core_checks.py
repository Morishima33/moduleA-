"""双平台核心检查入口；逐项保留跳过，不把科学工具或真实病例缺失记作通过。"""
from pathlib import Path
import json
import os
import platform
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
os.environ['PYTHONPATH']=str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')
MODULES=(
 'tests.modulea.test_archive_checkout',
 'tests.modulea.test_service_identity','tests.modulea.test_service_control',
 'tests.modulea.test_service_delivery_http','tests.modulea.test_platform_launcher',
 'tests.modulea.test_native_process_cancel','tests.modulea.test_compute_budget',
 'tests.modulea.test_resource_runner','tests.modulea.test_tasks',
 'tests.modulea.test_rescue_evidence_http','tests.modulea.test_rescue_read_evidence_v2',
 'tests.modulea.test_rescue_read_records','tests.modulea.test_read_evidence_scope',
 'tests.modulea.test_migration_integrity','tests.modulea.test_scientific_progress',
 'tests.modulea.test_system_receptor_rescue_http_v2',
 'tests.modulea.test_system_receptor_rescue_v2_core','tests.modulea.test_system_receptor_rescue_v2_worker',
)
suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
result=unittest.TextTestRunner(verbosity=2).run(suite)
summary={'system':platform.system(),'machine':platform.machine(),'python':sys.version,
         'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
         'skipped':[{'test':str(test),'reason':reason} for test,reason in result.skipped],
         'scientific_tools_executed':False,'real_case_verified':False,
         'successful':result.wasSuccessful()}
print(json.dumps(summary,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)

"""PPI新旧规则分派：既已应用的身份方案保持，同一上游才可沿用。"""
from science_modules.a04.flow_v3 import run_ppi as base_run, docking_validator
from science_modules.a04.identity_flow import validator, run_authorized

# 再次计算保留本研究、本A03已应用的明确方案，不退回未补查状态。
def run_ppi(workflow, sid, expected_a03, expected_a04, reason, bundle=None):
    manifest = workflow.load(sid)
    if expected_a04 and expected_a04 in manifest["runs"]:
        prior = workflow.run(manifest, expected_a04)
        record = prior.get("inputs", {}).get("identity_authorization")
        if record and prior.get("parent_runs", {}).get("A03") == expected_a03:
            return run_authorized(workflow, sid, expected_a03, expected_a04, reason, record, bundle)
    return base_run(workflow, sid, expected_a03, expected_a04, reason, bundle)

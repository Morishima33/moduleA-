"""A04身份方案应用第1版：复用已确认科学算法，归档每次人工方案，历史独立复算。"""

from pathlib import Path
from types import FunctionType
from contracts import require
from storage import read_json, verified_file
from ppi_identity import SNAPSHOT
from science_modules.a04 import flow_v3 as prior
from modulea.core.identity_workflow import SCHEMA, RULE, identity_snapshot

VERSION = "A04.identity_apply.1"
CONFIG = dict(prior.CONFIG, version=VERSION, identity_authorization_rule="A04.identity.plan.1")


# 决定只能用于其原研究、原上游；绑定的A03/A04归档必须完整且一致。
def scope_from_record(root, sid, a03, record):
    home = Path(root) / "studies" / sid
    decision = read_json(verified_file(home, record))
    require(
        decision.get("schema_version") == SCHEMA
        and decision.get("identity_rule") == RULE
        and decision.get("study_id") == sid
        and decision.get("scope", {}).get("study_id") == sid
        and decision["scope"].get("a03_run") == a03,
        "身份方案不属于本研究、本A03版本",
    )
    from modulea.core.identity_workflow import IdentityWorkflow

    workflow = IdentityWorkflow(root)
    manifest = workflow.load(sid)
    require(record in manifest.get("identity_decisions", []), "身份方案未登记为本研究的人工决定")
    previous_run = workflow.run(manifest, decision["a04_run"])
    require(
        decision["a03_result"] == manifest["runs"][a03]["result_file"]
        and decision["a04_result"] == manifest["runs"][decision["a04_run"]]["result_file"],
        "身份方案归档索引不一致",
    )
    parent = read_json(verified_file(home, decision["a03_result"]))
    previous = read_json(verified_file(home, decision["a04_result"]))
    require(
        parent["run_id"] == a03
        and parent["study_id"] == sid
        and previous["run_id"] == decision["a04_run"]
        and previous["study_id"] == sid
        and previous_run["parent_runs"].get("A03") == a03,
        "身份方案与上游归档不一致",
    )
    allowed = {r["target_id"] for r in previous["tables"].get("identity_issues", [])}
    carried = decision.get("carried_authorization")
    require(
        carried == previous_run.get("inputs", {}).get("identity_authorization"),
        "沿用身份方案与原A04不一致",
    )
    if carried:
        require(carried != record, "身份方案不能循环引用自身")
        inherited = scope_from_record(root, sid, a03, carried)
        allowed.update(inherited["check_ids"])
        require(
            set(inherited["check_ids"]) <= set(decision["scope"]["check_ids"])
            and set(inherited["omit_ids"]) <= set(decision["scope"]["omit_ids"]),
            "已应用身份方案的范围不能被隐式撤销",
        )
    scope = decision["scope"]
    require(
        set(scope["check_ids"]) <= allowed and set(scope["omit_ids"]) <= set(scope["check_ids"]),
        "身份方案超出原问题清单",
    )
    return scope


# 冻结的第3版校验器复用全部来源、名单、阈值、图元校验，只替换本次决定的读取入口。
def validator(root):
    previous = prior.validator(root)

    def check(run, *args):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, *args)
        record = run["inputs"].get("identity_authorization")
        scope = scope_from_record(root, run["study_id"], run["parent_runs"]["A03"], record)
        factory = FunctionType(
            prior.validator.__code__,
            dict(
                prior.validator.__globals__,
                VERSION=VERSION,
                CONFIG=CONFIG,
                authorization=lambda *_: scope,
            ),
        )
        return factory(root)(run, *args)

    return check


# 后台获取完整官方证据，原始名称冲突不放宽；只新增A04，不批准或接续其他模块。
def run_identity(workflow, sid, payload, bundle=None):
    decision, record = workflow.save_identity_plan(sid, payload)
    return apply_authorization(
        workflow, sid, payload["expected_a03"], payload["expected_a04"], decision, record, bundle
    )


# 已成功应用的同上游授权在再次计算时继续使用，不重复保存人工决定。
def run_authorized(workflow, sid, a03, a04, reason, record, bundle=None):
    decision = read_json(verified_file(workflow.location(sid), record))
    return apply_authorization(workflow, sid, a03, a04, decision, record, bundle, reason)


# 人工补查与再次计算共用同一应用路径，历史来源与决定均不覆盖。
def apply_authorization(workflow, sid, a03, a04, decision, record, bundle=None, reason=None):
    scope = scope_from_record(workflow.root, sid, a03, record)
    raw = identity_snapshot(workflow.root, sid, SNAPSHOT)
    require(
        bundle is None or bundle.get("schema_version") == "A04.source.2",
        "应用身份方案需要完整稳定编号补查包",
    )

    # 在临时函数全局中绑定本次决定，不修改冻结实现、模块全局或任何历史默认授权。
    def contextual_fetch(targets, *args):
        from science_modules.a04.source_io import request
        from ppi_flow import fetch as frozen_fetch

        responses = []

        def capture(method, params):
            response = request(method, params)
            responses.append(response)
            return response

        fetch = FunctionType(
            frozen_fetch.__code__,
            dict(frozen_fetch.__globals__, request=capture, SNAPSHOT=SNAPSHOT),
        )
        try:
            result = fetch(targets, raw, scope)
        except Exception as error:
            workflow.save_identity_evidence(sid, record, responses, str(error))
            raise
        workflow.save_identity_evidence(sid, record, responses, "")
        return result

    def scoped_begin(manifest, module, inputs, config, reason):
        current, _ = workflow.identity_plan(manifest, a03)
        require(
            current and current["decision_id"] == decision["decision_id"],
            "身份方案已更新，请刷新后重新确认",
        )
        inputs = dict(inputs, identity_authorization=record)
        return workflow._begin(manifest, module, inputs, config, reason)

    class BoundWorkflow:
        def __getattr__(self, name):
            return scoped_begin if name == "_begin" else getattr(workflow, name)

    runner = FunctionType(
        prior.run_ppi.__code__,
        dict(
            prior.run_ppi.__globals__,
            CONFIG=CONFIG,
            authorization=lambda *_: scope,
            context=lambda *_: raw,
            fetch=contextual_fetch,
            SNAPSHOT=SNAPSHOT,
        ),
    )
    return runner(
        BoundWorkflow(),
        sid,
        a03,
        a04,
        reason or ("用户确认身份补查方案：" + decision["note"]),
        bundle=bundle,
    )

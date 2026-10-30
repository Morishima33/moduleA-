"""新批次真实结构准备：系统固定输入与原完整科学质控，旧人工协议保持。"""
from copy import deepcopy
from pathlib import Path
import hashlib,shutil
from types import FunctionType
from contracts import fingerprint,require
from storage import file_record,new_id,read_json,verified_file,write_json

VERSION='A06.system_preparation.1'


def configuration(plan):
    """实际参数仍用原第二版，只将执行协议及输入类型明确分开。"""
    from .plan_preparation_v2 import execution_config
    return dict(execution_config(plan),version=VERSION,system_input_schema='A06.system_preparation_input.1')


def read_input(workflow,m,reference,batch_ref):
    """核对本批真实系统固定范围，不能用旧人工输入或伪造审核替代。"""
    from modulea.core import system_decisions,system_execution
    value=system_decisions.read_record(workflow,m,reference)
    require(value['stage']=='A06_INPUT' and value['binding']['batch_file']==batch_ref
        and system_decisions.active(workflow,m,value),'系统结构准备固定输入或真实依赖已失效')
    batch,record=system_execution.require_batch(workflow,m,batch_ref)
    require(value['payload']['plan_ref']==batch['plan_file'],
        '系统结构准备方案不一致')
    return value['payload'],record['plan']


def reports(packet,compounds,receptors):
    """原完整组合统计只局部绑定新输入版本，准备仍不表示评分或人工批准。"""
    from . import plan_preparation_v2 as legacy
    from .system_input import pair_statuses
    calculate=FunctionType(legacy.reports.__code__,dict(vars(legacy),pair_statuses=pair_statuses),legacy.reports.__name__)
    summary,tables=calculate(packet,compounds,receptors)
    summary.update(science_version=VERSION,analysis_parameter_hash=packet['analysis_parameter_hash'],human_review_written=False,
        message_zh='本批真实结构准备事实已归档；预测口袋及后续资格仍按实际证据核验，尚未执行组合评分或人工批准')
    return summary,tables


def compute(workflow,m,batch,record,batch_ref,tools,progress):
    """锁外实际来源与工具执行；每次尝试独立归档，固定名单不补位。"""
    from modulea.core import system_decisions
    from . import plan_preparation_v2 as legacy
    home=workflow.location(m['study_id']);ref,fixed=system_decisions.current(workflow,m,batch['batch_id'],'A06_INPUT')
    require(fixed,'请先生成本批系统固定准备范围')
    packet,plan=read_input(workflow,m,ref,batch_ref);require(packet['pair_count']>0,'本批固定准备范围为空，不启动结构工具')
    tools=Path(tools);executable=legacy._version(tools);config=configuration(plan)
    from .system_preparation_recovery import recover
    restored=recover(workflow,m,batch,batch_ref,ref,packet,config,executable)
    if restored:
        fact_ref,recovery_ref=restored
        return prepared_output(workflow,m,batch,record,batch_ref,ref,packet,config,fact_ref,recovery_ref)
    folder=home/'decisions/analysis_plans/system_batches'/batch['batch_id']/'acquisition/A06_PREP'/new_id('attempt')
    folder.mkdir(parents=True);write_json(folder/'request.json',{'batch_file':batch_ref,'system_input_ref':ref,
        'input_key':packet['input_key'],'configuration':config,'human_review_written':False})
    binary=folder/'software/vina_1.2.7.exe';binary.parent.mkdir();shutil.copyfile(executable,binary)
    src=Path(__file__).resolve().parents[2]
    code_names=('science_modules/a06/system_preparation.py','science_modules/a06/system_input.py',
        'science_modules/a06/plan_preparation_v2.py','science_modules/a06/plan_quality_engine_v2.py',
        'science_modules/a06/plan_input.py','science_modules/a06/automatic_sources.py','science_modules/a06/automatic_engine.py',
        'science_modules/a06/quality_engine.py','science_modules/a06/two_pass.py','docking_ligand.py','docking_audit.py',
        'docking_receptor.py','docking_p2rank.py','docking_reference_ligand.py','docking_redocking.py','docking_top10_execute.py')
    implementations=[]
    for name in code_names:
        destination=folder/'code'/name;destination.parent.mkdir(parents=True,exist_ok=True);raw=(src/name).read_bytes();destination.write_bytes(raw)
        implementations.append((src/name,raw))
    connection=legacy.connect(home,packet,folder/'sources',progress)
    compounds,receptors=legacy.prepare(home,connection,folder,tools,progress,config)
    require(all(path.read_bytes()==raw for path,raw in implementations),'结构准备期间实际实现源码改变')
    summary,tables=reports(packet,compounds,receptors)
    fact={'schema_version':VERSION,'study_id':m['study_id'],'system_input_ref':ref,'batch_file':batch_ref,
        'input_key':packet['input_key'],'attempt_path':folder.relative_to(home).as_posix(),'config':config,'connection':connection,
        'compounds':compounds,'receptors':receptors,'vina_binary':file_record(home,binary,'vina_binary'),
        'vina_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'vina_version_stdout':'AutoDock Vina v1.2.7','human_review_written':False,
        'files':[file_record(home,p,'preparation_evidence') for p in folder.rglob('*') if p.is_file()]}
    write_json(folder/'packet.json',fact);fact_ref=file_record(home,folder/'packet.json','preparation_packet');tables['preparation_packet']=[fact_ref]
    return prepared_output(workflow,m,batch,record,batch_ref,ref,packet,config,fact_ref)


def prepared_output(workflow,m,batch,record,batch_ref,ref,packet,config,fact_ref,recovery_ref=None):
    """新算和真实原件恢复都从同一事实包重建结果，不借用旧摘要。"""
    fact=read_json(verified_file(workflow.location(m['study_id']),fact_ref))
    summary,tables=reports(packet,fact['compounds'],fact['receptors']);tables['preparation_packet']=[fact_ref]
    inputs={'study_id':m['study_id'],'bound_a00':batch['request']['expected_a00'],'analysis_plan_id':record['plan_id'],
        'analysis_plan_file':deepcopy(batch['plan_file']),'analysis_parameter_hash':packet['analysis_parameter_hash'],
        'system_input_ref':ref,'preparation_fact':fact_ref}
    sources=[batch_ref,ref,batch['plan_file'],fact_ref,*fact['files']]
    if recovery_ref:
        inputs['preparation_recovery']=recovery_ref;sources.append(recovery_ref)
        sources.extend(read_json(verified_file(workflow.location(m['study_id']),recovery_ref)).get('implementation_files',[]))
    return inputs,config,summary,tables,[],sources,{'outcome':'success'}


def validate_evidence(home,packet,fact,expected_config):
    """保留原第二版完整科学复算；仅工具路径改为真实本批尝试目录。"""
    from .plan_preparation_v2 import assess_plan_attempt
    import subprocess
    require([r['compound_id'] for r in fact['compounds']]==[r['compound_id'] for r in packet['compounds']]
        and [r['target_id'] for r in fact['receptors']]==[r['target_id'] for r in packet['receptors']],
        '准备事实未覆盖原固定名单或改变次序')
    connection = fact["connection"]
    require([r["compound_id"] for r in connection["compounds"]] ==
            [r["compound_id"] for r in packet["compounds"]] and
            [r["target_id"] for r in connection["receptors"]] ==
            [r["target_id"] for r in packet["receptors"]], "准备对象与固定选择不一致")
    for record in fact["files"] + connection["files"]:
        verified_file(home, record)
    require(fact["vina_binary"]["path"] ==
            (fact["attempt_path"]+"/software/vina_1.2.7.exe") and
            hashlib.sha256(verified_file(home, fact["vina_binary"]).read_bytes()).hexdigest()
            == fact["vina_sha256"], "Vina工具快照与记录指纹不符")
    from .plan_quality_engine_v2 import tool_path
    version=subprocess.run([tool_path(verified_file(home,fact['vina_binary'])),'--version'],capture_output=True,text=True,timeout=20)
    require(version.returncode==0 and version.stdout.strip()==fact['vina_version_stdout']=='AutoDock Vina v1.2.7',
        '系统准备实际工具版本不符')
    from docking_ligand import prepare_ligand
    from docking_top10_execute import _meeko_settings
    connected = {r["compound_id"]: r for r in connection["compounds"]
                 if r["state"] == "connected"}
    for row in fact["compounds"]:
        source = connected.get(row["compound_id"])
        if row["state"] == "ready":
            require(source and source["identity_matched"], "配体通过项缺少官方身份证据")
            actual = prepare_ligand(verified_file(home, source["sdf"]).read_text("utf-8"),
                                    source["cid"], source["audit"]["inchi_key"],
                                    _meeko_settings())
            prepared = next(r for r in row["files"] if r["role"] == "prepared_ligand")
            # JSON将Meeko默认元组保存为数组；比较序列化内容，PDBQT仍逐字节复核。
            require(verified_file(home, prepared).read_text("ascii") ==
                    actual.pop("pdbqt_text") and fingerprint(row["preparation"]) == fingerprint(actual),
                    "配体准备文件与来源三维复算不一致")
        else:
            require(row["state"] == "NA" and row["reason_zh"], "失败配体须保留NA和原因")
    from docking_redocking import _poses, symmetry_rmsd
    originals = {r["target_id"]: r for r in connection["receptors"]}
    for row in fact["receptors"]:
        require(row["target_id"] in originals, "受体不属于固定输入")
        assessments = []
        for trace in row["attempts"]:
            spec, evidence = trace["candidate"]["spec"], trace["evidence"]
            require(trace["candidate"] in originals[row["target_id"]].get("candidates", []),
                    "受体尝试不属于官方连接候选")
            if evidence.get("predicted_pocket"):
                from docking_p2rank import _prediction_rows
                from .plan_quality_engine_v2 import prediction_box
                predicted = evidence["predicted_pocket"]
                predictions = [r for r in predicted["files"] if r["role"] == "p2rank_prediction"]
                require(len(predictions) == 2, "预测口袋缺少两次原始文件")
                rows = [_prediction_rows(verified_file(home, ref))[0] for ref in predictions]
                keys = ("rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids")
                require(all(rows[0][k] == rows[1][k] for k in keys), "两次预测口袋不一致")
                expected_box = prediction_box(verified_file(home, predicted["input_pdb"]).read_text("ascii"),
                                              rows[0], expected_config["box_padding"])
                require(evidence.get("box") == expected_box, "预测搜索盒与方案参数或原始坐标不符")
            if evidence.get("top1_rmsd") is not None:
                from docking_top10_execute import _ligand_lines
                from .plan_quality_engine_v2 import reference_box
                conversions = [r for r in evidence["files"] if r["path"].endswith("/original_conversion.pdb")]
                require(len(conversions) == 1, "参考重对接缺少实际结构转换文件")
                reference = _ligand_lines(verified_file(home, conversions[0]), spec["reference_code"],
                                          spec["reference_chain"], spec["reference_sequence"], spec.get("altloc"))
                require(evidence["box"] == reference_box(reference, expected_config["box_padding"]),
                        "参考搜索盒与实际坐标或方案外扩不符")
                commands = [r for r in evidence["files"] if r["path"].endswith("/redocking/command.json")]
                require(len(commands) == 1, "参考重对接缺少实际命令记录")
                command = read_json(verified_file(home, commands[0]))
                require(command["parameters"] == expected_config["vina_parameters"] and
                        command["box"] == evidence["box"], "重对接命令与方案参数不符")
                args = command["arguments"]
                for flag, value in (("--scoring", expected_config["vina_parameters"]["scoring"]),
                    ("--exhaustiveness", expected_config["vina_parameters"]["exhaustiveness"]),
                    ("--num_modes", expected_config["vina_parameters"]["num_modes"]),
                    ("--energy_range", expected_config["vina_parameters"]["energy_range_kcal_mol"]),
                    ("--seed", expected_config["vina_parameters"]["seed"])):
                    require(args.count(flag) == 1 and args[args.index(flag)+1] == str(value),
                            "实际命令参数与方案不一致")
                for axis, center, size in zip("xyz", evidence["box"]["center"], evidence["box"]["size"]):
                    for flag, value in (("--center_" + axis, center), ("--size_" + axis, size)):
                        require(args.count(flag) == 1 and args[args.index(flag)+1] == str(value),
                                "实际命令搜索盒与归档不一致")
                pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
                value = symmetry_rmsd(verified_file(home, evidence["reference_sdf"]).read_bytes(),
                                      verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"),
                                      pose)["rmsd_angstrom"]
                require(abs(value - evidence["top1_rmsd"]) < 1e-9,
                        "参考重对接RMSD与Top-1原文件不符")
            assessment = assess_plan_attempt(spec, evidence, originals[row["target_id"]],
                                        1 if spec["pocket"] == "reference" else 2, expected_config)
            require(assessment == trace["assessment"], "受体质控结论与证据复算不一致")
            assessments.append(assessment)
        ready = next((a for a in assessments if a["state"] == "ready"), None)
        require(row['quality']==(ready['quality'] if ready else '待核查'),'准备质控等级与实际原始证据不同')
        require(row["state"] == ("ready" if ready else "NA") and
                row["reason_zh"] == (ready["reason_zh"] if ready else
                (originals[row["target_id"]].get("reason_zh") or "官方结构未连接") if not assessments
                else "; ".join(a["reason_zh"] for a in assessments)),
                "受体准备状态与原始证据不一致")


def validator(root,previous):
    """新授权契约独立核对，全部结构/命令/构型证据仍实际复算，不放宽旧规范。"""
    def check(run,summary,tables,anomalies,outcome):
        if run['config'].get('version')!=VERSION:return previous(run,summary,tables,anomalies,outcome)
        from modulea.core.analysis_plans import AnalysisPlanWorkflow
        w=AnalysisPlanWorkflow(root);m=w.load(run['study_id']);home=w.location(run['study_id']);inputs=run['inputs']
        require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
            and run['execution_authority']=='system_validation','结构准备不能伪造人工批准')
        packet,plan=read_input(w,m,inputs['system_input_ref'],run['batch_file']);expected_config=configuration(plan)
        require(run['config']==expected_config and anomalies==[] and outcome=='success','系统准备配置或计算状态不一致')
        require(inputs['analysis_plan_file']==packet['plan_ref'] and inputs['analysis_parameter_hash']==plan['parameter_hash']
            and all(run['parent_runs'][key]==packet['runs'][key] for key in ('A03','A03_SELECT','A04')),
            '系统准备运行、固定对象或方案不一致')
        require(tables.get('preparation_packet')==[inputs['preparation_fact']],'系统准备事实包引用不一致')
        fact=read_json(verified_file(home,inputs['preparation_fact']))
        prefix='decisions/analysis_plans/system_batches/'+read_json(verified_file(home,run['batch_file']))['batch_id']+'/acquisition/A06_PREP/'
        require(fact['attempt_path'].startswith(prefix) and '/' not in fact['attempt_path'][len(prefix):]
            and inputs['preparation_fact']['path']==fact['attempt_path']+'/packet.json', '系统准备事实不属于本批独立尝试')
        require(fact['schema_version']==VERSION and fact['study_id']==run['study_id'] and fact['human_review_written'] is False
            and fact['system_input_ref']==inputs['system_input_ref'] and fact['batch_file']==run['batch_file']
            and fact['input_key']==packet['input_key'] and fact['config']==expected_config,'系统准备事实与明确批次或输入不同')
        validate_evidence(home,packet,fact,expected_config)
        if inputs.get('preparation_recovery'):
            recovery=read_json(verified_file(home,inputs['preparation_recovery']))
            require(recovery['schema_version']=='A06.system_preparation_recovery.1' and recovery['study_id']==run['study_id']
                and recovery['batch_file']==run['batch_file'] and recovery['preparation_fact']==inputs['preparation_fact']
                and recovery['system_input_ref']==inputs['system_input_ref'] and recovery['input_key']==packet['input_key']
                and recovery['network_requested'] is False and recovery['new_preparation_executed'] is False
                and recovery['human_review_written'] is False,'结构准备恢复记录与实际原件不同')
            for source in recovery.get('implementation_files',[]):verified_file(home,source)
        expected,rows=reports(packet,fact['compounds'],fact['receptors']);rows['preparation_packet']=[inputs['preparation_fact']]
        require(fingerprint((summary,tables))==fingerprint((expected,rows)),'系统准备摘要或完整NA范围与证据复算不一致')
    return check

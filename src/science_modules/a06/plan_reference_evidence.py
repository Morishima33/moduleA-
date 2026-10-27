"""新方案共晶参考的证据适配；只消费明确稳定键，不替研究选择配体或批准。"""
from copy import deepcopy

from contracts import require
from storage import verified_file
from .reference_candidates import apply_choices, validate_choices
from .reference_prepare import complete_reference, verify_sequence
from .automatic_engine import preparation_source
from .plan_preparation_v2 import assess_plan_attempt

VERSION = "A06.plan_reference_evidence.1"


def prepare_selected(home, connection, choice, folder, tools, config, progress):
    """对明确选择的共晶独立核对序列、CCD和参考重对接，失败保留原因。"""
    from .plan_quality_engine_v2 import attempt, download_ccd
    selected = validate_choices(home, connection, [choice])
    require(len(selected) == 1, "共晶选择不能唯一定位")
    adapted = apply_choices(home, connection, [choice])
    row = next(r for r in adapted["receptors"] if r["target_id"] == choice["target_id"])
    candidate = deepcopy(row["candidates"][0])
    value = {"schema_version": VERSION, "choice": deepcopy(choice), "candidate": candidate,
             "state": "NA", "quality": "待核查", "reason_zh": "尚未完成参考准备"}
    folder.mkdir(parents=True, exist_ok=False)
    try:
        sequence_audit = verify_sequence(home, candidate, row, folder / "sequence")
        topology = folder / "topology"
        topology.mkdir()
        ccd = download_ccd(candidate["spec"]["reference_code"], topology)
        candidate = complete_reference(home, candidate, ccd.read_text("utf-8"))
        candidate["reference_sequence_audit"] = sequence_audit
        row = dict(row, candidates=[candidate])
        source = preparation_source(dict(adapted, receptors=[row]))
        evidence = attempt(home, source, row, candidate["spec"], 1, folder / "attempt", tools, progress,
                           box_padding=config["box_padding"], vina_parameters=config["vina_parameters"])
        assessment = assess_plan_attempt(candidate["spec"], evidence, row, 1, config)
        value.update(candidate=candidate, evidence=evidence, assessment=assessment,
                     state="ready" if assessment["state"] == "ready" else "NA",
                     quality=assessment["quality"], reason_zh=assessment["reason_zh"])
        if evidence.get("error_zh"):
            value["reason_zh"] = evidence["error_zh"]
        return value
    except Exception as error:
        value.update(candidate=candidate, reason_zh=str(error))
        return value


def validate_ready(home, connection, result, config):
    """成功项再次从CCD、坐标、序列和实际Top-1文件复算，不能以选择代替通过。"""
    from .reference_candidates import candidate_key
    from .automatic_coverage_sources import sequence_scope
    from .plan_quality_engine_v2 import environment_audit, reference_box
    from docking_top10_execute import _ligand_lines, _meeko_settings
    from docking_reference_ligand import prepare_reference_ligand
    from docking_redocking import _poses, symmetry_rmsd
    from storage import read_json
    import gemmi
    require(result["schema_version"] == VERSION and result["state"] == "ready", "共晶参考尚未准备通过")
    selected = validate_choices(home, connection, [result["choice"]])[0]
    row = next(r for r in connection["receptors"] if r["target_id"] == selected["target_id"])
    original = next(c for c in row["candidates"] if candidate_key(c) == result["choice"]["candidate_key"])
    candidate, evidence = result["candidate"], result["evidence"]
    expected = apply_choices(home, connection, [result["choice"]])
    expected_origin = next(r for r in expected["receptors"] if r["target_id"] == selected["target_id"])["candidates"][0]
    records = [r for r in evidence["files"] if r["path"].endswith("/ccd_" + selected["component_id"] + ".cif")]
    require(len(records) == 1, "参考证据缺少实际CCD原件")
    complete = complete_reference(home, expected_origin, verified_file(home, records[0]).read_text("utf-8"))
    require({k:v for k,v in candidate.items() if k != "reference_sequence_audit"} == complete,
            "实际参考配体与明确选择或CCD原子完整性不符")
    audit = candidate["reference_sequence_audit"]
    official = read_json(verified_file(home, audit["official_sequence_file"]))
    cif = verified_file(home, original["cif"]).read_text("utf-8")
    require(sequence_scope(cif, candidate["spec"], official) == audit["sequence_scope"], "实际序列映射不一致")
    conversions = [r for r in evidence["files"] if r["path"].endswith("/original_conversion.pdb")]
    require(len(conversions) == 1, "参考准备缺少原结构转换文件")
    converted = verified_file(home, conversions[0])
    structure = gemmi.make_structure_from_block(gemmi.cif.read_string(cif).sole_block())
    require(len(structure) == 1 and converted.read_text("ascii") == structure.make_pdb_string(),
            "参考结构转换与官方原件不一致")
    spec = candidate["spec"]
    reference = _ligand_lines(converted, spec["reference_code"],
                              spec["reference_chain"], spec["reference_sequence"], spec.get("altloc"))
    expected_reference = prepare_reference_ligand(verified_file(home, records[0]).read_text("utf-8"),
        reference, spec["reference_code"], spec["reference_chain"], spec["reference_sequence"], _meeko_settings())
    require(verified_file(home,evidence["reference_sdf"]).read_text("utf-8") == expected_reference["sdf_text"] and
            verified_file(home,evidence["reference_pdbqt"]).read_text("ascii") == expected_reference["pdbqt_text"],
            "参考配体实际准备文件与官方CCD及坐标复算不一致")
    require(evidence["box"] == reference_box(reference, config["box_padding"]), "参考搜索盒与实际坐标不一致")
    env = environment_audit(cif, spec, evidence["box"])
    require(evidence["environment_audit"] == env and env["pocket_complete"] and env["environment_resolved"],
            "参考口袋结构环境未通过复验")
    commands = [r for r in evidence["files"] if r["path"].endswith("/redocking/command.json")]
    require(len(commands) == 1, "参考重对接缺少实际命令记录")
    command = read_json(verified_file(home,commands[0]))
    require(command["parameters"] == config["vina_parameters"] and command["box"] == evidence["box"],
            "参考重对接命令参数与方案不一致")
    expected_flags = {"--scoring":config["vina_parameters"]["scoring"],
        "--exhaustiveness":config["vina_parameters"]["exhaustiveness"],
        "--num_modes":config["vina_parameters"]["num_modes"],
        "--energy_range":config["vina_parameters"]["energy_range_kcal_mol"],
        "--seed":config["vina_parameters"]["seed"],
        "--receptor":str(verified_file(home,evidence["receptor"])),
        "--ligand":str(verified_file(home,evidence["reference_pdbqt"])),
        "--out":str(verified_file(home,evidence["redocking_output"]))}
    for axis, center, size in zip("xyz",evidence["box"]["center"],evidence["box"]["size"]):
        expected_flags["--center_"+axis] = center
        expected_flags["--size_"+axis] = size
    arguments = command["arguments"]
    for flag, value in expected_flags.items():
        require(arguments.count(flag) == 1 and arguments[arguments.index(flag)+1] == str(value),
                "实际参考重对接命令与文件或方案不一致")
    pose = _poses(verified_file(home, evidence["redocking_output"]).read_text("ascii"))[0]
    value = symmetry_rmsd(verified_file(home, evidence["reference_sdf"]).read_bytes(),
                          verified_file(home, evidence["reference_pdbqt"]).read_text("ascii"), pose)["rmsd_angstrom"]
    require(abs(value - evidence["top1_rmsd"]) < 1e-9, "参考重对接RMSD与Top-1文件不符")
    assessment = assess_plan_attempt(spec, evidence, row, 1, config)
    require(assessment == result["assessment"] and assessment["state"] == "ready" and assessment["quality"] == "严格",
            "共晶参考质控结论与证据不一致")
    require(result.get("quality") == assessment["quality"] and result.get("reason_zh") == assessment["reason_zh"],
            "共晶参考摘要与实际质控结论不一致")
    return assessment

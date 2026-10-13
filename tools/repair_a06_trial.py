"""独立PDBFixer环境中的有限修补；禁止新增主链或改动已解析重原子。"""

import argparse
import json
import sys
from pathlib import Path


def heavy_atoms(path):
    """以链、残基和原子名定位原已解析重原子。"""
    atoms = {}
    for line in path.read_text("ascii").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and line[76:78].strip() not in {
            "H",
            "D",
        }:
            key = (line[21], line[22:27].strip(), line[12:16].strip())
            if key in atoms:
                raise ValueError("输入存在未消除的替代构象")
            atoms[key] = tuple(float(line[a : a + 8]) for a in (30, 38, 46))
    return atoms


def main():
    """只增加既有残基的侧链原子；先验证再交给固定Meeko参数化。"""
    parser = argparse.ArgumentParser()
    for name in ("packages", "input", "output", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.packages))
    from importlib.metadata import version

    from openmm import Platform
    from openmm.app import PDBFile
    from pdbfixer import PDBFixer

    # OpenMM Windows原生插件枚举不识别中文目录；使用同一目录的8.3名称，不复制工具。
    if sys.platform == "win32":
        import ctypes
        import os

        library = args.packages / "OpenMM.libs/lib"
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetShortPathNameW(
            str(library), buffer, len(buffer)
        ):
            raise ValueError("无法获得同一OpenMM插件目录的Windows短路径")
        with os.add_dll_directory(str(library)):
            Platform.loadPluginsFromDirectory(buffer.value + "/plugins")

    if version("pdbfixer") != "1.12.0" or version("OpenMM") != "8.4.0":
        raise ValueError("有限修补工具版本改变")
    before = heavy_atoms(args.input)
    fixer = PDBFixer(
        filename=str(args.input), platform=Platform.getPlatformByName("CPU")
    )
    fixer.findMissingResidues()
    missing_residues = {str(k): v for k, v in fixer.missingResidues.items()}
    fixer.missingResidues = {}
    fixer.findMissingAtoms()
    for residue, atoms in fixer.missingAtoms.items():
        if any(a.name in {"N", "CA", "C", "O"} for a in atoms):
            raise ValueError(
                f"残基{residue.chain.id}:{residue.id}主链缺失，禁止自行补建"
            )
    # 末端OXT属于主链末端，不在本轮许可的缺失侧链范围内。
    fixer.missingTerminals = {}
    fixer.addMissingAtoms(seed=1)
    with args.output.open("x", encoding="ascii") as stream:
        PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
    after = heavy_atoms(args.output)
    if any(k not in after or before[k] != after[k] for k in before):
        raise ValueError("有限修补改变了原已解析重原子坐标或身份")
    added = [
        {"chain": k[0], "residue": k[1], "atom": k[2], "xyz": v}
        for k, v in after.items()
        if k not in before
    ]
    if any(a["atom"] in {"N", "CA", "C", "O", "OXT"} for a in added):
        raise ValueError("有限修补新增主链原子，拒绝输出")
    args.evidence.write_text(
        json.dumps(
            {
                "pdbfixer": "1.12.0",
                "openmm": "8.4.0",
                "original_heavy_atoms": len(before),
                "original_coordinates_unchanged": True,
                "added_atoms": added,
                "unbuilt_missing_residues": missing_residues,
                "hydrogen_policy": "沿用固定Meeko，不另设pH或改变成分电离形态",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

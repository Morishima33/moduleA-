# 对接出图任务包验收；核对10组PyMOL兼容文件、姿势和热图评分同源。
from hashlib import sha256  # 独立复算任务包文件指纹。
from pathlib import Path  # 定位当前研究任务包。
import json  # 读取机器索引和A06标准结果。
import unittest  # 使用标准测试框架。


ROOT = Path(__file__).resolve().parents[1]  # 只访问独立新项目。
STUDY = ROOT / "studies/study_28a9580bd87543c98892e3c7ce4d1426"  # 固定本次流程测试研究。
PACKAGE = STUDY / "task_packages/D001_Yupingfengsan_COPD_10pairs_PyMOL"  # 固定首个出图任务包。


class DockingTaskPackageTests(unittest.TestCase):  # 每项检查都针对用户实际要打开的文件。
    @classmethod  # 十组共同读取一次索引。
    def setUpClass(cls):  # 加载任务包和来源结果。
        cls.index = json.loads((PACKAGE / "package_index.json").read_text(encoding="utf-8"))  # 读取机器索引。
        result_path = STUDY / "runs/A06/run_864530ba268b4cc7b6d3a4e4c68f798c/result.json"  # 读取热图所用A06事实。
        cls.a06 = json.loads(result_path.read_text(encoding="utf-8"))  # 不使用旧Kimi结果。

    def test_ten_stable_pairs_and_required_legacy_files(self):  # 十组均应直接供PyMOL使用。
        self.assertEqual(self.index["pair_count"], 10)  # 当前只交付已完成的十组。
        folders = sorted(path for path in (PACKAGE / "04_pairs").iterdir() if path.is_dir())  # 读取P01至P10。
        self.assertEqual(len(folders), 10)  # 不漏组也不夹带未完成组合。
        for folder in folders:  # 逐组检查旧流程要求的文件。
            pair_id = folder.name  # 文件名全部绑定稳定组号。
            required = ["config.txt", "log.txt", "output.pdbqt", "hbond_info.txt", "01_open_in_pymol.pml", "START_PYMOL.cmd", f"result_{pair_id}.pdb", f"session_{pair_id}.pse"]  # PyMOL输入、结果和会话齐全。
            self.assertTrue(all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in required), pair_id)  # 空文件不能交付。
            self.assertTrue(any(path.name.endswith(".pdbqt") and path.name[0].isdigit() for path in folder.iterdir()), pair_id)  # 受体沿用数字前缀格式。
            self.assertTrue(any(path.name.endswith(".pdbqt") and path.name[0] in "abcde" for path in folder.iterdir()), pair_id)  # 配体沿用a至e格式。

    def test_selected_pose_equals_a06_heatmap_score(self):  # 图片必须展示热图采用的同一个姿势。
        scores = {(row["compound_id"], target): float(row[target]) for row in self.a06["tables"]["score_matrix"] for target in ("AKT1", "MAPK1")}  # 建立A06矩阵索引。
        for row in self.index["pairs"]:  # 每个任务索引保存选定姿势。
            pose = PACKAGE / "04_pairs" / row["pair_id"] / "result/selected_pose.pdbqt"  # 读取单一姿势原文。
            lines = pose.read_text(encoding="utf-8").splitlines()  # 保留Vina评分备注。
            self.assertEqual(sum(line.startswith("MODEL ") for line in lines), 1)  # 不让用户在九个姿势中猜。
            score_line = next(line for line in lines if line.startswith("REMARK VINA RESULT:"))  # 读取实际Vina评分。
            self.assertEqual(float(score_line.split()[3]), scores[(row["compound_id"], row["target"])])  # 热图、索引和姿势完全一致。

    def test_pymol_outputs_and_contact_boundary(self):  # 合并结构、会话及接触说明必须可用。
        for row in self.index["pairs"]:  # 逐组检查实际生成结果。
            folder = PACKAGE / "04_pairs" / row["pair_id"]  # 定位当前组合。
            pdb = (folder / f"result_{row['pair_id']}.pdb").read_text(encoding="utf-8", errors="replace")  # PyMOL生成合并结构。
            self.assertIn("ATOM", pdb)  # 合并文件必须包含受体原子。
            self.assertIn("TER", pdb)  # 受体与配体之间必须存在明确分隔。
            self.assertRegex(pdb, r"ATOM\s+\d+\s+\S+\s+UNL")  # PyMOL会把当前配体写成UNL原子记录，不强求HETATM标签。
            contacts = (folder / "hbond_info.txt").read_text(encoding="utf-8")  # 读取距离接触记录。
            self.assertIn("N_O_distance_contact_not_confirmed_hydrogen_bond", contacts)  # 不把距离线冒充已确认氢键。
            (folder / "01_open_in_pymol.pml").read_text(encoding="ascii")  # 脚本必须严格ASCII，PyMOL才能稳定读取。

    def test_indexed_files_keep_sha256(self):  # 任务包交回后可发现被替换的输入文件。
        for record in self.index["files"]:  # 独立复算全部已登记文件。
            path = PACKAGE / record["path"]  # 相对路径不能逃出任务包。
            self.assertTrue(path.is_file())  # 索引不得指向缺失文件。
            self.assertEqual(path.stat().st_size, record["bytes"])  # 大小先快速核对。
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), record["sha256"])  # 完整内容必须一致。


if __name__ == "__main__":  # 支持独立验收。
    unittest.main(verbosity=2)  # 显示每项检查状态。

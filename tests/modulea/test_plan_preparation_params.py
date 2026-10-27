import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from science_modules.a06.plan_preparation_v2 import execution_config, assess_plan_attempt
from science_modules.a06.plan_quality_engine_v2 import reference_box, prediction_box, redock
from science_modules.analysis_protocol import compile_plan


class PlanPreparationParameterTests(unittest.TestCase):
    def test_compiled_plan_parameters_are_bound_to_execution_config(self):
        plan = compile_plan({"mode": "personalized", "parameters": {
            "a06.exhaustiveness": 12, "a06.num_modes": 7,
            "a06.energy_range": 4.5, "a06.seed": 9,
            "a06.box_padding": 3.0, "a06.redocking_rmsd_max": 1.5}})
        config = execution_config(plan)
        self.assertEqual(config["vina_parameters"], {
            "scoring": "vina", "exhaustiveness": 12, "num_modes": 7,
            "energy_range_kcal_mol": 4.5, "seed": 9})
        self.assertEqual(config["box_padding"], 3.0)
        self.assertEqual(config["strict_rmsd_A"], 2.0)
        self.assertEqual(config["requested_rmsd_max_A"], 1.5)

    def test_vina_command_and_reference_box_use_bound_values(self):
        parameters = {"scoring": "vina", "exhaustiveness": 12,
                      "num_modes": 7, "energy_range_kcal_mol": 4.5, "seed": 9}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            sdf = folder / 'ref.sdf'; sdf.write_bytes(b'reference')
            qt = folder / 'ref.pdbqt'; qt.write_text('ligand', encoding='ascii')
            captured = []
            def run(command, *args):
                captured.extend(command)
                Path(command[-1]).write_text('pose', encoding='ascii')
                return SimpleNamespace(returncode=0)
            with patch('science_modules.a06.plan_quality_engine_v2._run', side_effect=run), \
                 patch('docking_redocking._poses', return_value=['pose']), \
                 patch('docking_redocking.symmetry_rmsd', return_value={'rmsd_angstrom': 1.2}):
                value, _ = redock('vina.exe', 'receptor.pdbqt', qt, sdf,
                                  {'center': [1, 2, 3], 'size': [10, 11, 12]},
                                  'target', folder, parameters)
            self.assertEqual(value, 1.2)
            self.assertTrue((folder / 'redocking/command.json').is_file())
        command = captured
        self.assertEqual(command[command.index("--exhaustiveness") + 1], "12")
        self.assertEqual(command[command.index("--num_modes") + 1], "7")
        self.assertEqual(command[command.index("--energy_range") + 1], "4.5")
        self.assertEqual(command[command.index("--seed") + 1], "9")
        pdb = ("HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C  \n"
               "HETATM    2  C2  LIG A   1       2.000   4.000   6.000  1.00  0.00           C  \n")
        box = reference_box(pdb, 3.0)
        self.assertEqual(box["center"], [1.0, 2.0, 3.0])
        self.assertEqual(box["size"], [8.0, 10.0, 12.0])

    def test_personal_rmsd_never_weakens_strict_limit(self):
        spec = {'pocket': 'reference'}
        with patch('science_modules.a06.plan_preparation_v2.assess_attempt',
                   return_value={'state': 'ready', 'quality': '严格', 'rmsd': 1.8, 'reason_zh': '通过'}):
            stricter = {'strict_rmsd_A': 2.0, 'requested_rmsd_max_A': 1.5}
            wider = {'strict_rmsd_A': 2.0, 'requested_rmsd_max_A': 3.0}
            self.assertEqual(assess_plan_attempt(spec, {}, {}, 1, stricter)['state'], 'failed')
            self.assertEqual(assess_plan_attempt(spec, {}, {}, 1, wider)['state'], 'ready')

    def test_prediction_box_uses_plan_padding_including_zero(self):
        atoms = [{'chain': 'A', 'residue': '10', 'xyz': [0, 1, 2]},
                 {'chain': 'A', 'residue': '10', 'xyz': [2, 4, 6]}]
        prediction = {'residue_ids': 'A_10', 'center_x': '1', 'center_y': '2', 'center_z': '3'}
        with patch('science_modules.a06.plan_quality_engine_v2._pdb_atoms', return_value=atoms):
            self.assertEqual(prediction_box('pdb', prediction, 0)['size'], [2, 3, 4])
            self.assertEqual(prediction_box('pdb', prediction, 3)['size'], [8, 9, 10])


if __name__ == "__main__":
    unittest.main()

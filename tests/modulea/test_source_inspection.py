"""来源只读包装核查回归：目标链冲突不可绕过，不调用结构准备。"""
import unittest
from unittest.mock import patch
from contracts import ContractError
from science_modules.a06.source_inspection import inspect_experimental_source, inspect_ligand_source


class SourceInspectionTests(unittest.TestCase):
    def entity(self):
        return {"rcsb_polymer_entity_container_identifiers": {
                    "entry_id": "1ABC", "entity_id": "1", "auth_asym_ids": ["A"],
                    "uniprot_ids": ["P12345"], "asym_ids": ["A"]},
                "entity_poly": {"rcsb_entity_polymer_type": "Protein"},
                "rcsb_entity_source_organism": [{"ncbi_taxonomy_id": 9606}]}

    def cif(self, chain, reason):
        return "data_virtual\n_entry.id 1ABC\nloop_\n" + (
            "_struct_ref_seq_dif.pdbx_pdb_strand_id\n_struct_ref_seq_dif.details\n"
            + chain + " '" + reason + "'\n#\n"
        )

    def test_native_target_keeps_other_chain_conflict_separate(self):
        spec = {"pdb_id": "1ABC", "chains": ["A"], "pocket": "p2rank"}
        with patch("docking_receptor.inspect_structure", return_value={"coordinate_modified": False}):
            out = inspect_experimental_source(self.cif("B", "conflict"),
                    {"uniprot": "P12345"}, spec, [self.entity()])
        self.assertFalse(out["docking_ready"])
        self.assertFalse(out["receptor_prepared"])
        self.assertEqual(out["sequence_differences"], [])

    def test_target_conflict_blocked_before_structure_inspection(self):
        with patch("docking_receptor.inspect_structure") as inspect:
            with self.assertRaises(ContractError):
                inspect_experimental_source(self.cif("A", "conflict"), {"uniprot": "P12345"},
                    {"pdb_id": "1ABC", "chains": ["A"], "pocket": "p2rank"}, [self.entity()])
            inspect.assert_not_called()

    def test_official_chemical_conflict_never_rewrites_identity(self):
        approved = {"cid": "1", "official_evidence": {"properties": {
                    "InChIKey": "virtual-key", "MolecularFormula": "CH4"}}}
        with patch("docking_audit.ligand_identity") as inspect:
            with self.assertRaises(ContractError):
                inspect_ligand_source("virtual", approved,
                    {"CID": 1, "InChIKey": "different", "MolecularFormula": "CH4"})
            inspect.assert_not_called()

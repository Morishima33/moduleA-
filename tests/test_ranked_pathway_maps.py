"""虚构资料验证两种排名、命中身份以及归档下载边界，不使用真实研究。"""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from modulea.core.ranked_pathway_workflow import ranked_source, RankedPathwayWorkflow, VERSION
from science_modules.a05.ranked_pathway_maps import download_source
from storage import file_record, write_json


def fixture():
    meta = [
        {
            "base_run": "fixture",
            "decision_id": "fixture_decision",
            "excluded_ids_json": "[]",
            "missing_translations_json": "[]",
            "exclusions_confirmed": True,
            "layout_confirmed": True,
        }
    ]
    rows = [
        {
            "ID": "hsa00001",
            "Description": "Synthetic one - Homo sapiens (human)",
            "description_zh": "虚构一",
            "Count": 1,
            "geneID": "1",
            "p.adjust": 0.001,
        },
        {
            "ID": "hsa00002",
            "Description": "Synthetic two",
            "description_zh": "虚构二",
            "Count": 2,
            "geneID": "1/2",
            "p.adjust": 0.002,
        },
    ]
    result = {
        "module_id": "A05",
        "tables": {
            "display_metadata": meta,
            "kegg_p_top10": rows,
            "kegg_count_top10": list(reversed(rows)),
            "identity_mapping": [
                {"entrez_id": "1", "symbol": "TEST1"},
                {"entrez_id": "2", "symbol": "TEST2"},
            ],
        },
    }
    manifest = {
        "study_id": "synthetic_study",
        "current": {"A05": "synthetic_a05"},
        "runs": {
            "synthetic_a05": {
                "result_file": {"path": "result.json", "bytes": 1, "sha256": "synthetic"}
            }
        },
    }
    return manifest, result


class RankedMapTests(unittest.TestCase):
    def test_two_rankings_keep_exact_ids_counts_and_bh_without_mutation(self):
        manifest, result = fixture()
        old = deepcopy(result)
        fake = type("ReadWorkflow", (), {"result": lambda *args: result})()
        binding, rows = ranked_source(fake, manifest, "synthetic_a05")
        self.assertEqual([r["id"] for r in rows], ["hsa00001", "hsa00002"])
        self.assertEqual([r["count"] for r in rows], [1, 2])
        self.assertEqual([r["adjusted_p"] for r in rows], [0.001, 0.002])
        self.assertEqual(rows[1]["symbols"], ["TEST1", "TEST2"])
        self.assertEqual(result, old)
        self.assertEqual(binding["result"], manifest["runs"]["synthetic_a05"]["result_file"])

    def test_count_mismatch_missing_identity_and_unconfirmed_scope_block(self):
        for mutation in (
            lambda t: t["kegg_p_top10"][0].update(Count=2),
            lambda t: t["identity_mapping"].clear(),
            lambda t: t["display_metadata"][0].update(exclusions_confirmed=False),
        ):
            manifest, result = fixture()
            mutation(result["tables"])
            fake = type("ReadWorkflow", (), {"result": lambda *args: result})()
            with self.assertRaises(ContractError):
                ranked_source(fake, manifest, "synthetic_a05")

    def test_foreign_or_modified_archived_file_cannot_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "source.png"
            image.write_bytes(b"synthetic")
            row = {
                "schema_version": VERSION,
                "map_id": "ranked_maps_synthetic",
                "binding": {"study_id": "synthetic_study"},
                "files": [file_record(root, image, "fixture")],
            }
            index = root / "index.json"
            write_json(index, row)
            manifest = {
                "study_id": "synthetic_study",
                "ranked_pathway_map_records": [file_record(root, index, "fixture")],
            }
            workflow = object.__new__(RankedPathwayWorkflow)
            workflow.location = lambda *args: root
            self.assertEqual(workflow.ranked_map_file(manifest, row["map_id"], 0), image)
            with self.assertRaises(ContractError):
                workflow.ranked_map_file(manifest, "ranked_maps_foreign", 0)
            image.write_bytes(b"changed")
            with self.assertRaises(ContractError):
                workflow.ranked_map_file(manifest, row["map_id"], 0)

    def test_source_identifier_is_not_arbitrary_url_or_path(self):
        with patch("urllib.request.urlopen") as opening:
            with self.assertRaises(ContractError):
                download_source("../hsa00001", "image", Path("unused"))
            opening.assert_not_called()


if __name__ == "__main__":
    unittest.main()

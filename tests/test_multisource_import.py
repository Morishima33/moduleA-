"""参数化三库导入回归：虚构药味、结构身份、已有关系与错误输入。"""
import csv,gzip,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from science_modules.a01.collect_herb_existing import fetch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from contracts import ContractError
from science_modules.a01.multisource import make_record,deduplicate,batman_records,herb_records
from science_modules.a01.preview import build_candidate

KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"

class ImportTest(unittest.TestCase):
    def test_collector_invalid_id_cannot_be_used_as_a_path(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("science_modules.a01.collect_herb_existing.urllib.request.urlopen") as network:
                with self.assertRaises(ContractError):fetch("../escape",Path(d))
                network.assert_not_called()

    def test_collector_distinguishes_successful_zero_from_network_failure(self):
        raw=json.dumps({"summary":[[],["HBIN1"]],"ingredient_target":[["Target id","Target name","Database sources"]]}).encode()
        response=MagicMock();response.__enter__.return_value.read.return_value=raw
        with tempfile.TemporaryDirectory() as d:
            with patch("science_modules.a01.collect_herb_existing.urllib.request.urlopen",return_value=response), patch("science_modules.a01.collect_herb_existing.time.sleep"):
                result=fetch("HBIN1",Path(d))
                self.assertEqual(result["status"],"success")
                self.assertEqual(result["existing_rows"],0)
                self.assertEqual((Path(d)/"HBIN1.json").read_bytes(),raw)
            with patch("science_modules.a01.collect_herb_existing.urllib.request.urlopen",side_effect=TimeoutError("synthetic timeout")), patch("science_modules.a01.collect_herb_existing.time.sleep"):
                result=fetch("HBIN2",Path(d))
                self.assertEqual(result["status"],"failed")
                self.assertNotIn("existing_rows",result)
                self.assertFalse((Path(d)/"HBIN2.json").exists())

    def test_missing_structure_does_not_merge_by_name(self):
        records = [make_record("TCMSP", "MOL1", "相同名称", "甲", "r"), make_record("HERB", "HBIN1", "相同名称", "甲", "r")]
        compounds, _, _, _ = deduplicate(records, ["甲"])
        self.assertEqual(len(compounds), 2)

    def test_full_key_merge_preserves_all_herb_memberships(self):
        identity = {"InChIKey": KEY, "Molecular_formula": "C2H4"}
        records = [make_record("TCMSP", "MOL1", "x", "甲", "r1", identity), make_record("HERB", "HBIN1", "y", "乙", "r2", identity)]
        compounds,members,rows,conflicts = deduplicate(records, ["乙", "甲"])
        self.assertEqual(len(compounds),1)
        self.assertEqual(compounds[0]["herbs"], "乙、甲")
        self.assertEqual(len(members),2)
        self.assertEqual(len(rows),2)
        self.assertEqual(conflicts,[])

    def test_stereochemical_suffix_and_formula_conflict_are_not_merged(self):
        r1=make_record("HERB","HBIN1","x","甲","r",{"InChIKey":KEY,"Molecular_formula":"C2H4"})
        r2=make_record("BATMAN","1","x","甲","r",{"InChIKey":KEY[:-1]+"D","Molecular_formula":"C2H4"})
        self.assertEqual(len(deduplicate([r1,r2],["甲"])[0]),2)
        r2["inchikey"]=KEY;r2["formula"]="C3H6"
        compounds,_,_,conflicts=deduplicate([r1,r2],["甲"])
        self.assertEqual(len(compounds),2)
        self.assertEqual(conflicts,[KEY])

    def test_batman_uses_explicit_new_recipe_and_does_not_guess_names(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d)
            (raw/"BATMAN_herb_browse.txt").write_text("Pinyin.Name\tChinese.Name\tLatin.Name\tIngredients\nJIA\t甲\tPlant A\talpha(12)\nYI\t乙\tPlant B\tbeta(13)\n",encoding="utf-8")
            records,counts,pending=batman_records(raw,{}, {"JIA":"甲","YI":"乙"})
            self.assertEqual({r["herb"] for r in records},{"甲","乙"})
            self.assertEqual(counts,{"甲":1,"乙":1})
            self.assertEqual(len(pending),2)
            with self.assertRaises(ContractError):batman_records(raw,{}, {"JIA":"乙"})

    def test_herb_upload_cannot_escape_source_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ContractError):herb_records(Path(d),{}, {"甲":"../outside.xlsx"})

    def fixture(self, raw, gene="GENE1"):
        (raw/"HERB_existing_details").mkdir()
        (raw/"HERB_target_browse_page001.json").write_text(json.dumps({"browse_data":[[],[{"title":"HBTAR1"},gene]],"total_num":1}),encoding="utf-8")
        (raw/"HERB_existing_details/HBIN1.json").write_text(json.dumps({"summary":[[],["HBIN1"]],"ingredient_target":[["Target id","Target name","Database sources"],[{"title":"HBTAR1"},gene,"known"]]}),encoding="utf-8")
        (raw/"BATMAN_known_browse_by_ingredients.txt.gz").write_bytes(gzip.compress(b"PubChem_CID\tIUPAC_name\tknown_target_proteins\n1\tx\tGENE1\n"))
        identity={"InChIKey":KEY,"Molecular_formula":"C2H4"}
        tc=[make_record("TCMSP","MOL1","x","甲","tc",identity)]
        hr=[make_record("HERB","HBIN1","x","甲","hr",identity)]
        br=[make_record("BATMAN","1","x","甲","br",identity)]
        summary={"mapping_snapshot":"a"*64,"mapping_rule":"HGNC.resolve.3","identity_evidence_snapshot":"","namespace":"HGNC","analysis_purpose":"workflow_test"}
        mapper=SimpleNamespace(digest="a"*64,rule="HGNC.resolve.3",supplement=None,resolve=lambda name: {"status":"matched","target_id":"HGNC:1","symbol":"GENE1"} if name=="GENE1" else {"status":"unmatched","candidate_ids":[]})
        edge=[{"compound_id":"MOL1","target_id":"HGNC:1","symbol":"GENE1","species":9606,"source_ref":"tc"}]
        coverage={key:["甲"] for key in ("TCMSP","HERB","BATMAN")}
        return tc,hr,br,mapper,edge,summary,["甲"],coverage

    def test_known_relations_merge_evidence_without_inflating_target_count(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d);args=self.fixture(raw)
            candidate=build_candidate(raw,*args)
            edges=candidate["result"]["tables"]["normalized_compound_targets"]
            self.assertEqual(len(edges),1)
            self.assertIn("tc",edges[0]["source_ref"])
            self.assertIn("ingredient_target",edges[0]["source_ref"])
            self.assertFalse(candidate["result"]["summary"]["handoff_blocked"])

    def test_new_unknown_relation_is_not_automatically_omitted_or_approved(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d);args=self.fixture(raw,"UNKNOWN")
            candidate=build_candidate(raw,*args)
            self.assertTrue(candidate["result"]["summary"]["handoff_blocked"])
            self.assertEqual(len(candidate["identity_issues"]),1)
            self.assertTrue(candidate["result"]["summary"]["candidate_only"])

    def test_different_hgnc_evidence_and_missing_library_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d);args=list(self.fixture(raw))
            args[5]=dict(args[5],mapping_snapshot="b"*64)
            with self.assertRaises(ContractError):build_candidate(raw,*args)
            args[5]["mapping_snapshot"]="a"*64;args[-1].pop("HERB")
            with self.assertRaises(ContractError):build_candidate(raw,*args)

if __name__ == "__main__":unittest.main()

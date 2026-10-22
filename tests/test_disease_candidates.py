"""疾病映射边界回归：别名、编号冲突、合并疾病与宽泛疾病分开。"""
import hashlib
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from science_modules.a02.disease_candidates import ttd_candidates, pharmgkb_candidates
from ttd_source import BASE, FILES

IDENTITY = {'mesh_id':'D012221', 'preferred_term':'Rhinitis, Allergic', 'entry_terms':['Allergic Rhinitis']}


def request(rows):
    return [{'term':'Allergic Rhinitis','url':'https://api.clinpgx.org/v1/data/disease?name=Allergic+Rhinitis','status':200,'response':{'status':'success','data':rows}}]


class MappingTests(unittest.TestCase):
    def test_official_alias_locates_entity_but_never_approves_scope(self):
        r=pharmgkb_candidates(request([{'id':'PA1','name':'Different primary name','altNames':['Allergic Rhinitis']}]),IDENTITY)
        self.assertTrue(r[0]['direct_gene_eligible'])
        self.assertEqual(r[0]['scope'],'pending')
        self.assertFalse(r[0]['selected'])

    def test_mesh_cross_reference_requires_exact_id(self):
        row={'id':'PA1','name':'Other','terms':[{'src':'MeSH','termId':'D012221'}]}
        self.assertTrue(pharmgkb_candidates(request([row]),IDENTITY)[0]['direct_gene_eligible'])
        row['terms'][0]['termId']='D012220';row['altNames']=['Allergic Rhinitis']
        self.assertFalse(pharmgkb_candidates(request([row]),IDENTITY)[0]['direct_gene_eligible'])

    def test_broad_rhinitis_and_ambiguous_entities_not_accepted(self):
        rows=[{'id':'PA1','name':'Rhinitis'}]
        self.assertFalse(pharmgkb_candidates(request(rows),IDENTITY)[0]['direct_gene_eligible'])
        rows=[{'id':'PA1','name':'Allergic Rhinitis'},{'id':'PA2','name':'Rhinitis, Allergic'}]
        self.assertFalse(any(r['direct_gene_eligible'] for r in pharmgkb_candidates(request(rows),IDENTITY)))

    def test_combined_disease_and_subtype_are_only_candidates(self):
        header='TTD - Therapeutic Targets Database\nVersion test\n'
        files={}
        texts={'targets':header+'T1\tGENENAME\tA\n','diseases':header+'T1\tINDICATI\tclinical\tAsthma and Allergic Rhinitis\tICD:J30\nT1\tINDICATI\tclinical\tSeasonal Allergic Rhinitis\tICD:J30.2\n'}
        for role,text in texts.items():
            raw=text.encode();files[role]={'url':BASE+FILES[role],'text':text,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'retrieved_at':'test'}
        r=ttd_candidates({'version':'TTD.snapshot.1','query':'Allergic Rhinitis','files':files},IDENTITY)
        self.assertEqual(len(r),2)
        self.assertEqual({x['match_kind'] for x in r},{'combined_disease','related_name'})
        self.assertTrue(all(not x['direct_gene_eligible'] and x['scope']=='pending' for x in r))

    def test_failed_query_cannot_be_treated_as_zero(self):
        from contracts import ContractError
        with self.assertRaises(ContractError):
            pharmgkb_candidates([{'status':500,'response':[]}],IDENTITY)

    def test_network_failure_preview_preserves_current_disease_and_reviews(self):
        from test_source_uploads import fixture
        from science_modules.a02.disease_candidates import preview
        import json
        with tempfile.TemporaryDirectory() as d:
            w,sid,_=fixture(Path(d));before=json.dumps(w.load(sid),sort_keys=True)
            folder=w.location(sid)/'raw/mapping_test'
            with patch('science_modules.a02.disease_candidates.official_identity',return_value=IDENTITY),patch('science_modules.a02.disease_candidates._archived_sources',return_value={}):
                r=preview(w,sid,['PharmGKB'],folder,opener=lambda *a,**k:(_ for _ in ()).throw(OSError('offline')),sleeper=lambda _:None)
            self.assertEqual(r['databases'][0]['status'],'query_failed')
            self.assertTrue((folder/'preview.json').is_file())
            self.assertEqual(before,json.dumps(w.load(sid),sort_keys=True))


if __name__ == '__main__':unittest.main()

"""稳定编号、反证、碰撞及限定暂缓；不联网、不修改真实研究或旧PPI协议。"""
from copy import deepcopy
import hashlib,json,unittest
from unittest.mock import patch

from contracts import ContractError,fingerprint
import ppi_identity as prior
from science_modules.a04 import plan_identity as engine


class PlanPpiIdentityTests(unittest.TestCase):
    def setUp(self):
        self.targets=[{'target_id':'HGNC:1','symbol':'GENE_A'},{'target_id':'HGNC:2','symbol':'GENE_B'}]
        self.mapping=[{'queryIndex':0,'queryItem':'GENE_A','ncbiTaxonId':9606,'preferredName':'GENE_A','stringId':'9606.A'},
                      {'queryIndex':1,'queryItem':'GENE_B','ncbiTaxonId':9606,'preferredName':'OLD_B','stringId':'9606.B'}]
        self.scope={'study_id':'study_synthetic','a03_run':'run_synthetic','decision':'明确合成测试决定，不是实际用户科研批准',
                    'check_ids':['HGNC:2'],'omit_ids':['HGNC:2']}
        self.raw=('hgnc_id\tsymbol\tprev_symbol\tuniprot_ids\tensembl_gene_id\n'
                  'HGNC:1\tGENE_A\t\tP00001\tENSG1\nHGNC:2\tGENE_B\tOLD_B\tP00002\tENSG2\n').encode()
        self.snapshot=patch.object(prior,'SNAPSHOT',hashlib.sha256(self.raw).hexdigest());self.snapshot.start();self.addCleanup(self.snapshot.stop)
        self.probes=[]
        for spec in engine.queries(self.targets,self.raw,self.scope):
            rows=[{'queryIndex':0,'queryItem':spec['identifier'],'ncbiTaxonId':9606,'preferredName':'OLD_B','stringId':'9606.B'}]
            text=json.dumps(rows)
            self.probes.append({'query':spec,'source':{'url':prior.BASE+'get_string_ids','params':prior.params(spec['identifier']),
                'retrieved_at':'2026-11-01T00:00:00+00:00','query_state':'succeeded','response_text':text,'response_sha256':fingerprint(text)}})

    def change_rows(self,probes,edit):
        for probe in probes:
            rows=json.loads(probe['source']['response_text']);edit(rows)
            text=json.dumps(rows);probe['source'].update(response_text=text,response_sha256=fingerprint(text))

    def resolve(self,**changes):
        values={'targets':self.targets,'mapping':self.mapping,'probes':self.probes,'raw':self.raw,'scope':self.scope};values.update(changes)
        return engine.resolve(**values)

    def test_all_official_stable_ids_and_historical_name_must_agree_without_changing_originals(self):
        before=deepcopy(self.mapping);corrected,adjusted,decisions=self.resolve()
        self.assertEqual(len(adjusted),1);self.assertEqual(decisions[0]['action'],'resolved_by_exact_evidence')
        self.assertEqual(next(row for row in corrected if row['queryIndex']==1)['preferredName'],'GENE_B')
        self.assertEqual(self.mapping,before);self.assertEqual(len(self.probes),2)

    def test_original_name_contradiction_stays_unresolved_and_is_only_temporarily_omitted(self):
        self.mapping[1]['stringId']='9606.WRONG'
        corrected,adjusted,decisions=self.resolve()
        self.assertFalse(adjusted);self.assertEqual(corrected,self.mapping)
        self.assertEqual(decisions[0]['action'],'temporarily_omitted');self.assertIn('冲突',decisions[0]['reason_zh'])

    def test_empty_response_and_inconsistent_proteins_never_pick_a_candidate(self):
        for change in ('empty','different'):
            probes=deepcopy(self.probes)
            if change=='empty':self.change_rows(probes,lambda rows:rows.clear())
            else:
                rows=json.loads(probes[-1]['source']['response_text']);rows[0]['stringId']='9606.OTHER'
                text=json.dumps(rows);probes[-1]['source'].update(response_text=text,response_sha256=fingerprint(text))
            with self.subTest(change=change):
                corrected,adjusted,decisions=self.resolve(probes=probes)
                self.assertFalse(adjusted);self.assertEqual(corrected,self.mapping);self.assertEqual(decisions[0]['action'],'temporarily_omitted')

    def test_missing_failed_foreign_query_and_hash_changes_cannot_be_omitted_as_empty(self):
        variants=[self.probes[:-1]]
        for key,value in (('query_state','failed'),('url','https://example.invalid/probe'),('response_sha256','wrong')):
            probes=deepcopy(self.probes);probes[0]['source'][key]=value;variants.append(probes)
        probes=deepcopy(self.probes);self.change_rows(probes,lambda rows:rows[0].update(queryItem='FOREIGN'));variants.append(probes)
        for probes in variants:
            with self.subTest(probes=probes),self.assertRaises(ContractError):self.resolve(probes=probes)

    def test_ambiguous_species_or_unapproved_symbol_never_becomes_valid_human_mapping(self):
        for change in ('multiple','species','name'):
            probes=deepcopy(self.probes)
            def edit(rows):
                if change=='multiple':rows.append(dict(rows[0],stringId='9606.OTHER'))
                elif change=='species':rows[0]['ncbiTaxonId']=10090
                else:rows[0]['preferredName']='UNVERIFIED_ALIAS'
            self.change_rows(probes,edit)
            corrected,adjusted,decisions=self.resolve(probes=probes)
            self.assertFalse(adjusted);self.assertEqual(decisions[0]['action'],'temporarily_omitted')

    def test_no_omit_authorization_keeps_gate_unresolved(self):
        self.mapping[1]['stringId']='9606.CONTRADICTION'
        _,adjusted,decisions=self.resolve(scope=dict(self.scope,omit_ids=[]))
        self.assertFalse(adjusted);self.assertEqual(decisions[0]['action'],'unresolved')

    def test_no_stable_id_does_not_fabricate_query_or_identity(self):
        raw=self.raw.replace(b'P00002\tENSG2',b'\t')
        with patch.object(prior,'SNAPSHOT',hashlib.sha256(raw).hexdigest()):
            self.assertEqual(engine.queries(self.targets,raw,self.scope),[])
            _,adjusted,decisions=self.resolve(raw=raw,probes=[])
        self.assertFalse(adjusted);self.assertEqual(decisions[0]['query_count'],0)
        self.assertEqual(decisions[0]['action'],'temporarily_omitted')

    def test_same_string_protein_cannot_merge_two_hgnc_genes(self):
        self.mapping[1]['stringId']='9606.A'
        probes=deepcopy(self.probes);self.change_rows(probes,lambda rows:rows[0].update(stringId='9606.A'))
        corrected,adjusted,decisions=self.resolve(probes=probes)
        self.assertFalse(adjusted);self.assertEqual(decisions[0]['action'],'temporarily_omitted')
        self.assertIn('同一STRING蛋白',decisions[0]['reason_zh']);self.assertEqual(corrected,self.mapping)

    def test_exact_original_problem_scope_rejects_extra_ids_or_tampered_hgnc(self):
        with self.assertRaises(ContractError):self.resolve(raw=self.raw+b'changed')
        with self.assertRaises(ContractError):self.resolve(scope=dict(self.scope,check_ids=['HGNC:1','HGNC:2']))
        with self.assertRaises(ContractError):self.resolve(scope=dict(self.scope,omit_ids=['HGNC:1','HGNC:2']))


if __name__=='__main__':unittest.main()

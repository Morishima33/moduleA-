"""待核原字段与原请求关联，缺证据不当作零、不科学映射；全为虚构输入。"""
import csv,hashlib,io,json,tempfile,unittest,urllib.parse
from copy import deepcopy
from pathlib import Path
from contracts import ContractError
from storage import file_record
from modulea.core import component_identity_evidence as evidence


class ComponentIdentityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.home=Path(self.temp.name)
        self.refs=[]
        rows=[['Chinesename','MOLID','Organism','raw_target_id','raw_target_name'],
              ['测试药','MOL1','','T1','Protein A'],['测试药','MOL2','','T1','Protein A'],['测试药','MOL3','','','']]
        stream=io.StringIO();csv.writer(stream,delimiter='\t',lineterminator='\n').writerows(rows)
        self.put('TCMSP/references/tcmsp_snapshot.tsv',stream.getvalue().encode('utf-8-sig'))
        query='(protein_name:"Protein A") AND (organism_id:9606) AND (reviewed:true)'
        self.url='https://rest.uniprot.org/uniprotkb/search?'+urllib.parse.urlencode({'query':query,'format':'json','size':500})
        token=hashlib.sha256(self.url.encode()).hexdigest();self.base='TCMSP/original_requests/'+token
        raw=json.dumps({'results':[{'primaryAccession':'P1','organism':{'taxonId':9606},'genes':[{'geneName':{'value':'G1'}}]}]}).encode()
        self.response=self.put(self.base+'.bin',raw)
        self.index=self.put(self.base+'.json',json.dumps({'url':self.url,'payload':None,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}).encode())
        herb=self.put('HERB/HERB_existing_details/HBIN1.json',b'{"ingredient_target":[]}')
        self.slots={'TCMSP':{'folder':'TCMSP','files':self.refs[:3]},'HERB':{'folder':'HERB','files':[herb]},'BATMAN':{'folder':'BATMAN','files':[]}}
        issues=[{'source_line':line,'compound_id':'MOL'+str(line-1),'herb':'测试药','organism':'','reason':'物种缺失，待核验',
                 'issue_key':hashlib.sha256(str(line).encode()).hexdigest(),'decision':'待核验'} for line in (2,3,4)]
        issues.append({'database':'HERB','raw_symbol':'OldGene','raw_target_id':'HBTAR1','raw_compound_id':'HBIN1',
          'source_ref':'raw/HERB_existing_details/HBIN1.json:ingredient_target:1','identity_status':'unmapped',
          'issue_key':hashlib.sha256(b'herb').hexdigest(),'decision':'待核验'})
        self.result={'tables':{'identity_decisions':issues}}

    def put(self,name,raw):
        path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        ref=file_record(self.home,path,'fixture');self.refs.append(ref);return ref

    def build(self):
        self.files=[]
        def add(ref,label):
            if ref not in self.files:self.files.append(ref)
            return self.files.index(ref)
        return evidence.build_units(self.result,self.slots,lambda ref:evidence.read_bytes(self.home,ref),add)

    def test_repeated_relations_group_but_keep_all_rows_and_pending_state(self):
        before=deepcopy(self.result);units,stats=self.build()
        self.assertEqual(stats,{'source_rows':4,'protein_query_groups':1,'source_without_target_rows':1,'other_identity_rows':1,'display_groups':3})
        query=units[0];self.assertEqual(query['record_count'],2);self.assertEqual(query['response_records'],1)
        self.assertEqual(query['response_state'],'archived_success');self.assertEqual(query['protein_candidates'][0]['accession'],'P1')
        self.assertTrue(all(row['decision']=='待核验' for unit in units for row in unit['records']))
        self.assertEqual(units[-1]['original_reason_zh'],'原符号未匹配到人类基因')
        self.assertEqual(units[-1]['records'][0]['identity_status'],'unmapped')
        self.assertEqual(self.result,before);self.assertNotIn('resolved_identity',query)

    def test_missing_target_stays_not_applicable_and_does_not_claim_zero_query(self):
        units,_=self.build();missing=next(row for row in units if row['kind']=='source_without_target')
        self.assertEqual(missing['response_state'],'not_applicable');self.assertIsNone(missing['response_records'])
        self.assertNotIn('original_url',missing)

    def test_missing_query_pair_is_unarchived_but_half_pair_rejected(self):
        self.slots['TCMSP']['files']=[ref for ref in self.slots['TCMSP']['files'] if '/original_requests/' not in ref['path']]
        units,_=self.build();self.assertEqual(units[0]['response_state'],'not_archived');self.assertIsNone(units[0]['response_records'])
        self.slots['TCMSP']['files'].append(self.index)
        with self.assertRaises(ContractError):self.build()

    def test_corrupt_response_cannot_be_shown_as_success_or_no_candidates(self):
        (self.home/self.response['path']).write_bytes(b'tampered')
        with self.assertRaises(ContractError):self.build()

    def test_changed_request_url_rejected_even_with_self_consistent_file_digest(self):
        value=json.loads((self.home/self.index['path']).read_bytes());value['url']='https://example.com/wrong'
        replacement=self.put(self.index['path'],json.dumps(value).encode())
        self.slots['TCMSP']['files']=[replacement if ref==self.index else ref for ref in self.slots['TCMSP']['files']]
        with self.assertRaises(ContractError):self.build()

    def test_source_row_mismatch_and_cross_database_reference_rejected(self):
        self.result['tables']['identity_decisions'][0]['compound_id']='MOL999'
        with self.assertRaises(ContractError):self.build()
        self.result['tables']['identity_decisions'][0]['compound_id']='MOL1'
        self.result['tables']['identity_decisions'][-1]['source_ref']='raw/../TCMSP/references/tcmsp_snapshot.tsv:2'
        with self.assertRaises(ContractError):self.build()

    def test_true_empty_official_response_keeps_archived_success_separate_from_absent(self):
        body=self.put(self.response['path'],b'{"results":[]}')
        index=self.put(self.index['path'],json.dumps({'url':self.url,'payload':None,'bytes':len(b'{"results":[]}'),
            'sha256':hashlib.sha256(b'{"results":[]}').hexdigest()}).encode())
        self.slots['TCMSP']['files']=[ref for ref in self.slots['TCMSP']['files'] if '/original_requests/' not in ref['path']]+[body,index]
        units,_=self.build();self.assertEqual(units[0]['response_state'],'archived_success');self.assertEqual(units[0]['response_records'],0)

    def test_csv_keeps_every_original_issue_and_binding(self):
        units,_=self.build();value={'study_id':'study_fixture','expected_a01':'run_fixture','expected_input_hash':'x','units':units}
        rows=list(csv.DictReader(io.StringIO(evidence.export_csv(value).decode('utf-8-sig'))))
        self.assertEqual(len(rows),4);self.assertEqual({json.loads(row['original_record_json'])['issue_key'] for row in rows},
            {row['issue_key'] for row in self.result['tables']['identity_decisions']})


if __name__=='__main__':unittest.main()

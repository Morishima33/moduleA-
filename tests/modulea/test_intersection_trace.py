import csv
import io
import unittest

from modulea.api.intersection_trace import _evidence_type, trace_csv


class IntersectionTraceTests(unittest.TestCase):
    def test_only_identifiable_archived_evidence_tables_are_labeled(self):
        self.assertIn('已有靶点表', _evidence_type('方剂', 'HERB', 'raw/item.json:ingredient_target:3'))
        self.assertEqual(_evidence_type('方剂', 'BATMAN', 'raw/BATMAN_known_browse_by_ingredients.txt.gz:18'),
                         'BATMAN已知关联表')
        self.assertEqual(_evidence_type('方剂', 'BATMAN', 'raw/prediction.tsv:18'), '')
        self.assertEqual(_evidence_type('疾病', 'HERB', 'raw/item.json:ingredient_target:3'), '')

    def test_counts_keep_overlaps_and_unattributed_records(self):
        result = {'summary': {'交集靶点数': 2}, 'tables': {
            'intersection_targets': [{'target_id': 'HGNC:1', 'symbol': 'A'},
                                     {'target_id': 'HGNC:2', 'symbol': 'B'}],
            'ranking': [{'compound_id': 'c', 'name': 'C', 'herbs': '黄芪、白术'}],
            'formula_evidence': [
                {'compound_id': 'c', 'target_id': 'HGNC:1', 'source_ref': 'herb:1|batman:3'},
                {'compound_id': 'c', 'target_id': 'HGNC:2', 'source_ref': 'herb:2|unidentified:9'}],
            'disease_evidence': [
                {'target_id': gene, 'database': 'OTP', 'source_ref': gene} for gene in ('HGNC:1', 'HGNC:2')],
        }}
        parent = {'tables': {'new_relation_evidence': [
            {'source_ref': ref, 'database': source} for ref, source in
            [('herb:1', 'HERB'), ('herb:2', 'HERB'), ('batman:3', 'BATMAN')]]}}
        rows = list(csv.DictReader(io.StringIO(trace_csv(result, parent).decode('utf-8-sig'))))
        formula = [r for r in rows if r['记录类型'] == '交集来源明细' and r['侧别'] == '方剂']
        self.assertEqual(len(formula), 4)
        self.assertEqual({r['来源定位'] for r in formula}, {'herb:1', 'herb:2', 'batman:3', 'unidentified:9'})
        self.assertTrue(all(r['成分关联药味'] == '黄芪、白术' for r in formula))
        herb = next(r for r in rows if r['记录类型'] == '来源汇总' and r['数据库'] == 'HERB')
        self.assertEqual((herb['不同交集基因数'], herb['仅见于此来源'], herb['已知跨库重叠'], herb['含未归属证据']),
                         ('2', '0', '1', '1'))

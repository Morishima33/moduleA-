"""救援展示回归：完整固定范围、同名身份、NA原因和原始评分不得被绘图改写。"""
from copy import deepcopy
import csv
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from contracts import ContractError
from storage import file_record, write_json


def packet_fixture():
    """虚构16×15同批数据：26项旧评分、16项新增评分及198项NA。"""
    compounds = [{'compound_id': f'candidate_{i:04d}', 'name': '同名成分' if i < 2 else f'本批成分{i + 1}'} for i in range(16)]
    receptors = [{'target_id': f'T{i + 1}', 'symbol': f'基因{i + 1}', 'state': 'ready' if i < 3 else 'NA',
                  'quality': '探索', 'reason_zh': '' if i < 3 else '缺少可核实口袋'} for i in range(15)]
    pairs = []
    for i, compound in enumerate(compounds):
        for j, receptor in enumerate(receptors):
            complete = (i < 13 and j < 2) or j == 2
            pairs.append({'compound_id': compound['compound_id'], 'target_id': receptor['target_id'],
                          'state': 'completed' if complete else 'NA', 'score': -8.123456789 if complete else None,
                          'quality': '探索', 'reason_zh': '' if complete else '原始NA原因，保持原文',
                          'source_kind': 'original' if j < 2 else 'rescue', 'execution': None})
    pairs[0]['score'] = -9.25
    pairs[1]['score'] = -3.125
    summary = {'science_version': 'A06.system_rescue.1', 'compound_count': 16, 'receptor_count': 15,
               'pair_count': 240, 'scored_pairs': 42, 'na_pairs': 198, 'failed_pairs': 0,
               'rescue_target_count': 13, 'rescued_receptors': 1, 'reused_scored_pairs': 26, 'new_scored_pairs': 16,
               'strict_scored_pairs': 0, 'exploratory_scored_pairs': 42, 'input_key': 'fixed-scope',
               'analysis_parameter_hash': 'original-parameters', 'message_zh': '实际评分完成，待独立人工复核'}
    return {'schema_version': 'A06.system_rescue.1', 'study_id': 'study_display', 'run_id': 'run_display',
            'inputs': {}, 'source_fixed': {'input_key': 'fixed-scope', 'compounds': compounds,
                                          'receptors': [{'target_id': r['target_id'], 'symbol': r['symbol']} for r in receptors]},
            'compounds': deepcopy(compounds), 'receptors': receptors, 'pairs': pairs, 'summary': summary, 'files': []}


class SystemRescueDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_display_', dir=Path(__file__).resolve().parents[2] / '.test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.packet = packet_fixture()

    def test_full_scope_order_names_and_exact_scores_survive_display(self):
        from science_modules.a06.system_rescue_display import build_view
        before = deepcopy(self.packet)
        self.packet['compounds'][0]['name'] = '准备层不应替换固定名称'
        view = build_view(self.packet)
        self.assertEqual(len(view['table']['rows']), 16)
        self.assertEqual(len(view['table']['columns']), 15)
        self.assertEqual(len(view['heatmap']['rows']), 16)
        self.assertEqual(len(view['heatmap']['columns']), 15)
        self.assertEqual(view['table']['rows'][0]['name'], '同名成分')
        self.assertNotEqual(view['table']['rows'][0]['label'], view['table']['rows'][1]['label'])
        self.assertIn('0000', view['table']['rows'][0]['label'])
        self.assertEqual(view['table']['cells'][0][2]['score'], -8.123456789)
        self.assertEqual(view['table']['cells'][0][0]['color'], '#B2182B')
        self.assertEqual(view['table']['cells'][0][1]['color'], '#2166AC')
        self.assertEqual(view['table']['cells'][15][14]['display_score'], 'NA')
        self.assertEqual(view['table']['cells'][15][14]['color'], '#FFFFFF')
        self.assertEqual(view['table']['cells'][15][14]['reason_zh'], '原始NA原因，保持原文')
        self.assertEqual(self.packet['pairs'], before['pairs'])

    def test_focus_is_display_only_and_uses_full_batch_colour_range(self):
        from science_modules.a06.system_rescue_display import build_view
        before = deepcopy(self.packet)
        view = build_view(self.packet, selected_compounds=['candidate_0015'], selected_targets=['T3'])
        self.assertEqual([r['compound_id'] for r in view['heatmap']['rows']], ['candidate_0015'])
        self.assertEqual([r['target_id'] for r in view['heatmap']['columns']], ['T3'])
        self.assertEqual(view['heatmap']['cells'][0][0], view['table']['cells'][15][2])
        self.assertEqual(view['score_range'], [-9.25, -3.125])
        self.assertEqual(view['initial_focus']['target_ids'], ['T1', 'T2', 'T3'])
        self.assertEqual(len(view['initial_focus']['compound_ids']), 16)
        self.assertEqual(self.packet, before)

    def test_incomplete_duplicate_or_invalid_score_matrix_is_rejected(self):
        from science_modules.a06.system_rescue_display import build_view
        for mutation in ('missing', 'duplicate', 'bool_score', 'na_score', 'schema'):
            packet = deepcopy(self.packet)
            if mutation == 'missing': packet['pairs'].pop()
            elif mutation == 'duplicate': packet['pairs'][-1] = deepcopy(packet['pairs'][0])
            elif mutation == 'bool_score': packet['pairs'][0]['score'] = True
            elif mutation == 'na_score': packet['pairs'][-1]['score'] = 0
            else: packet['schema_version'] = 'A06.automatic.3'
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                build_view(packet)
        with self.assertRaises(ContractError): build_view(self.packet, selected_targets=['unknown'])

    def test_all_na_retains_full_scope_and_only_exports_full_figures(self):
        from science_modules.a06.system_rescue_display import build_view, export
        for row in self.packet['pairs']:
            row.update(state='NA', score=None, reason_zh='同批资料不足，未运行评分')
        self.packet['summary'].update(scored_pairs=0, na_pairs=240, reused_scored_pairs=0, new_scored_pairs=0)
        view = build_view(self.packet)
        self.assertEqual(view['score_range'], [None, None])
        self.assertEqual(len(view['table']['cells']), 16)
        self.assertTrue(all(len(line) == 15 and all(cell['score'] is None for cell in line) for line in view['table']['cells']))
        self.assertEqual(view['initial_focus'], {'compound_ids': [], 'target_ids': []})
        figures, _ = export(self.home, self.packet, self.home / 'all_na')
        self.assertEqual([row['role'] for row in figures], ['plot_a06_rescue_full_png', 'plot_a06_rescue_full_svg'])

    def test_export_keeps_full_csv_precision_and_real_png_svg(self):
        from PIL import Image
        from science_modules.a06.system_rescue_display import export
        before = deepcopy(self.packet)
        figures, attachments = export(self.home, self.packet, self.home / 'display')
        full_png = next(r for r in figures if r['role'] == 'plot_a06_rescue_full_png')
        full_svg = next(r for r in figures if r['role'] == 'plot_a06_rescue_full_svg')
        with Image.open(self.home / full_png['path']) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertGreater(image.width, 1200)
        tree = ElementTree.parse(self.home / full_svg['path'])
        svgtext = ''.join(tree.getroot().itertext())
        self.assertIn('16×15', svgtext)
        self.assertIn('同名成分', svgtext)
        self.assertIn('0000', svgtext)
        self.assertIn('NA', svgtext)
        csv_ref = next(r for r in attachments if r['role'] == 'a06_rescue_matrix_csv')
        with (self.home / csv_ref['path']).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 240)
        self.assertEqual(rows[2]['score'], '-8.123456789')
        self.assertEqual(rows[-1]['score'], 'NA')
        self.assertEqual(rows[-1]['reason_zh'], '原始NA原因，保持原文')
        self.assertEqual(self.packet, before)
        self.assertFalse(any((self.home / r['path']).suffix == '.docx' for r in figures + attachments))

    def test_api_uses_registered_evidence_and_never_writes_or_changes_review(self):
        from modulea.api.system_rescue_view import apply
        fixed = {'study_id': self.packet['study_id'], 'stage': 'A06_INPUT', 'payload': self.packet['source_fixed']}
        write_json(self.home / 'fixed.json', fixed)
        fixed_ref = file_record(self.home, self.home / 'fixed.json', 'system_input')
        self.packet['inputs'] = {'system_input_ref': fixed_ref}
        (self.home / 'execution.json').write_text('{}', encoding='utf-8')
        execution = file_record(self.home, self.home / 'execution.json', 'scoring_execution')
        self.packet['pairs'][0]['execution'] = execution
        # 未登记的Top-1引用不能借任意路径成为下载链接。
        self.packet['pairs'][0]['top1_pose'] = {'path': 'unregistered.pdbqt', 'sha256': 'x', 'bytes': 1}
        write_json(self.home / 'packet.json', self.packet)
        packet_ref = file_record(self.home, self.home / 'packet.json', 'scoring_packet')
        run = {'run_id': self.packet['run_id'], 'study_id': self.packet['study_id'],
               'config': {'version': 'A06.system_rescue.1'}, 'inputs': self.packet['inputs']}
        simple = [{k: p[k] for k in ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')} for p in self.packet['pairs']]
        result = {'summary': self.packet['summary'], 'tables': {'scoring_packet': [packet_ref],
                  'plan_scoring_pairs': simple, 'receptor_preparation': self.packet['receptors']}, 'files': [packet_ref, execution]}
        response = {'state': {'code': 'awaiting_review'}, 'review': {'can_review': True, 'already_approved': False,
                    'continue': {'available': True}}, 'files': [dict(execution, key='run_display.1', name='execution.json')]}
        before_review = deepcopy(response['review'])
        before_files = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        class Reader:
            def location(_, sid):
                return self.home
        apply(Reader(), {'study_id': self.packet['study_id']}, run, result, response)
        shown = response['special']['system_rescue']
        self.assertEqual(shown['summary_rows'][0]['text'], '13')
        self.assertEqual(len(shown['table']['rows']), 16)
        self.assertEqual(shown['table']['cells'][0][0]['downloads'][0]['url'], '/api/v1/studies/study_display/files/run_display.1')
        self.assertNotIn('unregistered', str(shown))
        self.assertIsNone(response['automatic_docking'])
        self.assertEqual(response['review']['can_review'], before_review['can_review'])
        self.assertEqual(response['review']['already_approved'], before_review['already_approved'])
        self.assertFalse(response['review']['continue']['available'])
        self.assertEqual(response['state'], {'code': 'awaiting_review'})
        self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before_files)


if __name__ == '__main__':
    unittest.main()

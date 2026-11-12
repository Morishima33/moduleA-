"""补救展示2回归：历史评分身份不回写，本轮图件不混入继承图，原展示1不变。"""
from copy import deepcopy
import csv
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, read_json, write_json
from tests.modulea.test_system_rescue_display import packet_fixture


def packet_v2_fixture():
    """沿用42格历史成功，另增16格成功及1格新失败，固定范围仍为240格。"""
    packet = packet_fixture()
    packet.update(schema_version='A06.system_rescue.2', run_id='run_display_v2')
    packet['reused_pair_keys'] = [[row['compound_id'], row['target_id']] for row in packet['pairs'] if row['state'] == 'completed']
    packet['new_pair_keys'] = []
    for row in packet['pairs']:
        if row['target_id'] == 'T4':
            row.update(state='completed', score=-6.987654321, reason_zh='', source_kind='rescue')
            packet['new_pair_keys'].append([row['compound_id'], row['target_id']])
    failed = packet['pairs'][4]
    failed.update(state='failed', score=None, reason_zh='本轮真实工具执行失败，保留原始诊断')
    packet['new_pair_keys'].append([failed['compound_id'], failed['target_id']])
    packet['summary'].update(science_version='A06.system_rescue.2', scored_pairs=58, na_pairs=181, failed_pairs=1,
        rescue_target_count=12, rescued_receptors=1, reused_scored_pairs=42, baseline_scored_pairs=42, new_scored_pairs=16,
        cumulative_rescue_scored_pairs=32, cumulative_rescue_target_count=13, cumulative_rescued_receptors=2,
        ready_receptors_total=4, exploratory_scored_pairs=58)
    return packet


class SystemRescueDisplayV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rescue_display_v2_', dir=Path(__file__).resolve().parents[2] / '.test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.packet = packet_v2_fixture()

    def test_round_sets_define_source_without_rewriting_historical_pair(self):
        from science_modules.a06 import system_rescue_display as first, system_rescue_display_v2 as second
        frozen = Path(first.__file__).read_bytes()
        before = deepcopy(self.packet)
        value = second.build_view(self.packet)
        self.assertEqual(value['schema_version'], 'A06.system_rescue.display.2')
        self.assertEqual(value['science_version'], 'A06.system_rescue.2')
        self.assertEqual(len(value['table']['rows']), 16)
        self.assertEqual(len(value['table']['columns']), 15)
        self.assertEqual(value['table']['cells'][0][2]['source_kind'], 'rescue')
        self.assertEqual(value['table']['cells'][0][2]['source_zh'], '沿用已核验评分')
        self.assertEqual(value['table']['cells'][0][3]['source_zh'], '本轮新增评分')
        self.assertEqual(value['table']['cells'][0][3]['score'], -6.987654321)
        self.assertEqual(value['table']['cells'][0][4]['state'], 'failed')
        self.assertEqual(value['table']['cells'][0][4]['reason_zh'], '本轮真实工具执行失败，保留原始诊断')
        self.assertEqual(value['table']['cells'][-1][-1]['score_text'], 'NA')
        self.assertEqual(value['table']['cells'][-1][-1]['reason_zh'], '原始NA原因，保持原文')
        self.assertEqual(self.packet, before)
        legacy = first.build_view(packet_fixture())
        self.assertEqual(legacy['schema_version'], 'A06.system_rescue.display.1')
        self.assertEqual(legacy['table']['cells'][0][2]['source_zh'], '本轮补救评分')
        self.assertEqual(sha256(Path(first.__file__).read_bytes()).digest(), sha256(frozen).digest())

    def test_duplicate_overlap_unknown_and_unclassified_completed_keys_rejected(self):
        from science_modules.a06.system_rescue_display_v2 import build_view
        for mutation in ('duplicate', 'overlap', 'unknown', 'unclassified', 'reuse_na'):
            packet = deepcopy(self.packet)
            if mutation == 'duplicate': packet['new_pair_keys'].append(packet['new_pair_keys'][0])
            elif mutation == 'overlap': packet['new_pair_keys'].append(packet['reused_pair_keys'][0])
            elif mutation == 'unknown': packet['new_pair_keys'].append(['unknown', 'T4'])
            elif mutation == 'unclassified': packet['reused_pair_keys'].pop(0)
            else: packet['reused_pair_keys'].append(['candidate_0015', 'T15'])
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                build_view(packet)

    def test_export_requires_own_current_folder_and_round_sources_in_csv(self):
        from PIL import Image
        from science_modules.a06.system_rescue_display_v2 import export
        own = self.home / ('runs/A06/run_display_v2/rescue/display/display_' + 'a' * 32)
        before = deepcopy(self.packet)
        with self.assertRaises(ContractError):
            export(self.home, self.packet, self.home / 'runs/A06/run_old/rescue/display')
        figures, attachments = export(self.home, self.packet, own)
        self.assertEqual(len(figures), 4)
        self.assertEqual(len(attachments), 2)
        self.assertTrue(all(row['path'].startswith('runs/A06/run_display_v2/rescue/display/') for row in figures + attachments))
        with Image.open(self.home / figures[0]['path']) as image:
            self.assertEqual(image.format, 'PNG')
        csv_ref = next(row for row in attachments if row['role'] == 'a06_rescue_matrix_csv')
        with (self.home / csv_ref['path']).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 240)
        self.assertEqual(rows[2]['source_kind'], 'rescue')
        self.assertEqual(rows[2]['source_zh'], '沿用已核验评分')
        self.assertEqual(rows[3]['source_zh'], '本轮新增评分')
        self.assertEqual(rows[3]['score'], '-6.987654321')
        view_ref = next(row for row in attachments if row['role'] == 'a06_rescue_display_view')
        self.assertEqual(read_json(self.home / view_ref['path'])['schema_version'], 'A06.system_rescue.display.2')
        self.assertEqual(self.packet, before)

    def test_interrupted_export_preserves_partial_attempt_and_uses_new_folder(self):
        from science_modules.a06 import system_rescue_display_v2 as second
        first = self.home / ('runs/A06/run_display_v2/rescue/display/display_' + 'b' * 32)
        later = self.home / ('runs/A06/run_display_v2/rescue/display/display_' + 'c' * 32)
        namespace = second.renderer()
        def interrupted_png(*args, **kwargs):
            raise OSError('合成出图中断')
        namespace['_png'] = interrupted_png
        with patch.object(second, 'renderer', return_value=namespace), self.assertRaisesRegex(OSError, '合成出图中断'):
            second.export(self.home, self.packet, first)
        partial = first / 'A06_完整结合能热图.svg'
        original_bytes = partial.read_bytes()
        self.assertFalse((first / 'A06_完整结合能热图.png').exists())
        with self.assertRaises(ContractError):
            second.export(self.home, self.packet, first)
        figures, attachments = second.export(self.home, self.packet, later)
        self.assertEqual(len(figures), 4)
        self.assertEqual(len(attachments), 2)
        self.assertTrue(all((self.home / row['path']).parent == later for row in figures + attachments))
        self.assertEqual(partial.read_bytes(), original_bytes)
        self.assertFalse((first / 'A06_完整结合能热图.png').exists())

    def test_api_only_current_exports_but_keeps_inherited_pair_evidence(self):
        from modulea.api.system_rescue_view import apply
        fixed = {'study_id': self.packet['study_id'], 'stage': 'A06_INPUT', 'payload': self.packet['source_fixed']}
        write_json(self.home / 'fixed.json', fixed)
        fixed_ref = file_record(self.home, self.home / 'fixed.json', 'system_input')
        self.packet['inputs'] = {'system_input_ref': fixed_ref}
        files = []
        for name, role in [('A06_完整结合能热图.png', 'plot_a06_rescue_full_png'),
                           ('A06_完整结合能热图.svg', 'plot_a06_rescue_full_svg'),
                           ('A06_完整评分明细.csv', 'a06_rescue_matrix_csv'),
                           ('A06_补救展示.json', 'a06_rescue_display_view')]:
            for identity in ('run_baseline', 'run_display_v2'):
                destination = self.home / f'runs/A06/{identity}/rescue/display' / ('display_' + 'd' * 32) / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(identity, encoding='utf-8')
                files.append(file_record(self.home, destination, role))
        for name, role in [('execution.json', 'scoring_execution'), ('top1.pdbqt', 'scoring_pose')]:
            destination = self.home / 'runs/A06/run_baseline/rescue/scores/pair_001' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('historical-exact-pair-evidence', encoding='utf-8')
            ref = file_record(self.home, destination, role)
            files.append(ref)
            self.packet['pairs'][2]['execution' if name.endswith('.json') else 'top1_pose'] = ref
        self.packet['files'] = deepcopy(files)
        write_json(self.home / 'packet.json', self.packet)
        packet_ref = file_record(self.home, self.home / 'packet.json', 'scoring_packet')
        files.append(packet_ref)
        run = {'run_id': self.packet['run_id'], 'study_id': self.packet['study_id'], 'config': {'version': 'A06.system_rescue.2'},
               'inputs': self.packet['inputs']}
        simple = [{key: row[key] for key in ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')} for row in self.packet['pairs']]
        result = {'summary': self.packet['summary'], 'tables': {'scoring_packet': [packet_ref], 'plan_scoring_pairs': simple,
                  'receptor_preparation': self.packet['receptors']}, 'files': files}
        response = {'state': {'code': 'awaiting_review'}, 'review': {'can_review': True, 'already_approved': False,
                    'continue': {'available': True}}, 'files': [dict(ref, key=f'run_display_v2.{i}', name=Path(ref['path']).name)
                                                               for i, ref in enumerate(files)]}
        before = deepcopy((self.packet, run, result))
        class Reader:
            def location(_, sid):
                return self.home
        apply(Reader(), {'study_id': self.packet['study_id']}, run, result, response)
        shown = response['special']['system_rescue']
        self.assertEqual(shown['schema_version'], 'A06.system_rescue.display.2')
        self.assertEqual(len(shown['downloads']), 4)
        self.assertEqual(len(shown['figures']), 1)
        self.assertTrue(all('run_display_v2.' in item['url'] for item in shown['downloads']))
        self.assertEqual(len({item['name'] for item in shown['downloads']}), 4)
        expected_current_keys = {f'run_display_v2.{i}' for i, ref in enumerate(files)
                                 if ref['path'].startswith('runs/A06/run_display_v2/rescue/display/')}
        self.assertEqual({item['url'].rsplit('/', 1)[-1] for item in shown['downloads']}, expected_current_keys)
        evidence = shown['table']['cells'][0][2]['downloads']
        self.assertEqual([item['label_zh'] for item in evidence], ['本组合执行证据', 'Top-1构象'])
        self.assertTrue(all(item['url'] in {f"/api/v1/studies/{self.packet['study_id']}/files/run_display_v2.8",
            f"/api/v1/studies/{self.packet['study_id']}/files/run_display_v2.9"} for item in evidence))
        labels = {row['label_zh']: row['text'] for row in shown['summary_rows']}
        self.assertEqual(labels['基线有效评分'], '42')
        self.assertEqual(labels['本轮新增有效评分'], '16')
        self.assertEqual(labels['累计补救有效评分'], '32')
        self.assertEqual(response['state'], {'code': 'awaiting_review'})
        self.assertTrue(response['review']['can_review'])
        self.assertEqual((self.packet, run, result), before)
        duplicate = deepcopy(response)
        duplicate['files'].append(next(deepcopy(row) for row in response['files']
            if row['role'] == 'plot_a06_rescue_full_png' and row['path'].startswith('runs/A06/run_display_v2/')))
        with self.assertRaises(ContractError):
            apply(Reader(), {'study_id': self.packet['study_id']}, run, result, duplicate)


if __name__ == '__main__':
    unittest.main()

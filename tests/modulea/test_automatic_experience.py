"""隔离自动流程接续：分页、来源、展示修订和第三版授权边界。"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modulea.core.automatic_experience import (
    AutomaticExperienceWorkflow, batch_for, packet_for, pairs_page,
    pair_evidence, page_rows, status_text,
)
from modulea.core.automatic_coverage import AutomaticCoverageWorkflow
from modulea.core.docking_artifacts import pair_key
from storage import file_record, write_json


class ExperienceFixture(AutomaticExperienceWorkflow):
    """只替换存储和上游状态；接续方法走实际生产实现。"""
    def __init__(self, root):
        self.root = root
        self.home = root / 'study_fixture'
        self.home.mkdir()
        self.packet = {'schema_version': 'A06.automatic.2', 'study_id': 'study_fixture', 'run_id': 'run_fixture', 'id': 'auto_fixture',
            'compounds': [{'compound_id': f'c{i}', 'name': f'compound {i}'} for i in range(5)],
            'receptors': [{'target_id': f't{i}', 'symbol': f'TARGET{i}', 'quality': '探索'} for i in range(16)],
            'pairs': [{'compound_id': f'c{i}', 'target_id': f't{j}', 'state': 'completed', 'score': -6.5, 'quality': '探索', 'reason_zh': ''} for i in range(5) for j in range(16)], 'policy': {'version': 2}}
        self.packet['pairs'][10].update(state='failed', score=None, reason_zh='所有预定区域执行失败', regions=[{'returncode': 0, 'state': 'failed', 'reason_zh': '实际Top-1姿势越出预定搜索盒'}])
        self.packet['pairs'][20].update(state='NA', score=None, reason_zh='受体准备未通过')
        self.packet_record = self.record('packet.json', self.packet)
        self.batch = {'id': 'auto_fixture', 'state': 'completed', 'run_id': 'run_fixture', 'packet': self.packet_record, 'files': [self.packet_record]}
        self.manifest = {'study_id': 'study_fixture', 'current': {'A06': 'run_fixture', 'A03': 'a03_fixture'}, 'reviews': ['preserved_review'],
                         'automatic_batches': [self.batch], 'runs': {'run_fixture': {'fixture': True}}, 'automatic_displays': []}
        self.run_info = {'study_id': 'study_fixture', 'module_id': 'A06', 'config': {'schema_version': 'A06.automatic.2'},
                         'parent_runs': {'A03_SELECT': 'selection_fixture', 'A03': 'a03_fixture'}}
        self.result_info = {'tables': {'pairs': [{k: p[k] for k in ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')} for p in self.packet['pairs']],
                                      'receptor_setup': [{'HGNC': r['target_id'], '基因': r['symbol']} for r in self.packet['receptors']]}}
        self.payload = {'expected_a06': 'run_fixture', 'batch_id': 'auto_fixture', 'compound_ids': ['c0', 'c1'], 'target_ids': ['t0', 't1']}
        self.active_value = True
        self.saved = 0

    def record(self, filename, value):
        path = self.home / filename
        write_json(path, value)
        return file_record(self.home, path, 'fixture')

    def load(self, sid):
        if sid != self.manifest['study_id']:
            raise ValueError('本隔离资料不存在该研究')
        return deepcopy(self.manifest)

    def save(self, manifest):
        self.manifest = deepcopy(manifest)
        self.saved += 1

    def location(self, sid):
        return self.home

    def run(self, manifest, rid):
        return deepcopy(self.run_info)

    def result(self, manifest, rid):
        if rid == 'selection_fixture':
            return {'tables': {'selected': deepcopy(self.packet['compounds'])}}
        return deepcopy(self.result_info)

    def active(self, manifest, rid):
        return self.active_value


class AutomaticExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workflow = ExperienceFixture(Path(self.temp.name))

    def test_all_eighty_pairs_page_once_without_loss_or_duplicate(self):
        w = self.workflow
        rows = []
        for page in range(1, 7):
            data = pairs_page(w, w.manifest, w.batch, page, 13)
            self.assertEqual(data['total'], 80)
            rows.extend(data['items'])
        rows.extend(pairs_page(w, w.manifest, w.batch, 7, 13)['items'])
        self.assertEqual(len(rows), 80)
        self.assertEqual(len({r['pair_key'] for r in rows}), 80)
        failed = next(r for r in rows if r['state'] == 'failed')
        self.assertEqual(failed['status_zh'], '姿势质控未通过')
        self.assertIn('越出', failed['reason_zh'])

    def test_failed_page_only_loads_big_packet_when_needed(self):
        w = self.workflow
        with patch('modulea.core.automatic_experience.packet_for', wraps=packet_for) as read:
            pairs_page(w, w.manifest, w.batch, 1, 10)
            read.assert_not_called()
            pairs_page(w, w.manifest, w.batch, 2, 10)
            self.assertEqual(read.call_count, 1)

    def test_evidence_returns_selected_pair_and_precise_qc_status(self):
        w = self.workflow
        row = pair_evidence(w, w.manifest, w.batch, pair_key('c0', 't10'))
        self.assertEqual(row['status_zh'], '姿势质控未通过')
        self.assertEqual(row['compound_id'], 'c0')
        self.assertEqual(row['target_id'], 't10')
        self.assertNotIn('pairs', row)
        self.assertEqual(status_text({'state': 'failed', 'regions': [{'returncode': 1}]}), '计算失败')
        self.assertEqual(status_text({'state': 'NA'}), '准备未通过')

    def test_foreign_batch_pair_and_packet_identity_are_rejected(self):
        w = self.workflow
        with self.assertRaisesRegex(ValueError, '不存在该自动批次'):
            batch_for(w, w.manifest, 'auto_another_study')
        with self.assertRaisesRegex(ValueError, '不存在该组合'):
            pair_evidence(w, w.manifest, w.batch, pair_key('foreign', 'target'))
        w.run_info['study_id'] = 'other_study'
        with self.assertRaisesRegex(ValueError, '归属'):
            batch_for(w, w.manifest, 'auto_fixture')
        w.run_info['study_id'] = w.manifest['study_id']
        other = dict(w.packet, study_id='other_study')
        bad_batch = dict(w.batch, packet=w.record('foreign_packet.json', other))
        with self.assertRaisesRegex(ValueError, '归属'):
            packet_for(w, w.manifest, bad_batch)

    def test_display_source_rejects_stale_trashed_inactive_and_extra_fields(self):
        w = self.workflow
        for state in ('stale', 'trashed', 'inactive', 'extra'):
            payload = deepcopy(w.payload)
            if state == 'stale':
                payload['expected_a06'] = 'old_run'
            elif state == 'trashed':
                w.manifest['trashed'] = True
            elif state == 'inactive':
                w.active_value = False
            else:
                payload['hidden_path'] = '/foreign'
            with self.subTest(state=state), self.assertRaises(ValueError):
                w.automatic_display_source('study_fixture', payload)
            w.manifest.pop('trashed', None)
            w.active_value = True

    def test_display_source_rejects_duplicate_unknown_and_empty_selections(self):
        w = self.workflow
        for field, values in (('compound_ids', ['c0', 'c0']), ('target_ids', ['t1', 't1']),
                              ('compound_ids', ['foreign']), ('target_ids', ['foreign']), ('compound_ids', []), ('target_ids', [])):
            payload = dict(w.payload, **{field: values})
            with self.subTest(field=field, values=values), self.assertRaises(ValueError):
                w.automatic_display_source('study_fixture', payload)

    def test_publish_appends_display_without_current_reviews_or_scores_change(self):
        w = self.workflow
        from science_modules.a06.automatic_exports import build_view
        expected_view = build_view(w.packet, {}, w.payload['compound_ids'], w.payload['target_ids'])
        view = w.record('display/view.json', expected_view)
        file = w.record('display/image.json', {'fixture': True})
        before = deepcopy(w.manifest)
        result_before = deepcopy(w.result_info)
        with patch('modulea.core.automatic_experience.automatic_names', return_value={}):
            row = w.publish_automatic_display('study_fixture', w.payload, view, [file])
        expected = deepcopy(before)
        expected['automatic_displays'].append(row)
        self.assertEqual(w.manifest, expected)
        self.assertEqual(w.result_info, result_before)
        self.assertEqual(w.saved, 1)
        self.assertEqual(row['packet'], w.packet_record)

    def test_publish_rejects_changed_bytes_before_manifest_write(self):
        w = self.workflow
        record = w.record('view.json', {'fixture': True})
        (w.home / 'view.json').write_text('tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            w.publish_automatic_display('study_fixture', w.payload, record, [])
        self.assertEqual(w.saved, 0)

    def test_publish_rejects_valid_hash_but_forged_scores_or_selection(self):
        w = self.workflow
        from science_modules.a06.automatic_exports import build_view
        for mode in ('score', 'selection'):
            view = build_view(w.packet, {}, w.payload['compound_ids'], w.payload['target_ids'])
            if mode == 'score':
                view['table']['cells'][0][0]['score'] = -99
            else:
                view['heatmap']['columns'].reverse()
            record = w.record('forged_'+mode+'.json', view)
            with patch('modulea.core.automatic_experience.automatic_names', return_value={}):
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    w.publish_automatic_display('study_fixture', w.payload, record, [])
            self.assertEqual(w.saved, 0)

    def test_technical_prepared_state_never_signs_scientific_approval(self):
        w = self.workflow
        original = {'manifest': deepcopy(w.manifest), 'modules': [{'module_id': 'A06_PREP', 'state': 'ready'}, {'module_id': 'A06', 'state': 'review'}]}
        for batch_state, expected in (('running', 'execution_confirmed'), ('completed', 'prepared')):
            original['manifest']['automatic_batches'][0]['state'] = batch_state
            with patch.object(AutomaticCoverageWorkflow, 'view', return_value=deepcopy(original)):
                response = w.view('study_fixture')
            prep = response['modules'][0]
            self.assertEqual(prep['state'], expected)
            self.assertIs(prep['automatic_preparation']['approved'], False)
            self.assertEqual(response['manifest']['reviews'], ['preserved_review'])

    def test_v3_explicit_reference_choices_and_policy_are_required(self):
        w = self.workflow
        request = {'expected_binding': 'a'*64, 'expected_connection_id': 'connection_fixture', 'expected_a06': 'run_fixture',
                   'request_id': 'auto_'+'a'*32, 'policy_version': 'A06.automatic.3', 'reviewer': '实际用户', 'note': '隔离授权核验', 'confirmed': True}
        with self.assertRaisesRegex(ValueError, '共晶核定'):
            w.validate_automatic_request('study_fixture', request)
        for old in ('A06.automatic.1', 'A06.automatic.2'):
            payload = dict(request, reference_choices=[], policy_version=old)
            with self.subTest(policy=old), self.assertRaisesRegex(ValueError, '明确确认'):
                w.validate_automatic_request('study_fixture', payload)
        connection_packet = {'summary': {'connected_compounds': 5, 'connected_receptors': 16}, 'receptors': []}
        connection = {'id': 'connection_fixture', 'packet': w.record('connection.json', connection_packet)}
        with patch.object(w, 'automatic_binding', return_value=(deepcopy(w.manifest), {'fixture': True})), \
             patch.object(w, 'validate_extended_scope', return_value={'ready': True}), \
             patch.object(w, 'current_automatic_connection', return_value=connection), \
             patch.object(w, 'automatic_record', return_value=None):
            manifest, bound, returned = w.validate_automatic_request('study_fixture', dict(request, reference_choices=[]))
            self.assertEqual(returned, connection)
            self.assertEqual(manifest['current']['A06'], 'run_fixture')
            with self.assertRaisesRegex(ValueError, '列表'):
                w.validate_automatic_request('study_fixture', dict(request, reference_choices='not-a-list'))

    def test_pagination_search_does_not_change_archive(self):
        rows = [{'symbol': 'FIRST'}, {'symbol': 'second'}, {'symbol': 'FIRST2'}]
        before = deepcopy(rows)
        self.assertEqual(page_rows(rows, 1, 1, 'first')['total'], 2)
        self.assertEqual(page_rows(rows, 2, 1, 'FIRST')['items'], [rows[2]])
        self.assertEqual(rows, before)
        for page, size in ((0, 10), (1, 0), (1, 101)):
            with self.assertRaises(ValueError):
                page_rows(rows, page, size)

    def test_matrix_downloads_match_displayed_selection_and_get_is_readonly(self):
        from science_modules.a06.automatic_exports import build_view
        from modulea.api import automatic_view
        w = self.workflow
        view = build_view(w.packet, {}, ['c0'], ['t0'])
        w.manifest['automatic_displays'] = [{'id': 'display_fixture', 'batch_id': w.batch['id'], 'packet': w.packet_record,
            'view': w.record('saved_view.json', view), 'files': [w.record('download.json', {'fixture': True})]}]
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: w), tasks=SimpleNamespace(active_for=lambda sid: False))
        req = SimpleNamespace(query1=lambda key: None)
        original = deepcopy(w.manifest)
        aligned = automatic_view.matrix(app, req, 'study_fixture', 'auto_fixture')
        self.assertEqual(len(aligned['downloads']), 1)
        explicit = SimpleNamespace(query1=lambda key: {'compound_ids': 'c1', 'target_ids': 't0'}.get(key))
        with patch('modulea.api.automatic_view.automatic_names', return_value={}):
            changed = automatic_view.matrix(app, explicit, 'study_fixture', 'auto_fixture')
        self.assertEqual(changed['downloads'], [])
        self.assertEqual(changed['view']['heatmap']['rows'][0]['compound_id'], 'c1')
        self.assertEqual(w.manifest, original)
        self.assertEqual(w.saved, 0)

    def test_display_file_rejects_foreign_identity_negative_and_out_of_bounds(self):
        from modulea.api import automatic_view
        from modulea.api.errors import ApiError
        w = self.workflow
        w.manifest['automatic_displays'] = [{'id': 'display_fixture', 'files': [w.record('download.json', {'fixture': True})]}]
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: w))
        for identity, index in (('foreign_display', '0'), ('display_fixture', '-1'), ('display_fixture', '1')):
            with self.subTest(identity=identity, index=index), self.assertRaises(ApiError):
                automatic_view.display_file(app, None, 'study_fixture', identity, index)
        response = automatic_view.display_file(app, None, 'study_fixture', 'display_fixture', '0')
        self.assertEqual(response[0], 'file')

    def test_display_post_waits_for_existing_task_and_never_starts_vina(self):
        from modulea.api import automatic_view
        from modulea.api.errors import ApiError
        w = self.workflow
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: w),
            tasks=SimpleNamespace(active_for=lambda sid: True, submit=lambda *args: self.fail('busy gate submitted task')))
        with self.assertRaises(ApiError):
            automatic_view.display(app, SimpleNamespace(json=lambda: w.payload), 'study_fixture')
        calls = []
        app.tasks.active_for = lambda sid: False
        app.tasks.submit = lambda *args: (calls.append(args) or {'fixture': True}, True)
        response, status = automatic_view.display(app, SimpleNamespace(json=lambda: w.payload), 'study_fixture')
        self.assertEqual(status, 202)
        self.assertEqual(calls[0][1], 'a06_display')
        self.assertEqual(calls[0][3], w.payload)


if __name__ == '__main__':
    unittest.main()

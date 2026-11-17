"""独立名称修订展示：仅用合成评分与名称证据，冻结科学包和构象保持。"""
from copy import deepcopy
import csv
import importlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contracts import ContractError, fingerprint


class RescuePresentationRenderTests(unittest.TestCase):
    def setUp(self):
        try:
            self.render = importlib.import_module('science_modules.a06.system_rescue_presentation')
        except ModuleNotFoundError:
            self.fail('尚未实现独立名称展示修订构造器')
        compounds = [{'compound_id': key, 'name': name} for key, name in
                     [('C1', 'Alpha compound'), ('C2', 'Alpha compound'), ('C3', 'Source beta')]]
        targets = [{'target_id': 'HGNC:1', 'symbol': 'TEST', 'quality': '探索'}]
        self.packet = {'schema_version': 'A06.system_rescue.2', 'study_id': 'study_' + 'a' * 32,
                       'run_id': 'run_' + 'b' * 32, 'source_fixed': {'compounds': compounds, 'receptors': targets},
                       'compounds': [dict(row, state='ready', cid=1) if i < 2 else dict(row, state='NA')
                                     for i, row in enumerate(compounds)], 'receptors': targets,
                       'summary': {'input_key': 'synthetic'}, 'pairs': [
                           {'compound_id': row['compound_id'], 'target_id': 'HGNC:1',
                            'state': 'completed' if i < 2 else 'NA', 'score': -7.125 if i < 2 else None,
                            'quality': '探索', 'reason_zh': '' if i < 2 else '原服务404；未评分'}
                           for i, row in enumerate(compounds)],
                       'reused_pair_keys': [['C1', 'HGNC:1']], 'new_pair_keys': [['C2', 'HGNC:1']]}
        self.names = [{'compound_id': row['compound_id'], 'source_name': row['name'],
                       'display_name_zh': '甲成分' if i < 2 else '乙术语',
                       'scope': 'prepared_identity_translation' if i < 2 else 'source_term_translation_only',
                       'identity': {'scheme': 'PubChem', 'id': '1'} if i < 2 else {'scheme': 'HERB', 'id': 'HBIN123456'},
                       'evidence': [{'path': 'names/source.json', 'bytes': 1, 'sha256': 'f' * 64}],
                       'translation_basis': '合成名称证据，仅用于测试'} for i, row in enumerate(compounds)]

    def test_bilingual_rows_preserve_duplicates_scores_na_and_original_packet(self):
        before = fingerprint(self.packet)
        view = self.render.build_view(self.packet, self.names)
        self.assertEqual(view['schema_version'], 'A06.system_rescue.display.3')
        rows = view['table']['rows']
        self.assertEqual([r['compound_id'] for r in rows], ['C1', 'C2', 'C3'])
        self.assertEqual([r['name_zh'] for r in rows], ['甲成分', '甲成分', '乙术语'])
        self.assertNotEqual(rows[0]['label'], rows[1]['label'])
        self.assertIn('仅来源术语', rows[2]['label'])
        self.assertIn('不是结构身份确认', rows[2]['name_scope_note_zh'])
        self.assertEqual(rows[2]['name_en'], 'Source beta')
        self.assertEqual([line[0]['score'] for line in view['table']['cells']], [-7.125, -7.125, None])
        self.assertEqual(view['table']['cells'][2][0]['reason_zh'], '原服务404；未评分')
        self.assertEqual(view['table']['cells'][0][0]['source_zh'], '沿用已核验评分')
        self.assertEqual(view['table']['cells'][1][0]['source_zh'], '本轮新增评分')
        self.assertEqual(fingerprint(self.packet), before)

    def test_wrong_cid_name_scope_or_missing_evidence_is_rejected(self):
        for change in ({'identity': {'scheme': 'PubChem', 'id': '2'}},
                       {'source_name': 'Another compound'}, {'display_name_zh': 'English only'},
                       {'display_name_zh': '中文待核译'}, {'evidence': []},
                       {'scope': 'source_term_translation_only'}):
            with self.subTest(change=change):
                names = deepcopy(self.names)
                names[0].update(change)
                with self.assertRaises(ContractError):
                    self.render.build_view(self.packet, names)

    def test_names_require_exact_fixed_order_and_unique_ids(self):
        for names in (self.names[::-1], self.names[:-1], [self.names[0], self.names[0], self.names[2]]):
            with self.subTest(ids=[row['compound_id'] for row in names]), self.assertRaises(ContractError):
                self.render.build_view(self.packet, names)

    def test_first_science_protocol_keeps_original_versions_and_scoring(self):
        from science_modules.a06 import system_rescue_display as first, system_rescue_display_v2 as second
        packet = deepcopy(self.packet)
        packet['schema_version'] = 'A06.system_rescue.1'
        packet.pop('reused_pair_keys')
        packet.pop('new_pair_keys')
        for index, pair in enumerate(packet['pairs']):
            pair['source_kind'] = 'original' if index == 0 else 'rescue'
        before = fingerprint(packet)
        view = self.render.build_view(packet, self.names)
        self.assertEqual(view['science_version'], 'A06.system_rescue.1')
        self.assertIn('甲成分', self.render.heatmap_svg(view))
        self.assertEqual(view['table']['cells'][0][0]['source_zh'], '沿用原评分')
        self.assertEqual(fingerprint(packet), before)
        self.assertEqual(first.VERSION, 'A06.system_rescue.display.1')
        self.assertEqual(second.VERSION, 'A06.system_rescue.display.2')

    def test_original_proper_name_requires_explicit_allowlist_and_stays_na(self):
        names = deepcopy(self.names)
        names[2].update(scope='original_proper_name', display_name_zh='')
        with self.assertRaises(ContractError):
            self.render.build_view(self.packet, names)
        view = self.render.build_view(self.packet, names, allowed_original_names={'C3'})
        self.assertEqual(view['table']['rows'][2]['name_zh'], '')
        self.assertIn('原来源专名', view['table']['rows'][2]['label'])
        self.assertEqual(view['name_counts'], {'chinese': 2, 'source_term_only': 0, 'original_proper_name': 1})
        self.assertEqual(view['table']['cells'][2][0]['state'], 'NA')

    def test_scope_notes_are_present_in_svg_and_focus_uses_same_names(self):
        view = self.render.build_view(self.packet, self.names)
        svg = self.render.heatmap_svg(view)
        self.assertIn('仅来源术语', svg)
        self.assertIn('Source beta', svg)
        focused = self.render.build_view(self.packet, self.names, selected_compounds=['C2'], selected_targets=['HGNC:1'])
        self.assertEqual(focused['heatmap']['rows'][0]['label'], view['table']['rows'][1]['label'])
        self.assertEqual(focused['score_range'], view['score_range'])

    def test_original_proper_name_scope_is_visible_in_standalone_figure(self):
        names = deepcopy(self.names)
        names[2].update(scope='original_proper_name', display_name_zh='')
        view = self.render.build_view(self.packet, names, allowed_original_names={'C3'})
        svg = self.render.heatmap_svg(view)
        self.assertIn('结构身份未核实', svg)
        self.assertIn('本批未评分', svg)
        self.assertIn('不计为已核中文译名', svg)

    def test_exports_keep_scope_in_csv_and_refuse_overwrite(self):
        font = next((p for p in (Path('C:/Windows/Fonts/msyh.ttc'),
                                Path('/System/Library/Fonts/Supplemental/Songti.ttc')) if p.is_file()), None)
        if not font:
            self.skipTest('需要实际中文绘图字体')
        with TemporaryDirectory(prefix='名称修订 ') as temporary:
            root = Path(temporary)
            folder = root / 'runs/A06' / self.packet['run_id'] / 'rescue/presentations' / ('rescueview_' + 'c' * 32)
            before = fingerprint(self.packet)
            figures, attachments = self.render.export(root, self.packet, self.names, folder, font_path=font)
            self.assertEqual(len(figures), 4)
            ref = next(r for r in attachments if r['role'] == 'a06_rescue_matrix_csv')
            rows = list(csv.DictReader(io.StringIO((root / ref['path']).read_text('utf-8-sig'))))
            self.assertEqual(rows[2]['name_scope'], 'source_term_translation_only')
            self.assertEqual(rows[2]['name_en'], 'Source beta')
            self.assertIn('不是结构身份确认', rows[2]['name_scope_note_zh'])
            view_ref = next(r for r in attachments if r['role'] == 'a06_rescue_display_view')
            self.assertEqual(json.loads((root / view_ref['path']).read_text('utf-8'))['name_counts']['chinese'], 3)
            with self.assertRaises(ContractError):
                self.render.export(root, self.packet, self.names, folder, font_path=font)
            self.assertEqual(fingerprint(self.packet), before)

    def test_concurrent_exports_reserve_directory_before_any_write(self):
        """两个同目录调用都到达mkdir后再竞争，失败调用不能写首份图件。"""
        from concurrent.futures import ThreadPoolExecutor
        from hashlib import sha256
        import threading
        from unittest.mock import patch
        font = next((p for p in (Path('C:/Windows/Fonts/msyh.ttc'),
                                Path('/System/Library/Fonts/Supplemental/Songti.ttc')) if p.is_file()), None)
        if not font:
            self.skipTest('本反例需要明确中文字体')
        with TemporaryDirectory(prefix='独占修订 ') as temporary:
            root = Path(temporary)
            folder = root / 'runs/A06' / self.packet['run_id'] / 'rescue/presentations' / ('rescueview_' + 'd' * 32)
            folder.parent.mkdir(parents=True)
            barrier = threading.Barrier(2)
            mkdir, write_text = Path.mkdir, Path.write_text
            writers = set()
            reservations = set()
            def reserve(path, *args, **kwargs):
                identity = threading.get_ident()
                if path == folder and identity not in reservations:
                    reservations.add(identity)
                    barrier.wait(timeout=10)
                return mkdir(path, *args, **kwargs)
            def write(path, *args, **kwargs):
                if path.parent == folder:
                    writers.add(threading.get_ident())
                return write_text(path, *args, **kwargs)
            def call():
                identity = threading.get_ident()
                try:
                    output = self.render.export(root, self.packet, self.names, folder, font_path=font)
                    return identity, output, None
                except Exception as error:
                    return identity, None, error
            with patch.object(Path, 'mkdir', reserve), patch.object(Path, 'write_text', write), ThreadPoolExecutor(2) as pool:
                answers = list(pool.map(lambda _: call(), range(2)))
            winners = [row for row in answers if row[2] is None]
            failures = [row for row in answers if row[2] is not None]
            self.assertEqual(len(winners), 1, answers)
            self.assertEqual(len(failures), 1, answers)
            self.assertEqual(writers, {winners[0][0]})
            self.assertIsInstance(failures[0][2], ContractError)
            for ref in winners[0][1][0] + winners[0][1][1]:
                self.assertEqual(sha256((root / ref['path']).read_bytes()).hexdigest(), ref['sha256'])

    def test_export_rejects_foreign_run_before_creating_files(self):
        with TemporaryDirectory(prefix='修订归属 ') as temporary:
            root = Path(temporary)
            folder = root / 'runs/A06' / ('run_' + 'e' * 32) / 'rescue/presentations' / ('rescueview_' + 'f' * 32)
            with self.assertRaises(ContractError):
                self.render.export(root, self.packet, self.names, folder)
            self.assertFalse(folder.exists())

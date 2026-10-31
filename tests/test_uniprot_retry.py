"""UniProt临时传输错误有界补取；虚构网络，不改变身份映射和旧缓存。"""
import hashlib
import http.client
import io
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from contracts import ContractError
from science_modules.a01.acquisition import Fetcher, _human_target

URL = 'https://rest.uniprot.org/uniprotkb/search?query=fixture&format=json&size=500'


class Response(io.BytesIO):
    """固定官方主机、长度及关闭行为的内存响应。"""
    status = 200

    def __init__(self, raw=b'{"results":[]}', url=URL):
        super().__init__(raw)
        self.url = url
        self.headers = {'Content-Length': str(len(raw))}

    def geturl(self):
        return self.url


def failure(code, headers=None):
    """每次创建独立错误流，验证失败原文和关闭，不能复用已读流。"""
    return HTTPError(URL, code, 'fixture failure', headers or {}, io.BytesIO(b'original failure'))


class UniProtRetryTests(unittest.TestCase):
    def test_transient_statuses_backoff_preserve_original_and_then_cache(self):
        for code in (429, 500, 502, 503, 504):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as d:
                folder = Path(d)
                errors = [failure(code) for _ in range(3)]
                opener = Mock(side_effect=errors + [Response()])
                sleeps, progress = [], []
                fetch = Fetcher(folder, opener, sleeps.append, progress.append)
                self.assertEqual(fetch.get(URL), b'{"results":[]}')
                self.assertEqual(opener.call_count, 4)
                self.assertEqual([v for v in sleeps if v != .5], [2, 4, 8])
                records = [json.loads(p.read_bytes()) for p in folder.glob('*failure*.json')]
                self.assertEqual(len(records), 3)
                self.assertEqual(sorted(v['attempt'] for v in records), [1, 2, 3])
                self.assertTrue(all(v['http_status'] == code and v['retry_policy'] == 'A01.uniprot_transport.1' for v in records))
                self.assertTrue(all(p.read_bytes() == b'original failure' for p in folder.glob('*failure*.bin')))
                self.assertTrue(all(error.fp.closed for error in errors))
                self.assertEqual(len(progress), 3)
                self.assertTrue(all('UniProt' in v for v in progress))
                ledger = {p.name: p.read_bytes() for p in folder.iterdir()}
                self.assertEqual(fetch.get(URL), b'{"results":[]}')
                self.assertEqual(opener.call_count, 4)
                self.assertEqual(ledger, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_five_attempt_limit_leaves_no_success_cache(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            opener = Mock(side_effect=[failure(500) for _ in range(5)])
            sleeps = []
            with self.assertRaises(HTTPError):
                Fetcher(folder, opener, sleeps.append).get(URL)
            self.assertEqual(opener.call_count, 5)
            self.assertEqual([v for v in sleeps if v != .5], [2, 4, 8, 16])
            records = [json.loads(p.read_bytes()) for p in folder.glob('*failure*.json')]
            self.assertEqual(len(records), 5)
            terminal = next(v for v in records if v['attempt'] == 5)
            self.assertFalse(terminal['will_retry'])
            self.assertIsNone(terminal['retry_seconds'])
            self.assertFalse(any('failure' not in p.name for p in folder.iterdir()))

    def test_permanent_statuses_and_certificate_errors_are_not_retried(self):
        for error in [failure(code) for code in (400, 401, 403, 404, 422)] + [URLError(ssl.SSLCertVerificationError('bad certificate'))]:
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as d:
                opener = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    Fetcher(Path(d), opener, lambda _: None).get(URL)
                self.assertEqual(opener.call_count, 1)

    def test_connection_errors_retry_and_incomplete_bytes_are_retained(self):
        for error in (TimeoutError('timed out'), ConnectionResetError('reset'),
                      URLError(TimeoutError('timed out')), http.client.IncompleteRead(b'partial', 20)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as d:
                opener = Mock(side_effect=[error, Response()])
                sleeps = []
                self.assertEqual(Fetcher(Path(d), opener, sleeps.append).get(URL), b'{"results":[]}')
                self.assertEqual(opener.call_count, 2)
                self.assertIn(2, sleeps)
                if isinstance(error, http.client.IncompleteRead):
                    self.assertEqual(next(Path(d).glob('*failure*.bin')).read_bytes(), b'partial')

    def test_retry_after_is_capped_and_only_between_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            sleeps = []
            opener = Mock(side_effect=[failure(429, {'Retry-After': '120'}), Response()])
            Fetcher(Path(d), opener, sleeps.append).get(URL)
            self.assertEqual(sleeps, [.5, 60, .5])

    def test_format_identity_and_partial_length_errors_are_not_retried(self):
        def rejected(raw):
            raise ContractError('fixture identity conflict')
        for kind in ('identity', 'length', 'redirect'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                response = Response()
                if kind == 'length':
                    response.headers['Content-Length'] = '100'
                if kind == 'redirect':
                    response.url = 'https://example.com/unsupported'
                opener = Mock(return_value=response)
                with self.assertRaises(ContractError):
                    Fetcher(Path(d), opener, lambda _: None).get(URL, validate=rejected if kind == 'identity' else None)
                self.assertEqual(opener.call_count, 1)
                self.assertTrue(response.closed)
                self.assertFalse(any('failure' not in p.name for p in Path(d).iterdir()))

    def test_existing_cache_bytes_unchanged_and_tamper_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            token = hashlib.sha256(URL.encode()).hexdigest()
            raw = b'{"results":[]}'
            (folder / (token + '.bin')).write_bytes(raw)
            (folder / (token + '.json')).write_text(json.dumps({'url': URL, 'payload': None,
                'retrieved_at': '2020-01-01', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf8')
            before = {p.name: p.read_bytes() for p in folder.iterdir()}
            opener = Mock(side_effect=AssertionError('must not access network'))
            fetch = Fetcher(folder, opener, lambda _: None)
            self.assertEqual(fetch.get(URL), raw)
            self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})
            (folder / (token + '.bin')).write_bytes(b'corrupt')
            with self.assertRaises(ContractError):
                fetch.get(URL)
            opener.assert_not_called()

    def test_policy_is_limited_to_fixed_uniprot_get_endpoint(self):
        for url, payload in [('https://rest.uniprot.org/other', None),
                             ('http://rest.uniprot.org/uniprotkb/search', None),
                             ('https://rest.uniprot.org/uniprotkb/search', {'fixture': True}),
                             ('https://old.tcmsp-e.com/tcmsp.php', None)]:
            with self.subTest(url=url, payload=payload), tempfile.TemporaryDirectory() as d:
                opener = Mock(side_effect=[failure(500), failure(500)])
                sleeps = []
                with self.assertRaises(HTTPError):
                    Fetcher(Path(d), opener, sleeps.append).get(url, payload)
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(sleeps, [.5, .5])

    def test_human_mapping_after_transient_failure_preserves_exact_query_and_uniqueness(self):
        row = {'primaryAccession': 'P1', 'organism': {'taxonId': 9606},
               'genes': [{'geneName': {'value': 'A'}}],
               'proteinDescription': {'recommendedName': {'fullName': {'value': 'Protein A'}}}}
        for rows, expected in [([row], ('P1', 'A', 'Homo sapiens (Human)')),
                               ([row, dict(row, primaryAccession='P2')], ('', '', '')),
                               ([dict(row, organism={'taxonId': 10090})], ('', '', ''))]:
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as d:
                opener = Mock(side_effect=[failure(500), Response(json.dumps({'results': rows}).encode())])
                result = _human_target(Fetcher(Path(d), opener, lambda _: None), 'Protein A')
                self.assertEqual(result, expected)
                requests = [call.args[0].full_url for call in opener.call_args_list]
                self.assertEqual(requests[0], requests[1])
                self.assertIn('organism_id%3A9606', requests[0])
                self.assertIn('reviewed%3Atrue', requests[0])


if __name__ == '__main__':
    unittest.main()

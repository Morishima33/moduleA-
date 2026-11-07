"""只替换明确合成的官方响应，生产来源补救和离线重放照常执行。"""
import io
import json
import zipfile
from unittest.mock import patch
from storage import file_record, verified_file
from science_modules.a06 import source_context, compound_sources_v2


def stable_ids(original):
    def package(database):
        raw = original(database)
        if database != 'TCMSP':
            return raw
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        path = 'references/tcmsp_snapshot.tsv'
        files[path] = files[path].replace(b'MOL1', b'MOL000001').replace(b'MOL2', b'MOL000002')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in files.items():
                archive.writestr(name, value)
        return out.getvalue()
    return package


def bound_connector(source):
    def connect(home, packet, folder, progress):
        value = source.connect(home, packet, folder, progress)
        for index, row in enumerate(value['compounds']):
            if row['state'] != 'connected':
                continue
            fixed = packet['compounds'][index]
            key = row['audit']['inchi_key']
            fetch = source_context.Fetcher(home, folder / 'explicit_synthetic_official_responses')
            def get(fetcher, url, suffix='json'):
                if suffix == 'sdf':
                    return {}, row['sdf']
                if suffix == 'html':
                    identifier = 'MOL' + url.split('qn=')[1].zfill(6)
                    original = next(r for r in packet['source_identities'][fixed['compound_id']] if r['source_id'] == identifier)
                    answer = 'var mol = ' + json.dumps([{'MOL_ID': identifier, 'molecule_ID': str(int(identifier[3:])),
                        'molecule_name': original['name'], 'inchikey': key, 'pubchem_cid': '123'}]) + ';'
                elif '/property/' in url:
                    answer = {'PropertyTable': {'Properties': [{'CID': 123, 'InChIKey': key, 'MolecularFormula': 'C2H6O'}]}}
                else:
                    answer = {'IdentifierList': {'CID': [123]}}
                path = fetcher.folder / ('synthetic_response_' + str(len(fetcher.events)) + '.' + suffix)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(answer) if suffix == 'json' else answer, encoding='utf8')
                ref = file_record(home, path, 'explicit_synthetic_official_response')
                fetcher.records.append(ref)
                return answer, ref
            with patch.object(source_context.OriginalFetcher, 'get', new=get):
                actual = compound_sources_v2.resolve(fixed, fetch, packet['source_identities'].get(fixed['compound_id'], []))
            actual['source_requests'] = fetch.events
            value['compounds'][index] = actual
            value['files'].extend(fetch.records)
        return value
    return connect

"""Check read-only database evidence for an existing Module A analysis."""

import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from contracts import require
from modulea.core.rescue_result_read import load_rescue_result
from storage import verified_file
from workflow import Workflow


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'ModuleA/database-evidence'}), timeout=20) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    require(0 < len(raw) <= 8 * 1024 * 1024, '官方响应为空或超出允许大小')
    return raw, {'url': url, 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


def structure_evidence(pdb, accession, chains):
    require(re.fullmatch(r'[0-9][A-Za-z0-9]{3}', pdb) and bool(accession) and chains,
            '需要明确的既有实验结构、UniProt 与链')
    pdb = pdb.lower()
    sifts_url = f'https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb}'
    xml_url = f'https://files.wwpdb.org/pub/pdb/validation_reports/{pdb[1:3]}/{pdb}/{pdb}_validation.xml.gz'
    value = {'pdb_id': pdb.upper(), 'uniprot': accession, 'selected_chains': chains}
    try:
        raw, record = fetch(sifts_url)
        mappings = json.loads(raw)[pdb]['UniProt']
        segments = [segment for segment in mappings.get(accession, {}).get('mappings', [])
                    if segment.get('chain_id') in chains]
        mapped = {segment['chain_id'] for segment in segments}
        value['sifts'] = {**record, 'state': 'matched' if mapped == set(chains) else 'mapping_gap',
                          'segments': segments, 'unmapped_planned_chains': sorted(set(chains) - mapped)}
    except (OSError, ValueError, KeyError) as error:
        value['sifts'] = {'url': sifts_url, 'state': 'unavailable', 'reason': str(error)}
    try:
        raw, record = fetch(xml_url)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            xml = stream.read(16 * 1024 * 1024 + 1)
        require(len(xml) <= 16 * 1024 * 1024, '验证XML解压后超过允许大小')
        entry = ElementTree.fromstring(xml).find('.//Entry')
        require(entry is not None and str(entry.get('pdbid', '')).lower() == pdb,
                'wwPDB验证报告的结构编号不一致')
        fields = ('PDB-resolution', 'PDB-R', 'PDB-Rfree', 'clashscore', 'XMLcreationDate')
        value['wwpdb'] = {**record, 'state': 'available',
                          'entry_metrics': {key: entry.get(key) for key in fields if entry.get(key) is not None}}
    except (OSError, ValueError, EOFError, ElementTree.ParseError) as error:
        value['wwpdb'] = {'url': xml_url, 'state': 'unavailable', 'reason': str(error)}
    return value


def structures(workflow, manifest, run_id, targets):
    sid = manifest['study_id']
    bundle = load_rescue_result(workflow, manifest, sid, run_id)
    rows = {row['target_id']: row for row in bundle[5]['receptors']}
    require(set(targets) <= rows.keys(), '指定受体不在本批')
    output = []
    for target in targets:
        row = rows[target]
        spec = row.get('spec') or {}
        item = {key: row.get(key) for key in ('target_id', 'symbol', 'state', 'quality', 'reason_zh')}
        if spec.get('source_type') == 'experimental':
            item['evidence'] = structure_evidence(spec['pdb_id'], spec['uniprot'], spec['chains'])
        else:
            item['evidence'] = {'state': 'no_selected_experimental_structure'}
        output.append(item)
    return {'run_id': run_id, 'receptors': output}


def delta(before, after):
    return {'before_count': len(before), 'after_count': len(after),
            'added': sorted(after.keys() - before.keys()),
            'removed': sorted(before.keys() - after.keys()),
            'changed': sorted(key for key in before.keys() & after.keys() if before[key] != after[key])}


def compare(workflow, manifest, before_id, after_id):
    runs = [workflow.run(manifest, rid) for rid in (before_id, after_id)]
    module = runs[0]['module_id']
    parent = runs[0]['parent_runs'].get('A03')
    require(module in ('A04', 'A05') and runs[1]['module_id'] == module and parent
            and runs[1]['parent_runs'].get('A03') == parent, '只比较同一A03下的同类归档')
    data = [workflow.result(manifest, rid) for rid in (before_id, after_id)]
    require(all(data), '缺少完整归档结果')
    tables = [result['tables'] for result in data]
    if module == 'A04':
        edges = [{'|'.join(sorted((row['source'], row['target']))):
                  row['score'] for row in table['edges']} for table in tables]
        differences = {'edges_by_hgnc_pair': delta(*edges)}
    else:
        differences = {group: delta(*({row['ID']: (row['Count'], row['p.adjust'], frozenset(row['geneID'].split('/')))
                                       for row in table[group + '_significant']} for table in tables))
                       for group in ('bp', 'cc', 'mf', 'kegg')}
    sources = [run['inputs'].get('source_file') for run in runs]
    require(all(sources), '归档缺少显式来源文件')
    locations = [verified_file(workflow.location(manifest['study_id']), source) for source in sources]
    string_versions = [json.loads(path.read_bytes()).get('string_version') for path in locations] if module == 'A04' else None
    return {'module': module, 'a03': parent, 'runs': [before_id, after_id],
            'protocols': [run['config']['version'] for run in runs],
            'sources': sources, 'same_source_sha256': sources[0]['sha256'] == sources[1]['sha256'],
            'string_versions': string_versions, 'differences': differences}


def chembl(inchikey, accession):
    require(re.fullmatch(r'[A-Z]{14}-[A-Z]{10}-[A-Z]', inchikey) and
            re.fullmatch(r'[A-Z0-9]{6,10}', accession), '需要完整InChIKey及UniProt编号')
    base = 'https://www.ebi.ac.uk/chembl/api/data/'
    result = {'inchikey': inchikey, 'uniprot': accession, 'sources': []}

    def lookup(resource, **query):
        raw, ref = fetch(base + resource + '.json?' + urlencode(query))
        result['sources'].append(ref)
        return json.loads(raw)

    molecules = lookup('molecule', molecule_structures__standard_inchi_key=inchikey, limit=50)
    targets = lookup('target', target_components__accession=accession, target_type='SINGLE PROTEIN', limit=50)
    m = sorted({row['molecule_chembl_id'] for row in molecules['molecules']
                if (row.get('molecule_structures') or {}).get('standard_inchi_key') == inchikey})
    t = sorted({row['target_chembl_id'] for row in targets['targets']
                if row['target_type'] == 'SINGLE PROTEIN' and row['organism'] == 'Homo sapiens'
                and {part['accession'] for part in row['target_components']} == {accession}})
    result.update(molecule_ids=m, target_ids=t)
    if len(m) != 1 or len(t) != 1 or any(page['page_meta']['next'] for page in (molecules, targets)):
        return {**result, 'state': 'identity_missing_or_ambiguous'}
    activities = lookup('activity', molecule_chembl_id=m[0], target_chembl_id=t[0], limit=100)
    fields = ('activity_id', 'assay_chembl_id', 'document_chembl_id', 'assay_type',
              'standard_type', 'standard_relation', 'standard_value', 'standard_units', 'data_validity_comment')
    rows = [{key: row.get(key) for key in fields} for row in activities['activities']
            if row.get('molecule_chembl_id') == m[0] and row.get('target_chembl_id') == t[0]]
    require(len(rows) == len(activities['activities']), 'ChEMBL活性记录身份不一致')
    return {**result, 'state': 'partial' if activities['page_meta']['next'] else 'complete',
            'reported_total': activities['page_meta']['total_count'], 'activities': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('structures', 'compare'):
        command = sub.add_parser(action)
        command.add_argument('--data-root', type=Path, required=True)
        command.add_argument('--study-id', required=True)
        command.add_argument('--run', required=True)
        if action == 'structures':
            command.add_argument('--target', action='append', required=True)
        else:
            command.add_argument('--against', required=True, help='second run of the same stage and A03')
    command = sub.add_parser('chembl')
    command.add_argument('--inchikey', required=True)
    command.add_argument('--uniprot', required=True)
    args = parser.parse_args()
    if args.action == 'chembl':
        result = chembl(args.inchikey, args.uniprot)
    else:
        workflow = Workflow(args.data_root)
        manifest = workflow.load(args.study_id)
        result = (structures(workflow, manifest, args.run, list(dict.fromkeys(args.target)))
                  if args.action == 'structures' else compare(workflow, manifest, args.run, args.against))
    output = {'kind': 'read_only_supplement', 'retrieved_at': datetime.now(timezone.utc).isoformat(), **result}
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()

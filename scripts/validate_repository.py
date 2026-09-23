#!/usr/bin/env python3
"""Offline source, skill metadata, citation and local-link checks."""
from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]

def validate():
    errors = []
    documents = {path: path.read_text(encoding='utf-8') for path in ROOT.rglob('*.md')
                 if not any(part in {'.git', '.venv', 'work', 'private'} for part in path.relative_to(ROOT).parts)}
    front = documents[ROOT/'SKILL.md'].split('---', 2)
    if len(front) < 3:
        errors.append('SKILL.md: frontmatter missing')
    else:
        metadata = yaml.safe_load(front[1])
        if metadata.get('name') != 'pcb-routing-knowledge' or not metadata.get('description'):
            errors.append('SKILL.md: invalid name or description')
    ui = yaml.safe_load((ROOT/'agents/openai.yaml').read_text(encoding='utf-8'))
    if '$pcb-routing-knowledge' not in ui['interface']['default_prompt']:
        errors.append('openai.yaml: invocation missing')
    if ui.get('policy', {}).get('allow_implicit_invocation') is not True:
        errors.append('openai.yaml: automatic selection should remain enabled')
    corpus = '\n'.join(documents.values())
    rule_ids = set(re.findall(r'^#{2,4}\s+(?:`)?([A-Z]+-\d{3})', corpus, re.M))
    schema = json.loads((ROOT/'references/source-record.schema.json').read_text(encoding='utf-8'))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    sources, seen = [], set()
    for path in sorted((ROOT/'references/sources').glob('*.json')):
        content = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(content, list):
            errors.append(f'{path.name}: expected list')
            continue
        for source in content:
            source_id = source.get('id', '<missing>')
            for error in validator.iter_errors(source):
                errors.append(f'{source_id}: {error.message}')
            if source_id in seen:
                errors.append(f'duplicate source: {source_id}')
            seen.add(source_id)
            for rule in source.get('supports', []):
                if rule not in rule_ids:
                    errors.append(f'{source_id}: missing supported rule heading {rule}')
            if source.get('access_status') in {'content_reviewed', 'partial_content_reviewed'} and not source.get('reviewed_sections'):
                errors.append(f'{source_id}: reviewed sections missing')
            sources.append(source)
    for path, body in documents.items():
        if '\ufffd' in body:
            errors.append(f'{path.name}: replacement character found')
        for link in re.findall(r'\]\(([^)]+)\)', body):
            target = link.split('#', 1)[0].strip('<>')
            if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            target_path = (path.parent/unquote(target)).resolve()
            if not target_path.is_relative_to(ROOT) or not target_path.exists():
                errors.append(f'{path.relative_to(ROOT)}: broken local link {link}')
    applicability_schema = json.loads((ROOT/'references/applicability.schema.json').read_text(encoding='utf-8'))
    applicability_validator = jsonschema.Draft202012Validator(applicability_schema)
    catalog_path = ROOT/'references/applicability-catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    for path in [catalog_path, *sorted((ROOT/'examples/applicability').glob('*.json'))]:
        data = json.loads(path.read_text(encoding='utf-8'))
        for error in applicability_validator.iter_errors(data):
            errors.append(f'{path.relative_to(ROOT)}: {error.message}')
    source_index = {source['id']: source for source in sources}
    seen_entries = set()
    for entry in catalog['entries']:
        if entry['id'] in seen_entries:
            errors.append(f'duplicate applicability entry: {entry["id"]}')
        seen_entries.add(entry['id'])
        supported = set()
        for source_id in entry['sources']:
            source = source_index.get(source_id)
            if not source or source['access_status'] not in {'content_reviewed', 'partial_content_reviewed'}:
                errors.append(f'{entry["id"]}: unread or missing source {source_id}')
            elif source:
                supported.update(source['supports'])
        for rule in entry['rule_ids']:
            if rule not in supported:
                errors.append(f'{entry["id"]}: rule {rule} has no evidence in declared sources')
    evidence_linked = {rule for source in sources for rule in source.get('supports', [])}
    return {'sources': len(sources), 'status_counts': dict(Counter(s['access_status'] for s in sources)),
            'kind_counts': dict(Counter(s['kind'] for s in sources)),
            'evidence_linked_rules': len(evidence_linked - {r for r in rule_ids if r.startswith('PUB-')}),
            'architecture_checklists': len([r for r in rule_ids if r.startswith('MLA-')]),
            'published_cases': len([r for r in rule_ids if r.startswith('PUB-')]),
            'applicability_entries': len(catalog['entries']),
            'markdown_files': len(documents), 'errors': errors}

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result['errors']))

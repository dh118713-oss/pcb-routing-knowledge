#!/usr/bin/env python3
"""Small, offline evidence tools. No EDA, network or third-party dependency."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {'content_reviewed', 'partial_content_reviewed', 'metadata_verified', 'unverified'}

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def source_records():
    records = []
    for path in sorted((ROOT / 'references' / 'sources').glob('*.json')):
        content = read_json(path)
        if not isinstance(content, list):
            raise ValueError(f'{path.name}: expected a source array')
        records.extend(content)
    ids = [record['id'] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate source ids')
    return records

def sources(args):
    records = source_records()
    if args.query:
        terms = args.query.casefold().split()
        records = [record for record in records
                   if all(term in json.dumps(record, ensure_ascii=False).casefold() for term in terms)]
    if args.status:
        records = [record for record in records if record['access_status'] == args.status]
    return {'count': len(records), 'sources': records}, 0

def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field}: non-empty string required')

def indexed_checks(document, name, allow_empty=False):
    if not isinstance(document, dict):
        raise ValueError(f'{name}: object required')
    if type(document.get('schema_version')) is not int or document.get('schema_version') != 1:
        raise ValueError(f'{name}: unsupported schema_version')
    require_text(document.get('board_revision'), f'{name}.board_revision')
    checks = document.get('checks')
    if not isinstance(checks, list) or (not allow_empty and not checks):
        raise ValueError(f'{name}.checks: non-empty array required')
    result = {}
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError(f'{name}.checks: objects required')
        require_text(check.get('id'), f'{name}.check.id')
        if check['id'] in result:
            raise ValueError(f'{name}: duplicate check id {check["id"]}')
        result[check['id']] = check
    return result

def audit(args):
    constraints, review = read_json(args.constraints), read_json(args.review)
    required = indexed_checks(constraints, 'constraints')
    results = indexed_checks(review, 'review', allow_empty=True)
    require_text(constraints.get('scope'), 'constraints.scope')
    if constraints['board_revision'] != review['board_revision']:
        raise ValueError('board revision mismatch: old review cannot validate a new board')
    revision = constraints['board_revision']
    catalog = {record['id']: record for record in source_records()}
    for check in required.values():
        for key in ('rule_id', 'target', 'acceptance_criterion', 'method'):
            require_text(check.get(key), f'{check["id"]}.{key}')
        if not isinstance(check.get('basis'), list) or not check['basis']:
            raise ValueError(f'{check["id"]}: basis required')
        for basis in check['basis']:
            if not isinstance(basis, dict):
                raise ValueError('basis must be an object')
            for key in ('id', 'locator'):
                require_text(basis.get(key), f'basis.{key}')
            if basis.get('kind') == 'source':
                record = catalog.get(basis['id'])
                if not record or record['access_status'] not in {'content_reviewed', 'partial_content_reviewed'}:
                    raise ValueError(f'{basis["id"]}: unread source cannot support an acceptance criterion')
                if check['rule_id'] not in record.get('supports', []):
                    raise ValueError(f'{basis["id"]}: source has not been mapped to rule {check["rule_id"]}')
            elif basis.get('kind') != 'project_requirement':
                raise ValueError('basis.kind must be source or project_requirement')
    extra = sorted(set(results) - set(required))
    if extra:
        raise ValueError(f'undeclared checks: {extra}')
    missing, failed, unknown, not_applicable = sorted(set(required)-set(results)), [], [], []
    for check_id, result in results.items():
        status = result.get('status')
        if status not in {'pass', 'fail', 'unknown', 'not_applicable'}:
            raise ValueError(f'{check_id}: invalid status')
        require_text(result.get('rationale'), f'{check_id}.rationale')
        evidence = result.get('evidence', [])
        if not isinstance(evidence, list):
            raise ValueError(f'{check_id}.evidence: array required')
        if status in {'pass', 'not_applicable'} and not evidence:
            raise ValueError(f'{check_id}: evidence required for {status}')
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError('evidence must be an object')
            for key in ('artifact', 'locator', 'board_revision'):
                require_text(item.get(key), f'evidence.{key}')
            if item['board_revision'] != revision:
                raise ValueError(f'{check_id}: stale evidence')
        if status == 'fail':
            failed.append(check_id)
        elif status == 'unknown':
            unknown.append(check_id)
        elif status == 'not_applicable':
            not_applicable.append(check_id)
    overall = ('needs_changes' if failed else 'incomplete' if missing or unknown
               else 'evidence_complete_for_declared_checks')
    return {'overall': overall, 'board_revision': revision, 'scope': constraints['scope'],
            'required_check_count': len(required), 'missing_checks': missing,
            'failed_checks': failed, 'unknown_checks': unknown,
            'not_applicable_checks': not_applicable,
            'limitations': ['Checks declaration coverage and evidence references, not their truth or file contents.',
                            'Does not prove that the declared check set covers all circuit risks.',
                            'Not a physical DRC, simulator, certification or manufacturing release.']}, 0 if overall == 'evidence_complete_for_declared_checks' else 1

def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite number greater than zero')
    return number

def dc_budget(args):
    length_m = args.length_mm / 1000
    thickness_m = args.copper_um / 1_000_000
    drop_v = args.drop_mv / 1000
    minimum_width_m = args.rho_ohm_m * length_m * args.current_a / (thickness_m * drop_v)
    if not math.isfinite(minimum_width_m) or minimum_width_m <= 0:
        raise ValueError('derived width is non-finite or underflowed; use realistic SI inputs')
    result = {
        'assessment': 'dc_drop_only',
        'minimum_width_mm_from_dc_drop': minimum_width_m * 1000,
        'thermal_current_rating_a': None,
        'inputs': {k: v for k, v in vars(args).items() if k != 'func'},
        'assumptions': ['Uniform rectangular conductor at the temperature represented by supplied resistivity.',
                        'Length covers only the conductor being calculated; include return path separately.',
                        'No vias, pads, neck-downs, contacts, skin/proximity effects or self-heating model.'],
        'next_checks': ['thermal model or applicable measured data', 'bottlenecks and return path',
                        'fabrication tolerances and finished copper thickness']
    }
    if args.width_mm is not None:
        resistance = args.rho_ohm_m * length_m / (thickness_m * args.width_mm / 1000)
        if not math.isfinite(resistance) or resistance <= 0:
            raise ValueError('derived resistance is non-finite or underflowed; use realistic SI inputs')
        result['at_requested_width'] = {
            'resistance_ohm': resistance,
            'voltage_drop_mv': args.current_a * resistance * 1000,
            'power_loss_w': args.current_a ** 2 * resistance,
            'meets_dc_drop_budget': args.current_a * resistance <= drop_v
        }
    return result, 0

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    dc = commands.add_parser('dc-budget', help='DC drop lower bound; NOT an ampacity calculator')
    for flag in ('current-a', 'length-mm', 'copper-um', 'drop-mv', 'rho-ohm-m'):
        dc.add_argument('--' + flag, type=positive, required=True)
    dc.add_argument('--width-mm', type=positive)
    dc.set_defaults(func=dc_budget)
    search = commands.add_parser('sources', help='Search curated local source records')
    search.add_argument('--query')
    search.add_argument('--status', choices=sorted(STATUSES))
    search.set_defaults(func=sources)
    review = commands.add_parser('audit', help='Check declared evidence coverage and board revisions')
    review.add_argument('--constraints', required=True)
    review.add_argument('--review', required=True)
    review.set_defaults(func=audit)
    args = parser.parse_args()
    try:
        result, code = args.func(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return code
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())

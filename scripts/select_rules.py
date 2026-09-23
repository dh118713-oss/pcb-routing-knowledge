#!/usr/bin/env python3
"""Select conditional PCB rules without assigning routing values.

The selector is deliberately EDA- and network-independent. It only evaluates
the conditions declared in a local applicability catalog and reports whether a
rule is a candidate, needs more profiled facts, or is excluded by a known
mismatch. It does not prove engineering applicability.
"""
import argparse
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
SCOPE_LEVELS = {'general_physics', 'structural', 'device_family',
                'device_specific', 'process_specific'}
OPERATORS = {'eq', 'in', 'contains_any', 'range_within'}
RANGE_UNIT = 'Hz'


def _reject_constant(value):
    raise ValueError(f'non-finite JSON number is not allowed: {value}')


def _parse_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'non-finite JSON number is not allowed: {value}')
    return number


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                          parse_constant=_reject_constant, parse_float=_parse_float)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path}: invalid JSON: {exc.msg}') from exc


def require_object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f'{name}: object required')


def require_nonempty_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name}: non-empty string required')
    return value


def require_version(value, name):
    if type(value) is not int or value != SCHEMA_VERSION:
        raise ValueError(f'{name}: unsupported schema_version')


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name}: finite number required')
    try:
        finite = math.isfinite(float(value))
    except OverflowError as exc:
        raise ValueError(f'{name}: number exceeds supported finite range') from exc
    if not finite:
        raise ValueError(f'{name}: finite number required')
    return value


def validate_range(value, name):
    require_object(value, name)
    if set(value) != {'min', 'max', 'unit'}:
        raise ValueError(f'{name}: range requires only min, max and unit')
    minimum = finite_number(value['min'], f'{name}.min')
    maximum = finite_number(value['max'], f'{name}.max')
    if value['unit'] != RANGE_UNIT:
        raise ValueError(f'{name}.unit: expected {RANGE_UNIT}')
    if minimum < 0 or maximum < minimum:
        raise ValueError(f'{name}: require 0 <= min <= max')
    return {'min': minimum, 'max': maximum, 'unit': RANGE_UNIT}


def validate_scalar_or_array(value, name, *, allow_range=True):
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f'{name}: finite number required')
        if isinstance(value, int) and not isinstance(value, bool):
            finite_number(value, name)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)) or item is None:
                raise ValueError(f'{name}[{index}]: scalar array item required')
            validate_scalar_or_array(item, f'{name}[{index}]', allow_range=False)
        return
    if allow_range and isinstance(value, dict):
        validate_range(value, name)
        return
    raise ValueError(f'{name}: scalar, scalar array, null, or Hz range required')


def validate_fact(name, fact):
    require_object(fact, f'facts.{name}')
    if 'value' not in fact:
        raise ValueError(f'facts.{name}.value: required')
    validate_scalar_or_array(fact['value'], f'facts.{name}.value')
    if 'provenance' in fact and fact['provenance'] is not None:
        require_object(fact['provenance'], f'facts.{name}.provenance')
        for part in ('artifact', 'locator'):
            value = fact['provenance'].get(part)
            if value is not None and not isinstance(value, str):
                raise ValueError(f'facts.{name}.provenance.{part}: string or null required')


def validate_profile(profile):
    require_object(profile, 'profile')
    require_version(profile.get('schema_version'), 'profile.schema_version')
    require_nonempty_string(profile.get('target_id'), 'profile.target_id')
    facts = profile.get('facts')
    require_object(facts, 'profile.facts')
    for name, fact in facts.items():
        require_nonempty_string(name, 'profile.facts key')
        validate_fact(name, fact)
    return profile


def validate_condition(condition, name):
    require_object(condition, name)
    field = require_nonempty_string(condition.get('field'), f'{name}.field')
    operator = condition.get('op')
    if operator not in OPERATORS:
        raise ValueError(f'{name}.op: unsupported operator')
    if 'value' not in condition:
        raise ValueError(f'{name}.value: required')
    expected = condition['value']
    if operator == 'range_within':
        expected = validate_range(expected, f'{name}.value')
    elif operator in {'in', 'contains_any'}:
        if not isinstance(expected, list) or not expected:
            raise ValueError(f'{name}.value: non-empty array required for {operator}')
        for index, item in enumerate(expected):
            if isinstance(item, (dict, list)) or item is None:
                raise ValueError(f'{name}.value[{index}]: scalar required')
            validate_scalar_or_array(item, f'{name}.value[{index}]', allow_range=False)
    else:
        validate_scalar_or_array(expected, f'{name}.value')
    return field, operator, expected


def validate_catalog(catalog):
    require_object(catalog, 'catalog')
    require_version(catalog.get('schema_version'), 'catalog.schema_version')
    entries = catalog.get('entries')
    if not isinstance(entries, list):
        raise ValueError('catalog.entries: array required')
    seen = set()
    normalized = []
    for index, entry in enumerate(entries):
        name = f'catalog.entries[{index}]'
        require_object(entry, name)
        identifier = require_nonempty_string(entry.get('id'), f'{name}.id')
        if identifier in seen:
            raise ValueError(f'{identifier}: duplicate catalog entry id')
        seen.add(identifier)
        rule_ids = entry.get('rule_ids')
        if not isinstance(rule_ids, list) or not rule_ids or any(
                not isinstance(rule, str) or not rule.strip() for rule in rule_ids):
            raise ValueError(f'{name}.rule_ids: non-empty string array required')
        scope_level = entry.get('scope_level')
        if scope_level not in SCOPE_LEVELS:
            raise ValueError(f'{name}.scope_level: unsupported scope level')
        conditions = entry.get('conditions')
        if not isinstance(conditions, list):
            raise ValueError(f'{name}.conditions: array required')
        parsed_conditions = [validate_condition(condition, f'{name}.conditions[{i}]')
                             for i, condition in enumerate(conditions)]
        required_facts = entry.get('required_facts')
        if not isinstance(required_facts, list) or any(
                not isinstance(fact, str) or not fact.strip() for fact in required_facts):
            raise ValueError(f'{name}.required_facts: string array required')
        if len(required_facts) != len(set(required_facts)):
            raise ValueError(f'{name}.required_facts: duplicate fact')
        sources = entry.get('sources')
        if not isinstance(sources, list) or any(
                not isinstance(source, str) or not source.strip() for source in sources):
            raise ValueError(f'{name}.sources: string array required')
        explanation = require_nonempty_string(entry.get('explanation'), f'{name}.explanation')
        normalized.append({'id': identifier, 'rule_ids': rule_ids,
                           'scope_level': scope_level, 'conditions': parsed_conditions,
                           'required_facts': required_facts, 'sources': sources,
                           'explanation': explanation})
    return normalized


def fact_state(facts, field):
    fact = facts.get(field)
    if fact is None or 'value' not in fact:
        return 'missing', None
    value = fact['value']
    if value is None or value == []:
        return 'unknown', value
    provenance = fact.get('provenance')
    if not isinstance(provenance, dict) or not isinstance(provenance.get('artifact'), str) \
            or not provenance['artifact'].strip() or not isinstance(provenance.get('locator'), str) \
            or not provenance['locator'].strip():
        return 'unproven', value
    return 'known', value


def display(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def json_equal(actual, expected):
    """Keep JSON booleans distinct from numbers, including inside scalar arrays."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            json_equal(a, b) for a, b in zip(actual, expected))
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            json_equal(actual[key], expected[key]) for key in actual)
    return actual == expected


def evaluate_condition(field, operator, expected, actual):
    if operator == 'eq':
        return json_equal(actual, expected)
    if operator == 'in':
        return not isinstance(actual, (list, dict)) and any(
            json_equal(actual, value) for value in expected)
    if operator == 'contains_any':
        return isinstance(actual, list) and any(
            json_equal(item, value) for item in actual for value in expected)
    return (isinstance(actual, dict) and actual.get('unit') == RANGE_UNIT
            and actual['min'] >= expected['min'] and actual['max'] <= expected['max'])


def select_entry(entry, facts):
    missing = set()
    matched = set()
    mismatch_reasons = []
    input_reasons = []
    for field, operator, expected in entry['conditions']:
        state, actual = fact_state(facts, field)
        if state == 'missing':
            missing.add(field)
            input_reasons.append(f'missing fact: {field}')
        elif state == 'unknown':
            missing.add(field)
            input_reasons.append(f'unknown fact: {field}')
        elif state == 'unproven':
            missing.add(field)
            input_reasons.append(f'fact lacks provenance: {field}')
        elif evaluate_condition(field, operator, expected, actual):
            matched.add(field)
        else:
            mismatch_reasons.append(
                f'{field} {operator} mismatch (actual={display(actual)}, expected={display(expected)})')
    for field in entry['required_facts']:
        state, actual = fact_state(facts, field)
        if state != 'known':
            missing.add(field)
            input_reasons.append(f'{state} required fact: {field}')
        else:
            matched.add(field)
    if mismatch_reasons:
        status, reasons = 'excluded', mismatch_reasons
    elif input_reasons:
        status, reasons = 'needs_input', input_reasons
    else:
        status, reasons = 'candidate', ['all declared conditions and required facts match']
    return {'id': entry['id'], 'status': status, 'reasons': reasons,
            'missing_facts': sorted(missing), 'matched_facts': sorted(matched)}


def run(args):
    profile = validate_profile(read_json(args.profile))
    catalog = validate_catalog(read_json(args.catalog))
    entries = [select_entry(entry, profile['facts']) for entry in catalog]
    return {'schema_version': SCHEMA_VERSION, 'target_id': profile['target_id'],
            'entries': entries,
            'limitations': [
                'Candidate status only means the declared catalog conditions and fact provenance matched.',
                'This tool does not select routing values or prove device, package, stackup, manufacturing, SI, PI, EMC, thermal or compliance applicability.',
                'A caller must perform engineering review with the exact device manual, layout, stackup and validation evidence.'
            ]}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--catalog', default=str(ROOT / 'references' / 'applicability-catalog.json'))
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Public CLI behavior for independent, evidence-tagged target profiles."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/select_rules.py'


def fact(value):
    return {'value': value, 'provenance': {'artifact': '目标器件手册.pdf', 'locator': 'p.2'}}


def band(low, high):
    return {'min': low, 'max': high, 'unit': 'Hz'}


def entry(identifier, conditions=None, required=None):
    return {'id': identifier, 'rule_ids': ['RF-001'], 'scope_level': 'structural',
            'conditions': conditions or [], 'required_facts': required or [],
            'sources': ['TEST-SOURCE'], 'explanation': 'Synthetic selection fixture only.'}


class ApplicabilityTests(unittest.TestCase):
    def run_documents(self, profile, catalog):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            p, c = path/'目标.json', path/'候选.json'
            p.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8-sig')
            c.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
            run = subprocess.run([sys.executable, str(CLI), '--profile', str(p), '--catalog', str(c)],
                                 capture_output=True, text=True, encoding='utf-8')
        return run

    def run_selector(self, facts, entries, target='radio-24', **profile_fields):
        profile = {'schema_version': 1, 'target_id': target, 'facts': facts, **profile_fields}
        return self.run_documents(profile, {'schema_version': 1, 'entries': entries})

    def invalid(self, run):
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertEqual(run.stdout, '')
        self.assertTrue(json.loads(run.stderr)['error'])
        self.assertNotIn('Traceback', run.stderr)

    def selected(self, run):
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        return data, {row['id']: row for row in data['entries']}

    def test_frequency_domains_are_evaluated_separately(self):
        entries = [entry('2G4', [{'field': 'frequency', 'op': 'range_within',
                                  'value': band(2400000000, 2500000000)}]),
                   entry('SUB1', [{'field': 'frequency', 'op': 'range_within',
                                   'value': band(100000000, 1000000000)}])]
        data, rows = self.selected(self.run_selector({'frequency': fact(band(2402000000, 2480000000))}, entries))
        self.assertEqual(rows['2G4']['status'], 'candidate')
        self.assertEqual(rows['SUB1']['status'], 'excluded')
        self.assertEqual(data['target_id'], 'radio-24')
        self.assertTrue(data['limitations'])

    def test_missing_protocol_does_not_infer_from_target_id(self):
        row = entry('radio', [{'field': 'protocol', 'op': 'in', 'value': ['BLE']}])
        data, rows = self.selected(self.run_selector({}, [row], target='BLE-2G4-radio'))
        self.assertEqual(rows['radio']['status'], 'needs_input')
        self.assertEqual(rows['radio']['missing_facts'], ['protocol'])

    def test_null_and_empty_array_are_unknown(self):
        row = entry('radio', [{'field': 'protocol', 'op': 'contains_any', 'value': ['BLE']}])
        for value in (None, []):
            with self.subTest(value=value):
                _, rows = self.selected(self.run_selector({'protocol': fact(value)}, [row]))
                self.assertEqual(rows['radio']['status'], 'needs_input')

    def test_missing_or_incomplete_provenance_needs_input(self):
        row = entry('radio', [{'field': 'protocol', 'op': 'eq', 'value': 'BLE'}])
        for provenance in (None, {}, {'artifact': 'manual.pdf'}, {'locator': 'p.1'},
                           {'artifact': '', 'locator': 'p.1'}):
            with self.subTest(provenance=provenance):
                _, rows = self.selected(self.run_selector(
                    {'protocol': {'value': 'BLE', 'provenance': provenance}}, [row]))
                self.assertEqual(rows['radio']['status'], 'needs_input')
        _, rows = self.selected(self.run_selector({'protocol': {'value': 'BLE'}}, [row]))
        self.assertEqual(rows['radio']['status'], 'needs_input')

    def test_known_mismatch_has_priority_over_missing_and_unproven_facts(self):
        row = entry('radio', [
            {'field': 'protocol', 'op': 'eq', 'value': 'BLE'},
            {'field': 'frequency', 'op': 'range_within', 'value': band(2400000000, 2500000000)}
        ], required=['package'])
        _, rows = self.selected(self.run_selector({
            'frequency': fact(band(863000000, 870000000)),
            'package': {'value': 'QFN'}
        }, [row]))
        self.assertEqual(rows['radio']['status'], 'excluded')
        self.assertEqual(rows['radio']['missing_facts'], ['package', 'protocol'])

    def test_general_physics_does_not_require_a_frequency_condition(self):
        row = entry('return-path', [{'field': 'signal', 'op': 'eq', 'value': 'digital'}])
        row['scope_level'] = 'general_physics'
        _, rows = self.selected(self.run_selector({'signal': fact('digital')}, [row]))
        self.assertEqual(rows['return-path']['status'], 'candidate')

    def test_each_target_has_independent_facts(self):
        row = entry('radio', [{'field': 'protocol', 'op': 'in', 'value': ['BLE']}])
        first, a = self.selected(self.run_selector({'protocol': fact('BLE')}, [row], target='A'))
        second, b = self.selected(self.run_selector({}, [row], target='B'))
        third, c = self.selected(self.run_selector({'protocol': fact('BLE')}, [row], target='C'))
        self.assertEqual([first['target_id'], second['target_id'], third['target_id']], ['A', 'B', 'C'])
        self.assertEqual([a['radio']['status'], b['radio']['status'], c['radio']['status']],
                         ['candidate', 'needs_input', 'candidate'])

    def test_required_fact_must_exist_with_provenance(self):
        row = entry('device', required=['package'])
        for facts in ({}, {'package': {'value': 'QFN'}}, {'package': fact(None)}):
            with self.subTest(facts=facts):
                _, rows = self.selected(self.run_selector(facts, [row]))
                self.assertEqual(rows['device']['status'], 'needs_input')
                self.assertEqual(rows['device']['missing_facts'], ['package'])
        _, rows = self.selected(self.run_selector({'package': fact('QFN')}, [row]))
        self.assertEqual(rows['device']['status'], 'candidate')

    def test_supported_operators_and_json_boolean_identity(self):
        cases = [
            ('eq', 'BLE', 'BLE', 'candidate'),
            ('in', ['BLE', '802.15.4'], 'BLE', 'candidate'),
            ('contains_any', ['BLE', '802.15.4'], ['BLE', 'Wi-Fi'], 'candidate'),
            ('contains_any', ['BLE'], ['Wi-Fi'], 'excluded'),
            ('eq', 1, True, 'excluded'),
            ('in', [1], True, 'excluded'),
            ('contains_any', [1], [True], 'excluded'),
            ('eq', 1, 1.0, 'candidate'),
        ]
        for op, expected, actual, status in cases:
            with self.subTest(op=op, expected=expected, actual=actual):
                row = entry('rule', [{'field': 'value', 'op': op, 'value': expected}])
                _, rows = self.selected(self.run_selector({'value': fact(actual)}, [row]))
                self.assertEqual(rows['rule']['status'], status)

    def test_invalid_schema_versions_are_json_errors(self):
        for version in (True, False, 0, 2, 1.0, '1', None):
            with self.subTest(version=version):
                self.invalid(self.run_selector({}, [], schema_version=version))
                self.invalid(self.run_documents(
                    {'schema_version': 1, 'target_id': 'A', 'facts': {}},
                    {'schema_version': version, 'entries': []}))

    def test_invalid_operators_are_json_errors(self):
        for operator in ('gt', '', None, [], {}):
            with self.subTest(operator=operator):
                row = entry('rule', [{'field': 'x', 'op': operator, 'value': 1}])
                self.invalid(self.run_selector({'x': fact(1)}, [row]))

    def test_invalid_frequency_ranges_are_json_errors(self):
        for value in ({'min': 2400, 'max': 2480, 'unit': 'MHz'}, band(2, 1),
                      band(-1, 1), band(True, 1), band('1', 2),
                      {'min': 1, 'unit': 'Hz'}, band(1, 10 ** 400)):
            with self.subTest(value=value):
                row = entry('rule', [{'field': 'frequency', 'op': 'range_within', 'value': value}])
                self.invalid(self.run_selector({}, [row]))
                self.invalid(self.run_selector({'frequency': fact(value)}, []))

    def test_nonfinite_numbers_are_json_errors(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                self.invalid(self.run_selector({'x': fact(value)}, []))
                row = entry('rule', [{'field': 'x', 'op': 'eq', 'value': value}])
                self.invalid(self.run_selector({}, [row]))


if __name__ == '__main__':
    unittest.main()

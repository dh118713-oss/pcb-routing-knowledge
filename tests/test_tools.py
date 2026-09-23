"""Behavior tests through the public command line (standard library only)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'pcb_knowledge.py'

class ToolTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True,
                              text=True, encoding='utf-8')

    def test_dc_budget_is_only_a_voltage_drop_lower_bound(self):
        run = self.run_cli('dc-budget', '--current-a', '2', '--length-mm', '100',
                           '--copper-um', '35', '--drop-mv', '100',
                           '--rho-ohm-m', '1.724e-8', '--width-mm', '1')
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertAlmostEqual(data['minimum_width_mm_from_dc_drop'], 0.9851428571)
        self.assertAlmostEqual(data['at_requested_width']['voltage_drop_mv'], 98.51428571)
        self.assertIsNone(data['thermal_current_rating_a'])
        self.assertEqual(data['assessment'], 'dc_drop_only')

    def test_audit_does_not_pass_an_omitted_required_check(self):
        constraints = {'schema_version': 1, 'board_revision': 'rev-a',
                       'scope': 'Synthetic example: one power check', 'checks': [
            {'id': 'power-width', 'rule_id': 'PROJECT-001', 'target': 'VCC',
             'acceptance_criterion': 'Width satisfies the project constraint.',
             'method': 'geometry', 'basis': [{'kind': 'project_requirement',
                 'id': 'REQ-1', 'locator': 'requirements.md#power'}]}]}
        review = {'schema_version': 1, 'board_revision': 'rev-a', 'checks': []}
        with tempfile.TemporaryDirectory() as directory:
            c, r = Path(directory)/'constraints.json', Path(directory)/'review.json'
            c.write_text(json.dumps(constraints), encoding='utf-8')
            r.write_text(json.dumps(review), encoding='utf-8')
            run = self.run_cli('audit', '--constraints', str(c), '--review', str(r))
        self.assertEqual(run.returncode, 1, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result['overall'], 'incomplete')
        self.assertEqual(result['missing_checks'], ['power-width'])

    def audit_documents(self, constraints, review):
        with tempfile.TemporaryDirectory() as directory:
            c, r = Path(directory)/'c.json', Path(directory)/'r.json'
            c.write_text(json.dumps(constraints), encoding='utf-8')
            r.write_text(json.dumps(review), encoding='utf-8')
            return self.run_cli('audit', '--constraints', str(c), '--review', str(r))

    def example_documents(self):
        return (json.loads((ROOT/'examples/constraints.json').read_text(encoding='utf-8')),
                json.loads((ROOT/'examples/review.incomplete.json').read_text(encoding='utf-8')))

    def test_failed_and_unknown_checks_are_reported_separately(self):
        c, r = self.example_documents()
        run = self.audit_documents(c, r)
        self.assertEqual(run.returncode, 1, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(data['overall'], 'needs_changes')
        self.assertEqual(data['failed_checks'], ['vcc-width'])
        self.assertEqual(data['unknown_checks'], ['return-path'])

    def test_claimed_pass_requires_current_evidence(self):
        for evidence in [[], [{'artifact': 'demo', 'locator': 'row 1', 'board_revision': 'old'}]]:
            with self.subTest(evidence=evidence):
                c, r = self.example_documents()
                r['checks'][0].update(status='pass', evidence=evidence)
                run = self.audit_documents(c, r)
                self.assertEqual(run.returncode, 2, run.stdout)

    def test_revision_mismatch_and_duplicate_checks_are_invalid(self):
        for error in ('revision', 'duplicate'):
            with self.subTest(error=error):
                c, r = self.example_documents()
                if error == 'revision':
                    r['board_revision'] = 'old'
                else:
                    r['checks'].append(r['checks'][0])
                self.assertEqual(self.audit_documents(c, r).returncode, 2)

    def test_complete_evidence_is_not_named_engineering_approval(self):
        c, r = self.example_documents()
        for check in r['checks']:
            check.update(status='pass', rationale='Synthetic unit test evidence only.', evidence=[{
                'artifact': 'synthetic.txt', 'locator': 'test fixture',
                'board_revision': r['board_revision']}])
        run = self.audit_documents(c, r)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['overall'], 'evidence_complete_for_declared_checks')

    def test_unknown_source_cannot_support_a_confirmed_criterion(self):
        c, r = self.example_documents()
        c['checks'][0]['basis'] = [{'kind': 'source', 'id': 'NONEXISTENT', 'locator': 'p.1'}]
        self.assertEqual(self.audit_documents(c, r).returncode, 2)

    def test_reviewed_source_must_support_the_selected_rule(self):
        c, r = self.example_documents()
        c['checks'][0]['basis'] = [{'kind': 'source', 'id': 'OSS-KICAD', 'locator': 'Run'}]
        self.assertEqual(self.audit_documents(c, r).returncode, 2)

    def test_nonpositive_and_nonfinite_calculation_inputs_are_rejected(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value):
                run = self.run_cli('dc-budget', '--current-a', value, '--length-mm', '100',
                                  '--copper-um', '35', '--drop-mv', '100', '--rho-ohm-m', '1.724e-8')
                self.assertEqual(run.returncode, 2)

    def test_unrealistic_finite_inputs_are_rejected_after_derivation(self):
        for current, length, copper in [('1', '1e-320', '35'), ('1', '100', '1e-320'), ('1e308', '100', '35')]:
            with self.subTest(current=current, length=length, copper=copper):
                run = self.run_cli('dc-budget', '--current-a', current, '--length-mm', length,
                                   '--copper-um', copper, '--drop-mv', '100',
                                   '--rho-ohm-m', '1.724e-8', '--width-mm', '1')
                self.assertEqual(run.returncode, 2)
                self.assertIn('error', json.loads(run.stderr))

    def test_boolean_schema_version_is_not_integer_version_one(self):
        c, r = self.example_documents()
        c['schema_version'] = True
        self.assertEqual(self.audit_documents(c, r).returncode, 2)

    def test_double_length_requires_double_width_for_the_same_drop(self):
        values = []
        for length in ('100', '200'):
            run = self.run_cli('dc-budget', '--current-a', '2', '--length-mm', length,
                              '--copper-um', '35', '--drop-mv', '100', '--rho-ohm-m', '1.724e-8')
            values.append(json.loads(run.stdout)['minimum_width_mm_from_dc_drop'])
        self.assertAlmostEqual(values[1], 2 * values[0])

if __name__ == '__main__':
    unittest.main()

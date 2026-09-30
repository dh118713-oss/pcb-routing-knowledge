"""Shape validation tests for the documented constraints/review contract."""
import copy
import json
from pathlib import Path
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


class IntegrationSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.constraints_schema = load_json(ROOT / 'references/constraints.schema.json')
        cls.review_schema = load_json(ROOT / 'references/review.schema.json')
        cls.constraints_validator = jsonschema.Draft202012Validator(cls.constraints_schema)
        cls.review_validator = jsonschema.Draft202012Validator(cls.review_schema)

    def test_schemas_are_valid_draft_2020_12_documents(self):
        jsonschema.Draft202012Validator.check_schema(self.constraints_schema)
        jsonschema.Draft202012Validator.check_schema(self.review_schema)

    def test_existing_audit_examples_match_the_contract(self):
        constraints = load_json(ROOT / 'examples/constraints.json')
        review = load_json(ROOT / 'examples/review.incomplete.json')
        self.constraints_validator.validate(constraints)
        self.review_validator.validate(review)

    def test_documented_extension_fields_remain_accepted(self):
        constraints = load_json(ROOT / 'examples/constraints.json')
        constraints['checks'][0].update({
            'parameters': {'width': {'value': 0.5, 'unit': 'mm'}},
            'severity': 'high',
            'expected_action': 'inspect geometry',
            'dependencies': ['stackup'],
            'rule_category': 'power',
        })
        self.constraints_validator.validate(constraints)

        review = load_json(ROOT / 'examples/review.incomplete.json')
        review['checks'][0]['evidence'][0]['sha256'] = 'a' * 64
        self.review_validator.validate(review)

    def test_required_constraint_basis_and_valid_method_are_enforced(self):
        constraints = load_json(ROOT / 'examples/constraints.json')
        del constraints['checks'][0]['basis']
        self.assertTrue(list(self.constraints_validator.iter_errors(constraints)))

        constraints = load_json(ROOT / 'examples/constraints.json')
        constraints['checks'][0]['method'] = 'guess'
        self.assertTrue(list(self.constraints_validator.iter_errors(constraints)))

    def test_constraint_package_binds_schematic_constraints_and_complexity_evidence(self):
        constraints = load_json(ROOT / 'examples/constraints.json')
        self.constraints_validator.validate(constraints)
        self.assertEqual(constraints['design_complexity']['level'], 'beginner_simple')
        self.assertTrue(constraints['schematic_revision'])
        self.assertTrue(constraints['constraints_revision'])

        for field in ('schematic_revision', 'constraints_revision', 'design_complexity'):
            with self.subTest(missing=field):
                invalid = copy.deepcopy(constraints)
                del invalid[field]
                self.assertTrue(list(self.constraints_validator.iter_errors(invalid)))

    def test_complexity_requires_a_supported_level_and_traceable_evidence(self):
        for update in (
            {'level': 'automatic_complete'},
            {'evidence': []},
            {'evidence': [{'kind': 'schematic', 'id': 'intent'}]},
        ):
            with self.subTest(update=update):
                constraints = load_json(ROOT / 'examples/constraints.json')
                constraints['design_complexity'].update(update)
                self.assertTrue(list(self.constraints_validator.iter_errors(constraints)))

    def test_pass_and_not_applicable_need_evidence(self):
        for status in ('pass', 'not_applicable'):
            with self.subTest(status=status):
                review = load_json(ROOT / 'examples/review.incomplete.json')
                review['checks'][0]['status'] = status
                review['checks'][0]['evidence'] = []
                self.assertTrue(list(self.review_validator.iter_errors(review)))

    def test_unknown_or_fail_can_omit_evidence_as_audit_treats_it_as_empty(self):
        for status in ('unknown', 'fail'):
            with self.subTest(status=status):
                review = load_json(ROOT / 'examples/review.incomplete.json')
                review['checks'][0] = {
                    'id': 'check-a', 'status': status, 'rationale': 'Evidence is unavailable.'
                }
                self.review_validator.validate(review)

    def test_boolean_schema_version_is_rejected(self):
        for schema, validator, path in (
            (self.constraints_schema, self.constraints_validator, ROOT / 'examples/constraints.json'),
            (self.review_schema, self.review_validator, ROOT / 'examples/review.incomplete.json'),
        ):
            with self.subTest(title=schema['title']):
                document = copy.deepcopy(load_json(path))
                document['schema_version'] = True
                self.assertTrue(list(validator.iter_errors(document)))


if __name__ == '__main__':
    unittest.main()

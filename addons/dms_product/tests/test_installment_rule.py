from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestDmsInstallmentRule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['dms.brand'].create({'name': '產品測試品牌 C'})
        cls.product = cls.env['dms.product'].create({
            'brand_id': cls.brand.id,
            'name': 'FNX',
            'model': 'FNX001',
            'year': '2026',
            'color': '黑',
            'energy_type': 'oil',
        })
        cls.version = cls.env['dms.price.version'].create({
            'name': '2026-07',
            'effective_date': date(2026, 7, 1),
            'state': 'effective',
        })
        cls.env['dms.price.line'].create({
            'version_id': cls.version.id,
            'product_id': cls.product.id,
            'cash_price': 78000,
            'list_price': 82000,
        })
        cls.fee_opening = cls.env['dms.fee.type'].search([('code', '=', 'opening_fee')], limit=1)
        cls.fee_setup = cls.env['dms.fee.type'].search([('code', '=', 'setup_fee')], limit=1)

    def test_01_rule_line_overlap_validation(self):
        rule = self.env['dms.installment.rule'].create({'name': '分期規則 A'})
        self.env['dms.installment.rule.line'].create({
            'rule_id': rule.id,
            'period_from': 12,
            'period_to': 24,
            'price_basis': 'cash',
        })
        with self.assertRaises(ValidationError):
            self.env['dms.installment.rule.line'].create({
                'rule_id': rule.id,
                'period_from': 18,
                'period_to': 36,
                'price_basis': 'list',
            })

    def test_02_binding_returns_effective_rule(self):
        rule = self.env['dms.installment.rule'].create({
            'name': '分期規則 B',
            'line_ids': [(0, 0, {
                'period_from': 12,
                'period_to': 24,
                'price_basis': 'cash',
                'fee_ids': [
                    (0, 0, {
                        'fee_type_id': self.fee_opening.id,
                        'amount': 1200,
                        'charge_mode': 'extra',
                    }),
                    (0, 0, {
                        'fee_type_id': self.fee_setup.id,
                        'amount': 800,
                        'charge_mode': 'company_absorb',
                    }),
                ],
            })],
        })
        binding = self.env['dms.installment.rule.binding'].create({
            'product_id': self.product.id,
            'price_version_id': self.version.id,
            'rule_id': rule.id,
            'active': True,
        })

        effective_binding = self.env['dms.installment.rule.binding'].get_effective_binding(
            self.product, query_date=date(2026, 7, 20))

        self.assertEqual(effective_binding, binding)
        self.assertEqual(len(rule.line_ids), 1)
        self.assertEqual(len(rule.line_ids.fee_ids), 2)

    def test_03_same_product_can_bind_different_rules_by_version(self):
        version_2 = self.env['dms.price.version'].create({
            'name': '2026-08',
            'effective_date': date(2026, 8, 1),
            'state': 'effective',
        })
        self.env['dms.price.line'].create({
            'version_id': version_2.id,
            'product_id': self.product.id,
            'cash_price': 80000,
            'list_price': 84000,
        })
        rule_1 = self.env['dms.installment.rule'].create({'name': '分期規則 C1'})
        rule_2 = self.env['dms.installment.rule'].create({'name': '分期規則 C2'})
        binding_1 = self.env['dms.installment.rule.binding'].create({
            'product_id': self.product.id,
            'price_version_id': self.version.id,
            'rule_id': rule_1.id,
            'active': True,
        })
        binding_2 = self.env['dms.installment.rule.binding'].create({
            'product_id': self.product.id,
            'price_version_id': version_2.id,
            'rule_id': rule_2.id,
            'active': True,
        })

        self.assertEqual(
            self.env['dms.installment.rule.binding'].get_effective_binding(
                self.product, query_date=date(2026, 7, 20)),
            binding_1,
        )
        self.assertEqual(
            self.env['dms.installment.rule.binding'].get_effective_binding(
                self.product, query_date=date(2026, 8, 20)),
            binding_2,
        )

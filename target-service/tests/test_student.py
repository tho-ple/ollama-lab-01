"""Additional customer behavior regressions (acceptance tests are unchanged)."""

import unittest
from decimal import Decimal as D

from orders.pricing import quote


class StudentPricingRegression(unittest.TestCase):
    def test_round_line_after_multiplying_quantity(self):
        """One line rounds after multiplication, not once per individual item."""
        result = quote([{'unit_price': D('0.335'), 'quantity': 3}])
        self.assertEqual(result['subtotal'], D('1.01'))
        self.assertEqual(result['shipping'], D('5.00'))
        self.assertEqual(result['total'], D('6.01'))

    def test_round_up_to_exact_free_shipping_threshold(self):
        """The half-cent line boundary must qualify for free shipping."""
        result = quote([{'unit_price': D('99.995'), 'quantity': 1}])
        self.assertEqual(result['subtotal'], D('100.00'))
        self.assertEqual(result['shipping'], D('0.00'))
        self.assertEqual(result['total'], D('100.00'))


if __name__ == '__main__':
    unittest.main()

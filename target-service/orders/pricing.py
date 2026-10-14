"""Customer order pricing using line-level and discount-level half-up rounding."""

from decimal import Decimal, ROUND_HALF_UP

from .validation import validate_order


CENT = Decimal('0.01')
FREE_SHIPPING_THRESHOLD = Decimal('100.00')
SHIPPING_CHARGE = Decimal('5.00')


def quote(lines, discount=Decimal('0')):
    """Compute a quote without changing validation, storage, or the public API.

    Rounding sequence: individual (unit * quantity) line amounts -> subtotal
    -> discount amount -> discounted goods -> threshold -> shipping -> total.
    """
    validate_order(lines, discount)
    subtotal = sum(
        ((line['unit_price'] * line['quantity']).quantize(CENT, rounding=ROUND_HALF_UP)
         for line in lines),
        Decimal('0.00'),
    )
    discount_amount = (subtotal * discount).quantize(CENT, rounding=ROUND_HALF_UP)
    discounted_goods = subtotal - discount_amount
    shipping = (Decimal('0.00') if discounted_goods >= FREE_SHIPPING_THRESHOLD
                else SHIPPING_CHARGE)
    total = discounted_goods + shipping
    return {'subtotal': subtotal, 'shipping': shipping, 'total': total}

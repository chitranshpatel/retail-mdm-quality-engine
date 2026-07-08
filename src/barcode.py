"""
barcode.py — Real EAN-13 check-digit maths.

EAN-13 is a 13-digit barcode. The 13th digit is a check digit computed from the
first 12: multiply digits in odd positions (1st, 3rd, ...) by 1 and even
positions by 3, sum them, and the check digit is whatever makes the total a
multiple of 10.

This is genuine barcode validation logic, not a toy. It's what lets the project
catch "won't scan at POS" defects, which almost no portfolio project does.
"""


def ean13_check_digit(first_12: str) -> int:
    """Compute the correct EAN-13 check digit for a 12-digit string."""
    if len(first_12) != 12 or not first_12.isdigit():
        raise ValueError(f"Expected 12 digits, got: {first_12!r}")
    total = 0
    for i, ch in enumerate(first_12):
        d = int(ch)
        # positions are 1-indexed in the standard; i=0 is position 1 (odd, weight 1)
        weight = 1 if i % 2 == 0 else 3
        total += d * weight
    return (10 - (total % 10)) % 10


def make_valid_ean13(first_12: str) -> str:
    """Return a full, valid 13-digit EAN-13 from a 12-digit body."""
    return first_12 + str(ean13_check_digit(first_12))


def is_valid_ean13(barcode: str) -> bool:
    """True iff barcode is 13 digits with a correct check digit."""
    if not isinstance(barcode, str) or len(barcode) != 13 or not barcode.isdigit():
        return False
    return ean13_check_digit(barcode[:12]) == int(barcode[12])


if __name__ == "__main__":
    # quick self-test
    body = "930012345678"  # 12 digits
    full = make_valid_ean13(body)
    assert is_valid_ean13(full), "generated barcode should be valid"
    # corrupt the check digit -> must be invalid
    bad = full[:12] + str((int(full[12]) + 1) % 10)
    assert not is_valid_ean13(bad), "corrupted barcode should be invalid"
    print("barcode self-test passed:", full, "valid |", bad, "invalid")

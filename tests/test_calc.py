from bfa.calc import cagr, calculated_fact, fmt_num, fold_change, product, value_range
from bfa.schemas import Fact


def test_arithmetic():
    assert round(cagr(100, 200, 5), 4) == 0.1487
    assert fold_change(2, 6) == 3
    assert value_range([3, 1, 2]) == (1, 3)
    assert product([2, 3, 4]) == 24
    assert cagr(0, 5, 3) is None


def test_formatting():
    assert fmt_num(21_600_000, "USD") == "$21.6 million"
    assert fmt_num(1_100_000_000, "USD") == "$1.1 billion"
    assert fmt_num(60000) == "60,000"
    assert fmt_num(12, "%") == "12%"


def test_calculated_fact_basis_follows_inputs():
    a = Fact(id="a", source_id="s", claim="x", basis="primary", tier="A", kind="regulator")
    b = Fact(id="b", source_id="s", claim="y", basis="secondary", tier="B", kind="news")
    assert calculated_fact("c", 1.0, "", [a], "m", []).basis == "primary"
    c = calculated_fact("c", 1.0, "", [a, b], "m", [])
    assert c.basis == "secondary" and c.inputs == ["a", "b"] and c.id.startswith("CALC-")

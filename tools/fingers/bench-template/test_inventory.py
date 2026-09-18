from inventory import restock, total_value, low_stock


def test_restock_adds():
    assert restock({"pen": 2}, "pen", 3) == {"pen": 5}


def test_restock_creates_missing_item():
    assert restock({}, "pad", 4) == {"pad": 4}


def test_total_value_skips_unpriced_items():
    assert total_value({"pen": 2, "ghost": 9}, {"pen": 1.5}) == 3.0


def test_low_stock_is_at_or_below_threshold():
    assert sorted(low_stock({"pen": 1, "pad": 5, "ink": 2}, 2)) == ["ink", "pen"]

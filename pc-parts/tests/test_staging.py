from decimal import Decimal

from pc_parts.staging import Stage


def test_invalid_item_dropped_and_duplicates_choose_specific_path():
    with Stage("sigma", "https://www.sigma-computer.com/en", batch_size=2) as stage:
        stage.add({"name": "", "category": "cpu", "product_url": "/en/item?id=broken"})
        stage.add({"name": "Part", "category": "cpu", "depth": 1,
                   "product_url": "/en/item?id=abc&utm_source=foo", "price": None})
        stage.add({"name": "Part", "category": "cpu", "depth": 3,
                   "product_url": "/en/item?id=abc", "price": "1,234 EGP", "in_stock": False})
        stage.add({"name": "Impossible price", "category": "cpu", "depth": 1,
                   "product_url": "/en/item?id=large", "price": "99999999999 EGP"})
        assert stage.finish() == 1
        assert stage.invalid_count == 2
        row = next(stage.rows())
        assert row[3] == Decimal("1234.00")
        assert row[4] is False
        assert row[5].endswith("id=abc")


def test_unknown_values_remain_null():
    with Stage("elbadr", "https://elbadrgroupeg.store/") as stage:
        stage.add({"name": "Part", "category": "ram", "product_url": "/part",
                   "price": None, "in_stock": None})
        stage.finish()
        row = next(stage.rows())
        assert row[3] is None and row[4] is None
        assert stage.category_counts() == [("ram", 1)]
        assert stage.sample_by_category(1)[0][0] == "Part"

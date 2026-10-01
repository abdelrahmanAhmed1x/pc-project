from pc_parts.identity import Evidence, attributes, conflicts, deterministic_verdict
from pc_parts.resolution import Listing, candidates, request_body, reserve_cost, safe_to_apply


def listing(variant_id, product_id, provider_id, category, brand, title, **kw):
    return Listing(variant_id, product_id, provider_id, str(variant_id),
                   Evidence(category, brand, title, **kw))


def test_cpu_model_is_strong_but_package_is_a_hard_conflict():
    a = Evidence("cpu", "AMD", "AMD Ryzen 7 7800X3D Box")
    b = Evidence("cpu", "AMD", "Ryzen 7 7800X3D Box Processor")
    c = Evidence("cpu", "AMD", "AMD Ryzen 7 7800X3D Tray")
    assert deterministic_verdict(a, b) == "same_exact_variant"
    assert "package" in conflicts(a, c)
    assert deterministic_verdict(a, c) == "same_product_different_variant"


def test_identifiers_do_not_override_configuration_conflict():
    a = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 256GB Black", mpn="ABC")
    b = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 512GB Black", mpn="ABC")
    assert "storage" in conflicts(a, b)
    assert deterministic_verdict(a, b) == "same_product_different_variant"


def test_laptops_ram_and_gpu_require_exact_configuration():
    a = Evidence("laptops", "Lenovo", "LOQ 15IRX9 i5-13450HX RTX 4050 16GB RAM 512GB SSD")
    b = Evidence("laptops", "Lenovo", "LOQ 15IRX9 i7-13650HX RTX 4060 16GB RAM 512GB SSD")
    assert {"cpu", "gpu"} <= set(conflicts(a, b))
    a = Evidence("ram", "Corsair", "Vengeance 32GB 2x16GB DDR5 6000 CL30")
    b = Evidence("ram", "Corsair", "Vengeance 32GB 2x16GB DDR5 6000 CL36")
    assert "latency" in conflicts(a, b)
    a = Evidence("gpu", "ASUS", "TUF RTX 5070 OC 12GB")
    b = Evidence("gpu", "ASUS", "TUF RTX 5070 Ti OC 12GB")
    assert "chip" in conflicts(a, b)


def test_only_strong_evidence_auto_applies_luna_decision():
    a = Evidence("laptops", "Lenovo", "LOQ 15IRX9 i5-13450HX RTX 4050")
    b = Evidence("laptops", "Lenovo", "Lenovo LOQ 15IRX9 i5-13450HX RTX 4050")
    assert not safe_to_apply(a, b, "same_exact_variant", "luna_medium", False)
    a = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 256GB")
    b = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 512GB")
    assert safe_to_apply(a, b, "same_product_different_variant", "human", True)
    assert not safe_to_apply(a, b, "same_product_different_variant", "luna_medium", False)


def test_candidate_blocking_and_batch_budget():
    items = [listing(1,1,1,"cpu","AMD","Ryzen 7 7800X3D Box"),
             listing(2,2,2,"cpu","AMD","AMD Ryzen 7 7800X3D Box"),
             listing(3,3,3,"cpu","Intel","Core i7-14700K Box")]
    pairs = list(candidates(items))
    assert len(pairs) == 1
    assert {pairs[0][0].variant_id,pairs[0][1].variant_id} == {1,2}
    body = request_body(items[0],items[1])
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"]["effort"] == "medium"
    assert body["store"] is False
    assert reserve_cost(body) > 0


def test_missing_values_are_not_invented():
    attrs = attributes("laptops", "Lenovo LOQ 15IRX9 RTX 4050")
    assert attrs.get("gpu") == "rtx4050"
    assert "cpu" not in attrs and "ram" not in attrs and "storage" not in attrs

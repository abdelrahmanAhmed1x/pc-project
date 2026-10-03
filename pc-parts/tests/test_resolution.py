from pc_parts.identity import Evidence, attributes, conflicts, deterministic_verdict
from pc_parts.resolution import Listing, candidates, phone_family_name, request_body, reserve_cost, safe_to_apply


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
    a = Evidence("gpu", "Gigabyte", "RTX 3050 Eagle OC 6G")
    b = Evidence("gpu", "Gigabyte", "RTX 3050 Windforce OC V2 6GB")
    assert "board_family" in conflicts(a, b)
    assert a.attrs["vram"] == b.attrs["vram"] == "6"


def test_luna_matches_apply_without_shared_identifiers_but_not_hard_conflicts():
    a = Evidence("laptops", "Lenovo", "LOQ 15IRX9 i5-13450HX RTX 4050")
    b = Evidence("laptops", "Lenovo", "Lenovo LOQ 15IRX9 i5-13450HX RTX 4050")
    assert safe_to_apply(a, b, "same_exact_variant", "luna_medium", False)
    different_gpu = Evidence("laptops", "Lenovo", "LOQ 15IRX9 i5-13450HX RTX 4060")
    assert not safe_to_apply(a, different_gpu, "same_exact_variant", "luna_medium", False)
    a = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 256GB")
    b = Evidence("mobile_phones", "Apple", "iPhone 17 Pro 512GB")
    assert safe_to_apply(a, b, "same_product_different_variant", "human", True)
    assert safe_to_apply(a, b, "same_product_different_variant", "luna_medium", False)
    assert not safe_to_apply(a, Evidence("mobile_phones", "Samsung", "Galaxy S25 256GB"),
                             "same_product_different_variant", "luna_medium", False)


def test_variant_family_merge_requires_explicit_family_and_supported_category():
    gpu_a = Evidence("gpu", "Gigabyte", "RTX 3050 Eagle OC 6GB")
    gpu_b = Evidence("gpu", "Gigabyte", "RTX 3050 Windforce OC 6GB")
    assert not safe_to_apply(gpu_a, gpu_b, "same_product_different_variant", "luna_medium", False)
    phone_a = Evidence("mobile_phones", "Apple", "iPhone 18 Pro Max 256GB Burgundy")
    phone_b = Evidence("mobile_phones", "Apple", "iPhone 18 Pro 256GB Burgundy")
    assert not safe_to_apply(phone_a, phone_b, "same_product_different_variant", "luna_medium", False)
    assert phone_family_name(phone_a) == "iPhone 18 Pro Max"


def test_arabic_titles_retain_phone_generation_and_audio_model_codes():
    arabic = Evidence("mobile_phones", "Apple", "آيفون ١٨ برو ماكس ٢٥٦ جيجابايت")
    english = Evidence("mobile_phones", "Apple", "iPhone 18 Pro Max 512GB")
    assert arabic.attrs["generation"] == english.attrs["generation"]
    assert arabic.attrs["storage"] == "256gb"
    a = listing(1, 1, 1, "headphones", "JBL", "سماعة JBL 530BT لاسلكية")
    b = listing(2, 2, 2, "headphones", "JBL", "JBL Tune 530BT Wireless Headphones")
    assert len(list(candidates([a, b]))) == 1


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


def test_alternate_retailer_title_can_find_candidate_without_more_model_context():
    first = Listing(1, 1, 1, "first", Evidence("headphones", "JBL", "Wireless headphones"),
                    aliases=("JBL Tune 530BT headphones",), provider_ids=frozenset({1, 3}))
    second = Listing(2, 2, 2, "second", Evidence("headphones", "JBL", "JBL 530BT wireless headset"),
                     provider_ids=frozenset({2}))
    pairs = list(candidates([first, second]))
    assert len(pairs) == 1
    assert "530BT" in request_body(first, second)["input"]
    same_provider = Listing(3, 3, 3, "third", Evidence("headphones", "JBL", "JBL 530BT"),
                            provider_ids=frozenset({2, 3}))
    assert not list(candidates([first, same_provider]))


def test_missing_values_are_not_invented():
    attrs = attributes("laptops", "Lenovo LOQ 15IRX9 RTX 4050")
    assert attrs.get("gpu") == "rtx4050"
    assert "cpu" not in attrs and "ram" not in attrs and "storage" not in attrs

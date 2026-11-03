import json

import pytest

from evals.run_evals import CASES_FILE, evaluate_checks, malformed_amounts, normalize

KNOWN_CHECKS = {"no_tools", "tools_called", "tools_not_called", "must_contain", "must_contain_any", "must_not_contain"}


def test_normalize_ignores_case_accents_punctuation_and_spacing():
    assert normalize("R$ 2.199,00") == normalize("r$2.199,00") == normalize("R$ 2.199,00") == "r 2 199 00"
    assert normalize("Violão Aço") == "violao aco"


def test_checks_pass_and_fail():
    checks = {
        "tools_called": ["search_products"],
        "must_contain": ["R$ 2.199,00"],
        "must_contain_any": ["não está ativa", "encerrada"],
        "must_not_contain": ["1.935"],
    }
    assert evaluate_checks(checks, ["Custa R$ 2.199,00, a promoção foi encerrada."], ["search_products"]) == []
    failures = evaluate_checks(checks, ["Custa R$ 1.935,12!"], [])
    assert len(failures) == 4


def test_needles_match_whole_words_only():
    # "br" must not match inside "obrigada"
    assert evaluate_checks({"must_not_contain": ["BR"]}, ["Obrigada!"], []) == []


def test_malformed_brl_amounts_are_detected():
    text = "De R$ 2.199,00 por R$ 2,199,00, ou R$ 2199.00, ou R$ 89,90, ou R$1000, ou até R$ 1.000, ou R$ 5."
    assert malformed_amounts(text) == ["R$ 2,199,00", "R$ 2199.00", "R$1000"]


def test_no_tools_check():
    assert evaluate_checks({"no_tools": True}, ["oi"], ["search_products"]) != []


def test_cases_file_is_well_formed():
    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    ids = [c["id"] for c in spec["cases"]]
    assert len(ids) == len(set(ids)) >= 15
    for case in spec["cases"]:
        assert case["messages"] and case["expected"] and case["description"]
        assert set(case.get("checks", {})) <= KNOWN_CHECKS, case["id"]


@pytest.mark.parametrize("case_id", ["catalog_guitars_under_1000", "store_address", "price_takamine_gd20", "regret_return_expired"])
def test_challenge_scenarios_are_covered(case_id):
    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    assert case_id in {c["id"] for c in spec["cases"]}

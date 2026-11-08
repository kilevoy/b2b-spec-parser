from spec_parser.exporter import build_amocrm_payload, export_to_1c_csv
from spec_parser.models import ApprovalStatus, MatchType, PriceTier, ProjectDirection
from spec_parser.parser_engine import SpecParserEngine


def test_lstk_tonnage_conversion_and_analog():
    engine = SpecParserEngine()
    spec = """
    1. Профиль С-образный ПС 200х50х2.0 — 4.95 тн
    2. Швеллер горячекатаный г/к 24 для прогонов — 200 п.м.
    """
    result = engine.parse_specification(spec, price_tier=PriceTier.BUILDER_OPT)

    assert len(result.lines) == 2
    assert result.primary_direction == ProjectDirection.HANGARS

    # 4.95 т = 4950 кг / 4.95 кг/м = 1000 м.п.
    line1 = result.lines[0]
    assert line1.sku == "LSTK-PS-200-20"
    assert line1.normalized_qty == 1000.0
    assert line1.billing_unit == "м.п."

    # Замена швеллера на Z-профиль ЛСТК
    line2 = result.lines[1]
    assert line2.sku == "LSTK-PZ-250-25"
    assert line2.match_type == MatchType.ANALOG

    # Рекомендация высокопрочного крепежа М16
    rec_skus = {r.sku for r in result.cross_sell_recommendations}
    assert "MET-BOLT-M16" in rec_skus


def test_gasblock_pallet_rounding_and_cross_sell():
    engine = SpecParserEngine()
    spec = """
    Блок газобетонный D500 625*400*250 — 140 м3
    Перемычка газобетонная ПГБ 2000 — 12 шт
    """
    result = engine.parse_specification(spec, price_tier=PriceTier.RETAIL)

    assert result.primary_direction == ProjectDirection.GASBLOCK
    block_line = result.lines[0]
    # 140 / 1.875 = 74.666 -> 75 поддонов = 140.625 м3
    assert block_line.pallets_count == 75
    assert block_line.normalized_qty == 140.625
    assert result.logistics.trucks_20t_count >= 4

    # Авто-рекомендация клея и базальтовой сетки
    rec_skus = {r.sku for r in result.cross_sell_recommendations}
    assert "GB-GLUE-25" in rec_skus
    assert "GB-MESH-50" in rec_skus

    # Включение клея в КП
    result_with_glue = engine.parse_specification(
        spec,
        price_tier=PriceTier.RETAIL,
        include_cross_sell_skus=["GB-GLUE-25"],
    )
    assert len(result_with_glue.lines) == 3
    assert result_with_glue.margin.final_total_rub > result.margin.final_total_rub


def test_margin_guardrails_and_exports():
    engine = SpecParserEngine()
    spec = "Кассета фасадная закрытого типа КФ-1 1.2мм — 850 м2"

    res_normal = engine.parse_specification(spec, price_tier=PriceTier.RETAIL, discount_pct=0.0)
    assert res_normal.margin.approval_status == ApprovalStatus.AUTO_APPROVED

    res_rop = engine.parse_specification(spec, price_tier=PriceTier.BUILDER_OPT, discount_pct=7.0)
    assert res_rop.margin.approval_status == ApprovalStatus.ROP_APPROVAL

    res_dir = engine.parse_specification(spec, price_tier=PriceTier.DEALER, discount_pct=12.0)
    assert res_dir.margin.approval_status == ApprovalStatus.DIRECTOR_APPROVAL

    csv_text = export_to_1c_csv(res_normal)
    assert "FAS-KF1-12" in csv_text

    crm_payload = build_amocrm_payload(res_normal)
    assert crm_payload["price"] > 0
    assert len(crm_payload["catalog_elements"]) == 1


import argparse
import sys
from .models import PriceTier
from .parser_engine import SpecParserEngine

DEMO_SPEC = """
# Выписка из ведомости объёмов работ (Объект: Логистический комплекс, г. Челябинск)
1. Профиль гнутый С-образный ПС 200х60х2.0 оцинк — 4.5 тн
2. Профиль ГПС нестандартный 215х65х20 (развертка 340 мм по чертежу заказчика) — 320 п.м.
3. Сэндвич-панель стеновая ПСБ 120мм минвата RAL 7024 — 680 м2
4. Сэндвич-панель кровельная ПСК 150мм — 920 м2
5. Газоблок автоклавный D500 625х400х250 (перегородки АБК) — 65 м3
"""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="B2B Spec Parser & Proposal Generator CLI")
    parser.add_argument("--demo", action="store_true", help="Запустить демонстрационный расчёт ТЗ")
    parser.add_argument("--discount", type=float, default=3.0, help="Проектная скидка, %")
    args = parser.parse_args()

    engine = SpecParserEngine()
    result = engine.parse_specification(
        raw_text=DEMO_SPEC,
        price_tier=PriceTier.BUILDER_OPT,
        discount_pct=args.discount,
    )

    print("=" * 78)
    print(f"📄 КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ: {result.proposal_number} (Демо-данные)")
    print(f"Направление: {result.direction_title}")
    print("=" * 78)
    for line in result.lines:
        badge = "🔄 АНАЛОГ" if line.match_type.value == "analog" else "✅ ТОЧНО"
        print(
            f"{line.line_no}. [{badge}] {line.catalog_name}\n"
            f"   Исходник: '{line.raw_text}'\n"
            f"   Расчёт: {line.normalized_qty} {line.billing_unit} × {line.unit_price_rub:,.2f} ₽ = {line.line_total_rub:,.2f} ₽"
        )
        if line.conversion_note:
            print(f"   💡 Инженерное примечание: {line.conversion_note}")
    print("-" * 78)
    print(f"💰 ИТОГО С НДС: {result.margin.final_total_rub:,.2f} ₽ (Маржа: {result.margin.gross_margin_pct}%)")
    print(f"🚦 Статус согласования: {result.margin.approval_comment}")
    print(
        f"🚚 Логистика: {result.logistics.total_weight_tons} т | "
        f"{result.logistics.total_volume_m3} м³ | Еврофур (20т): {result.logistics.trucks_20t_count} шт."
    )
    if result.cross_sell_recommendations:
        print("-" * 78)
        print("🔥 РЕКОМЕНДУЕМАЯ ДОПРОДАЖА (Забытые комплектующие в ТЗ клиента):")
        for rec in result.cross_sell_recommendations:
            print(
                f"   + {rec.name}: {rec.recommended_qty} {rec.unit} "
                f"на сумму {rec.total_price_rub:,.2f} ₽ ({rec.reason})"
            )
    print("=" * 78)


if __name__ == "__main__":
    main()


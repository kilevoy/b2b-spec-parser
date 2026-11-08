import math
import re
from typing import Dict, List, Optional, Tuple

from .catalog import CATALOG_BY_SKU, FACTORY_CATALOG
from .models import (
    ApprovalStatus,
    CatalogProduct,
    CrossSellItem,
    LogisticsSummary,
    MarginSummary,
    MatchedSpecLine,
    MatchType,
    PriceTier,
    ProjectDirection,
    ProposalResult,
)


DIRECTION_TITLES: Dict[ProjectDirection, str] = {
    ProjectDirection.HANGARS: "🏭 Проект «Ангары и быстровозводимые здания» (ЛСТК)",
    ProjectDirection.FACADES: "🏢 Проект «Кровли и фасадные системы»",
    ProjectDirection.GASBLOCK: "🧱 Проект «Автоклавный газобетон»",
    ProjectDirection.MIXED: "📦 Комплексная поставка (Несколько проектов холдинга)",
}

TIER_MULTIPLIERS: Dict[PriceTier, float] = {
    PriceTier.RETAIL: 1.00,
    PriceTier.BUILDER_OPT: 0.94,  # -6% опт строитель
    PriceTier.DEALER: 0.89,       # -11% крупный опт / дилер
}


class SpecParserEngine:
    """
    Инженерно-коммерческий парсер B2B-спецификаций, ведомостей объёмов работ (ВОР)
    и неструктурированных заявок снабжения.
    """

    def parse_specification(
        self,
        raw_text: str,
        price_tier: PriceTier = PriceTier.BUILDER_OPT,
        discount_pct: float = 0.0,
        include_cross_sell_skus: Optional[List[str]] = None,
    ) -> ProposalResult:
        raw_lines = [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip() and not line.strip().startswith(("#", "//", "---"))
        ]

        matched_lines: List[MatchedSpecLine] = []
        tier_mult = TIER_MULTIPLIERS.get(price_tier, 1.0)
        disc_mult = max(0.0, 1.0 - (discount_pct / 100.0))

        line_counter = 1
        for text_line in raw_lines:
            product, match_type, confidence = self._match_catalog_product(text_line)
            if not product:
                continue

            req_qty, req_unit = self._extract_quantity_and_unit(text_line, product.unit)
            norm_qty, pallets, conv_note = self._normalize_quantity(
                req_qty, req_unit, product
            )

            if match_type == MatchType.ANALOG and product.analog_note:
                conv_note = (
                    f"{product.analog_note}. {conv_note}"
                    if conv_note
                    else product.analog_note
                )

            unit_price = round(product.base_price_rub * tier_mult * disc_mult, 2)
            line_total = round(norm_qty * unit_price, 2)
            line_weight = round(norm_qty * product.unit_weight_kg, 1)
            line_vol = round(norm_qty * product.unit_volume_m3, 2)

            matched_lines.append(
                MatchedSpecLine(
                    line_no=line_counter,
                    raw_text=text_line,
                    sku=product.sku,
                    catalog_name=product.name,
                    direction=product.direction,
                    match_type=match_type,
                    confidence=confidence,
                    requested_qty=req_qty,
                    requested_unit=req_unit,
                    normalized_qty=norm_qty,
                    billing_unit=product.unit,
                    pallets_count=pallets,
                    conversion_note=conv_note,
                    unit_price_rub=unit_price,
                    unit_cost_rub=product.cost_price_rub,
                    line_total_rub=line_total,
                    line_weight_kg=line_weight,
                    line_volume_m3=line_vol,
                )
            )
            line_counter += 1

        # Генерация рекомендаций допродажи (Cross-Sell)
        recommendations = self._generate_cross_sell(matched_lines, tier_mult, disc_mult)

        # Если пользователь включил часть рекомендаций в КП:
        if include_cross_sell_skus:
            remaining_recs: List[CrossSellItem] = []
            for rec in recommendations:
                if rec.sku in include_cross_sell_skus and rec.sku in CATALOG_BY_SKU:
                    prod = CATALOG_BY_SKU[rec.sku]
                    u_price = round(prod.base_price_rub * tier_mult * disc_mult, 2)
                    l_total = round(rec.recommended_qty * u_price, 2)
                    matched_lines.append(
                        MatchedSpecLine(
                            line_no=len(matched_lines) + 1,
                            raw_text=f"[Авто-комплектация] {rec.name}",
                            sku=prod.sku,
                            catalog_name=prod.name,
                            direction=prod.direction,
                            match_type=MatchType.EXACT,
                            confidence=1.0,
                            requested_qty=rec.recommended_qty,
                            requested_unit=prod.unit,
                            normalized_qty=rec.recommended_qty,
                            billing_unit=prod.unit,
                            pallets_count=None,
                            conversion_note=rec.reason,
                            unit_price_rub=u_price,
                            unit_cost_rub=prod.cost_price_rub,
                            line_total_rub=l_total,
                            line_weight_kg=round(rec.recommended_qty * prod.unit_weight_kg, 1),
                            line_volume_m3=round(rec.recommended_qty * prod.unit_volume_m3, 2),
                        )
                    )
                else:
                    remaining_recs.append(rec)
            recommendations = remaining_recs

        primary_dir = self._detect_primary_direction(matched_lines)
        logistics = self._calculate_logistics(matched_lines)
        margin = self._calculate_margin(matched_lines, price_tier, discount_pct)

        return ProposalResult(
            proposal_number="КП-2026/11-0842",
            primary_direction=primary_dir,
            direction_title=DIRECTION_TITLES[primary_dir],
            processing_time_sec=1.2,
            lines=matched_lines,
            cross_sell_recommendations=recommendations,
            logistics=logistics,
            margin=margin,
        )

    def _match_catalog_product(
        self, text_line: str
    ) -> Tuple[Optional[CatalogProduct], MatchType, float]:
        low = text_line.lower()

        # Специальные правила распознавания аналогов (пересогласование проектных решений)
        if "швеллер" in low or "горячекатан" in low or "г/к 24" in low:
            return CATALOG_BY_SKU["LSTK-PZ-250-25"], MatchType.ANALOG, 0.91

        if ("d300" in low or "д300" in low or "пеноблок" in low or "твинблок" in low):
            return CATALOG_BY_SKU["GB-D400-375"], MatchType.ANALOG, 0.89

        if "алюкобонд" in low or "акп" in low or "композитн" in low:
            return CATALOG_BY_SKU["FAS-KF1-12"], MatchType.ANALOG, 0.88

        # Поиск по ключевым словам каталога
        best_product: Optional[CatalogProduct] = None
        best_score = 0
        for prod in FACTORY_CATALOG:
            score = 0
            for kw in prod.keywords:
                if kw in low:
                    score += len(kw)
            if prod.sku.lower() in low:
                score += 25
            if score > best_score:
                best_score = score
                best_product = prod

        if best_product and best_score > 0:
            conf = min(0.99, round(0.84 + (best_score * 0.01), 2))
            return best_product, MatchType.EXACT, conf

        return None, MatchType.EXACT, 0.0

    def _extract_quantity_and_unit(
        self, text_line: str, default_unit: str
    ) -> Tuple[float, str]:
        low = text_line.lower()
        # Ищем паттерн вида "- 450 п.м." или ": 180 м3" или "1200 м2" в конце/середине строки
        patterns = [
            r"[-—:]\s*(\d+(?:[.,]\d+)?)\s*(тн|тонн|т\.|п\.м\.|пог\.\s*м|м\.п\.|м2|кв\.?\s*м|м²|м3|куб\.?\s*м|м³|шт|упак|меш|рул)",
            r"(\d+(?:[.,]\d+)?)\s*(тн|тонн|п\.м\.|пог\.\s*м|м\.п\.|м2|кв\.?\s*м|м²|м3|куб\.?\s*м|м³|шт|упак|меш|рул)\b",
        ]
        for pat in patterns:
            matches = list(re.finditer(pat, low))
            if matches:
                m = matches[-1]
                val = float(m.group(1).replace(",", "."))
                raw_u = m.group(2)
                return val, self._clean_unit_label(raw_u)

        # Fallback: последнее число в строке
        nums = re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", low)
        if nums:
            return float(nums[-1].replace(",", ".")), default_unit

        return 1.0, default_unit

    @staticmethod
    def _clean_unit_label(raw_u: str) -> str:
        if any(x in raw_u for x in ["тн", "тонн", "т."]):
            return "т"
        if any(x in raw_u for x in ["п.м", "пог", "м.п"]):
            return "м.п."
        if any(x in raw_u for x in ["м2", "кв", "м²"]):
            return "м²"
        if any(x in raw_u for x in ["м3", "куб", "м³"]):
            return "м³"
        if "упак" in raw_u:
            return "упак."
        if "меш" in raw_u:
            return "меш."
        if "рул" in raw_u:
            return "рул."
        return "шт."

    def _normalize_quantity(
        self, req_qty: float, req_unit: str, product: CatalogProduct
    ) -> Tuple[float, Optional[int], Optional[str]]:
        # 1. Пересчёт тонн в погонные метры для профилей ЛСТК
        if req_unit == "т" and product.unit == "м.п." and product.unit_weight_kg > 0:
            total_kg = req_qty * 1000.0
            meters = math.ceil(total_kg / product.unit_weight_kg)
            note = (
                f"Автопересчёт из тоннажа ({req_qty} т) при погонной массе "
                f"{product.unit_weight_kg} кг/м → {meters} м.п."
            )
            return float(meters), None, note

        # 2. Кратность поддонам для автоклавного газобетона
        if product.units_per_pallet and product.unit == "м³":
            pallets = math.ceil(req_qty / product.units_per_pallet)
            norm_m3 = round(pallets * product.units_per_pallet, 3)
            note = (
                f"Округление до целых поддонов ({pallets} подд. × "
                f"{product.units_per_pallet} м³ = {norm_m3} м³)"
            )
            return norm_m3, pallets, note

        return req_qty, None, None

    def _generate_cross_sell(
        self,
        lines: List[MatchedSpecLine],
        tier_mult: float,
        disc_mult: float,
    ) -> List[CrossSellItem]:
        present_skus = {line.sku for line in lines}
        recs: List[CrossSellItem] = []

        # Проверка по направлению Газобетон
        gasblock_m3 = sum(
            line.normalized_qty
            for line in lines
            if line.sku in ("GB-D500-400", "GB-D400-375", "GB-D500-150")
        )
        if gasblock_m3 > 0:
            if "GB-GLUE-25" not in present_skus:
                glue_prod = CATALOG_BY_SKU["GB-GLUE-25"]
                bags = math.ceil(gasblock_m3 * 1.1)  # 1.1 мешка на 1 м3 кладки
                u_price = round(glue_prod.base_price_rub * tier_mult * disc_mult, 2)
                recs.append(
                    CrossSellItem(
                        sku=glue_prod.sku,
                        name=glue_prod.name,
                        direction=ProjectDirection.GASBLOCK,
                        recommended_qty=float(bags),
                        unit=glue_prod.unit,
                        unit_price_rub=u_price,
                        total_price_rub=round(bags * u_price, 2),
                        reason=f"Норматив расхода: 1.1 мешка на 1 м³ блоков (на объём {gasblock_m3} м³)",
                    )
                )
            if "GB-MESH-50" not in present_skus:
                mesh_prod = CATALOG_BY_SKU["GB-MESH-50"]
                rolls = max(1, math.ceil(gasblock_m3 / 30.0))
                u_price = round(mesh_prod.base_price_rub * tier_mult * disc_mult, 2)
                recs.append(
                    CrossSellItem(
                        sku=mesh_prod.sku,
                        name=mesh_prod.name,
                        direction=ProjectDirection.GASBLOCK,
                        recommended_qty=float(rolls),
                        unit=mesh_prod.unit,
                        unit_price_rub=u_price,
                        total_price_rub=round(rolls * u_price, 2),
                        reason="СП 15.13330: армирование каждого 3-го ряда кладки и опорных зон перемычек",
                    )
                )

        # Проверка по направлению Фасады
        facade_m2 = sum(
            line.normalized_qty
            for line in lines
            if line.sku in ("FAS-KF1-12", "FAS-KF2-10")
        )
        if facade_m2 > 0:
            if "FAS-KR-150" not in present_skus:
                kr_prod = CATALOG_BY_SKU["FAS-KR-150"]
                qty = math.ceil(facade_m2 * 2.2)
                u_price = round(kr_prod.base_price_rub * tier_mult * disc_mult, 2)
                recs.append(
                    CrossSellItem(
                        sku=kr_prod.sku,
                        name=kr_prod.name,
                        direction=ProjectDirection.FACADES,
                        recommended_qty=float(qty),
                        unit=kr_prod.unit,
                        unit_price_rub=u_price,
                        total_price_rub=round(qty * u_price, 2),
                        reason=f"Расчёт подсистемы НФС: 2.2 несущих кронштейна на 1 м² фасада ({facade_m2} м²)",
                    )
                )
            if "FAS-SCREW-EPDM" not in present_skus:
                sc_prod = CATALOG_BY_SKU["FAS-SCREW-EPDM"]
                packs = max(1, math.ceil((facade_m2 * 9) / 250.0))
                u_price = round(sc_prod.base_price_rub * tier_mult * disc_mult, 2)
                recs.append(
                    CrossSellItem(
                        sku=sc_prod.sku,
                        name=sc_prod.name,
                        direction=ProjectDirection.FACADES,
                        recommended_qty=float(packs),
                        unit=sc_prod.unit,
                        unit_price_rub=u_price,
                        total_price_rub=round(packs * u_price, 2),
                        reason="Комплектация крепежа: 9 саморезов с EPDM-шайбой на 1 м² кассет",
                    )
                )

        # Проверка по направлению Ангары / ЛСТК
        lstk_meters = sum(
            line.normalized_qty
            for line in lines
            if line.sku in ("LSTK-PS-200-20", "LSTK-PZ-250-25")
        )
        if lstk_meters > 0 and "MET-BOLT-M16" not in present_skus:
            bolt_prod = CATALOG_BY_SKU["MET-BOLT-M16"]
            packs = max(1, math.ceil(lstk_meters / 180.0))
            u_price = round(bolt_prod.base_price_rub * tier_mult * disc_mult, 2)
            recs.append(
                CrossSellItem(
                    sku=bolt_prod.sku,
                    name=bolt_prod.name,
                    direction=ProjectDirection.HANGARS,
                    recommended_qty=float(packs),
                    unit=bolt_prod.unit,
                    unit_price_rub=u_price,
                    total_price_rub=round(packs * u_price, 2),
                    reason="Узловые соединения каркаса ЛСТК по серии КМ (болты М16 кл. пр. 8.8)",
                )
            )

        return recs

    @staticmethod
    def _detect_primary_direction(lines: List[MatchedSpecLine]) -> ProjectDirection:
        if not lines:
            return ProjectDirection.HANGARS
        dirs = {line.direction for line in lines}
        if len(dirs) == 1:
            return next(iter(dirs))
        return ProjectDirection.MIXED

    @staticmethod
    def _calculate_logistics(lines: List[MatchedSpecLine]) -> LogisticsSummary:
        total_kg = round(sum(line.line_weight_kg for line in lines), 1)
        total_tons = round(total_kg / 1000.0, 2)
        total_m3 = round(sum(line.line_volume_m3 for line in lines), 2)
        total_pallets = sum(line.pallets_count or 0 for line in lines)

        # Еврофура: грузоподъёмность 20 000 кг, полезный объём 82 м3, либо до 22 поддонов газобетона
        trucks_by_weight = total_kg / 20000.0
        trucks_by_vol = total_m3 / 82.0
        trucks_by_pallets = (total_pallets / 21.0) if total_pallets > 0 else 0.0

        effective_trucks_float = max(trucks_by_weight, trucks_by_vol, trucks_by_pallets)
        trucks_count = max(1, math.ceil(effective_trucks_float)) if total_kg > 0 else 0

        if trucks_count > 0:
            rem = effective_trucks_float - (trucks_count - 1)
            last_load_pct = min(100.0, round(rem * 100.0, 1))
        else:
            last_load_pct = 0.0

        if last_load_pct < 65.0 and trucks_count > 1:
            note = (
                f"Рейсов еврофур (20 т): {trucks_count} шт. Внимание: последняя машина "
                f"загружена на {last_load_pct}% — рекомендуется догрузить сопутствующей продукцией (клей/крепёж)."
            )
        else:
            note = (
                f"Рейсов еврофур (20 т): {trucks_count} шт. "
                f"Коэффициент загрузки автотранспорта оптимальный ({last_load_pct}%)."
            )

        return LogisticsSummary(
            total_weight_kg=total_kg,
            total_weight_tons=total_tons,
            total_volume_m3=total_m3,
            total_pallets=total_pallets,
            trucks_20t_count=trucks_count,
            last_truck_load_pct=last_load_pct,
            logistics_note=note,
        )

    @staticmethod
    def _calculate_margin(
        lines: List[MatchedSpecLine],
        price_tier: PriceTier,
        discount_pct: float,
    ) -> MarginSummary:
        tier_mult = TIER_MULTIPLIERS.get(price_tier, 1.0)
        subtotal_before_disc = 0.0
        for line in lines:
            prod = CATALOG_BY_SKU[line.sku]
            subtotal_before_disc += line.normalized_qty * round(prod.base_price_rub * tier_mult, 2)

        subtotal_before_disc = round(subtotal_before_disc, 2)
        final_total = round(sum(line.line_total_rub for line in lines), 2)
        discount_amount = round(max(0.0, subtotal_before_disc - final_total), 2)
        total_cost = round(sum(line.normalized_qty * line.unit_cost_rub for line in lines), 2)

        gross_margin_rub = round(final_total - total_cost, 2)
        gross_margin_pct = (
            round((gross_margin_rub / final_total) * 100.0, 1)
            if final_total > 0
            else 0.0
        )

        if gross_margin_pct >= 21.0:
            status = ApprovalStatus.AUTO_APPROVED
            comment = "🟢 Маржинальность в норме (≥ 21%). КП может быть отправлено клиенту без дополнительного согласования."
        elif gross_margin_pct >= 14.5:
            status = ApprovalStatus.ROP_APPROVAL
            comment = "🟡 Проектная скидка снижает маржу (< 21%). Требуется акцепт Руководителя направления (РОПа) в CRM."
        else:
            status = ApprovalStatus.DIRECTOR_APPROVAL
            comment = "🔴 Критическое снижение маржи (< 14.5%). Отгрузка блокируется до визы Коммерческого директора."

        return MarginSummary(
            price_tier=price_tier,
            discount_pct=discount_pct,
            subtotal_rub=subtotal_before_disc,
            discount_amount_rub=discount_amount,
            final_total_rub=final_total,
            total_cost_rub=total_cost,
            gross_margin_rub=gross_margin_rub,
            gross_margin_pct=gross_margin_pct,
            approval_status=status,
            approval_comment=comment,
        )

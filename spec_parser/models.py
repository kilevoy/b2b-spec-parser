from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ProjectDirection(str, Enum):
    HANGARS = "hangars"      # Проект «Ангары и быстровозводимые здания» (ЛСТК)
    FACADES = "facades"      # Проект «Кровли и фасадные системы»
    GASBLOCK = "gasblock"    # Проект «Автоклавный газобетон»
    MIXED = "mixed"          # Комплексная поставка по нескольким направлениям


class MatchType(str, Enum):
    EXACT = "exact"          # Точное совпадение с номенклатурой завода
    ANALOG = "analog"        # Подобран заводской аналог (пересогласование ТЗ)
    CUSTOM = "custom"        # Нестандартная позиция (требует расчёта ПТО)


class PriceTier(str, Enum):
    RETAIL = "retail"                # Базовый прайс (Розница / малый объём)
    BUILDER_OPT = "builder_opt"      # Строитель (Опт от 500 тыс. руб.)
    DEALER = "dealer"                # Крупный Опт / Дилер (от 3 млн руб.)


class ApprovalStatus(str, Enum):
    AUTO_APPROVED = "auto_approved"          # 🟢 В рамках полномочий менеджера
    ROP_APPROVAL = "rop_approval"            # 🟡 Требуется согласование РОПа
    DIRECTOR_APPROVAL = "director_approval"  # 🔴 Требуется виза Коммерческого директора


class CatalogProduct(BaseModel):
    sku: str = Field(..., description="Артикул / Код 1С")
    name: str = Field(..., description="Полное наименование по ТУ/ГОСТ завода")
    direction: ProjectDirection
    unit: str = Field(..., description="Базовая единица измерения (м.п., м2, м3, шт, упак)")
    unit_weight_kg: float = Field(..., description="Масса единицы продукции в кг")
    unit_volume_m3: float = Field(default=0.0, description="Габаритный объём единицы в м3")
    units_per_pallet: Optional[float] = Field(
        default=None,
        description="Кратность отгрузки на поддоне (например, 1.875 м3 для газобетона)"
    )
    cost_price_rub: float = Field(..., description="Заводская себестоимость единицы, руб.")
    base_price_rub: float = Field(..., description="Базовая отпускная цена с НДС, руб.")
    keywords: List[str] = Field(default_factory=list, description="Ключевые маркеры для распознавания")
    analog_note: Optional[str] = Field(default=None, description="Обоснование замены при пересогласовании")


class MatchedSpecLine(BaseModel):
    line_no: int
    raw_text: str = Field(..., description="Исходная строка из ТЗ / заявки клиента")
    sku: str
    catalog_name: str
    direction: ProjectDirection
    match_type: MatchType = MatchType.EXACT
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    requested_qty: float
    requested_unit: str
    normalized_qty: float = Field(..., description="Количество с учётом кратности поддонов / пересчёта единиц")
    billing_unit: str
    pallets_count: Optional[int] = None
    conversion_note: Optional[str] = None
    unit_price_rub: float
    unit_cost_rub: float
    line_total_rub: float
    line_weight_kg: float
    line_volume_m3: float


class CrossSellItem(BaseModel):
    sku: str
    name: str
    direction: ProjectDirection
    recommended_qty: float
    unit: str
    unit_price_rub: float
    total_price_rub: float
    reason: str = Field(..., description="Инженерное обоснование допродажи (по нормативу расхода)")


class LogisticsSummary(BaseModel):
    total_weight_kg: float
    total_weight_tons: float
    total_volume_m3: float
    total_pallets: int
    trucks_20t_count: int = Field(..., description="Количество еврофур (20 т / 82 м3)")
    last_truck_load_pct: float = Field(..., description="Коэффициент загрузки последней машины, %")
    logistics_note: str


class MarginSummary(BaseModel):
    price_tier: PriceTier
    discount_pct: float
    subtotal_rub: float
    discount_amount_rub: float
    final_total_rub: float
    total_cost_rub: float
    gross_margin_rub: float
    gross_margin_pct: float
    approval_status: ApprovalStatus
    approval_comment: str


class ProposalResult(BaseModel):
    proposal_number: str
    primary_direction: ProjectDirection
    direction_title: str
    processing_time_sec: float = 1.4
    lines: List[MatchedSpecLine]
    cross_sell_recommendations: List[CrossSellItem]
    logistics: LogisticsSummary
    margin: MarginSummary


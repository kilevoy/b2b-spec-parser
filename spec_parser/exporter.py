import csv
import io
from typing import Any, Dict

from .models import ProposalResult


def export_to_1c_csv(proposal: ProposalResult) -> str:
    """
    Формирует CSV-выгрузку спецификации (разделитель ';') для импорта в 1С:УТ / 1С:ERP или Excel.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "№",
            "Артикул (Код 1С)",
            "Наименование номенклатуры",
            "Кол-во",
            "Ед. изм.",
            "Цена с НДС (руб.)",
            "Сумма с НДС (руб.)",
            "Масса (кг)",
            "Примечание / Инженерный комментарий",
        ]
    )
    for line in proposal.lines:
        writer.writerow(
            [
                line.line_no,
                line.sku,
                line.catalog_name,
                line.normalized_qty,
                line.billing_unit,
                f"{line.unit_price_rub:.2f}",
                f"{line.line_total_rub:.2f}",
                f"{line.line_weight_kg:.1f}",
                line.conversion_note or "Точное соответствие ТЗ",
            ]
        )
    return output.getvalue()


def build_amocrm_payload(proposal: ProposalResult, client_name: str = "ООО «ПромСтройМонтаж»") -> Dict[str, Any]:
    """
    Генерирует JSON-пакет для автоматического прикрепления сметы и обновления бюджета сделки в amoCRM v4.
    """
    return {
        "lead_name": f"Расчёт ТЗ {proposal.proposal_number} — {client_name}",
        "price": int(round(proposal.margin.final_total_rub)),
        "pipeline_direction": proposal.primary_direction.value,
        "custom_fields_values": [
            {"field_name": "Номер КП", "values": [{"value": proposal.proposal_number}]},
            {"field_name": "Направление", "values": [{"value": proposal.direction_title}]},
            {"field_name": "Маржинальность (%)", "values": [{"value": f"{proposal.margin.gross_margin_pct}%"}]},
            {"field_name": "Статус согласования", "values": [{"value": proposal.margin.approval_status.value}]},
            {
                "field_name": "Логистика (Еврофуры 20т)",
                "values": [{"value": f"{proposal.logistics.trucks_20t_count} маш. ({proposal.logistics.total_weight_tons} т)"}],
            },
        ],
        "catalog_elements": [
            {
                "sku": line.sku,
                "name": line.catalog_name,
                "quantity": line.normalized_qty,
                "unit": line.billing_unit,
                "unit_price": line.unit_price_rub,
                "total": line.line_total_rub,
            }
            for line in proposal.lines
        ],
    }

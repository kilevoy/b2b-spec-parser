from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .exporter import build_amocrm_payload, export_to_1c_csv
from .models import PriceTier, ProposalResult
from .parser_engine import SpecParserEngine

app = FastAPI(
    title="B2B Spec Parser & Proposal Generator API",
    description="AI-парсер строительных спецификаций, ведомостей объёмов работ (ВОР) и авто-генератор коммерческих предложений.",
    version="1.0.0",
)

engine = SpecParserEngine()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ParseRequest(BaseModel):
    raw_text: str
    price_tier: PriceTier = PriceTier.BUILDER_OPT
    discount_pct: float = 0.0
    include_cross_sell_skus: Optional[List[str]] = None


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/parse", response_model=ProposalResult)
async def parse_spec(req: ParseRequest):
    return engine.parse_specification(
        raw_text=req.raw_text,
        price_tier=req.price_tier,
        discount_pct=req.discount_pct,
        include_cross_sell_skus=req.include_cross_sell_skus,
    )


@app.post("/api/export/csv", response_class=PlainTextResponse)
async def export_csv(req: ParseRequest):
    result = engine.parse_specification(
        raw_text=req.raw_text,
        price_tier=req.price_tier,
        discount_pct=req.discount_pct,
        include_cross_sell_skus=req.include_cross_sell_skus,
    )
    return export_to_1c_csv(result)


@app.post("/api/export/amocrm")
async def export_amocrm(req: ParseRequest):
    result = engine.parse_specification(
        raw_text=req.raw_text,
        price_tier=req.price_tier,
        discount_pct=req.discount_pct,
        include_cross_sell_skus=req.include_cross_sell_skus,
    )
    return build_amocrm_payload(result)

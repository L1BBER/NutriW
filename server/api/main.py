from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .ocr import run_ocr
from .vision import aggregate_by_product, image_embedding_bgr, top_k_similar

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(title="NutriW API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)

# static for stored images
app.mount("/static", StaticFiles(directory=str(db.DATA_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# --------------------------
# Core scan pipeline
# --------------------------

def _confidence_logic(final_conf: float, gap: float) -> Dict[str, Any]:
    warnings: List[str] = []
    need_review = False

    if final_conf < 0.75:
        need_review = True
        warnings.append("Low confidence. Please confirm or edit product info.")
    if gap < 0.08:
        need_review = True
        warnings.append("Ambiguous match. Multiple products look similar.")

    if not warnings:
        warnings.append("OK")

    return {"need_user_review": need_review, "warnings": [w for w in warnings if w != "OK"]}


def _fuse_scores(ocr_conf: float, img_conf: float) -> float:
    # OCR is often weaker; image embedding is stronger baseline here.
    w_txt, w_img = 0.40, 0.60
    return float(w_txt * ocr_conf + w_img * img_conf)


def _parse_percent_from_name(name: str) -> Optional[float]:
    import re

    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*%", name)
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except Exception:
        return None


def _parse_net_from_name(name: str) -> Optional[str]:
    import re

    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|ml|l)\b", name.lower())
    if not m:
        return None
    val = m.group(1).replace(',', '.')
    unit = m.group(2)
    return f"{val} {unit}"


def _adjust_similarity_with_ocr(pname: str, base_sim: float, o) -> float:
    """Re-rank visual matches using OCR-extracted hints (fat %, net volume).

    This is critical for visually similar products like milk 1.5% vs 3.2%.
    """
    sim = float(base_sim)

    # Fat percent hint
    o_pct = getattr(o, "fat_percent", None)
    p_pct = _parse_percent_from_name(pname)
    if o_pct is not None and p_pct is not None:
        diff = abs(o_pct - p_pct)
        if diff <= 0.2:
            sim += 0.10
        elif diff >= 0.6:
            sim -= 0.18

    # Net hint
    o_net = getattr(o, "net", None)
    p_net = _parse_net_from_name(pname)
    if o_net and p_net and o_net == p_net:
        sim += 0.05

    # Clamp
    if sim < 0.0:
        sim = 0.0
    if sim > 1.0:
        sim = 1.0
    return sim


@app.post("/scan/confirm")
async def scan_confirm(image: UploadFile = File(...)):
    """Step 1 OCR + Step 2 visual analysis.

    Returns:
    - products (with candidates)
    - warnings
    - need_user_review
    - recipes (only if confident)
    """
    raw = await image.read()
    np_arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img is None:
        return {"products": [], "recipes": [], "warnings": ["Invalid image"], "need_user_review": True}

    # Step 1: OCR
    o = run_ocr(img)

    # Step 2: Visual
    emb = image_embedding_bgr(img)
    samples = db.load_samples()

    if not samples:
        # No training data yet -> force review
        prod = {
            "name": "",
            "brand": None,
            "amount": o.net,
            "confidence": 0.0,
            "candidates": [],
            "fields": {
                "ocrText": o.text,
                "net": o.net,
                "fat_percent": o.fat_percent,
                "kcal_100": o.kcal_100,
                "p_100": o.p_100,
                "f_100": o.f_100,
                "c_100": o.c_100,
            },
        }
        return {
            "products": [prod],
            "recipes": [],
            "warnings": ["No training data. Please add training samples."],
            "need_user_review": True,
        }

    scored = top_k_similar(emb, samples, k=25)
    agg = aggregate_by_product(scored, top_n=5)

    # OCR-aware re-ranking of aggregated candidates
    reranked = []
    for _, pname, sim in agg:
        adj = _adjust_similarity_with_ocr(pname, sim, o)
        reranked.append((pname, sim, adj))
    reranked.sort(key=lambda x: x[2], reverse=True)

    # Build candidates (show adjusted score as confidence)
    candidates = [{"name": pname, "confidence": round(adj, 3)} for pname, _, adj in reranked]
    best_sim = reranked[0][2] if reranked else 0.0
    second_sim = reranked[1][2] if len(reranked) > 1 else 0.0
    gap = float(best_sim - second_sim)

    final_conf = _fuse_scores(o.confidence, best_sim)
    logic = _confidence_logic(final_conf, gap)

    best_name = candidates[0]["name"] if candidates else ""

    product = {
        "name": best_name,
        "brand": None,
        "amount": o.net,
        "confidence": round(final_conf, 2),
        "candidates": candidates,
        "fields": {
            "ocrText": o.text,
            "net": o.net,
            "fat_percent": o.fat_percent,
            "kcal_100": o.kcal_100,
            "p_100": o.p_100,
            "f_100": o.f_100,
            "c_100": o.c_100,
        },
    }

    recipes = []
    if not logic["need_user_review"]:
        recipes = db.get_recipes_for_products([best_name], max_missing=2)

    return {
        "products": [product],
        "recipes": recipes,
        "warnings": logic["warnings"],
        "need_user_review": logic["need_user_review"],
    }


@app.post("/scan/confirm_user_edit")
async def scan_confirm_user_edit(payload: Dict[str, Any]):
    """User confirms/edits products; server returns recipe suggestions."""
    products = payload.get("products", [])
    names = [p.get("name", "") for p in products]
    recipes = db.get_recipes_for_products(names, max_missing=2)
    return {"recipes": recipes}


# --------------------------
# Training endpoints
# --------------------------

@app.post("/train/add")
async def train_add(
    product_name: str = Form(...),
    default_amount: Optional[str] = Form(None),
    default_weight_g: Optional[str] = Form(None),
    image: UploadFile = File(...),
):
    """Training: user enters product info + uploads photo.

    We store the product and a sample embedding.
    """
    # HTML forms send empty string for optional number inputs; treat '' as None
    parsed_weight: Optional[float] = None
    if default_weight_g is not None:
        s = default_weight_g.strip()
        if s != "":
            try:
                parsed_weight = float(s.replace(",", "."))
            except ValueError:
                return {"ok": False, "error": "default_weight_g must be a number (grams)"}

    pid = db.upsert_product(product_name, default_amount, parsed_weight)

    raw = await image.read()
    np_arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "error": "Invalid image"}

    emb = image_embedding_bgr(img)

    # save image
    safe_name = product_name.strip().lower().replace(" ", "_")
    out_path = db.IMAGES_DIR / f"{safe_name}_{pid}_{image.filename}"
    out_path.write_bytes(raw)

    sid = db.add_sample(pid, str(out_path.relative_to(db.DATA_DIR)), emb)
    return {"ok": True, "product_id": pid, "sample_id": sid}


@app.get("/train/products")
def train_products():
    return {"products": db.list_products()}


# --------------------------
# Recipe management
# --------------------------

@app.post("/recipes/add")
async def recipes_add(payload: Dict[str, Any]):
    """Add recipe.

    payload example:
    {
      "titlePl": "Owsianka",
      "stepsPl": "...",
      "servings": 2,
      "ingredients": [
        {"name":"mleko", "amount_text":"200 ml", "grams":200, "required":true},
        {"name":"płatki owsiane", "amount_text":"50 g", "grams":50, "required":true}
      ]
    }
    """
    title = payload.get("titlePl")
    if not title:
        return {"ok": False, "error": "titlePl is required"}

    steps = payload.get("stepsPl", "")
    servings = int(payload.get("servings", 1))
    ingredients = payload.get("ingredients", [])

    rid = db.add_recipe(title, steps, servings, ingredients)
    return {"ok": True, "recipe_id": rid}


@app.get("/recipes/list")
def recipes_list():
    return {"recipes": db.list_recipes()}


# --------------------------
# Simple Admin UI (optional, for easy demos)
# --------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_home():
    tpl = jinja.get_template("admin.html")
    return tpl.render(
        products=db.list_products(),
        recipes=db.list_recipes(),
    )


@app.get("/health")
def health():
    return {"ok": True}

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
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
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for stored training images and other data assets.
app.mount("/static", StaticFiles(directory=str(db.DATA_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


# --------------------------
# Helpers
# --------------------------


def _parse_optional_number(raw_value: Optional[str], field_name: str) -> Optional[float]:
    if raw_value is None:
        return None

    value = raw_value.strip()
    if not value:
        return None

    try:
        parsed = float(value.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number") from exc

    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")

    return parsed


def _parse_pieces(raw_value: str) -> int:
    value = raw_value.strip()
    if not value:
        raise ValueError("pieces is required")

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("pieces must be an integer") from exc

    if parsed <= 0:
        raise ValueError("pieces must be greater than 0")

    return parsed


def _slugify_filename_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value).strip("_").lower()
    return slug or "product"


def _safe_training_image_name(product_name: str, product_id: int, original_filename: Optional[str]) -> str:
    extension = Path(original_filename or "").suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        extension = ".jpg"

    unique_suffix = uuid.uuid4().hex[:8]
    product_slug = _slugify_filename_part(product_name)
    return f"{product_slug}_{product_id}_{unique_suffix}{extension}"


def _normalize_recipe_payload(payload: Dict[str, Any]) -> tuple[str, str, int, List[Dict[str, Any]]]:
    title = str(payload.get("titlePl", "")).strip()
    if not title:
        raise ValueError("titlePl is required")

    steps = str(payload.get("stepsPl", "")).strip()

    try:
        servings = int(payload.get("servings", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("servings must be an integer") from exc

    if servings <= 0:
        raise ValueError("servings must be greater than 0")

    raw_ingredients = payload.get("ingredients", [])
    if not isinstance(raw_ingredients, list):
        raise ValueError("ingredients must be a list")

    ingredients: List[Dict[str, Any]] = []
    for index, ingredient in enumerate(raw_ingredients, start=1):
        if not isinstance(ingredient, dict):
            raise ValueError(f"ingredient #{index} must be an object")

        name = str(ingredient.get("name", "")).strip()
        if not name:
            raise ValueError(f"ingredient #{index} name is required")

        amount_text = str(ingredient.get("amount_text", "")).strip() or None
        grams_raw = ingredient.get("grams")
        grams_value: Optional[float] = None
        if grams_raw not in (None, ""):
            try:
                grams_value = float(str(grams_raw).replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"ingredient #{index} grams must be a number") from exc
            if grams_value <= 0:
                raise ValueError(f"ingredient #{index} grams must be greater than 0")

        ingredients.append(
            {
                "name": name,
                "amount_text": amount_text,
                "grams": grams_value,
                "required": bool(ingredient.get("required", True)),
            }
        )

    if not ingredients:
        raise ValueError("at least one ingredient is required")

    return title, steps, servings, ingredients


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

    return {"need_user_review": need_review, "warnings": [warning for warning in warnings if warning != "OK"]}


def _fuse_scores(ocr_conf: float, img_conf: float) -> float:
    # OCR is often weaker; image embedding is stronger baseline here.
    w_txt, w_img = 0.40, 0.60
    return float(w_txt * ocr_conf + w_img * img_conf)


def _parse_percent_from_name(name: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*%", name)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except Exception:
        return None


def _parse_net_from_name(name: str) -> Optional[str]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|ml|l)\b", name.lower())
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    unit = match.group(2)
    return f"{value} {unit}"


def _adjust_similarity_with_ocr(product_name: str, base_similarity: float, ocr_result: Any) -> float:
    """Re-rank visual matches using OCR-extracted hints."""
    similarity = float(base_similarity)

    ocr_percent = getattr(ocr_result, "fat_percent", None)
    product_percent = _parse_percent_from_name(product_name)
    if ocr_percent is not None and product_percent is not None:
        diff = abs(ocr_percent - product_percent)
        if diff <= 0.2:
            similarity += 0.10
        elif diff >= 0.6:
            similarity -= 0.18

    ocr_net = getattr(ocr_result, "net", None)
    product_net = _parse_net_from_name(product_name)
    if ocr_net and product_net and ocr_net == product_net:
        similarity += 0.05

    return max(0.0, min(1.0, similarity))


# --------------------------
# Core scan pipeline
# --------------------------


@app.post("/scan/confirm")
async def scan_confirm(image: UploadFile = File(...)):
    """Step 1 OCR + Step 2 visual analysis."""
    raw = await image.read()
    np_arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img is None:
        return {"products": [], "recipes": [], "warnings": ["Invalid image"], "need_user_review": True}

    ocr_result = run_ocr(img)
    embedding = image_embedding_bgr(img)
    samples = db.load_samples()

    if not samples:
        product = {
            "name": "",
            "brand": None,
            "amount": ocr_result.net,
            "confidence": 0.0,
            "candidates": [],
            "fields": {
                "ocrText": ocr_result.text,
                "net": ocr_result.net,
                "fat_percent": ocr_result.fat_percent,
                "kcal_100": ocr_result.kcal_100,
                "p_100": ocr_result.p_100,
                "f_100": ocr_result.f_100,
                "c_100": ocr_result.c_100,
            },
        }
        return {
            "products": [product],
            "recipes": [],
            "warnings": ["No training data. Please add training samples."],
            "need_user_review": True,
        }

    scored = top_k_similar(embedding, samples, k=25)
    aggregated = aggregate_by_product(scored, top_n=5)

    reranked = []
    for _, product_name, similarity in aggregated:
        adjusted_similarity = _adjust_similarity_with_ocr(product_name, similarity, ocr_result)
        reranked.append((product_name, similarity, adjusted_similarity))
    reranked.sort(key=lambda item: item[2], reverse=True)

    candidates = [{"name": product_name, "confidence": round(adjusted_similarity, 3)} for product_name, _, adjusted_similarity in reranked]
    best_similarity = reranked[0][2] if reranked else 0.0
    second_similarity = reranked[1][2] if len(reranked) > 1 else 0.0
    gap = float(best_similarity - second_similarity)

    final_confidence = _fuse_scores(ocr_result.confidence, best_similarity)
    confidence_logic = _confidence_logic(final_confidence, gap)

    best_name = candidates[0]["name"] if candidates else ""
    product = {
        "name": best_name,
        "brand": None,
        "amount": ocr_result.net,
        "confidence": round(final_confidence, 2),
        "candidates": candidates,
        "fields": {
            "ocrText": ocr_result.text,
            "net": ocr_result.net,
            "fat_percent": ocr_result.fat_percent,
            "kcal_100": ocr_result.kcal_100,
            "p_100": ocr_result.p_100,
            "f_100": ocr_result.f_100,
            "c_100": ocr_result.c_100,
        },
    }

    recipes = []
    if not confidence_logic["need_user_review"]:
        recipes = db.get_recipes_for_products([best_name], max_missing=2)

    return {
        "products": [product],
        "recipes": recipes,
        "warnings": confidence_logic["warnings"],
        "need_user_review": confidence_logic["need_user_review"],
    }


@app.post("/scan/confirm_user_edit")
async def scan_confirm_user_edit(payload: Dict[str, Any]):
    """User confirms/edits products; server returns recipe suggestions."""
    products = payload.get("products", [])
    names = [product.get("name", "") for product in products]
    recipes = db.get_recipes_for_products(names, max_missing=2)
    return {"recipes": recipes}


# --------------------------
# Training endpoints
# --------------------------


@app.post("/train/add")
async def train_add(
    product_name: str = Form(...),
    pieces: str = Form(...),
    volume_l: Optional[str] = Form(None),
    weight_g: Optional[str] = Form(None),
    image: UploadFile = File(...),
):
    """Store product metadata and a training image."""
    product_name = product_name.strip()
    if not product_name:
        return {"ok": False, "error": "product_name is required"}

    try:
        parsed_pieces = _parse_pieces(pieces)
        parsed_volume_l = _parse_optional_number(volume_l, "volume_l")
        parsed_weight_g = _parse_optional_number(weight_g, "weight_g")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if parsed_volume_l is not None and parsed_weight_g is not None:
        return {"ok": False, "error": "Use either volume_l or weight_g, not both"}

    raw = await image.read()
    if not raw:
        return {"ok": False, "error": "Image file is empty"}

    np_arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "error": "Invalid image"}

    embedding = image_embedding_bgr(img)
    product_id = db.upsert_product(product_name, parsed_pieces, parsed_volume_l, parsed_weight_g)

    out_path = db.IMAGES_DIR / _safe_training_image_name(product_name, product_id, image.filename)
    out_path.write_bytes(raw)

    sample_id = db.add_sample(product_id, str(out_path.relative_to(db.DATA_DIR)), embedding)
    return {"ok": True, "product_id": product_id, "sample_id": sample_id}


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
        {"name":"platki owsiane", "amount_text":"50 g", "grams":50, "required":true}
      ]
    }
    """
    try:
        title, steps, servings, ingredients = _normalize_recipe_payload(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    recipe_id = db.add_recipe(title, steps, servings, ingredients)
    return {"ok": True, "recipe_id": recipe_id}


@app.put("/recipes/{recipe_id}")
async def recipes_update(recipe_id: int, payload: Dict[str, Any]):
    try:
        title, steps, servings, ingredients = _normalize_recipe_payload(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    updated = db.update_recipe(recipe_id, title, steps, servings, ingredients)
    if not updated:
        return {"ok": False, "error": "recipe not found"}

    return {"ok": True, "recipe_id": recipe_id}


@app.get("/recipes/list")
def recipes_list():
    return {"recipes": db.list_recipes()}


# --------------------------
# Simple Admin UI
# --------------------------


@app.get("/admin", response_class=HTMLResponse)
def admin_home():
    template = jinja.get_template("admin.html")
    return template.render(
        products=db.list_products(),
        recipes=db.list_recipes(),
    )


@app.get("/health")
def health():
    return {"ok": True}

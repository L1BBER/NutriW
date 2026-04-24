from __future__ import annotations

import re
import unicodedata
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageOps, UnidentifiedImageError

from . import db
from .dietary_labels import available_dietary_label_icons, available_dietary_labels, normalize_selected_labels
from .ocr import OcrResult, run_ocr
from .recipe_tools import parse_recipe_source_text
from .recognition import normalize_text as normalize_match_text
from .recognition import rank_catalog
from .vision import image_embedding_bgr

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(title="NutriW API", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(db.DATA_DIR)), name="static")


def _embedding_for_saved_image(image_path: Path) -> Optional[List[float]]:
    try:
        raw = image_path.read_bytes()
    except OSError:
        return None
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        return None
    return image_embedding_bgr(image_bgr)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    db.deduplicate_samples()
    db.refresh_sample_embeddings(_embedding_for_saved_image)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


def _parse_optional_number(raw_value: Any, field_name: str) -> Optional[float]:
    if raw_value is None:
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    try:
        parsed = float(value.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number") from exc

    # Allow 0 as "not used" so users can explicitly zero the irrelevant field.
    if parsed == 0:
        return None

    if parsed < 0:
        raise ValueError(f"{field_name} must be greater than 0")

    return parsed


def _require_measurement(volume_l: Optional[float], weight_g: Optional[float]) -> None:
    return None


def _parse_pieces(raw_value: Any) -> int:
    value = str(raw_value).strip()
    if not value:
        raise ValueError("pieces is required")

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("pieces must be an integer") from exc

    if parsed <= 0:
        raise ValueError("pieces must be greater than 0")

    return parsed


def _parse_aliases(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = re.split(r"[,;\n]", str(raw_value))

    aliases: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        normalized = normalize_match_text(text)
        if not text or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(text)
    return aliases


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


def _decode_image_bytes(raw: bytes) -> Optional[np.ndarray]:
    if not raw:
        return None

    try:
        with Image.open(BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            array = np.asarray(image)
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    if array.size == 0:
        return None

    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def _encode_image_bytes(image_bgr: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise ValueError("Failed to encode image")
    return encoded.tobytes()


def _relative_data_path(path: Path) -> str:
    try:
        return str(path.relative_to(db.DATA_DIR))
    except ValueError:
        return str(path)


def _normalize_recipe_payload(payload: Dict[str, Any]) -> tuple[str, str, int, List[Dict[str, Any]], List[str], str, str]:
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

    source_mode = str(payload.get("sourceMode", "manual")).strip().lower() or "manual"
    if source_mode not in {"manual", "auto"}:
        raise ValueError("sourceMode must be 'manual' or 'auto'")

    source_text = str(payload.get("sourceText", "")).strip()

    raw_ingredients = payload.get("ingredients", [])
    if source_mode == "auto" and (not isinstance(raw_ingredients, list) or not raw_ingredients) and source_text:
        raw_ingredients = parse_recipe_source_text(source_text, db.list_products())
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

    dietary_labels = payload.get("dietaryLabels", [])
    if dietary_labels is None:
        dietary_labels = []
    if not isinstance(dietary_labels, list):
        raise ValueError("dietaryLabels must be a list")

    return title, steps, servings, ingredients, normalize_selected_labels(dietary_labels), source_mode, source_text


def _confidence_logic(final_confidence: float, gap: float) -> Dict[str, Any]:
    warnings: List[str] = []
    need_review = False

    if final_confidence < 0.72:
        need_review = True
        warnings.append("Low confidence. Please confirm or edit product info.")
    if gap < 0.06:
        need_review = True
        warnings.append("Ambiguous match. Multiple products look similar.")

    return {"need_user_review": need_review, "warnings": warnings}


def _serialize_ocr(ocr_result: OcrResult) -> Dict[str, Any]:
    return {
        "text": ocr_result.text,
        "net": ocr_result.net,
        "fat_percent": ocr_result.fat_percent,
        "kcal_100": ocr_result.kcal_100,
        "p_100": ocr_result.p_100,
        "f_100": ocr_result.f_100,
        "c_100": ocr_result.c_100,
        "confidence": round(float(ocr_result.confidence), 3),
        "available": ocr_result.available,
        "warning": ocr_result.warning,
    }


def _fallback_scan_payload(ocr_result: OcrResult, warning: str) -> Dict[str, Any]:
    product = {
        "name": "",
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
        "warnings": [warning],
        "need_user_review": True,
    }


def _analyze_image(image_bgr: np.ndarray, *, top_n: int = 5) -> Dict[str, Any]:
    ocr_result = run_ocr(image_bgr)
    embedding = image_embedding_bgr(image_bgr)
    catalog = db.load_product_catalog()
    candidates = rank_catalog(embedding, ocr_result, catalog, top_n=top_n) if catalog else []
    return {
        "ocr": ocr_result,
        "embedding": embedding,
        "candidates": candidates,
        "catalog_size": len(catalog),
    }


def _build_product_response(candidate: Dict[str, Any], ocr_result: OcrResult, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "name": candidate["name"],
        "dietaryLabels": list(candidate.get("dietary_labels") or []),
        "amount": ocr_result.net,
        "confidence": round(float(candidate["confidence"]), 2),
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


@app.post("/scan/confirm")
async def scan_confirm(image: UploadFile = File(...)):
    raw = await image.read()
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        return {"products": [], "recipes": [], "warnings": ["Invalid image"], "need_user_review": True}

    analysis = _analyze_image(image_bgr, top_n=5)
    ocr_result = analysis["ocr"]
    candidates = analysis["candidates"]

    if not analysis["catalog_size"]:
        return _fallback_scan_payload(ocr_result, "No training data. Please add training samples.")
    if not candidates:
        return _fallback_scan_payload(ocr_result, "No confident product match. Please confirm or edit.")

    best_candidate = candidates[0]
    second_confidence = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
    gap = float(best_candidate["confidence"] - second_confidence)
    confidence_logic = _confidence_logic(float(best_candidate["confidence"]), gap)

    recipes = []
    if not confidence_logic["need_user_review"]:
        recipes = db.get_recipes_for_products([best_candidate["name"]], max_missing=2)

    return {
        "products": [_build_product_response(best_candidate, ocr_result, candidates)],
        "recipes": recipes,
        "warnings": confidence_logic["warnings"],
        "need_user_review": confidence_logic["need_user_review"],
    }


@app.post("/scan/confirm_user_edit")
async def scan_confirm_user_edit(payload: Dict[str, Any]):
    products = payload.get("products", [])
    names = [str(product.get("name", "")).strip() for product in products]
    recipes = db.get_recipes_for_products(names, max_missing=2)
    return {"recipes": recipes}


@app.post("/train/add")
async def train_add(
    product_name: str = Form(...),
    pieces: str = Form(...),
    volume_l: Optional[str] = Form(None),
    weight_g: Optional[str] = Form(None),
    aliases: Optional[str] = Form(None),
    image: UploadFile = File(...),
):
    product_name = product_name.strip()
    if not product_name:
        return {"ok": False, "error": "product_name is required"}

    try:
        parsed_pieces = _parse_pieces(pieces)
        parsed_volume_l = _parse_optional_number(volume_l, "volume_l")
        parsed_weight_g = _parse_optional_number(weight_g, "weight_g")
        parsed_aliases = _parse_aliases(aliases)
        _require_measurement(parsed_volume_l, parsed_weight_g)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    raw = await image.read()
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        return {"ok": False, "error": "Invalid image"}

    embedding = image_embedding_bgr(image_bgr)
    file_hash = db.compute_sample_hash(raw)
    product_id = db.upsert_product(
        product_name,
        parsed_pieces,
        parsed_volume_l,
        parsed_weight_g,
        aliases=parsed_aliases,
    )

    existing_sample = db.find_sample_by_hash(product_id, file_hash)
    if existing_sample is not None:
        return {
            "ok": True,
            "product_id": product_id,
            "sample_id": existing_sample["id"],
            "duplicate_sample": True,
        }

    out_path = db.IMAGES_DIR / _safe_training_image_name(product_name, product_id, image.filename)
    out_path.write_bytes(raw)

    sample_id = db.add_sample(
        product_id,
        _relative_data_path(out_path),
        embedding,
        file_hash=file_hash,
    )
    return {"ok": True, "product_id": product_id, "sample_id": sample_id, "duplicate_sample": False}


@app.get("/train/products")
def train_products():
    return {"products": db.list_products()}


@app.put("/products/{product_id}")
async def products_update(product_id: int, payload: Dict[str, Any]):
    name = str(payload.get("name", "")).strip()

    try:
        pieces = _parse_pieces(payload.get("pieces"))
        volume_l = _parse_optional_number(payload.get("volume_l"), "volume_l")
        weight_g = _parse_optional_number(payload.get("weight_g"), "weight_g")
        aliases = _parse_aliases(payload.get("aliases"))
        _require_measurement(volume_l, weight_g)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        updated = db.update_product(
            product_id,
            name,
            pieces,
            volume_l,
            weight_g,
            aliases=aliases,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if not updated:
        return {"ok": False, "error": "product not found"}

    return {"ok": True, "product_id": product_id}


@app.post("/products/{product_id}/samples")
async def product_sample_add(product_id: int, image: UploadFile = File(...)):
    product_name = db.get_product_name(product_id)
    if not product_name:
        return {"ok": False, "error": "product not found"}

    raw = await image.read()
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        return {"ok": False, "error": "Invalid image"}

    file_hash = db.compute_sample_hash(raw)
    existing_sample = db.find_sample_by_hash(product_id, file_hash)
    if existing_sample is not None:
        return {
            "ok": True,
            "product_id": product_id,
            "sample_id": existing_sample["id"],
            "sample": existing_sample,
            "duplicate_sample": True,
        }

    embedding = image_embedding_bgr(image_bgr)
    out_path = db.IMAGES_DIR / _safe_training_image_name(product_name, product_id, image.filename)
    out_path.write_bytes(raw)
    relative_image_path = _relative_data_path(out_path)
    sample_id = db.add_sample(product_id, relative_image_path, embedding, file_hash=file_hash)
    sample = db.get_sample(product_id, sample_id)

    return {
        "ok": True,
        "product_id": product_id,
        "sample_id": sample_id,
        "sample": sample,
        "duplicate_sample": False,
    }


@app.delete("/products/{product_id}/samples/{sample_id}")
async def product_sample_delete(product_id: int, sample_id: int):
    deleted = db.delete_sample(product_id, sample_id)
    if deleted is None:
        return {"ok": False, "error": "sample not found"}
    return {"ok": True, **deleted}


@app.delete("/products/{product_id}")
async def product_delete(product_id: int):
    deleted = db.delete_product(product_id)
    if deleted is None:
        return {"ok": False, "error": "product not found"}
    return {"ok": True, **deleted}


@app.post("/trainer/predict")
async def trainer_predict(image: UploadFile = File(...)):
    raw = await image.read()
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        return {"ok": False, "error": "Invalid image"}

    analysis = _analyze_image(image_bgr, top_n=6)
    token = uuid.uuid4().hex
    pending_path = db.TRAINER_PENDING_DIR / f"{token}.jpg"
    pending_path.write_bytes(_encode_image_bytes(image_bgr))

    prediction = analysis["candidates"][0] if analysis["candidates"] else None
    return {
        "ok": True,
        "token": token,
        "prediction": prediction,
        "candidates": analysis["candidates"],
        "ocr": _serialize_ocr(analysis["ocr"]),
        "catalog_size": analysis["catalog_size"],
        "original_filename": image.filename,
    }


@app.post("/trainer/confirm")
async def trainer_confirm(payload: Dict[str, Any]):
    token = str(payload.get("token", "")).strip()
    if not token:
        return {"ok": False, "error": "token is required"}

    pending_path = db.TRAINER_PENDING_DIR / f"{token}.jpg"
    if not pending_path.exists():
        return {"ok": False, "error": "Training session expired. Analyze the photo again."}

    raw = pending_path.read_bytes()
    image_bgr = _decode_image_bytes(raw)
    if image_bgr is None:
        pending_path.unlink(missing_ok=True)
        return {"ok": False, "error": "Stored image is invalid"}

    name = str(payload.get("name", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    try:
        pieces = _parse_pieces(payload.get("pieces"))
        volume_l = _parse_optional_number(payload.get("volume_l"), "volume_l")
        weight_g = _parse_optional_number(payload.get("weight_g"), "weight_g")
        aliases = _parse_aliases(payload.get("aliases"))
        _require_measurement(volume_l, weight_g)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    analysis = _analyze_image(image_bgr, top_n=6)
    prediction = analysis["candidates"][0] if analysis["candidates"] else None
    file_hash = db.compute_sample_hash(raw)
    product_id = db.upsert_product(
        name,
        pieces,
        volume_l,
        weight_g,
        aliases=aliases,
    )

    embedding = image_embedding_bgr(image_bgr)
    duplicate_sample = db.find_sample_by_hash(product_id, file_hash)
    if duplicate_sample is not None:
        relative_image_path = duplicate_sample["image_path"]
        sample_id = duplicate_sample["id"]
        duplicate_removed = True
    else:
        original_filename = str(payload.get("original_filename", "")) or f"{token}.jpg"
        out_path = db.IMAGES_DIR / _safe_training_image_name(name, product_id, original_filename)
        out_path.write_bytes(raw)
        relative_image_path = _relative_data_path(out_path)
        sample_id = db.add_sample(product_id, relative_image_path, embedding, file_hash=file_hash)
        duplicate_removed = False

    predicted_name = prediction["name"] if prediction else None
    was_correct = False
    if prediction:
        was_correct = normalize_match_text(predicted_name or "") == normalize_match_text(name)

    feedback_id = db.log_scan_feedback(
        saved_image_path=relative_image_path,
        predicted_product_id=prediction.get("id") if prediction else None,
        predicted_name=predicted_name,
        predicted_brand=None,
        predicted_confidence=float(prediction["confidence"]) if prediction else None,
        confirmed_product_id=product_id,
        confirmed_name=name,
        confirmed_brand=None,
        was_correct=was_correct,
        ocr_text=analysis["ocr"].text,
        candidates=analysis["candidates"],
    )

    pending_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "product_id": product_id,
        "sample_id": sample_id,
        "feedback_id": feedback_id,
        "was_correct": was_correct,
        "saved_name": name,
        "duplicate_sample": duplicate_removed,
    }


@app.post("/recipes/add")
async def recipes_add(payload: Dict[str, Any]):
    try:
        title, steps, servings, ingredients, dietary_labels, source_mode, source_text = _normalize_recipe_payload(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    recipe_id = db.add_recipe(title, steps, servings, ingredients, dietary_labels, source_mode, source_text)
    return {"ok": True, "recipe_id": recipe_id}


@app.put("/recipes/{recipe_id}")
async def recipes_update(recipe_id: int, payload: Dict[str, Any]):
    try:
        title, steps, servings, ingredients, dietary_labels, source_mode, source_text = _normalize_recipe_payload(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    updated = db.update_recipe(recipe_id, title, steps, servings, ingredients, dietary_labels, source_mode, source_text)
    if not updated:
        return {"ok": False, "error": "recipe not found"}

    return {"ok": True, "recipe_id": recipe_id}


@app.post("/recipes/parse-ingredients")
async def recipes_parse_ingredients(payload: Dict[str, Any]):
    source_text = str(payload.get("sourceText", "")).strip()
    if not source_text:
        return {"ok": False, "error": "sourceText is required"}

    ingredients = parse_recipe_source_text(source_text, db.list_products())
    return {"ok": True, "ingredients": ingredients, "detected_count": len(ingredients)}


@app.get("/recipes/list")
def recipes_list():
    return {"recipes": db.list_recipes()}


@app.get("/admin", response_class=HTMLResponse)
def admin_home():
    template = jinja.get_template("admin.html")
    return template.render(
        products=db.list_products(),
        recipes=db.list_recipes(),
        dietary_labels=available_dietary_labels(),
        dietary_label_icons=available_dietary_label_icons(),
    )


@app.get("/trainer", response_class=HTMLResponse)
def trainer_home():
    template = jinja.get_template("trainer.html")
    return template.render(
        product_count=len(db.list_products()),
        sample_count=len(db.load_samples()),
        dietary_label_icons=available_dietary_label_icons(),
    )


@app.get("/health")
def health():
    return {"ok": True}

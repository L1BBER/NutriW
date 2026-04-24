import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .dietary_labels import infer_dietary_labels, normalize_product_labels, normalize_selected_labels
from .text_utils import normalize_text as shared_normalize_text

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
TRAINER_PENDING_DIR = DATA_DIR / "trainer_pending"
DB_PATH = DATA_DIR / "nutriw.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
TRAINER_PENDING_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(cur: sqlite3.Cursor, table_name: str) -> set[str]:
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _normalize_text(value: str) -> str:
    return shared_normalize_text(value)


def _load_string_list(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    try:
        loaded = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    aliases: List[str] = []
    for alias in loaded:
        text = str(alias).strip()
        if text:
            aliases.append(text)
    return aliases


def _load_aliases(raw_aliases: Optional[str]) -> List[str]:
    return _load_string_list(raw_aliases)


def _load_dietary_labels(raw_labels: Optional[str]) -> List[str]:
    return normalize_selected_labels(_load_string_list(raw_labels))


def _load_product_dietary_labels(raw_labels: Optional[str]) -> List[str]:
    return normalize_product_labels(_load_string_list(raw_labels))


def _normalize_aliases(
    aliases: Optional[Iterable[Any]],
    *,
    product_name: Optional[str] = None,
    brand: Optional[str] = None,
) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    blocked = {
        text
        for text in (
            _normalize_text(product_name or ""),
            _normalize_text(brand or ""),
        )
        if text
    }

    for alias in aliases or []:
        text = str(alias).strip()
        normalized = _normalize_text(text)
        if not text or not normalized or normalized in blocked or normalized in seen:
            continue
        seen.add(normalized)
        result.append(text)

    return result


def _infer_product_dietary_labels(product_name: str, aliases: Iterable[str]) -> List[str]:
    return infer_dietary_labels([product_name, *(str(alias) for alias in aliases)])


def _validate_product_measurements(pieces: int, volume_l: Optional[float], weight_g: Optional[float]) -> None:
    if pieces <= 0:
        raise ValueError("pieces must be greater than 0")


def _piece_based(pieces: int, volume_l: Optional[float], weight_g: Optional[float]) -> bool:
    return pieces > 0 and volume_l is None and weight_g is None


def _grams_per_piece(pieces: int, weight_g: Optional[float]) -> Optional[float]:
    if weight_g is None or pieces <= 0:
        return None
    return round(float(weight_g) / float(pieces), 2)


def _enrich_product_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    pieces = int(row["pieces"]) if row.get("pieces") is not None else 1
    volume_l = row.get("volume_l")
    weight_g = row.get("weight_g")
    row["pieces"] = pieces
    row["piece_based"] = _piece_based(pieces, volume_l, weight_g)
    row["grams_per_piece"] = _grams_per_piece(pieces, weight_g)
    return row


def compute_sample_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sample_static_url(image_path: str) -> str:
    normalized_path = str(image_path).replace("\\", "/")
    return f"/static/{normalized_path}"


def _sample_file_path(image_path: str) -> Path:
    return DATA_DIR / str(image_path)


def _sample_hash_for_path(image_path: str) -> Optional[str]:
    file_path = _sample_file_path(image_path)
    try:
        raw = file_path.read_bytes()
    except OSError:
        return None
    return compute_sample_hash(raw)


def _sample_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "image_path": str(row["image_path"]),
        "image_url": _sample_static_url(str(row["image_path"])),
        "created_at": row["created_at"],
    }


def _parse_legacy_amount(default_amount: Optional[str]) -> Dict[str, Optional[float]]:
    parsed: Dict[str, Optional[float]] = {
        "pieces": None,
        "volume_l": None,
        "weight_g": None,
    }
    if not default_amount:
        return parsed

    normalized = default_amount.strip().lower().replace(",", ".")

    piece_match = re.search(r"(\d+)\s*(?:pcs?|pieces?|szt|szt\.|x)\b", normalized)
    if piece_match:
        parsed["pieces"] = float(piece_match.group(1))

    volume_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l)\b", normalized)
    if volume_match:
        value = float(volume_match.group(1))
        unit = volume_match.group(2)
        parsed["volume_l"] = value / 1000.0 if unit == "ml" else value

    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\b", normalized)
    if weight_match:
        value = float(weight_match.group(1))
        unit = weight_match.group(2)
        parsed["weight_g"] = value * 1000.0 if unit == "kg" else value

    return parsed


def _migrate_products_schema(cur: sqlite3.Cursor) -> None:
    columns = _table_columns(cur, "products")

    if "pieces" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN pieces INTEGER NOT NULL DEFAULT 1")
    if "volume_l" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN volume_l REAL")
    if "weight_g" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN weight_g REAL")
    if "brand" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN brand TEXT")
    if "aliases_json" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]'")
    if "dietary_labels_json" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN dietary_labels_json TEXT NOT NULL DEFAULT '[]'")

    columns = _table_columns(cur, "products")
    has_legacy_amount = "default_amount" in columns
    has_legacy_weight = "default_weight_g" in columns

    select_columns = ["id", "name", "pieces", "volume_l", "weight_g", "brand", "aliases_json", "dietary_labels_json"]
    if has_legacy_amount:
        select_columns.append("default_amount")
    if has_legacy_weight:
        select_columns.append("default_weight_g")

    rows = cur.execute(f"SELECT {', '.join(select_columns)} FROM products").fetchall()
    for row in rows:
        legacy_amount = row["default_amount"] if has_legacy_amount else None
        legacy_weight = row["default_weight_g"] if has_legacy_weight else None
        legacy_measurements = _parse_legacy_amount(legacy_amount)

        pieces = row["pieces"]
        volume_l = row["volume_l"]
        weight_g = row["weight_g"]
        aliases = row["aliases_json"]
        dietary_labels_json = row["dietary_labels_json"]

        updates: Dict[str, Any] = {}

        parsed_pieces = int(legacy_measurements["pieces"]) if legacy_measurements["pieces"] else 1
        if pieces is None or int(pieces) < 1:
            updates["pieces"] = parsed_pieces

        if volume_l is None and legacy_measurements["volume_l"] is not None:
            updates["volume_l"] = legacy_measurements["volume_l"]

        if weight_g is None:
            if legacy_measurements["weight_g"] is not None:
                updates["weight_g"] = legacy_measurements["weight_g"]
            elif legacy_weight is not None:
                updates["weight_g"] = float(legacy_weight)

        if aliases is None:
            updates["aliases_json"] = "[]"
            aliases = "[]"

        inferred_labels = _infer_product_dietary_labels(str(row["name"]), _load_aliases(aliases))
        stored_labels = _load_product_dietary_labels(dietary_labels_json)
        if stored_labels != inferred_labels:
            updates["dietary_labels_json"] = json.dumps(inferred_labels, ensure_ascii=True)

        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            params = list(updates.values()) + [row["id"]]
            cur.execute(f"UPDATE products SET {assignments} WHERE id = ?", params)


def _migrate_recipes_schema(cur: sqlite3.Cursor) -> None:
    columns = _table_columns(cur, "recipes")
    if "dietary_labels_json" not in columns:
        cur.execute("ALTER TABLE recipes ADD COLUMN dietary_labels_json TEXT NOT NULL DEFAULT '[]'")
    if "source_mode" not in columns:
        cur.execute("ALTER TABLE recipes ADD COLUMN source_mode TEXT NOT NULL DEFAULT 'manual'")
    if "source_text" not in columns:
        cur.execute("ALTER TABLE recipes ADD COLUMN source_text TEXT NOT NULL DEFAULT ''")


def _migrate_samples_schema(cur: sqlite3.Cursor) -> None:
    columns = _table_columns(cur, "samples")
    if "file_hash" not in columns:
        cur.execute("ALTER TABLE samples ADD COLUMN file_hash TEXT")


def init_db() -> None:
    con = connect()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            brand TEXT,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            dietary_labels_json TEXT NOT NULL DEFAULT '[]',
            pieces INTEGER NOT NULL DEFAULT 1,
            volume_l REAL,
            weight_g REAL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            image_path TEXT NOT NULL,
            file_hash TEXT,
            embedding_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_pl TEXT NOT NULL,
            steps_pl TEXT,
            dietary_labels_json TEXT NOT NULL DEFAULT '[]',
            source_mode TEXT NOT NULL DEFAULT 'manual',
            source_text TEXT NOT NULL DEFAULT '',
            servings INTEGER DEFAULT 1
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount_text TEXT,
            grams REAL,
            required INTEGER DEFAULT 1,
            FOREIGN KEY(recipe_id) REFERENCES recipes(id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_image_path TEXT NOT NULL,
            predicted_product_id INTEGER,
            predicted_name TEXT,
            predicted_brand TEXT,
            predicted_confidence REAL,
            confirmed_product_id INTEGER NOT NULL,
            confirmed_name TEXT NOT NULL,
            confirmed_brand TEXT,
            was_correct INTEGER NOT NULL DEFAULT 0,
            ocr_text TEXT,
            candidates_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(predicted_product_id) REFERENCES products(id),
            FOREIGN KEY(confirmed_product_id) REFERENCES products(id)
        );
        """
    )

    _migrate_products_schema(cur)
    _migrate_recipes_schema(cur)
    _migrate_samples_schema(cur)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_product_hash ON samples(product_id, file_hash)")

    con.commit()
    con.close()


def upsert_product(
    name: str,
    pieces: int,
    volume_l: Optional[float],
    weight_g: Optional[float],
    *,
    brand: Optional[str] = None,
    aliases: Optional[Iterable[Any]] = None,
) -> int:
    _validate_product_measurements(pieces, volume_l, weight_g)

    normalized_name = " ".join(name.strip().split())
    if not normalized_name:
        raise ValueError("Product name is required")

    normalized_brand = " ".join((brand or "").strip().split()) or None
    normalized_aliases = _normalize_aliases(aliases, product_name=normalized_name, brand=normalized_brand)
    inferred_dietary_labels = _infer_product_dietary_labels(normalized_name, normalized_aliases)

    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, brand, aliases_json, dietary_labels_json, pieces, volume_l, weight_g
        FROM products
        WHERE lower(name) = lower(?)
        LIMIT 1
        """,
        (normalized_name,),
    )
    row = cur.fetchone()

    if row:
        existing_brand = row["brand"]
        existing_aliases = _load_aliases(row["aliases_json"])
        resolved_brand = normalized_brand or existing_brand
        merged_aliases = _normalize_aliases(
            [*existing_aliases, *normalized_aliases],
            product_name=normalized_name,
            brand=resolved_brand,
        )
        resolved_dietary_labels = _infer_product_dietary_labels(normalized_name, merged_aliases)

        cur.execute(
            """
            UPDATE products
            SET name = ?, brand = ?, aliases_json = ?, dietary_labels_json = ?, pieces = ?, volume_l = ?, weight_g = ?
            WHERE id = ?
            """,
            (
                normalized_name,
                resolved_brand,
                json.dumps(merged_aliases, ensure_ascii=True),
                json.dumps(resolved_dietary_labels, ensure_ascii=True),
                pieces,
                volume_l,
                weight_g,
                row["id"],
            ),
        )
        con.commit()
        product_id = int(row["id"])
    else:
        cur.execute(
            """
            INSERT INTO products(name, brand, aliases_json, dietary_labels_json, pieces, volume_l, weight_g)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                normalized_name,
                normalized_brand,
                json.dumps(normalized_aliases, ensure_ascii=True),
                json.dumps(inferred_dietary_labels, ensure_ascii=True),
                pieces,
                volume_l,
                weight_g,
            ),
        )
        con.commit()
        product_id = int(cur.lastrowid)

    con.close()
    return product_id


def update_product(
    product_id: int,
    name: str,
    pieces: int,
    volume_l: Optional[float],
    weight_g: Optional[float],
    *,
    brand: Optional[str] = None,
    aliases: Optional[Iterable[Any]] = None,
) -> bool:
    _validate_product_measurements(pieces, volume_l, weight_g)

    normalized_name = " ".join(name.strip().split())
    if not normalized_name:
        raise ValueError("Product name is required")

    normalized_brand = " ".join((brand or "").strip().split()) or None
    normalized_aliases = _normalize_aliases(aliases, product_name=normalized_name, brand=normalized_brand)
    resolved_dietary_labels = _infer_product_dietary_labels(normalized_name, normalized_aliases)

    con = connect()
    cur = con.cursor()

    cur.execute("SELECT id FROM products WHERE id = ?", (product_id,))
    if cur.fetchone() is None:
        con.close()
        return False

    cur.execute(
        """
        SELECT id
        FROM products
        WHERE lower(name) = lower(?) AND id != ?
        LIMIT 1
        """,
        (normalized_name, product_id),
    )
    if cur.fetchone() is not None:
        con.close()
        raise ValueError("Another product with this name already exists")

    cur.execute(
        """
        UPDATE products
        SET name = ?, brand = ?, aliases_json = ?, dietary_labels_json = ?, pieces = ?, volume_l = ?, weight_g = ?
        WHERE id = ?
        """,
        (
            normalized_name,
            normalized_brand,
            json.dumps(normalized_aliases, ensure_ascii=True),
            json.dumps(resolved_dietary_labels, ensure_ascii=True),
            pieces,
            volume_l,
            weight_g,
            product_id,
        ),
    )

    con.commit()
    con.close()
    return True


def delete_product(product_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()

    product_row = cur.execute(
        """
        SELECT id, name
        FROM products
        WHERE id = ?
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if product_row is None:
        con.close()
        return None

    sample_rows = cur.execute(
        """
        SELECT id, image_path
        FROM samples
        WHERE product_id = ?
        ORDER BY id
        """,
        (product_id,),
    ).fetchall()

    image_paths = sorted({str(row["image_path"]) for row in sample_rows})
    deleted_sample_count = len(sample_rows)

    cur.execute("DELETE FROM samples WHERE product_id = ?", (product_id,))
    feedback_rows = cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM scan_feedback
        WHERE predicted_product_id = ? OR confirmed_product_id = ?
        """,
        (product_id, product_id),
    ).fetchone()
    deleted_feedback_count = int(feedback_rows["count"]) if feedback_rows is not None else 0
    cur.execute(
        """
        DELETE FROM scan_feedback
        WHERE predicted_product_id = ? OR confirmed_product_id = ?
        """,
        (product_id, product_id),
    )
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))

    con.commit()
    con.close()

    deleted_file_count = 0
    for image_path in image_paths:
        con = connect()
        cur = con.cursor()
        still_used = cur.execute(
            "SELECT 1 FROM samples WHERE image_path = ? LIMIT 1",
            (image_path,),
        ).fetchone()
        con.close()
        if still_used is not None:
            continue
        try:
            _sample_file_path(image_path).unlink(missing_ok=True)
            deleted_file_count += 1
        except OSError:
            continue

    return {
        "product_id": int(product_row["id"]),
        "product_name": str(product_row["name"]),
        "deleted_samples": deleted_sample_count,
        "deleted_files": deleted_file_count,
        "deleted_feedback": deleted_feedback_count,
    }


def list_products() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, aliases_json, dietary_labels_json, pieces, volume_l, weight_g
        FROM products
        ORDER BY name
        """
    )
    rows = [dict(r) for r in cur.fetchall()]

    sample_rows = cur.execute(
        """
        SELECT id, product_id, image_path, created_at
        FROM samples
        ORDER BY product_id, id DESC
        """
    ).fetchall()
    con.close()

    samples_by_product: Dict[int, List[Dict[str, Any]]] = {}
    for sample_row in sample_rows:
        product_id = int(sample_row["product_id"])
        samples_by_product.setdefault(product_id, []).append(_sample_to_dict(sample_row))

    for row in rows:
        product_id = int(row["id"])
        row["aliases"] = _load_aliases(row.pop("aliases_json", None))
        row["dietary_labels"] = _load_product_dietary_labels(row.pop("dietary_labels_json", None))
        row["samples"] = samples_by_product.get(product_id, [])
        row["sample_count"] = len(row["samples"])
        _enrich_product_fields(row)

    return rows


def load_samples() -> List[Tuple[int, str, List[float]]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT s.product_id, p.name as product_name, s.embedding_json
        FROM samples s
        JOIN products p ON p.id = s.product_id
        """
    )
    out = []
    for row in cur.fetchall():
        out.append((int(row["product_id"]), str(row["product_name"]), json.loads(row["embedding_json"])))
    con.close()
    return out


def load_product_catalog() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            p.id,
            p.name,
            p.aliases_json,
            p.dietary_labels_json,
            p.pieces,
            p.volume_l,
            p.weight_g,
            s.embedding_json
        FROM products p
        LEFT JOIN samples s ON s.product_id = p.id
        ORDER BY p.id
        """
    )

    products: Dict[int, Dict[str, Any]] = {}
    for row in cur.fetchall():
        product_id = int(row["id"])
        if product_id not in products:
            products[product_id] = _enrich_product_fields(
                {
                "id": product_id,
                "name": str(row["name"]),
                "aliases": _load_aliases(row["aliases_json"]),
                "dietary_labels": _load_product_dietary_labels(row["dietary_labels_json"]),
                "pieces": int(row["pieces"]) if row["pieces"] is not None else 1,
                "volume_l": row["volume_l"],
                "weight_g": row["weight_g"],
                "embeddings": [],
                }
            )
        if row["embedding_json"]:
            products[product_id]["embeddings"].append(json.loads(row["embedding_json"]))

    con.close()
    return list(products.values())


def find_sample_by_hash(product_id: int, file_hash: str) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    row = cur.execute(
        """
        SELECT id, image_path, created_at
        FROM samples
        WHERE product_id = ? AND file_hash = ?
        ORDER BY id
        LIMIT 1
        """,
        (product_id, file_hash),
    ).fetchone()
    con.close()
    if row is None:
        return None
    return _sample_to_dict(row)


def get_product_name(product_id: int) -> Optional[str]:
    con = connect()
    cur = con.cursor()
    row = cur.execute("SELECT name FROM products WHERE id = ? LIMIT 1", (product_id,)).fetchone()
    con.close()
    if row is None:
        return None
    return str(row["name"])


def get_sample(product_id: int, sample_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    row = cur.execute(
        """
        SELECT id, image_path, created_at
        FROM samples
        WHERE id = ? AND product_id = ?
        LIMIT 1
        """,
        (sample_id, product_id),
    ).fetchone()
    con.close()
    if row is None:
        return None
    return _sample_to_dict(row)


def delete_sample(product_id: int, sample_id: int) -> Optional[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    row = cur.execute(
        """
        SELECT image_path
        FROM samples
        WHERE id = ? AND product_id = ?
        LIMIT 1
        """,
        (sample_id, product_id),
    ).fetchone()
    if row is None:
        con.close()
        return None

    image_path = str(row["image_path"])
    cur.execute("DELETE FROM samples WHERE id = ?", (sample_id,))

    still_used = cur.execute(
        "SELECT 1 FROM samples WHERE image_path = ? LIMIT 1",
        (image_path,),
    ).fetchone()
    con.commit()
    con.close()

    removed_file = False
    if still_used is None:
        try:
            _sample_file_path(image_path).unlink(missing_ok=True)
            removed_file = True
        except OSError:
            removed_file = False

    return {"sample_id": sample_id, "image_path": image_path, "removed_file": removed_file}


def add_sample(product_id: int, image_path: str, embedding: List[float], *, file_hash: Optional[str] = None) -> int:
    resolved_hash = file_hash or _sample_hash_for_path(image_path)
    con = connect()
    cur = con.cursor()
    if resolved_hash:
        existing_row = cur.execute(
            """
            SELECT id
            FROM samples
            WHERE product_id = ? AND file_hash = ?
            ORDER BY id
            LIMIT 1
            """,
            (product_id, resolved_hash),
        ).fetchone()
        if existing_row is not None:
            con.close()
            return int(existing_row["id"])

    cur.execute(
        "INSERT INTO samples(product_id, image_path, file_hash, embedding_json) VALUES (?,?,?,?)",
        (product_id, image_path, resolved_hash, json.dumps(embedding)),
    )
    con.commit()
    sample_id = int(cur.lastrowid)
    con.close()
    return sample_id


def refresh_sample_embeddings(embedding_builder: Callable[[Path], Optional[List[float]]]) -> int:
    con = connect()
    cur = con.cursor()
    rows = cur.execute("SELECT id, image_path FROM samples ORDER BY id").fetchall()
    updated = 0

    for row in rows:
        image_path = DATA_DIR / str(row["image_path"])
        if not image_path.exists():
            continue

        embedding = embedding_builder(image_path)
        if not embedding:
            continue

        cur.execute(
            "UPDATE samples SET embedding_json = ? WHERE id = ?",
            (json.dumps(embedding), int(row["id"])),
        )
        updated += 1

    con.commit()
    con.close()
    return updated


def deduplicate_samples() -> Dict[str, int]:
    con = connect()
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT id, product_id, image_path, file_hash
        FROM samples
        ORDER BY product_id, id
        """
    ).fetchall()

    hash_updates: List[tuple[str, int]] = []
    rows_by_group: Dict[tuple[int, str], List[sqlite3.Row]] = {}
    for row in rows:
        file_hash = row["file_hash"] or _sample_hash_for_path(str(row["image_path"]))
        if not file_hash:
            continue
        if row["file_hash"] != file_hash:
            hash_updates.append((file_hash, int(row["id"])))
        rows_by_group.setdefault((int(row["product_id"]), file_hash), []).append(row)

    if hash_updates:
        cur.executemany("UPDATE samples SET file_hash = ? WHERE id = ?", hash_updates)

    paths_to_delete: set[Path] = set()
    removed_samples = 0

    for grouped_rows in rows_by_group.values():
        if len(grouped_rows) < 2:
            continue

        keeper = sorted(
            grouped_rows,
            key=lambda row: (0 if _sample_file_path(str(row["image_path"])).exists() else 1, int(row["id"])),
        )[0]
        for duplicate_row in grouped_rows:
            if int(duplicate_row["id"]) == int(keeper["id"]):
                continue
            duplicate_image_path = str(duplicate_row["image_path"])
            cur.execute("DELETE FROM samples WHERE id = ?", (int(duplicate_row["id"]),))
            removed_samples += 1

            still_used = cur.execute(
                "SELECT 1 FROM samples WHERE image_path = ? LIMIT 1",
                (duplicate_image_path,),
            ).fetchone()
            if still_used is None:
                paths_to_delete.add(_sample_file_path(duplicate_image_path))

    con.commit()
    con.close()

    removed_files = 0
    for file_path in paths_to_delete:
        try:
            file_path.unlink(missing_ok=True)
            removed_files += 1
        except OSError:
            continue

    return {"removed_samples": removed_samples, "removed_files": removed_files}


def log_scan_feedback(
    *,
    saved_image_path: str,
    predicted_product_id: Optional[int],
    predicted_name: Optional[str],
    predicted_brand: Optional[str],
    predicted_confidence: Optional[float],
    confirmed_product_id: int,
    confirmed_name: str,
    confirmed_brand: Optional[str],
    was_correct: bool,
    ocr_text: Optional[str],
    candidates: List[Dict[str, Any]],
) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO scan_feedback(
            saved_image_path,
            predicted_product_id,
            predicted_name,
            predicted_brand,
            predicted_confidence,
            confirmed_product_id,
            confirmed_name,
            confirmed_brand,
            was_correct,
            ocr_text,
            candidates_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            saved_image_path,
            predicted_product_id,
            predicted_name,
            predicted_brand,
            predicted_confidence,
            confirmed_product_id,
            confirmed_name,
            confirmed_brand,
            1 if was_correct else 0,
            ocr_text,
            json.dumps(candidates, ensure_ascii=True),
        ),
    )
    con.commit()
    feedback_id = int(cur.lastrowid)
    con.close()
    return feedback_id


def _replace_recipe_ingredients(cur: sqlite3.Cursor, recipe_id: int, ingredients: List[Dict[str, Any]]) -> None:
    cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))

    for ingredient in ingredients:
        cur.execute(
            """
            INSERT INTO recipe_ingredients(recipe_id, name, amount_text, grams, required)
            VALUES (?,?,?,?,?)
            """,
            (
                recipe_id,
                str(ingredient.get("name", "")).strip().lower(),
                ingredient.get("amount_text"),
                ingredient.get("grams"),
                1 if ingredient.get("required", True) else 0,
            ),
        )


def add_recipe(
    title_pl: str,
    steps_pl: str,
    servings: int,
    ingredients: List[Dict[str, Any]],
    dietary_labels: List[str],
    source_mode: str = "manual",
    source_text: str = "",
) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO recipes(title_pl, steps_pl, dietary_labels_json, source_mode, source_text, servings) VALUES(?,?,?,?,?,?)",
        (
            title_pl.strip(),
            steps_pl.strip(),
            json.dumps(normalize_selected_labels(dietary_labels), ensure_ascii=True),
            source_mode.strip().lower() or "manual",
            source_text.strip(),
            int(servings),
        ),
    )
    recipe_id = int(cur.lastrowid)

    _replace_recipe_ingredients(cur, recipe_id, ingredients)

    con.commit()
    con.close()
    return recipe_id


def update_recipe(
    recipe_id: int,
    title_pl: str,
    steps_pl: str,
    servings: int,
    ingredients: List[Dict[str, Any]],
    dietary_labels: List[str],
    source_mode: str = "manual",
    source_text: str = "",
) -> bool:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM recipes WHERE id = ?", (recipe_id,))
    if cur.fetchone() is None:
        con.close()
        return False

    cur.execute(
        """
        UPDATE recipes
        SET title_pl = ?, steps_pl = ?, dietary_labels_json = ?, source_mode = ?, source_text = ?, servings = ?
        WHERE id = ?
        """,
        (
            title_pl.strip(),
            steps_pl.strip(),
            json.dumps(normalize_selected_labels(dietary_labels), ensure_ascii=True),
            source_mode.strip().lower() or "manual",
            source_text.strip(),
            int(servings),
            recipe_id,
        ),
    )

    _replace_recipe_ingredients(cur, recipe_id, ingredients)

    con.commit()
    con.close()
    return True


def list_recipes() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT id, title_pl, steps_pl, dietary_labels_json, source_mode, source_text, servings FROM recipes ORDER BY id DESC"
    )
    recipes = [dict(row) for row in cur.fetchall()]

    for recipe in recipes:
        recipe["dietary_labels"] = _load_dietary_labels(recipe.pop("dietary_labels_json", None))
        cur.execute(
            "SELECT name, amount_text, grams, required FROM recipe_ingredients WHERE recipe_id = ?",
            (recipe["id"],),
        )
        recipe["ingredients"] = [dict(row) for row in cur.fetchall()]

    con.close()
    return recipes


def get_recipes_for_products(product_names: List[str], max_missing: int = 2) -> List[Dict[str, Any]]:
    available = {name.strip().lower() for name in product_names if name.strip()}

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title_pl, dietary_labels_json, servings FROM recipes")
    recipes = []

    for recipe_row in cur.fetchall():
        recipe_id = int(recipe_row["id"])
        cur.execute(
            "SELECT name, amount_text, grams, required FROM recipe_ingredients WHERE recipe_id = ?",
            (recipe_id,),
        )
        ingredients = [dict(row) for row in cur.fetchall()]

        required = [ingredient["name"] for ingredient in ingredients if int(ingredient.get("required", 1)) == 1]
        missing = [name for name in required if name not in available]
        if len(missing) <= max_missing:
            coverage = 0.0
            if required:
                coverage = (len(required) - len(missing)) / len(required)
            recipes.append(
                {
                    "id": recipe_id,
                    "titlePl": recipe_row["title_pl"],
                    "missing": missing,
                    "coverage": coverage,
                    "dietaryLabels": _load_dietary_labels(recipe_row["dietary_labels_json"]),
                    "servings": int(recipe_row["servings"]),
                }
            )

    con.close()
    recipes.sort(key=lambda recipe: (recipe["coverage"], -len(recipe["missing"])), reverse=True)
    return recipes

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "nutriw.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(cur: sqlite3.Cursor, table_name: str) -> set[str]:
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


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

    columns = _table_columns(cur, "products")
    has_legacy_amount = "default_amount" in columns
    has_legacy_weight = "default_weight_g" in columns

    select_columns = ["id", "pieces", "volume_l", "weight_g"]
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

        updates: Dict[str, Any] = {}

        parsed_pieces = int(legacy_measurements["pieces"]) if legacy_measurements["pieces"] else 1
        if pieces is None or int(pieces) < 1:
            updates["pieces"] = parsed_pieces

        if volume_l is None and legacy_measurements["volume_l"] is not None:
            updates["volume_l"] = legacy_measurements["volume_l"]

        # Keep only one measurement type. Volume wins over weight when both exist.
        resolved_volume_l = updates.get("volume_l", volume_l)
        if resolved_volume_l is None:
            if weight_g is None:
                if legacy_measurements["weight_g"] is not None:
                    updates["weight_g"] = legacy_measurements["weight_g"]
                elif legacy_weight is not None:
                    updates["weight_g"] = float(legacy_weight)
        elif weight_g is not None:
            updates["weight_g"] = None

        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            params = list(updates.values()) + [row["id"]]
            cur.execute(f"UPDATE products SET {assignments} WHERE id = ?", params)


def init_db() -> None:
    con = connect()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
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

    _migrate_products_schema(cur)

    con.commit()
    con.close()


# --- Products ---

def upsert_product(
    name: str,
    pieces: int,
    volume_l: Optional[float],
    weight_g: Optional[float],
) -> int:
    if volume_l is not None and weight_g is not None:
        raise ValueError("Use either volume_l or weight_g, not both")

    con = connect()
    cur = con.cursor()
    normalized_name = name.strip()

    cur.execute("SELECT id FROM products WHERE name = ?", (normalized_name,))
    row = cur.fetchone()

    if row:
        cur.execute(
            """
            UPDATE products
            SET pieces = ?, volume_l = ?, weight_g = ?
            WHERE id = ?
            """,
            (pieces, volume_l, weight_g, row["id"]),
        )
        con.commit()
        product_id = int(row["id"])
    else:
        cur.execute(
            "INSERT INTO products(name, pieces, volume_l, weight_g) VALUES(?,?,?,?)",
            (normalized_name, pieces, volume_l, weight_g),
        )
        con.commit()
        product_id = int(cur.lastrowid)

    con.close()
    return product_id


def list_products() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, pieces, volume_l, weight_g
        FROM products
        ORDER BY name
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    for row in rows:
        row["pieces"] = int(row["pieces"]) if row["pieces"] is not None else 1

    return rows


# --- Samples ---

def add_sample(product_id: int, image_path: str, embedding: List[float]) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO samples(product_id, image_path, embedding_json) VALUES (?,?,?)",
        (product_id, image_path, json.dumps(embedding)),
    )
    con.commit()
    sample_id = int(cur.lastrowid)
    con.close()
    return sample_id


def load_samples() -> List[Tuple[int, str, List[float]]]:
    """Return list of (product_id, product_name, embedding)."""
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


# --- Recipes ---

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


def add_recipe(title_pl: str, steps_pl: str, servings: int, ingredients: List[Dict[str, Any]]) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO recipes(title_pl, steps_pl, servings) VALUES(?,?,?)",
        (title_pl.strip(), steps_pl.strip(), int(servings)),
    )
    recipe_id = int(cur.lastrowid)

    _replace_recipe_ingredients(cur, recipe_id, ingredients)

    con.commit()
    con.close()
    return recipe_id


def update_recipe(recipe_id: int, title_pl: str, steps_pl: str, servings: int, ingredients: List[Dict[str, Any]]) -> bool:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM recipes WHERE id = ?", (recipe_id,))
    if cur.fetchone() is None:
        con.close()
        return False

    cur.execute(
        """
        UPDATE recipes
        SET title_pl = ?, steps_pl = ?, servings = ?
        WHERE id = ?
        """,
        (title_pl.strip(), steps_pl.strip(), int(servings), recipe_id),
    )

    _replace_recipe_ingredients(cur, recipe_id, ingredients)

    con.commit()
    con.close()
    return True


def list_recipes() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title_pl, steps_pl, servings FROM recipes ORDER BY id DESC")
    recipes = [dict(row) for row in cur.fetchall()]

    for recipe in recipes:
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
    cur.execute("SELECT id, title_pl, servings FROM recipes")
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
                    "servings": int(recipe_row["servings"]),
                }
            )

    con.close()
    recipes.sort(key=lambda recipe: (recipe["coverage"], -len(recipe["missing"])), reverse=True)
    return recipes

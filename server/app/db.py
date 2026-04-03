import json
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


def init_db() -> None:
    con = connect()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            default_amount TEXT,
            default_weight_g REAL
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

    con.commit()
    con.close()


# --- Products ---

def upsert_product(name: str, default_amount: Optional[str], default_weight_g: Optional[float]) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM products WHERE name = ?", (name.strip(),))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE products SET default_amount = COALESCE(?, default_amount), default_weight_g = COALESCE(?, default_weight_g) WHERE id = ?",
            (default_amount, default_weight_g, row["id"]),
        )
        con.commit()
        pid = int(row["id"])
    else:
        cur.execute(
            "INSERT INTO products(name, default_amount, default_weight_g) VALUES(?,?,?)",
            (name.strip(), default_amount, default_weight_g),
        )
        con.commit()
        pid = int(cur.lastrowid)
    con.close()
    return pid


def list_products() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, name, default_amount, default_weight_g FROM products ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
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
    sid = int(cur.lastrowid)
    con.close()
    return sid


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
    for r in cur.fetchall():
        out.append((int(r["product_id"]), str(r["product_name"]), json.loads(r["embedding_json"])))
    con.close()
    return out


# --- Recipes ---

def add_recipe(title_pl: str, steps_pl: str, servings: int, ingredients: List[Dict[str, Any]]) -> int:
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO recipes(title_pl, steps_pl, servings) VALUES(?,?,?)",
        (title_pl.strip(), steps_pl.strip(), int(servings)),
    )
    rid = int(cur.lastrowid)

    for ing in ingredients:
        cur.execute(
            """
            INSERT INTO recipe_ingredients(recipe_id, name, amount_text, grams, required)
            VALUES (?,?,?,?,?)
            """,
            (
                rid,
                str(ing.get("name", "")).strip().lower(),
                ing.get("amount_text"),
                ing.get("grams"),
                1 if ing.get("required", True) else 0,
            ),
        )

    con.commit()
    con.close()
    return rid


def list_recipes() -> List[Dict[str, Any]]:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title_pl, servings FROM recipes ORDER BY id DESC")
    recs = [dict(r) for r in cur.fetchall()]

    for r in recs:
        cur.execute(
            "SELECT name, amount_text, grams, required FROM recipe_ingredients WHERE recipe_id = ?",
            (r["id"],),
        )
        r["ingredients"] = [dict(x) for x in cur.fetchall()]

    con.close()
    return recs


def get_recipes_for_products(product_names: List[str], max_missing: int = 2) -> List[Dict[str, Any]]:
    available = set([p.strip().lower() for p in product_names if p.strip()])

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title_pl, servings FROM recipes")
    recipes = []
    for rr in cur.fetchall():
        rid = int(rr["id"])
        cur.execute(
            "SELECT name, amount_text, grams, required FROM recipe_ingredients WHERE recipe_id = ?",
            (rid,),
        )
        ings = [dict(x) for x in cur.fetchall()]

        required = [i["name"] for i in ings if int(i.get("required", 1)) == 1]
        missing = [x for x in required if x not in available]
        if len(missing) <= max_missing:
            coverage = 0.0
            if required:
                coverage = (len(required) - len(missing)) / len(required)
            recipes.append(
                {
                    "id": rid,
                    "titlePl": rr["title_pl"],
                    "missing": missing,
                    "coverage": coverage,
                    "servings": int(rr["servings"]),
                }
            )

    con.close()
    recipes.sort(key=lambda x: (x["coverage"], -len(x["missing"])), reverse=True)
    return recipes

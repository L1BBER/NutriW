# NutriW

NutriW is a full-stack product recognition project with:
- an Android scanning app in `android/mobile-app`
- a FastAPI backend in `server/`
- a dedicated mobile-friendly training web app at `/trainer`

The goal is simple:
1. take a photo of a food product
2. let the server guess what it is
3. confirm or correct the result
4. use that feedback to improve future recognition

## Current recognition pipeline

The backend now uses a stronger hybrid pipeline than before:
- image preprocessing with EXIF-aware decoding
- multi-view package embedding based on color layout, edges, and structure
- OCR with cached EasyOCR reader and multiple preprocessing variants
- reranking with image score, OCR text overlap, and measurement hints
- automatic sample embedding refresh on startup, so older saved images are upgraded to the current embedding format

## Main flows

### Android scan app

The Android app is still the main user-facing scanner:
1. take a product photo
2. send it to `/scan/confirm`
3. review the suggested product
4. confirm or edit the result
5. receive recipe suggestions

### Trainer app

The new training app is available in the browser at:
- `http://<server-ip>:8000/trainer`

It is designed for phone use and supports this workflow:
1. take a product photo in the mobile browser
2. see the AI prediction and top candidates
3. confirm or correct product name, brand, aliases, pieces, liters, or grams
4. save the image as a new training sample
5. record whether the AI was correct or needed correction

This is the fastest way to build a better dataset for the model without touching the database manually.

## Server endpoints

Core recognition:
- `POST /scan/confirm` - scan a product photo and return candidates, warnings, and recipes
- `POST /scan/confirm_user_edit` - accept corrected product names and return recipes

Training:
- `POST /train/add` - manual admin upload of a training sample
- `GET /train/products` - list trained products with brand, aliases, and measurements
- `GET /trainer` - open the dedicated training web app
- `POST /trainer/predict` - analyze a trainer image and return AI suggestions
- `POST /trainer/confirm` - confirm or correct a trainer prediction and save it as training data

Recipes:
- `POST /recipes/add` - add a recipe
- `PUT /recipes/{recipe_id}` - update a saved recipe
- `GET /recipes/list` - list saved recipes

UI and diagnostics:
- `GET /admin` - admin page with manual training form and recipe editor
- `GET /docs` - Swagger UI
- `GET /health` - health check

## Data layout

Server data is stored in:
- `server/data/nutriw.db` - SQLite database
- `server/data/images/` - saved training images
- `server/data/trainer_pending/` - temporary trainer uploads before confirmation

Important product metadata now stored by the backend:
- canonical product name
- optional brand
- optional aliases
- required `pieces`
- optional `volume_l`
- optional `weight_g`

`volume_l` and `weight_g` are mutually exclusive.

## Project structure

- `android/mobile-app` - Kotlin + Jetpack Compose Android client
- `server/api` - FastAPI app, OCR, ranking, templates, DB helpers
- `server/scripts` - local helper scripts
- `server/data` - SQLite data and stored product images

## Run the server

### Windows

Quick start from the project root:

```powershell
Set-Location .\server
.\scripts\run-server.ps1
```

If you are already inside `server/`, run:

```powershell
.\scripts\run-server.ps1
```

Manual startup on Windows:

```powershell
Set-Location .\server
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

After startup:
- Swagger UI: `http://127.0.0.1:8000/docs`
- Admin page: `http://127.0.0.1:8000/admin`
- Trainer app: `http://127.0.0.1:8000/trainer`
- Health check: `http://127.0.0.1:8000/health`

### Linux or macOS

From `server/` run:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Android app

Open `android/mobile-app` in Android Studio.

Open the Android project folder from PowerShell:

```powershell
Set-Location .\android\mobile-app
```

The server address is configured in:
- `android/mobile-app/app/src/main/java/com/example/nutriw/data/api/NetworkModule.kt`

Current default:
- Android Emulator: `http://10.0.2.2:8000`

If you use a real phone, replace it with:
- `http://<YOUR_PC_IP>:8000`

## Notes

- For best OCR quality, install EasyOCR in the server environment. The app still runs without it, but text-based reranking will be weaker.
- On startup, the backend refreshes saved sample embeddings from the stored images, so old training data stays compatible with the current visual embedding format.
- Low-confidence or ambiguous matches are intentionally sent back for manual confirmation.
- Build caches, local environments, IDE files, and other generated artifacts are ignored by `.gitignore`.

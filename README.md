# NutriW

NutriW is a small full-stack app for scanning food products and suggesting recipes.

The project has two parts:
- `android/mobile-app` - Android client built with Kotlin and Jetpack Compose
- `server/` - backend folder with API code, scripts, data, and local server environment

## What the app does

Current user flow:
1. Take a photo of a product in the Android app.
2. Send the image to the server.
3. The server combines OCR and visual similarity to detect the product.
4. The app shows the detected product for user review and correction.
5. After confirmation, the server returns matching recipe suggestions.

## Server features

The server currently provides:
- `POST /scan/confirm` - scan a product photo and return detected products, warnings, and recipes
- `POST /scan/confirm_user_edit` - accept corrected product names and return recipe suggestions
- `POST /train/add` - add a product and training photo
- `GET /train/products` - list trained products
- `POST /recipes/add` - add a recipe
- `GET /recipes/list` - list saved recipes
- `GET /admin` - simple admin page for demo/testing
- `GET /docs` - Swagger UI
- `GET /health` - health check

Server data is stored here:
- `server/data/nutriw.db` - SQLite database
- `server/data/images/` - training images and stored product photos

Server code is organized as:
- `server/api/` - FastAPI application code
- `server/scripts/` - local helper scripts
- `server/data/` - database and stored images

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

Manual Windows startup:

```powershell
Set-Location .\server
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The script:
- switches to the `server` folder
- recreates `venv` if it was copied from an old path
- installs dependencies from `requirements.txt`
- starts `uvicorn`

### Linux or macOS

From `server/` run:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

After startup:
- API docs: `http://<server-ip>:8000/docs`
- Admin page: `http://<server-ip>:8000/admin`
- Health check: `http://<server-ip>:8000/health`

## Android app

Open `android/mobile-app` in Android Studio.

Open the Android project folder from PowerShell:

```powershell
Set-Location .\android\mobile-app
```

Server address is configured in:
- `android/mobile-app/app/src/main/java/com/example/nutriw/data/api/NetworkModule.kt`

Current default:
- Android Emulator: `http://10.0.2.2:8000`

If you use a real phone, replace it with:
- `http://<YOUR_PC_IP>:8000`

## Notes

- OCR support is optional in `server/requirements.txt`.
- Low-confidence matches are intentionally sent back for manual confirmation.
- Build caches, local environments, IDE files, and other generated artifacts are ignored by `.gitignore`.

# NutriW (Android + Server)

This archive contains:
- `android/NutriW_android` — Android client (Camera -> upload -> show results)
- `server/` — FastAPI server with:
  - 2-step image pipeline: OCR -> Visual analysis
  - confidence + warnings when not sure
  - training endpoint (enter product + upload photo)
  - recipe storage + recipe suggestions

## Server setup (Windows / Linux)

```bash
cd server
python -m venv venv
# Windows: venv\\Scripts\\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:
- API docs: `http://<server-ip>:8000/docs`
- Admin demo UI: `http://<server-ip>:8000/admin`

### Training ("teaching" the AI)
Use `/admin` page or API:
- `POST /train/add` (form-data): `product_name`, optional `default_amount`, optional `default_weight_g`, and `image`.

### Add recipes
Use Swagger (`/docs`) -> `POST /recipes/add`.

## Android client

Open `android/NutriW_android` in Android Studio.

Edit server address in:
`app/src/main/java/com/example/nutriw/data/api/NetworkModule.kt`

- Emulator: `http://10.0.2.2:8000`
- Real phone: `http://<your-PC-LAN-IP>:8000`
- Public tunnel/cloud: `https://...`


# Deploying to Render

`render.yaml` describes one free web service that serves the API, the frontend and the WebSocket. Secrets are not in the file; Render asks for them when you create the Blueprint.

## 1. MongoDB Atlas

- **Network Access:** add `0.0.0.0/0`. Render's free plan has no fixed outgoing IP, so the cluster is reachable from anywhere and protected only by its credentials.
- **Database user:** give the app its own user with a long random password and `readWrite` on just `irminsul_prod` and `irminsul` (the model files live in `irminsul`). Don't give it an Atlas admin role.

## 2. Model files

The ONNX model is not in git. Upload it once from a machine that has it:

```bash
uv run python -I scripts/model/upload.py
```

This stores the files in GridFS and writes `ai/model_cards/plantvillage-mobilenetv2.lock.json`, which pins every file's SHA-256. Commit the lock file. The Render build runs `scripts/model/download.py`, which fails the build if a file is missing or doesn't match its checksum.

## 3. Production data

Seed the production database from your machine:

```bash
MONGODB_DB=irminsul_prod uv run python -I scripts/seed.py
```

Use the same `SEED_DEMO_PASSWORD` here and in Render. The mandi price snapshot loads itself the first time the app starts.

## 4. Render

1. New → Blueprint → pick the GitHub repository. Render reads `render.yaml`.
2. Fill in the values marked `sync: false`: `MONGODB_URI`, `SEED_DEMO_PASSWORD`, `PUBLIC_BASE_URL` and, optionally, `DATA_GOV_IN_API_KEY` (not used yet). Set `PUBLIC_BASE_URL` after the first deploy shows your URL, then redeploy.
3. Render generates `JWT_SECRET` for you. `ENVIRONMENT=production` turns on Secure cookies and HSTS.

## 5. After the first deploy

- `/api/v1/health` should return `{"status": "ok", "db": "ok"}`.
- Free instances sleep when idle and take a little while to wake up, so open the site a few minutes before showing it to anyone.
- Scan a batch QR code with a phone to check that the public verify page opens on the real URL.

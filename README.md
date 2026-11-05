# API Creator Studio

A local-first API development workspace with a responsive web UI and Android-installable PWA.

## What is included

- Create, rename, and delete API projects.
- Define endpoints using GET, POST, PUT, PATCH, and DELETE.
- Configure route paths, descriptions, response codes, static JSON, or CRUD resources.
- Run requests against a real local runtime and inspect JSON responses.
- Manage resource records.
- Generate and download OpenAPI 3.1 documents.
- Export and import project definitions as JSON.
- Optional project API-key protection (keys are hashed at rest and shown once).
- Request history stored in SQLite.
- Responsive UI, web app manifest, and service worker for Android browser installation.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Install on Android

1. Run the server on a computer or Android environment reachable from your phone.
2. Open the app URL in Chrome on Android.
3. Use Chrome's menu → **Install app** or **Add to Home screen**.

This is an installable PWA, not a native APK or Play Store release. To use it across devices, host the server on a reachable HTTPS URL. The SQLite database remains on the server.

## Runtime API shape

User-defined APIs are available under:

`/runtime/{project_slug}/{endpoint_path}`

Example starter routes:

- `GET /runtime/starter-api/users`
- `GET /runtime/starter-api/users/1`
- `POST /runtime/starter-api/users`

If API-key protection is enabled for a project, send:

`X-API-Key: <your-key>`

## Handler types

- `static`: returns the configured JSON response.
- `crud`: reads or changes records in the named resource.

CRUD handlers support collection list/create and item get/update/patch/delete. The route must contain `{id}` for item operations.

## Safety and limitations

- The runtime never evaluates user-supplied Python, JavaScript, shell commands, or SQL.
- This MVP is intended for development and prototyping. Before public production use, add rate limiting, audit logging, stronger account-level authentication, HTTPS termination, backups, resource quotas, and security review.
- The initial workspace is local and does not include multi-user cloud accounts.
- API keys are stored as SHA-256 hashes and cannot be recovered after creation.

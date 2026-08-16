# Deploying to Render

This gets the whole app (backend + widget, both served from one FastAPI
app at `/`) live on a public URL. Render's free tier is enough for trying
this out — it just spins down after inactivity, so the first request after
a quiet period is slow (~30-60s cold start) while it wakes back up.

## 1. Get your project into a GitHub repo

Render deploys from a git repo it can read. From inside the project folder:

```bash
git init
git add .
git commit -m "Initial commit: bookstore support agent"
```

Then create an empty repo on GitHub (via github.com → New repository — do
**not** initialize it with a README), and push:

```bash
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

(`.gitignore` already excludes caches, `.venv/`, and your local `.env` —
never commit real API keys.)

## 2. Create the Render service

1. Go to https://dashboard.render.com and sign in (or sign up).
2. Click **New +** → **Blueprint**.
3. Connect your GitHub account if you haven't, then select the repo you
   just pushed. Render will detect `render.yaml` in the repo root and
   propose the service defined there.
4. Click through to create it. It'll ask you to fill in the two env vars
   marked `sync: false` in `render.yaml`:
   - `ANTHROPIC_API_KEY` — your real Anthropic API key
   - `ADMIN_API_TOKEN` — make up any long random string yourself (e.g.
     `openssl rand -hex 24`). This protects the `/api/admin/approvals`
     endpoints — without it set, anyone who finds your URL could approve
     refunds, so don't skip this.
5. `render.yaml` also provisions a free Postgres database
   (`bookly-support-db`) and wires its connection string into the web
   service as `DATABASE_URL` automatically — no manual setup needed. This
   is what makes chat sessions survive restarts and lets staff review past
   conversations at `/api/admin/sessions`. **Free Postgres on Render
   expires 30 days after creation** (data is deleted after a 14-day grace
   period) — fine while you're testing this out, but if you want chat
   history to persist long-term, upgrade the database to a paid plan
   (Dashboard → the `bookly-support-db` database → Settings → change
   plan) before it expires; upgrading in place keeps the existing data.
6. Deploy. The build log will show `pip install` running, then the service
   starting. First deploy usually takes 1-3 minutes.

## 3. Try it

Render gives you a URL like `https://bookly-support-agent.onrender.com`.

- Open it in a browser → the chat widget loads (served at `/`), click the
  💬 bubble and chat with the agent.
- Health check: `curl https://<your-url>/api/health` → `{"status":"ok"}`
- Admin queue (needs your `ADMIN_API_TOKEN`):
  ```bash
  curl https://<your-url>/api/admin/approvals \
    -H "X-Admin-Token: <your ADMIN_API_TOKEN value>"
  ```

## 4. Updating later

Any `git push` to the branch Render is watching triggers an automatic
redeploy. No need to touch the dashboard again for code changes — only for
new/changed environment variables.

## Alternative platforms

The same `Dockerfile` in this repo works as-is on Railway, Fly.io, or any
other platform that can build from a Dockerfile — the only per-platform
differences are how you set the `ANTHROPIC_API_KEY` / `ADMIN_API_TOKEN`
environment variables and how you point the platform at this repo. Render
was chosen here for the simplest free path to a public URL with no infra
knowledge required; nothing about the app itself is Render-specific.

## Before you rely on this for real customers

This is still a prototype (see `docs/ARCHITECTURE.md` §9): the
approval-queue is still in-memory (resets on every deploy/restart) — chat
sessions can now optionally persist to Postgres (see above), but that's
still a free/expiring database, not a production-grade setup — plus open
CORS, mock order/policy data, and no customer login. Fine for testing and
demos; revisit those before pointing real traffic at it.

---
name: ProaltsGen web setup
description: Key facts about the Flask web app, Discord bot, and required environment variables for ProaltsGen.
---

## Guild info (discovered from bot logs)
- Guild: **PoalsG3n #BACK**
- Guild ID: `1517892677574590606`
- `GUILD_ID` env var must be set to this value for role verification to work.

## Required env vars still missing (OAuth)
- `DISCORD_CLIENT_ID` — from Discord Developer Portal → your app
- `DISCORD_CLIENT_SECRET` — from Discord Developer Portal → your app
- `DISCORD_REDIRECT_URI` — e.g. `https://yoursite.vercel.app/callback` or the Replit preview URL + `/callback`

## Already set
- `DISCORD_TOKEN` — bot token (in userenv.shared)
- `SESSION_SECRET` — Flask session secret (Replit secret)
- `DATABASE_URL` — auto-provided by Replit DB

## Role IDs
- Admin: `1517909085453029487`
- Owner: `1517892778938470531`

## Architecture
- `run.py` starts Flask (daemon thread, port 5000) + Discord bot (main thread)
- `app.py` is standalone Flask app for Vercel deployment
- `web_db.py` uses psycopg2 (sync) — separate from asyncpg in database.py
- CSRF tokens injected via `@app.context_processor` + validated in all POST routes
- OAuth state param stored in session and validated on callback

## Database column note
`role_cooldowns.cooldown_minutes` actually stores **seconds** (column name is misleading). 
Both bot (gen.py) and web (app.py) treat the value as seconds — this is consistent.

**Why:** The bot's config modal labels input as "en secondes" and passes the value directly; the column name was never updated. Do not "fix" the column name without migrating data.

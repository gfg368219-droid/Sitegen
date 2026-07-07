"""ProaltsGen — Flask web application."""
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import (Flask, abort, flash, redirect, render_template,
                   request, session, url_for)

from markupsafe import Markup
import web_db

load_dotenv()

app = Flask(__name__)

# Crée les tables si elles n'existent pas encore (idempotent)
try:
    web_db.init_db()
except Exception as _init_err:
    import logging as _log
    _log.getLogger("app").warning("init_db failed: %s", _init_err)
app.secret_key = os.getenv("SESSION_SECRET", "change-me-in-production")

# ── Constants ─────────────────────────────────────────────────────────────────
OWNER_ROLE_ID = 1517909085453029487
ADMIN_ROLE_ID = 1517892778938470531

DISCORD_API = "https://discord.com/api/v10"
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "")
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

def _guild_id() -> int:
    return 1517892677574590606


# ── Discord helpers ───────────────────────────────────────────────────────────

def discord_oauth_url(state: str) -> str:
    scopes = requests.utils.quote("identify guilds guilds.join")
    redir = requests.utils.quote(REDIRECT_URI)
    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={redir}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
    )


def exchange_code(code: str) -> dict:
    r = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def get_discord_user(access_token: str) -> dict:
    r = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def join_guild(user_id: str, access_token: str) -> bool:
    guild_id = _guild_id()
    if not guild_id or not BOT_TOKEN:
        return False
    try:
        r = requests.put(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}",
            headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"},
            json={"access_token": access_token},
            timeout=10,
        )
        return r.status_code in (201, 204)
    except Exception:
        return False


def get_member_roles(user_id: str) -> list[int]:
    """Fetch role IDs for a guild member using the bot token."""
    guild_id = _guild_id()
    if not guild_id:
        app.logger.warning("get_member_roles: GUILD_ID non configuré")
        return []
    if not BOT_TOKEN:
        app.logger.warning("get_member_roles: DISCORD_TOKEN non configuré")
        return []
    try:
        r = requests.get(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
            timeout=5,
        )
        app.logger.info(
            "get_member_roles: user=%s guild=%s status=%s",
            user_id, guild_id, r.status_code,
        )
        if r.status_code == 200:
            roles = [int(rid) for rid in r.json().get("roles", [])]
            app.logger.info("get_member_roles: roles=%s", roles)
            return roles
        else:
            app.logger.warning(
                "get_member_roles: Discord API error %s — %s",
                r.status_code, r.text[:200],
            )
    except Exception as exc:
        app.logger.error("get_member_roles: exception — %s", exc)
    return []


def check_roles(user_id: str) -> tuple[bool, bool]:
    """Returns (is_admin, is_owner)."""
    roles = get_member_roles(user_id)
    is_owner = OWNER_ROLE_ID in roles
    is_admin = ADMIN_ROLE_ID in roles or is_owner
    return is_admin, is_owner


# ── CSRF helpers ──────────────────────────────────────────────────────────────

def _csrf_token() -> str:
    """Return (and create if needed) the session's CSRF token."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def _require_csrf():
    """Abort 403 if the submitted CSRF token doesn't match the session token."""
    submitted = request.form.get("csrf_token", "")
    if not submitted or not secrets.compare_digest(submitted, _csrf_token()):
        abort(403)


@app.context_processor
def inject_csrf():
    return {"csrf_token": _csrf_token()}


# ── Auth decorators ───────────────────────────────────────────────────────────

_ROLES_TTL = 300  # re-check Discord roles every 5 minutes


def _refresh_roles(user_id: str) -> tuple[bool, bool]:
    """Re-verify roles from Discord API with a 5-minute cache in session."""
    now = time.time()
    if now - session.get("roles_checked_at", 0) > _ROLES_TTL:
        is_admin, is_owner = check_roles(user_id)
        session["user"]["is_admin"] = is_admin
        session["user"]["is_owner"] = is_owner
        session["roles_checked_at"] = now
        session.modified = True
    return session["user"].get("is_admin", False), session["user"].get("is_owner", False)


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            flash("Connectez-vous avec Discord pour continuer.", "info")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        is_admin, is_owner = _refresh_roles(session["user"]["id"])
        if not is_admin and not is_owner:
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def owner_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        _, is_owner = _refresh_roles(session["user"]["id"])
        if not is_owner:
            abort(403)
        return f(*args, **kwargs)
    return wrapped


# ── Utilities ─────────────────────────────────────────────────────────────────

def avatar_url(user_id: str, avatar_hash: str, size: int = 64) -> str:
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size={size}"
    return f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"


def fmt_cooldown(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h {m}m"
    return f"{m}m {s}s" if s else f"{m}m"


def parse_accounts(text: str) -> list[tuple[str, str, str]]:
    """Parse accounts from .txt content.
    Returns list of (identifier, password, account_type).
    Rules:
      - One account per line
      - Everything after the first | is discarded
      - Lines containing http/https are skipped
      - Must have identifier:password with both parts non-empty
      - Identifier must not contain spaces, / or \\
      - account_type = "email" if @ present, else "user"
    """
    accounts = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip URLs
        if "http" in line.lower():
            continue
        # Discard everything from | onwards
        if "|" in line:
            line = line.split("|", 1)[0].strip()
        if not line or ":" not in line:
            continue
        idx = line.index(":")
        identifier = line[:idx].strip()
        password = line[idx + 1:].strip()
        # Both parts must be present
        if not identifier or not password:
            continue
        # Reject suspicious identifiers
        if "/" in identifier or "\\" in identifier or " " in identifier:
            continue
        account_type = "email" if "@" in identifier else "user"
        accounts.append((identifier, password, account_type))
    return accounts


def _cooldown_info(user_id_str: str) -> dict:
    """Compute cooldown state for the current user."""
    user_id = int(user_id_str)
    guild_id = _guild_id()

    roles = get_member_roles(user_id_str)
    role_cd = web_db.get_role_cooldown_for_roles(guild_id, roles)

    config = web_db.get_guild_config(guild_id)
    default_min = (config.get("default_cooldown") or 60) if config else 60
    default_sec = default_min * 60

    cooldown = role_cd if role_cd is not None else default_sec

    last_gen = web_db.get_user_last_gen(user_id, guild_id)
    remaining = 0.0
    if last_gen:
        if last_gen.tzinfo is None:
            last_gen = last_gen.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_gen).total_seconds()
        remaining = max(0.0, cooldown - elapsed)

    return {"remaining": remaining, "cooldown": cooldown}


# ── Template filters ──────────────────────────────────────────────────────────

@app.template_filter("fmt_cooldown")
def fmt_cooldown_filter(s):
    return fmt_cooldown(s)


# ── Webhook notifications ─────────────────────────────────────────────────────

def _send_restock_webhook(service_name: str, image_url: str | None, added: int) -> None:
    """POST a Discord embed to DISCORD_WEBHOOK after a restock. Never raises."""
    url = os.getenv("DISCORD_WEBHOOK")
    if not url:
        return
    plural = "s" if added > 1 else ""
    embed: dict = {
        "title": f"Restock +{added} compte{plural} {service_name}",
        "color": 0x7C3AED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "ProaltsGen"},
    }
    if image_url:
        embed["thumbnail"] = {"url": image_url}
    try:
        requests.post(url, json={"embeds": [embed]}, timeout=5)
    except Exception:
        pass


# ── SVG icon library ──────────────────────────────────────────────────────────

_GRAD = (
    '<defs><linearGradient id="gp" x1="0%" y1="0%" x2="100%" y2="100%">'
    '<stop offset="0%" stop-color="#7c3aed"/>'
    '<stop offset="100%" stop-color="#3b82f6"/>'
    '</linearGradient></defs>'
)


def _svg(body: str, size: int, extra: str = "") -> Markup:
    return Markup(
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" class="icon" {extra}>'
        f'{_GRAD}{body}</svg>'
    )


_ICONS: dict[str, str] = {
    "bolt": (
        '<path d="M13 2L4.5 13H11L10 22L20.5 11H14L13 2Z" fill="url(#gp)"/>'
    ),
    "shield": (
        '<path d="M12 2L3 7V12C3 16.97 7.09 21.74 12 23C16.91 21.74 21 16.97 21 12V7L12 2Z" fill="url(#gp)"/>'
        '<path d="M9.5 11C9.5 9.62 10.62 8.5 12 8.5C13.38 8.5 14.5 9.62 14.5 11V12H9.5V11Z" fill="white" fill-opacity=".85"/>'
        '<rect x="9" y="12" width="6" height="5" rx="1" fill="white" fill-opacity=".85"/>'
        '<circle cx="12" cy="14.5" r="1" fill="url(#gp)"/>'
    ),
    "trophy": (
        '<path d="M8 3H16V11C16 13.21 14.21 15 12 15C9.79 15 8 13.21 8 11V3Z" fill="#f59e0b"/>'
        '<path d="M6 5H4C4 5 3 10 6.5 12L8 10C8 10 6 9 6 5Z" fill="#f59e0b"/>'
        '<path d="M18 5H20C20 5 21 10 17.5 12L16 10C16 10 18 9 18 5Z" fill="#f59e0b"/>'
        '<rect x="10" y="15" width="4" height="3" fill="#fbbf24"/>'
        '<rect x="7" y="18" width="10" height="2.5" rx="1.25" fill="#f59e0b"/>'
    ),
    "crown": (
        '<path d="M3 17L6.5 8L10.5 13L12 7L13.5 13L17.5 8L21 17H3Z" fill="#f59e0b"/>'
        '<rect x="3" y="17" width="18" height="2.5" rx="1.25" fill="#fcd34d"/>'
        '<circle cx="12" cy="7" r="1.5" fill="#fde68a"/>'
        '<circle cx="6.5" cy="8" r="1.5" fill="#fde68a"/>'
        '<circle cx="17.5" cy="8" r="1.5" fill="#fde68a"/>'
    ),
    "silver": (
        '<circle cx="12" cy="14" r="7" fill="#94a3b8"/>'
        '<circle cx="12" cy="14" r="5.5" fill="#cbd5e1"/>'
        '<text x="12" y="18" text-anchor="middle" font-size="7" font-weight="800" fill="#475569" font-family="Inter,sans-serif">2</text>'
        '<path d="M9 6.5L12 2.5L15 6.5" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "bronze": (
        '<circle cx="12" cy="14" r="7" fill="#92400e"/>'
        '<circle cx="12" cy="14" r="5.5" fill="#d97706"/>'
        '<text x="12" y="18" text-anchor="middle" font-size="7" font-weight="800" fill="#7c2d12" font-family="Inter,sans-serif">3</text>'
        '<path d="M9 6.5L12 2.5L15 6.5" stroke="#92400e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "box": (
        '<path d="M12 2L2 7V17L12 22L22 17V7L12 2Z" fill="url(#gp)" fill-opacity=".12" stroke="url(#gp)" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M2 7L12 12L22 7" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M12 12V22" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M7 4.5L17 9.5" stroke="url(#gp)" stroke-width="1" stroke-opacity=".5"/>'
    ),
    "edit": (
        '<path d="M16.47 3.53C17.26 2.74 18.54 2.74 19.33 3.53L20.47 4.67C21.26 5.46 21.26 6.74 20.47 7.53L9.5 18.5L4 20L5.5 14.5L16.47 3.53Z" fill="url(#gp)" fill-opacity=".8"/>'
        '<path d="M14.5 5.5L18.5 9.5" stroke="white" stroke-width="1.5" stroke-opacity=".4"/>'
    ),
    "trash": (
        '<path d="M9 3H15L16 5H8L9 3Z" fill="#ef4444"/>'
        '<rect x="5" y="5" width="14" height="2" rx="1" fill="#ef4444"/>'
        '<path d="M6 7L7.5 21H16.5L18 7H6Z" fill="#ef4444" fill-opacity=".7"/>'
        '<path d="M10 10V18M14 10V18" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-opacity=".6"/>'
    ),
    "check": (
        '<circle cx="12" cy="12" r="10" fill="#10b981" fill-opacity=".15" stroke="#10b981" stroke-width="1.5"/>'
        '<path d="M7.5 12L10.5 15L16.5 9" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="11" height="13" rx="2" fill="url(#gp)" fill-opacity=".12" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M5 15H4C2.9 15 2 14.1 2 13V4C2 2.9 2.9 2 4 2H13C14.1 2 15 2.9 15 4V5" stroke="url(#gp)" stroke-width="1.5" stroke-linecap="round"/>'
    ),
    "warning": (
        '<path d="M12 2.5L1.5 21H22.5L12 2.5Z" fill="#f59e0b" fill-opacity=".15" stroke="#f59e0b" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M12 9.5V14.5" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/>'
        '<circle cx="12" cy="17.5" r="1" fill="#f59e0b"/>'
    ),
    "file": (
        '<path d="M13 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V9L13 2Z" fill="url(#gp)" fill-opacity=".12" stroke="url(#gp)" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M13 2V9H20" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M8 13H16M8 17H13" stroke="url(#gp)" stroke-width="1.5" stroke-linecap="round"/>'
    ),
    "lock": (
        '<rect x="5" y="11" width="14" height="11" rx="2" fill="url(#gp)" fill-opacity=".8"/>'
        '<path d="M8 11V7C8 4.79 9.79 3 12 3C14.21 3 16 4.79 16 7V11" stroke="url(#gp)" stroke-width="2"/>'
        '<circle cx="12" cy="16.5" r="1.5" fill="white" fill-opacity=".8"/>'
    ),
    "leaderboard": (
        '<rect x="3" y="13" width="4" height="8" rx="1" fill="url(#gp)" fill-opacity=".5"/>'
        '<rect x="10" y="8" width="4" height="13" rx="1" fill="url(#gp)"/>'
        '<rect x="17" y="10" width="4" height="11" rx="1" fill="url(#gp)" fill-opacity=".7"/>'
    ),
    "gen": (
        '<circle cx="12" cy="12" r="10" fill="url(#gp)" fill-opacity=".15" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M13 6.5L8 13H12L11 17.5L17 11H13L13 6.5Z" fill="url(#gp)"/>'
    ),
    "arrow-right": (
        '<path d="M5 12H19M13 6L19 12L13 18" stroke="url(#gp)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "empty": (
        '<rect x="3" y="6" width="18" height="14" rx="2" fill="url(#gp)" fill-opacity=".1" stroke="url(#gp)" stroke-width="1.5"/>'
        '<path d="M3 10H21" stroke="url(#gp)" stroke-width="1.5"/>'
        '<circle cx="12" cy="15" r="2" stroke="url(#gp)" stroke-width="1.5"/>'
    ),
}


def _icon(name: str, size: int = 20) -> Markup:
    body = _ICONS.get(name, "")
    return _svg(body, size)


@app.context_processor
def inject_icons():
    return {"icon": _icon}


# ── Public routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    leaderboard = web_db.get_leaderboard(3)
    return render_template("index.html", leaderboard=leaderboard)


@app.route("/login")
def login():
    state = secrets.token_hex(16)
    session["oauth_state"] = state
    return redirect(discord_oauth_url(state))


@app.route("/callback")
def callback():
    # Validate OAuth state to prevent CSRF
    returned_state = request.args.get("state", "")
    expected_state = session.pop("oauth_state", None)
    if not returned_state or not expected_state or not secrets.compare_digest(returned_state, expected_state):
        flash("Erreur de sécurité OAuth. Réessayez.", "error")
        return redirect(url_for("index"))

    code = request.args.get("code")
    if not code:
        flash("Connexion annulée.", "error")
        return redirect(url_for("index"))
    try:
        token_data = exchange_code(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")

        user_data = get_discord_user(access_token)
        uid = user_data["id"]
        username = user_data.get("global_name") or user_data.get("username", "")
        avatar = user_data.get("avatar") or ""

        join_guild(uid, access_token)
        is_admin, is_owner = check_roles(uid)

        web_db.get_or_create_web_user(
            discord_id=int(uid),
            username=username,
            avatar=avatar,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        session["user"] = {
            "id": uid,
            "username": username,
            "avatar": avatar_url(uid, avatar),
            "is_admin": is_admin,
            "is_owner": is_owner,
        }

        flash(f"Bienvenue, {username} !", "success")
        return redirect(url_for("services"))

    except Exception as e:
        app.logger.exception("OAuth callback error: %s", e)
        flash("Erreur de connexion Discord. Réessayez.", "error")
        return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/leaderboard")
def leaderboard():
    top = web_db.get_leaderboard(50)
    return render_template("leaderboard.html", leaderboard=top)


# ── Authenticated routes ──────────────────────────────────────────────────────

@app.route("/services")
@login_required
def services():
    svc_list = web_db.get_services(_guild_id())
    return render_template("services.html", services=svc_list)


@app.route("/services/<int:service_id>")
@login_required
def service(service_id):
    svc = web_db.get_service(service_id, _guild_id())
    if not svc:
        abort(404)
    cd = _cooldown_info(session["user"]["id"])
    gen_result = session.pop("gen_result", None)
    return render_template(
        "service.html",
        service=svc,
        cooldown_info=cd,
        gen_result=gen_result,
    )


@app.route("/services/<int:service_id>/gen", methods=["POST"])
@login_required
def gen_account(service_id):
    _require_csrf()
    svc = web_db.get_service(service_id, _guild_id())
    if not svc:
        abort(404)

    user = session["user"]
    user_id = int(user["id"])
    guild_id = _guild_id()

    cd = _cooldown_info(user["id"])
    if cd["remaining"] > 0:
        flash(f"Cooldown actif — réessayez dans {fmt_cooldown(cd['remaining'])}.", "error")
        return redirect(url_for("service", service_id=service_id))

    account = web_db.pop_account(service_id)
    if not account:
        flash("Ce service est vide. Revenez plus tard.", "error")
        return redirect(url_for("service", service_id=service_id))

    credential = f"{account['email']}:{account['password']}"
    web_db.set_user_last_gen(user_id, guild_id)
    web_db.log_web_gen(service_id, user_id, user["username"], credential)

    session["gen_result"] = {
        "credential": credential,
        "service_name": svc["name"],
    }
    return redirect(url_for("service", service_id=service_id))


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin/debug")
@login_required
def admin_debug():
    """Diagnostic : affiche les rôles Discord de l'utilisateur connecté."""
    from flask import jsonify
    user_id = session["user"]["id"]
    guild_id = _guild_id()
    roles = get_member_roles(user_id)
    return jsonify({
        "user_id": user_id,
        "guild_id": guild_id,
        "guild_id_configured": bool(guild_id),
        "bot_token_configured": bool(BOT_TOKEN),
        "roles_fetched": roles,
        "ADMIN_ROLE_ID": ADMIN_ROLE_ID,
        "OWNER_ROLE_ID": OWNER_ROLE_ID,
        "is_admin": ADMIN_ROLE_ID in roles or OWNER_ROLE_ID in roles,
        "is_owner": OWNER_ROLE_ID in roles,
        "session_is_admin": session["user"].get("is_admin"),
        "session_is_owner": session["user"].get("is_owner"),
    })


@app.route("/admin")
@admin_required
def admin_dashboard():
    svc_list = web_db.get_services(_guild_id())
    return render_template("admin/dashboard.html", services=svc_list)


@app.route("/admin/services/create", methods=["GET", "POST"])
@admin_required
def admin_create_service():
    if request.method == "POST":
        _require_csrf()
        name = request.form.get("name", "").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Le nom est requis.", "error")
            return render_template("admin/create_service.html")
        try:
            web_db.create_service(_guild_id(), name, image_url, description)
            flash(f'Service "{name}" créé avec succès.', "success")
            return redirect(url_for("admin_dashboard"))
        except Exception as e:
            if "unique" in str(e).lower():
                flash(f'Un service nommé "{name}" existe déjà.', "error")
            else:
                app.logger.exception(e)
                flash("Erreur lors de la création.", "error")
    return render_template("admin/create_service.html")


@app.route("/admin/services/<int:service_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_service(service_id):
    svc = web_db.get_service(service_id, _guild_id())
    if not svc:
        abort(404)
    if request.method == "POST":
        _require_csrf()
        name = request.form.get("name", "").strip()
        image_url = request.form.get("image_url", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Le nom est requis.", "error")
            return render_template("admin/edit_service.html", service=svc)
        web_db.update_service(service_id, name, image_url, description)
        flash(f'Service "{name}" mis à jour.', "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin/edit_service.html", service=svc)


@app.route("/admin/services/<int:service_id>/delete", methods=["POST"])
@admin_required
def admin_delete_service(service_id):
    _require_csrf()
    svc = web_db.get_service(service_id, _guild_id())
    if not svc:
        abort(404)
    web_db.delete_service(service_id)
    flash(f'Service "{svc["name"]}" supprimé.', "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/services/<int:service_id>/stock", methods=["GET", "POST"])
@admin_required
def admin_stock(service_id):
    svc = web_db.get_service(service_id, _guild_id())
    if not svc:
        abort(404)
    if request.method == "POST":
        _require_csrf()
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".txt"):
            flash("Veuillez uploader un fichier .txt valide.", "error")
            return render_template("admin/stock.html", service=svc)
        try:
            content = f.read().decode("utf-8", errors="ignore")
        except Exception:
            flash("Impossible de lire le fichier.", "error")
            return render_template("admin/stock.html", service=svc)
        accounts = parse_accounts(content)
        if not accounts:
            flash("Aucun compte valide trouvé. Vérifiez le format (identifier:password, un par ligne).", "error")
            return render_template("admin/stock.html", service=svc)
        added = web_db.add_accounts(service_id, accounts)
        if added > 0:
            _send_restock_webhook(svc["name"], svc.get("image_url"), added)
        skipped = len(accounts) - added
        flash(
            f"{added} compte(s) ajouté(s) au stock"
            + (f" ({skipped} doublon(s) ignoré(s))." if skipped else "."),
            "success",
        )
        return redirect(url_for("admin_dashboard"))
    return render_template("admin/stock.html", service=svc)


# ── Owner routes ──────────────────────────────────────────────────────────────

@app.route("/owner")
@owner_required
def owner_dashboard():
    cooldowns = web_db.get_role_cooldowns(_guild_id())
    return render_template("owner/dashboard.html", cooldowns=cooldowns, guild_id=_guild_id())


@app.route("/owner/cooldowns", methods=["POST"])
@owner_required
def owner_set_cooldown():
    _require_csrf()
    role_id_str = request.form.get("role_id", "").strip()
    seconds_str = request.form.get("seconds", "").strip()
    try:
        role_id = int(role_id_str)
        seconds = int(seconds_str)
        if seconds < 0:
            raise ValueError
    except ValueError:
        flash("Valeurs invalides. Entrez un ID de rôle (nombre) et un temps en secondes.", "error")
        return redirect(url_for("owner_dashboard"))
    web_db.set_role_cooldown(_guild_id(), role_id, seconds)
    flash(f"Cooldown du rôle {role_id} défini à {fmt_cooldown(seconds)}.", "success")
    return redirect(url_for("owner_dashboard"))


@app.route("/owner/cooldowns/<int:role_id>/delete", methods=["POST"])
@owner_required
def owner_delete_cooldown(role_id):
    _require_csrf()
    web_db.delete_role_cooldown(_guild_id(), role_id)
    flash(f"Cooldown du rôle {role_id} supprimé.", "success")
    return redirect(url_for("owner_dashboard"))


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="Accès refusé — vous n'avez pas les permissions."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page introuvable."), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

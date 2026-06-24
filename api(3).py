# ═══════════════════════════════════════════════════════════════
#  NEXUS DASHBOARD API — Flask Backend
#  Login-Modell: Besucher gibt den Discord-Bot-Token ein → Backend
#  vergleicht ihn mit dem echten Token aus Railway (DISCORD_TOKEN) →
#  bei Übereinstimmung wird ein 6-stelliger Code per Bot-DM an den
#  Owner geschickt → Besucher gibt den Code ein → Session-Token wird
#  ausgestellt, mit dem alle weiteren /api/*-Aufrufe authentifiziert werden.
# ═══════════════════════════════════════════════════════════════
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import json, os, datetime, threading, time, subprocess, sys, secrets, hashlib, random

app = Flask(__name__)
CORS(app)

BOT_TOKEN     = os.environ.get("DISCORD_TOKEN")   # Vergleichswert für den Login — NICHT live gegen Discord geprüft
DATA_FILE     = "data.json"
BRAIN_FILE    = "brain.json"
CODELOG       = "codelog.json"
LOGIN_QUEUE   = "login_requests.json"
START_TIME    = datetime.datetime.utcnow()

SESSION_TTL_SECONDS    = 60 * 60 * 12   # Session 12h gültig, danach erneut einloggen
CODE_TTL_SECONDS       = 60 * 5         # Verifizierungscode 5 Minuten gültig

# In-Memory Session-Speicher: {session_token: ablauf_timestamp}
# Bewusst NICHT in einer Datei, damit Sessions beim Neustart automatisch verfallen.
_active_sessions = {}

def lade(f, default={}):
    if not os.path.exists(f):
        return default
    with open(f, "r", encoding="utf-8") as fp:
        return json.load(fp)

def speichere(f, data):
    with open(f, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=4, ensure_ascii=False)

def xp_fuer_level(level):
    return 100 * (level ** 2) + 100 * level

def get_level(xp):
    level = 0
    while xp >= xp_fuer_level(level + 1):
        level += 1
    return level

def uptime():
    diff = datetime.datetime.utcnow() - START_TIME
    h = int(diff.total_seconds() // 3600)
    m = int((diff.total_seconds() % 3600) // 60)
    s = int(diff.total_seconds() % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# ═══════════════════════════════════════════════════════════════
#  SESSION-AUTH
# ═══════════════════════════════════════════════════════════════
def auth(req):
    """Prüft das X-Session-Token Header gegen aktive, nicht abgelaufene Sessions."""
    token = req.headers.get("X-Session-Token")
    if not token:
        return False
    ablauf = _active_sessions.get(token)
    if not ablauf:
        return False
    if time.time() > ablauf:
        _active_sessions.pop(token, None)
        return False
    return True

def neue_session_erstellen():
    token = secrets.token_urlsafe(32)
    _active_sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token

# Routen, die OHNE Session erreichbar sein müssen: das Dashboard-HTML selbst,
# der gesamte Login-Flow, und der TikFinity-Webhook (der hat seinen eigenen
# Schutz über ein geheimes Pfad-Segment statt eines Headers, siehe unten).
PUBLIC_PATHS = {"/", "/health", "/api/login/request", "/api/login/verify"}
PUBLIC_PATH_PREFIXES = ("/api/login/status/", "/webhook/tikfinity/")

@app.before_request
def require_session_for_api_routes():
    if request.path in PUBLIC_PATHS:
        return None
    if request.path.startswith(PUBLIC_PATH_PREFIXES):
        return None
    if request.path.startswith("/api/"):
        if not auth(request):
            return jsonify({"error": "Unauthorized", "reason": "session_invalid_or_expired"}), 401
    return None

@app.route("/health")
def health():
    """Öffentlicher Health-Check ohne Login — zum schnellen Testen ob der Server überhaupt läuft."""
    return jsonify({
        "ok": True,
        "bot_token_configured": bool(BOT_TOKEN),
        "owner_id_configured": bool(os.environ.get("OWNER_ID")),
        "uptime": uptime(),
    })

# ═══════════════════════════════════════════════════════════════
#  ROUTES — LOGIN FLOW
# ═══════════════════════════════════════════════════════════════
def hash_token(token: str) -> str:
    """Token nie im Klartext vergleichen/loggen — nur als Hash."""
    return hashlib.sha256(token.strip().encode()).hexdigest()

@app.route("/api/login/request", methods=["POST"])
def login_request():
    """Schritt 1: Besucher schickt den Bot-Token. Bei Übereinstimmung mit dem
    echten DISCORD_TOKEN wird eine Anfrage in die Queue gelegt, die bot.py
    aufgreift und per DM an den Owner einen Code schickt."""
    if not BOT_TOKEN:
        return jsonify({"error": "Server nicht konfiguriert (DISCORD_TOKEN fehlt in Railway)"}), 500

    body = request.json or {}
    eingegebener_token = (body.get("token") or "").strip()
    if not eingegebener_token:
        return jsonify({"error": "Token erforderlich"}), 400

    if hash_token(eingegebener_token) != hash_token(BOT_TOKEN):
        # Bewusst dieselbe generische Fehlermeldung wie bei falschem Code,
        # damit niemand per Trial-and-Error herausfinden kann, ob der Token stimmt.
        return jsonify({"error": "Token konnte nicht verifiziert werden"}), 401

    # Token korrekt → Anfrage + Code in die Queue legen, bot.py verschickt die DM
    request_id = secrets.token_hex(8)
    code = f"{random.randint(0, 999999):06d}"
    q = lade(LOGIN_QUEUE, {"requests": []})
    q["requests"].append({
        "id": request_id,
        "code": code,
        "status": "pending_dm",
        "created_at": time.time(),
    })
    speichere(LOGIN_QUEUE, q)

    return jsonify({"ok": True, "request_id": request_id, "message": "Code wurde per DM an den Bot-Owner gesendet."})

@app.route("/api/login/verify", methods=["POST"])
def login_verify():
    """Schritt 2: Besucher gibt den Code ein, der per DM an den Owner ging."""
    body = request.json or {}
    request_id = (body.get("request_id") or "").strip()
    eingegebener_code = (body.get("code") or "").strip()
    if not request_id or not eingegebener_code:
        return jsonify({"error": "request_id und code erforderlich"}), 400

    q = lade(LOGIN_QUEUE, {"requests": []})
    eintrag = next((r for r in q["requests"] if r["id"] == request_id), None)
    if not eintrag:
        return jsonify({"error": "Unbekannte Anfrage — bitte neu starten"}), 404

    alter = time.time() - eintrag["created_at"]
    if alter > CODE_TTL_SECONDS:
        return jsonify({"error": "Code abgelaufen — bitte neu anfragen"}), 410

    if eintrag["code"] != eingegebener_code:
        return jsonify({"error": "Code falsch"}), 401

    # Erfolgreich verifiziert → Anfrage aus der Queue entfernen, Session ausstellen
    q["requests"] = [r for r in q["requests"] if r["id"] != request_id]
    speichere(LOGIN_QUEUE, q)

    session_token = neue_session_erstellen()
    return jsonify({"ok": True, "session_token": session_token, "expires_in": SESSION_TTL_SECONDS})

@app.route("/api/login/status/<request_id>")
def login_status(request_id):
    """Dashboard kann pollen ob die DM schon verschickt wurde (für UI-Feedback)."""
    q = lade(LOGIN_QUEUE, {"requests": []})
    eintrag = next((r for r in q["requests"] if r["id"] == request_id), None)
    if not eintrag:
        return jsonify({"status": "unknown"})
    alter = time.time() - eintrag["created_at"]
    if alter > CODE_TTL_SECONDS:
        return jsonify({"status": "expired"})
    return jsonify({"status": eintrag["status"]})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — STATUS
# ═══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return send_file("dashboard.html")

@app.route("/api/status")
def status():
    daten  = lade(DATA_FILE, {})
    brain  = lade(BRAIN_FILE, {})
    economy = lade("economy.json", {})
    achievements = lade("achievements.json", {})
    return jsonify({
        "online": True,
        "uptime": uptime(),
        "maintenance": daten.get("maintenance", False),
        "boot_count": daten.get("boot_count", 0),
        "einsaetze": daten.get("einsaetze", 0),
        "tickets": daten.get("tickets", 0),
        "ki_conversations": brain.get("stats", {}).get("total_conversations", 0),
        "giveaways_active": len([g for g in daten.get("giveaways", {}).values() if g.get("aktiv")]),
        "warnings_total": sum(len(v) for v in daten.get("warnings", {}).values()),
        "ki_moderation_enabled": daten.get("ki_moderation_enabled", False),
        "total_coins_circulating": sum(economy.get("balances", {}).values()),
        "achievements_unlocked_total": sum(len(v) for v in achievements.get("unlocked", {}).values()),
    })

# ═══════════════════════════════════════════════════════════════
#  ROUTES — RANGLISTE
# ═══════════════════════════════════════════════════════════════
@app.route("/api/ranking")
def ranking():
    daten = lade(DATA_FILE, {})
    xp_data = daten.get("xp", {})
    sortiert = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)[:20]
    result = []
    for uid, xp in sortiert:
        level = get_level(xp)
        aktuell = xp - xp_fuer_level(level)
        needed  = xp_fuer_level(level + 1) - xp_fuer_level(level)
        result.append({
            "uid": uid,
            "xp": xp,
            "level": level,
            "progress": round(aktuell / needed * 100) if needed > 0 else 0,
        })
    return jsonify(result)

# ═══════════════════════════════════════════════════════════════
#  ROUTES — ECONOMY (Reichste Mitglieder)
# ═══════════════════════════════════════════════════════════════
@app.route("/api/economy")
def economy_leaderboard():
    economy = lade("economy.json", {})
    sortiert = sorted(economy.get("balances", {}).items(), key=lambda x: x[1], reverse=True)[:20]
    return jsonify([{"uid": uid, "balance": bal} for uid, bal in sortiert])

# ═══════════════════════════════════════════════════════════════
#  ROUTES — ACHIEVEMENTS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/achievements")
def achievements_overview():
    a = lade("achievements.json", {"unlocked": {}, "definitions": {}})
    defs = a.get("definitions", {})
    unlocked = a.get("unlocked", {})
    counts = {key: sum(1 for u in unlocked.values() if key in u) for key in defs}
    return jsonify({
        "definitions": defs,
        "unlock_counts": counts,
        "total_users_with_achievements": len(unlocked),
    })

# ═══════════════════════════════════════════════════════════════
#  ROUTES — SETTINGS (GET + POST)
# ═══════════════════════════════════════════════════════════════
@app.route("/api/settings", methods=["GET"])
def get_settings():
    daten = lade(DATA_FILE, {})
    brain = lade(BRAIN_FILE, {})
    return jsonify({
        "maintenance":      daten.get("maintenance", False),
        "welcome_channel":  daten.get("welcome_channel"),
        "level_channel":    daten.get("level_channel"),
        "auto_roles":       daten.get("auto_roles", []),
        "level_rollen":     daten.get("level_rollen", {}),
        "personality":      brain.get("personality", ""),
        "xp_min":           daten.get("xp_min", 10),
        "xp_max":           daten.get("xp_max", 25),
        "xp_cooldown_secs": daten.get("xp_cooldown_secs", 60),
        "spam_max_msgs":    daten.get("spam_max_msgs", 6),
        "spam_window":      daten.get("spam_window", 5),
        "spam_timeout_min": daten.get("spam_timeout_min", 5),
        "ki_enabled":       daten.get("ki_enabled", True),
        "ki_welcome":       daten.get("ki_welcome", True),
        "ki_levelup":       daten.get("ki_levelup", True),
        "welcome_enabled":  daten.get("welcome_enabled", True),
        "show_member_count":daten.get("show_member_count", True),
        "welcome_message":  daten.get("welcome_message", ""),
        "ki_moderation_enabled": daten.get("ki_moderation_enabled", False),
        "antispam_enabled": daten.get("antispam_enabled", True),
    })

@app.route("/api/settings", methods=["POST"])
def post_settings():
    if not auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    body  = request.json or {}
    daten = lade(DATA_FILE, {})
    brain = lade(BRAIN_FILE, {})

    # Übernehme alle bekannten Felder
    fields = [
        "maintenance","welcome_channel","level_channel","auto_roles","level_rollen",
        "xp_min","xp_max","xp_cooldown_secs","spam_max_msgs","spam_window",
        "spam_timeout_min","ki_enabled","ki_welcome","ki_levelup",
        "welcome_enabled","show_member_count","welcome_message",
        "ki_moderation_enabled","antispam_enabled"
    ]
    for f in fields:
        if f in body:
            daten[f] = body[f]

    if "personality" in body:
        brain["personality"] = body["personality"]
        speichere(BRAIN_FILE, brain)

    speichere(DATA_FILE, daten)
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — WARTUNG
# ═══════════════════════════════════════════════════════════════
@app.route("/api/maintenance/on", methods=["POST"])
def maintenance_on():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    daten = lade(DATA_FILE, {})
    daten["maintenance"] = True
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True, "maintenance": True})

@app.route("/api/maintenance/off", methods=["POST"])
def maintenance_off():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    daten = lade(DATA_FILE, {})
    daten["maintenance"] = False
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True, "maintenance": False})

@app.route("/api/restart", methods=["POST"])
def restart():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    def do_restart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=do_restart).start()
    return jsonify({"ok": True, "message": "Neustart in 2 Sekunden..."})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — XP MANAGEMENT
# ═══════════════════════════════════════════════════════════════
@app.route("/api/xp/give", methods=["POST"])
def xp_give():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    body  = request.json or {}
    uid   = str(body.get("uid", ""))
    menge = int(body.get("menge", 0))
    if not uid or not menge:
        return jsonify({"error": "uid und menge erforderlich"}), 400
    daten = lade(DATA_FILE, {})
    daten.setdefault("xp", {})
    daten["xp"].setdefault(uid, 0)
    daten["xp"][uid] = max(0, daten["xp"][uid] + menge)
    daten.setdefault("levels", {})
    daten["levels"][uid] = get_level(daten["xp"][uid])
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True, "new_xp": daten["xp"][uid], "new_level": daten["levels"][uid]})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — WARNINGS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/warnings")
def get_warnings():
    daten = lade(DATA_FILE, {})
    warnings = daten.get("warnings", {})
    result = []
    for uid, warns in warnings.items():
        result.append({"uid": uid, "count": len(warns), "warns": warns[-3:]})
    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result[:20])

@app.route("/api/warnings/<uid>", methods=["DELETE"])
def delete_warnings(uid):
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    daten = lade(DATA_FILE, {})
    daten.get("warnings", {}).pop(uid, None)
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — GIVEAWAYS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/giveaways")
def get_giveaways():
    daten = lade(DATA_FILE, {})
    giveaways = daten.get("giveaways", {})
    result = []
    for msg_id, gw in giveaways.items():
        result.append({"id": msg_id, **gw})
    result.sort(key=lambda x: x.get("aktiv", False), reverse=True)
    return jsonify(result)

@app.route("/api/giveaways/<msg_id>/end", methods=["POST"])
def end_giveaway(msg_id):
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    daten = lade(DATA_FILE, {})
    if msg_id in daten.get("giveaways", {}):
        daten["giveaways"][msg_id]["aktiv"] = False
        speichere(DATA_FILE, daten)
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — KI / BRAIN
# ═══════════════════════════════════════════════════════════════
@app.route("/api/brain")
def get_brain():
    brain = lade(BRAIN_FILE, {})
    return jsonify({
        "personality": brain.get("personality", ""),
        "stats": brain.get("stats", {}),
        "recent_conversations": brain.get("conversation_history", [])[-10:],
        "self_improvements_count": len(brain.get("self_improvements", [])),
    })

@app.route("/api/brain/reset", methods=["POST"])
def reset_brain():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    brain = {
        "conversation_history": [],
        "personality": "Ich bin NEXUS, ein freundlicher Community-Bot.",
        "stats": {"total_conversations": 0},
        "self_improvements": []
    }
    speichere(BRAIN_FILE, brain)
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 NEXUS Dashboard API läuft auf Port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

# ═══════════════════════════════════════════════════════════════
#  ROUTES — SELFCODE
# ═══════════════════════════════════════════════════════════════
@app.route("/api/selfcode/generate", methods=["POST"])
def selfcode_generate():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    body    = request.json or {}
    aufgabe = body.get("aufgabe", "")
    if not aufgabe:
        return jsonify({"error": "Keine Aufgabe"}), 400

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        return jsonify({"error": "Kein GROQ_API_KEY"}), 500

    import urllib.request, json as _json
    url     = "https://api.groq.com/openai/v1/chat/completions"
    system  = """Du bist ein Python-Code-Generator für einen discord.py 2.x Bot.
Schreibe NUR den reinen Python-Funktionscode — keine Imports, kein if __name__, keine Erklärungen, keine Markdown-Backticks.
Nutze @bot.tree.command() für Slash-Commands. Kommentiere auf Deutsch. Max 60 Zeilen."""

    payload = _json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Schreibe eine neue Discord-Bot-Funktion für: {aufgabe}"}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {groq_key}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
            code = data["choices"][0]["message"]["content"]
            code = code.replace("```python","").replace("```","").strip()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cl = lade(CODELOG, {"extensions": [], "total_written": 0})
    cl["total_written"] += 1
    cl["extensions"].append({
        "id": cl["total_written"],
        "aufgabe": aufgabe,
        "code": code,
        "timestamp": str(datetime.datetime.utcnow())
    })
    speichere(CODELOG, cl)
    return jsonify({"ok": True, "code": code, "id": cl["total_written"]})

@app.route("/api/codelog")
def get_codelog():
    return jsonify(lade(CODELOG, {"extensions": [], "total_written": 0}))

# ═══════════════════════════════════════════════════════════════
#  ROUTES — WARNINGS ADD
# ═══════════════════════════════════════════════════════════════
@app.route("/api/warnings/add", methods=["POST"])
def add_warning():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    body  = request.json or {}
    uid   = str(body.get("uid", ""))
    grund = body.get("grund", "Kein Grund")
    if not uid: return jsonify({"error": "uid fehlt"}), 400
    daten = lade(DATA_FILE, {})
    daten.setdefault("warnings", {}).setdefault(uid, [])
    daten["warnings"][uid].append({
        "grund": grund,
        "datum": str(datetime.datetime.utcnow()),
        "mod": "Dashboard"
    })
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True, "total": len(daten["warnings"][uid])})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — GIVEAWAY CREATE
# ═══════════════════════════════════════════════════════════════
@app.route("/api/giveaways/create", methods=["POST"])
def create_giveaway():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    body = request.json or {}
    preis   = body.get("preis", "")
    dauer   = int(body.get("dauer_minuten", 60))
    gewinner= int(body.get("gewinner", 1))
    kanal   = str(body.get("kanal_id", ""))
    if not preis or not kanal:
        return jsonify({"error": "preis und kanal_id erforderlich"}), 400
    import uuid
    msg_id = str(uuid.uuid4())[:10]
    ende   = (datetime.datetime.utcnow() + datetime.timedelta(minutes=dauer)).isoformat()
    daten  = lade(DATA_FILE, {})
    daten.setdefault("giveaways", {})[msg_id] = {
        "preis": preis, "gewinner": gewinner,
        "ende": ende, "kanal_id": kanal, "aktiv": True
    }
    speichere(DATA_FILE, daten)
    return jsonify({"ok": True, "id": msg_id})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — ANNOUNCE
# ═══════════════════════════════════════════════════════════════
@app.route("/api/announce", methods=["POST"])
def announce():
    if not auth(request): return jsonify({"error": "Unauthorized"}), 401
    body     = request.json or {}
    nachricht= body.get("nachricht", "")
    typ      = body.get("typ", "info")
    # Write to a queue file the bot reads
    queue    = lade("announce_queue.json", {"messages": []})
    queue["messages"].append({
        "nachricht": nachricht, "typ": typ,
        "timestamp": str(datetime.datetime.utcnow())
    })
    speichere("announce_queue.json", queue)
    return jsonify({"ok": True, "sent": 1})

# ═══════════════════════════════════════════════════════════════
#  ROUTES — TIKFINITY WEBHOOK (TikTok LIVE Events → Discord)
#  TikFinity unterstützt keine Custom-Auth-Header für Webhooks, daher dient
#  das geheime <secret>-Pfad-Segment als Schutz statt eines Headers. Der
#  Secret-Wert kommt aus WEBHOOK_SECRET (Railway-Variable) und muss exakt
#  in der Webhook-URL stehen, die man bei TikFinity einträgt.
# ═══════════════════════════════════════════════════════════════
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

@app.route("/webhook/tikfinity/<secret>", methods=["POST"])
def tikfinity_webhook(secret):
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        # Bewusst keine Details verraten, ob das Secret existiert oder nur falsch ist.
        return jsonify({"error": "Unauthorized"}), 401

    body = request.json or {}
    # TikFinity schickt je nach Event unterschiedliche Felder — wir greifen defensiv zu,
    # damit ein unbekanntes/neues Event-Format den Bot nicht zum Absturz bringt.
    event_typ = body.get("event") or body.get("type") or "unbekannt"
    spender   = body.get("uniqueId") or body.get("nickname") or body.get("user") or "Jemand"
    geschenk  = body.get("giftName") or body.get("gift") or ""
    menge     = body.get("repeatCount") or body.get("amount") or 1
    kommentar = body.get("comment") or body.get("message") or ""

    queue = lade("tikfinity_queue.json", {"events": []})
    queue["events"].append({
        "event_typ": event_typ,
        "spender": spender,
        "geschenk": geschenk,
        "menge": menge,
        "kommentar": kommentar,
        "timestamp": str(datetime.datetime.utcnow()),
        "verarbeitet": False,
    })
    # Queue nicht unbegrenzt wachsen lassen — die letzten 200 Events reichen völlig
    queue["events"] = queue["events"][-200:]
    speichere("tikfinity_queue.json", queue)

    return jsonify({"ok": True}), 200

# ═══════════════════════════════════════════════════════════════
#  NEXUS DASHBOARD API — Flask Backend
#  Kommuniziert mit data.json + brain.json des Bots
# ═══════════════════════════════════════════════════════════════
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import json, os, datetime, threading, time, subprocess, sys

app = Flask(__name__)
CORS(app)

API_KEY     = os.environ.get("DASHBOARD_API_KEY")  # KEIN Default — fehlender Key blockiert lieber alles als ein bekanntes Passwort zu nutzen
DATA_FILE   = "data.json"
BRAIN_FILE  = "brain.json"
CODELOG     = "codelog.json"
START_TIME  = datetime.datetime.utcnow()

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def auth(req):
    if not API_KEY:
        return False  # Kein Key in Railway gesetzt → niemand kommt rein, statt unsicherem Fallback
    return req.headers.get("X-API-Key") == API_KEY

# Routen, die OHNE API-Key erreichbar sein müssen (das Dashboard-HTML selbst).
# Alles unter /api/* wird zentral hier geprüft, damit kein einzelner Endpunkt
# vergessen werden kann.
PUBLIC_PATHS = {"/"}

@app.before_request
def require_api_key_for_api_routes():
    if request.path in PUBLIC_PATHS:
        return None
    if request.path.startswith("/api/"):
        if not auth(request):
            return jsonify({"error": "Unauthorized"}), 401
    return None

@app.route("/health")
def health():
    """Öffentlicher Health-Check ohne API-Key — zum schnellen Testen ob der Server überhaupt läuft.
    Gibt KEINE sensiblen Bot-Daten zurück, nur den reinen Online-Status."""
    return jsonify({
        "ok": True,
        "api_key_configured": bool(API_KEY),
        "uptime": uptime(),
    })

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

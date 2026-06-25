import discord
from discord.ext import commands, tasks
import json
import os
import datetime
import asyncio
import aiohttp
import random
import secrets
import tempfile
import shutil
try:
    import edge_tts
    VOICE_TTS_VERFUEGBAR = True
except ImportError:
    VOICE_TTS_VERFUEGBAR = False
    print("⚠️  edge_tts nicht installiert — Voice-TTS-Features sind deaktiviert. requirements.txt prüfen.")

try:
    from TikTokLive import TikTokLiveClient
    TIKTOK_VERFUEGBAR = True
except ImportError:
    TIKTOK_VERFUEGBAR = False
    print("⚠️  TikTokLive nicht installiert — TikTok-Live-Benachrichtigungen sind deaktiviert. requirements.txt prüfen.")

# ═══════════════════════════════════════════════════════════════
#  NEXUS COMMUNITY BOT v7.0
#  Groq AI (Llama 3.1) + Level + XP + Rollen + Umfragen + Giveaways
# ═══════════════════════════════════════════════════════════════

TOKEN        = os.environ.get("DISCORD_TOKEN")
GROQ_KEY     = os.environ.get("GROQ_API_KEY")      # Kostenlos: console.groq.com
GEMINI_KEY   = GROQ_KEY  # Rückwärtskompatibler Alias, falls Code anderswo noch GEMINI_KEY referenziert
OWNER_ID     = int(os.environ.get("OWNER_ID", "0"))
PREFIX       = "!"
DATA_FILE    = "data.json"
BRAIN_FILE   = "brain.json"

# ── GitHub Self-Commit ──────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")        # Fine-grained PAT mit "Contents: Read & Write" für genau dieses Repo
GITHUB_REPO  = os.environ.get("GITHUB_REPO")          # Format: "username/repo-name", z.B. "biancarenneberg91-cpu/COMMUNITY"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

# Dateien, die der Bot NIE über /github-datei-erstellen anrühren darf —
# Schutz davor, dass die KI versehentlich den eigenen laufenden Code überschreibt
# und sich damit selbst lahmlegt oder das Deployment zerstört.
GITHUB_GESCHUETZTE_DATEIEN = {
    "bot.py", "api.py", "start.py", "Procfile", "requirements.txt",
    "data.json", "brain.json", "economy.json", "achievements.json",
    "login_requests.json", "knowledge.json", "codelog.json",
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
spam_tracker = {}
join_tracker = {}  # {guild_id: [timestamp, timestamp, ...]} — rollierendes Fenster für Raid-Erkennung

# ═══════════════════════════════════════════════════════════════
#  DATEN
# ═══════════════════════════════════════════════════════════════
def lade_daten():
    default = {
        "warnings": {}, "dienstgrade": {}, "einsaetze": 0,
        "tickets": 0, "maintenance": False, "boot_count": 0,
        "xp": {}, "levels": {}, "xp_cooldown": {},
        "giveaways": {}, "umfragen": {},
        "welcome_channel": None, "level_channel": None,
        "auto_roles": [], "ki_moderation_enabled": False,
        "level_rollen": {
            "5":  "Community Member",
            "10": "Aktives Mitglied",
            "20": "Veteran",
            "50": "Legende"
        },
        # ── Server-Management v10 ──
        "log_channel": None,
        "log_events": {
            "join": True, "leave": True, "ban": True, "kick": True,
            "warn": True, "timeout": True, "delete": False, "edit": False
        },
        "custom_commands": {},  # {"!regel": "Antworttext"}
        "quiz_scores": {},       # {uid: punktzahl}
        "inventar": {},          # {uid: [item_keys]}
        # ── v13: Erinnerungen, Automatisierung, Reaction-Roles ──
        "erinnerungen": [],  # [{"id","datum","text","kanal_id","wiederholend"(bool), "erstellt_von"}]
        "trigger": [],       # [{"id","bedingung_typ","bedingung_wert","aktion_typ","aktion_wert","aktiv"}]
        "reaction_roles": {},  # {"msg_id": {"emoji": "rollen_name"}}
        # ── v14: KI-Ticket-System ──
        "aktive_tickets": {},   # {kanal_id: {"ersteller_id","kategorie","erstellt_am","ki_aktiv"}}
        "ticket_log_channel": None,  # Kanal für Transkripte/Zusammenfassungen geschlossener Tickets
        "ticket_ki_aktiv": True,  # Globaler Schalter: soll die KI in Tickets automatisch antworten?
        # ── v15: Ticket-Dropdown-Panel + Team-Ping ──
        "ticket_kategorien": [
            {"label": "🐛 Bug melden",     "value": "bug",       "beschreibung": "Etwas funktioniert nicht wie erwartet"},
            {"label": "❓ Frage",           "value": "frage",     "beschreibung": "Allgemeine Frage zum Server/Bot"},
            {"label": "⚠️ Beschwerde",     "value": "beschwerde","beschreibung": "Ein Problem mit einem Mitglied/Inhalt melden"},
            {"label": "💡 Vorschlag",       "value": "vorschlag", "beschreibung": "Idee oder Feature-Wunsch"},
            {"label": "🤝 Sonstiges",       "value": "sonstiges", "beschreibung": "Passt in keine andere Kategorie"},
        ],
        "ticket_team_rolle": None,  # Rollen-Name, die bei Bedarf gepingt wird (z.B. "Support-Team")
        # ── v16: Voice Support (TTS + STT, befehlsbasiert) ──
        "voice_stimme": "de-DE-KatjaNeural",  # edge-tts Stimmen-ID, siehe /voice-stimmen-liste
        # ── v17: TikTok Live-Benachrichtigungen + Link-Automod ──
        "tiktok_ueberwachte_creator": {},  # {"username": {"kanal_id","letzte_meldung_live": bool}}
        "tiktok_link_automod_aktiv": False,
        "tiktok_link_erlaubte_kanaele": [],  # Kanal-Namen, in denen TikTok-Links erlaubt sind
        # ── v18: Offizieller TikTok-Account des Servers/Bots ──
        "tiktok_eigener_account": None,  # Username (ohne @), den der Owner als "unseren" Account hinterlegt hat
        "tiktok_eigener_account_beschreibung": "",  # Optionaler Freitext, z.B. "Folgt uns für Clips!"
        # ── v19: TikFinity Webhook-Integration (Live-Events: Geschenke, Follows, Kommentare) ──
        "tikfinity_kanal": None,  # Discord-Kanal-ID, in den TikFinity-Live-Events gepostet werden
        # ── v20: Anti-Raid / Security ──
        "antiraid_aktiv": False,
        "antiraid_join_schwelle": 5,       # X Joins
        "antiraid_join_zeitfenster": 10,   # innerhalb von Y Sekunden → Raid-Verdacht
        "antiraid_min_account_alter_tage": 7,  # Accounts jünger als das werden bei aktivem Raid-Modus eingeschränkt
        "antiraid_lockdown_aktiv": False,  # Wird automatisch True bei erkanntem Raid, manuell aufhebbar
        "antinuke_aktiv": False,
        "antinuke_log_kanal": None,
        "antinuke_max_aktionen": 3,        # X destruktive Aktionen (Kanal/Rolle löschen, Massen-Ban)
        "antinuke_zeitfenster": 30,        # innerhalb von Y Sekunden → automatische Reaktion
        "quarantaene_rolle": None,         # Rollen-Name für neue Mitglieder bei aktivem Lockdown
    }
    return _robust_json_lesen(DATA_FILE, default)

def _robust_json_lesen(pfad: str, default: dict) -> dict:
    """Zentrale, wiederverwendbare robuste JSON-Lesefunktion für ALLE Datendateien.
    Falls die Datei fehlt: legt sie mit Defaults an. Falls sie beschädigt ist
    (z.B. durch einen Absturz mitten im alten, nicht-atomaren Schreibvorgang):
    sichert die kaputte Version als .corrupt und fällt auf Defaults zurück,
    statt den ganzen Bot beim Start crashen zu lassen."""
    if not os.path.exists(pfad):
        _atomar_json_schreiben(pfad, default)
        return dict(default)
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            geladen = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  KRITISCH: {pfad} ist beschädigt ({e}) — falle auf Standard-Werte zurück!")
        try:
            os.replace(pfad, pfad + ".corrupt")
            print(f"⚠️  Beschädigte Datei gesichert als {pfad}.corrupt — manuell prüfbar.")
        except Exception as backup_err:
            print(f"⚠️  Konnte beschädigte Datei nicht sichern: {backup_err}")
        _atomar_json_schreiben(pfad, default)
        return dict(default)
    for k, v in default.items():
        geladen.setdefault(k, v)
    return geladen

def _atomar_json_schreiben(pfad: str, daten: dict):
    """Zentrale, wiederverwendbare atomare JSON-Schreibfunktion für ALLE Datendateien
    des Bots (data.json, brain.json, economy.json, achievements.json, knowledge.json).
    Schreibt erst in eine temporäre Datei, dann per os.replace() umbenennen — das ist
    auf praktisch allen Systemen atomar, ein 'halb geschriebener' Zustand bei einem
    Absturz/Neustart mitten im Schreiben ist so ausgeschlossen."""
    tmp_pfad = pfad + ".tmp"
    with open(tmp_pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=4, ensure_ascii=False)
    os.replace(tmp_pfad, pfad)

def speichere_daten(d):
    _atomar_json_schreiben(DATA_FILE, d)

def lade_brain():
    default = {
        "conversation_history": [],
        "personality": "Ich bin NEXUS, ein freundlicher Community-Bot. Ich helfe gerne und bin immer positiv.",
        "stats": {"total_conversations": 0},
        "user_chat_counts": {},
        "user_memory": {}  # {uid: "Notizen die die KI sich über diesen Nutzer merkt"}
    }
    return _robust_json_lesen(BRAIN_FILE, default)

def speichere_brain(b):
    _atomar_json_schreiben(BRAIN_FILE, b)

# ═══════════════════════════════════════════════════════════════
#  WISSENSDATENBANK — Owner-gepflegte Fakten/FAQ, die die KI in
#  JEDEM Gespräch (DM, @-Mention, /ki-chat) als Kontext mitbekommt.
# ═══════════════════════════════════════════════════════════════
KNOWLEDGE_FILE = "knowledge.json"

def lade_knowledge():
    default = {"entries": {}}  # {"schlüssel": "Fakteninhalt"}
    return _robust_json_lesen(KNOWLEDGE_FILE, default)

def speichere_knowledge(k):
    _atomar_json_schreiben(KNOWLEDGE_FILE, k)

def knowledge_als_kontext(max_zeichen: int = 1500) -> str:
    """Baut einen kompakten Text aus allen Wissenseinträgen für den System-Prompt.
    Begrenzt die Länge, damit der Prompt nicht unbegrenzt wächst."""
    k = lade_knowledge()
    if not k["entries"]:
        return ""
    zeilen = [f"- {schluessel}: {wert}" for schluessel, wert in k["entries"].items()]
    text = "\n".join(zeilen)
    if len(text) > max_zeichen:
        text = text[:max_zeichen] + "\n... (weitere Einträge gekürzt)"
    return text

# ═══════════════════════════════════════════════════════════════
#  GITHUB SELF-COMMIT — Bot kann eigenständig Dateien im Repo anlegen
# ═══════════════════════════════════════════════════════════════
import base64

def github_pfad_validieren(pfad: str) -> tuple[bool, str]:
    """Verhindert Path-Traversal (../) und Schreibzugriff auf geschützte
    Dateien, die den laufenden Bot selbst betreffen würden.
    Gibt (ok, fehler_oder_normalisierter_pfad) zurück — bei ok=True steht
    im zweiten Feld der normalisierte Pfad, bei ok=False die Fehlermeldung."""
    pfad = pfad.strip()
    if not pfad:
        return False, "Pfad darf nicht leer sein."
    if ":" in pfad:
        return False, "Ungültiger Pfad."
    if pfad.startswith("/"):
        pfad = pfad.lstrip("/")  # GitHub-Pfade sind immer repo-relativ, kein führendes "/"
        if not pfad:
            return False, "Pfad darf nicht leer sein."
    if ".." in pfad.split("/"):
        return False, "Pfad darf kein '..' enthalten (Path-Traversal)."
    dateiname = pfad.split("/")[-1]
    if dateiname in GITHUB_GESCHUETZTE_DATEIEN:
        return False, f"'{dateiname}' ist eine geschützte Systemdatei — der Bot darf sie nicht über diesen Befehl verändern."
    return True, pfad

async def github_datei_erstellen(pfad: str, inhalt: str, commit_message: str) -> dict:
    """Erstellt ODER aktualisiert eine Datei im verbundenen GitHub-Repo via Contents API.
    Gibt {"ok": True, "url": ...} bei Erfolg oder {"ok": False, "error": ...} zurück."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {"ok": False, "error": "GITHUB_TOKEN oder GITHUB_REPO ist in Railway nicht gesetzt."}

    valid, fehler_oder_pfad = github_pfad_validieren(pfad)
    if not valid:
        return {"ok": False, "error": fehler_oder_pfad}
    pfad = fehler_oder_pfad  # normalisierter, validierter Pfad

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{pfad}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Prüfen ob die Datei schon existiert — wenn ja, brauchen wir ihren sha für ein Update
            sha = None
            async with session.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}) as r:
                if r.status == 200:
                    bestehend = await r.json()
                    sha = bestehend.get("sha")
                elif r.status not in (404,):
                    text = await r.text()
                    return {"ok": False, "error": f"GitHub GET Fehler {r.status}: {text[:200]}"}

            inhalt_b64 = base64.b64encode(inhalt.encode("utf-8")).decode("ascii")
            payload = {
                "message": commit_message[:200],
                "content": inhalt_b64,
                "branch": GITHUB_BRANCH,
            }
            if sha:
                payload["sha"] = sha  # nötig, um eine bestehende Datei zu überschreiben

            async with session.put(api_url, headers=headers, json=payload) as r:
                data = await r.json()
                if r.status in (200, 201):
                    return {
                        "ok": True,
                        "url": data.get("content", {}).get("html_url", ""),
                        "neu_erstellt": sha is None,
                    }
                return {"ok": False, "error": f"GitHub PUT Fehler {r.status}: {str(data)[:300]}"}
    except Exception as e:
        return {"ok": False, "error": f"Verbindungsfehler: {e}"}

# ═══════════════════════════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════════════════════════
def ist_owner(uid): return uid == OWNER_ID

def owner_only():
    async def predicate(i: discord.Interaction):
        if not ist_owner(i.user.id):
            await i.response.send_message("❌ Nur der Owner kann das.", ephemeral=True)
            return False
        return True
    return discord.app_commands.check(predicate)

# ═══════════════════════════════════════════════════════════════
#  ANTI-RAID — automatischer Lockdown bei erkanntem Mass-Join
# ═══════════════════════════════════════════════════════════════
async def raid_lockdown_aktivieren(guild: discord.Guild, grund: str):
    """Wird automatisch ausgelöst, wenn zu viele Joins in kurzer Zeit erkannt werden.
    Hebt Discords eigenes Verifizierungslevel an (erfordert dann z.B. eine verifizierte
    E-Mail/Telefonnummer für neue Mitglieder — das bremst die allermeisten Raid-Bots
    zuverlässig aus, da das native Discord-Schutzmaßnahmen sind, kein Reverse-Engineering)."""
    daten = lade_daten()
    daten["antiraid_lockdown_aktiv"] = True
    speichere_daten(daten)

    try:
        await guild.edit(verification_level=discord.VerificationLevel.high)
    except Exception as e:
        print(f"[Anti-Raid] Konnte Verifizierungslevel nicht anheben: {e}")

    embed = discord.Embed(
        title="🚨 RAID ERKANNT — LOCKDOWN AKTIVIERT",
        description=(
            f"**Grund:** {grund}\n\n"
            "Das Server-Verifizierungslevel wurde automatisch auf **Hoch** angehoben.\n"
            "Neue Mitglieder mit jungen Accounts werden in Quarantäne gesetzt (falls eine Quarantäne-Rolle konfiguriert ist).\n\n"
            "Nutze `/antiraid-lockdown-aufheben` sobald die Lage geklärt ist."
        ),
        color=0xff0000,
        timestamp=datetime.datetime.utcnow()
    )
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(embed=embed)
        except Exception as e:
            print(f"[Anti-Raid] Konnte Owner nicht per DM benachrichtigen: {e}")

    log_kanal_id = daten.get("log_channel")
    if log_kanal_id:
        kanal = guild.get_channel(int(log_kanal_id))
        if kanal:
            try:
                await kanal.send(embed=embed)
            except Exception as e:
                print(f"[Anti-Raid] Konnte Log nicht senden: {e}")

# ═══════════════════════════════════════════════════════════════
#  ZENTRALES MOD-LOGGING
# ═══════════════════════════════════════════════════════════════
async def log_event(guild: discord.Guild, event_typ: str, embed: discord.Embed):
    """Schickt einen Log-Eintrag in den konfigurierten Log-Kanal, falls dieser
    Event-Typ aktiviert ist. event_typ z.B. 'join','leave','ban','kick','warn','timeout'."""
    daten = lade_daten()
    log_events = daten.get("log_events", {})
    if not log_events.get(event_typ, False):
        return
    ch_id = daten.get("log_channel")
    if not ch_id:
        return
    kanal = guild.get_channel(int(ch_id))
    if not kanal:
        return
    try:
        await kanal.send(embed=embed)
    except Exception as e:
        print(f"[Log] Konnte nicht in Log-Kanal senden: {e}")

def xp_fuer_level(level):
    return 100 * (level ** 2) + 100 * level

def get_level(xp):
    level = 0
    while xp >= xp_fuer_level(level + 1):
        level += 1
    return level

def xp_bar(xp, level):
    current = xp - xp_fuer_level(level)
    needed = xp_fuer_level(level + 1) - xp_fuer_level(level)
    filled = int((current / needed) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {current}/{needed} XP"

# ═══════════════════════════════════════════════════════════════
#  GROQ AI
# ═══════════════════════════════════════════════════════════════
#  GROQ AI — schnelle, kostenlose LLM-Engine (Llama 3.1 8B Instant)
#  Funktionsname "frage_gemini" bleibt erhalten, um alle bestehenden
#  Aufrufstellen im Code unverändert zu lassen — nur die Engine wechselt.
# ═══════════════════════════════════════════════════════════════
async def frage_gemini(system: str, user_msg: str, history: list = None) -> str:
    if not GROQ_KEY:
        return "❌ Kein GROQ_API_KEY gesetzt. Hol dir einen kostenlosen Key auf console.groq.com"

    clean_key = GROQ_KEY.strip().replace("\n", "").replace(" ", "")
    url = "https://api.groq.com/openai/v1/chat/completions"

    # Konversations-History aufbauen (OpenAI-Format: role/content)
    messages = [{"role": "system", "content": system}]
    if history:
        for h in history[-8:]:
            if h.get("frage"):
                messages.append({"role": "user", "content": h["frage"]})
            if h.get("antwort"):
                messages.append({"role": "assistant", "content": h["antwort"]})
    messages.append({"role": "user", "content": user_msg})

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 1000,
    }
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    return data["choices"][0]["message"]["content"]
                err = await r.text()
                print(f"[Groq] Fehler {r.status}: {err[:300]}")
                if r.status == 429:
                    return "🕐 Die KI braucht kurz eine Pause (Tageslimit erreicht). Versuch's in ein paar Minuten nochmal!"
                return f"❌ Groq Fehler {r.status}: {err[:150]}"
    except Exception as e:
        return f"❌ Verbindungsfehler: {e}"


async def lerne(frage: str, antwort: str, uid: str = None, channel=None):
    brain = lade_brain()
    brain["stats"]["total_conversations"] += 1
    brain["conversation_history"].append({
        "frage": frage, "antwort": antwort,
        "ts": str(datetime.datetime.utcnow())
    })
    if len(brain["conversation_history"]) > 50:
        brain["conversation_history"] = brain["conversation_history"][-50:]

    # Pro-Nutzer KI-Chat-Zähler (für /ki-chatter Achievement)
    if uid:
        brain.setdefault("user_chat_counts", {})
        brain["user_chat_counts"][uid] = brain["user_chat_counts"].get(uid, 0) + 1
        if brain["user_chat_counts"][uid] >= 50:
            await schalte_achievement_frei(uid, "ki_chatter", channel)

    speichere_brain(brain)

# ═══════════════════════════════════════════════════════════════
#  XP + LEVEL SYSTEM
# ═══════════════════════════════════════════════════════════════
async def gib_xp(message: discord.Message):
    if message.author.bot: return
    daten = lade_daten()
    uid = str(message.author.id)
    now = datetime.datetime.utcnow().timestamp()

    # Achievement: erste Nachricht (einmalig, unabhängig vom XP-Cooldown)
    try:
        a = lade_achievements()
        if "first_message" not in a["unlocked"].get(uid, []):
            await schalte_achievement_frei(uid, "first_message", message.channel)
    except Exception as e:
        print(f"[Achievement] Fehler: {e}")

    # Cooldown: 1 Minute zwischen XP-Vergabe
    cooldown = daten["xp_cooldown"].get(uid, 0)
    if now - cooldown < 60: return

    daten["xp_cooldown"][uid] = now
    daten["xp"].setdefault(uid, 0)
    daten["levels"].setdefault(uid, 0)

    xp_gewinn = random.randint(10, 25)
    daten["xp"][uid] += xp_gewinn

    alter_level = daten["levels"][uid]
    neuer_level = get_level(daten["xp"][uid])

    if neuer_level > alter_level:
        daten["levels"][uid] = neuer_level
        speichere_daten(daten)
        await level_up(message, neuer_level, daten)
    else:
        speichere_daten(daten)

async def level_up(message: discord.Message, level: int, daten: dict):
    guild = message.guild
    member = message.author
    uid = str(member.id)

    # Level-Achievements
    if level >= 10:
        await schalte_achievement_frei(uid, "level_10", message.channel)
    if level >= 25:
        await schalte_achievement_frei(uid, "level_25", message.channel)

    # Level-Rolle vergeben
    level_rollen = daten.get("level_rollen", {})
    for lvl_str, rollen_name in level_rollen.items():
        if int(lvl_str) == level:
            rolle = discord.utils.get(guild.roles, name=rollen_name)
            if not rolle:
                try:
                    rolle = await guild.create_role(name=rollen_name, color=discord.Color.blurple())
                except: pass
            if rolle:
                try: await member.add_roles(rolle)
                except: pass

    # Level-Up Nachricht
    embed = discord.Embed(
        title="⬆️ LEVEL UP!",
        description=f"🎉 {member.mention} hat **Level {level}** erreicht!",
        color=0x00f5ff
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Bonus-Text per KI (Groq)
    if GEMINI_KEY:
        bonus = await frage_gemini(
            "Du bist ein freundlicher Discord-Bot. Schreibe einen kurzen motivierenden Satz (max 1 Satz) auf Deutsch für einen Nutzer der gerade ein neues Level erreicht hat.",
            f"Nutzer {member.display_name} hat Level {level} erreicht!"
        )
        if not bonus.startswith("❌"):
            embed.add_field(name="🤖 NEXUS sagt:", value=bonus[:200])

    lvl_ch_id = daten.get("level_channel")
    if lvl_ch_id:
        ch = guild.get_channel(int(lvl_ch_id))
        if ch:
            await ch.send(embed=embed); return
    await message.channel.send(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  BOT EVENTS
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await bot.tree.sync()
    daten = lade_daten()
    daten["boot_count"] = daten.get("boot_count", 0) + 1
    speichere_daten(daten)

    # Persistente Views erneut registrieren — sonst reagiert der Bot nach einem
    # Neustart nicht mehr auf Klicks an alten Ticket-Panel-Nachrichten.
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"die Community 👀")
    )

    print(f"╔══════════════════════════════════╗")
    print(f"║  NEXUS COMMUNITY BOT v7.0        ║")
    print(f"║  {bot.user}".ljust(35) + "║")
    print(f"║  Owner: {OWNER_ID}".ljust(35) + "║")
    print(f"╚══════════════════════════════════╝")

    # Owner DM
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            embed = discord.Embed(title="🟢 NEXUS Online", description=f"Bot gestartet! Boot #{daten['boot_count']}", color=0x00ff88)
            embed.add_field(name="🌐 Server", value=str(len(bot.guilds)))
            embed.add_field(name="🤖 KI", value="Groq Llama 3.1 8B Instant")
            await owner.send(embed=embed)
        except: pass

    check_giveaways.start()
    verarbeite_login_queue.start()
    verarbeite_announce_queue.start()
    check_erinnerungen.start()
    check_zeit_trigger.start()
    check_tiktok_live.start()
    verarbeite_tikfinity_queue.start()

async def pruefe_mitgliederzahl_trigger(guild: discord.Guild):
    """Prüft alle aktiven Trigger vom Typ 'mitglieder_anzahl' und feuert sie,
    falls die aktuelle Mitgliederzahl die hinterlegte Schwelle erreicht/überschreitet.
    Markiert ausgelöste Trigger als 'ausgeloest', damit sie nicht jedes Mal erneut feuern."""
    daten = lade_daten()
    aktuelle_anzahl = guild.member_count
    geaendert = False

    for trigger in daten.get("trigger", []):
        if not trigger.get("aktiv", True):
            continue
        if trigger["bedingung_typ"] != "mitglieder_anzahl":
            continue
        try:
            schwelle = int(trigger["bedingung_wert"])
        except (ValueError, TypeError):
            continue
        if aktuelle_anzahl < schwelle:
            continue
        bereits_ausgeloest = trigger.get("ausgeloest_bei_anzahl", 0)
        if bereits_ausgeloest >= schwelle:
            continue  # Diese Schwelle wurde schon erreicht, nicht erneut feuern

        kanal = guild.system_channel
        if trigger.get("aktion_typ") == "nachricht" and kanal:
            try:
                await kanal.send(trigger["aktion_wert"].replace("{anzahl}", str(aktuelle_anzahl)))
            except Exception as e:
                print(f"[Trigger] Konnte Nachricht nicht senden: {e}")
        trigger["ausgeloest_bei_anzahl"] = schwelle
        geaendert = True

    if geaendert:
        speichere_daten(daten)

@tasks.loop(minutes=1)
async def check_zeit_trigger():
    """Prüft jede Minute ob ein 'tageszeit'-Trigger genau jetzt feuern soll (HH:MM Match)."""
    daten = lade_daten()
    jetzt = datetime.datetime.utcnow().strftime("%H:%M")

    for trigger in daten.get("trigger", []):
        if not trigger.get("aktiv", True):
            continue
        if trigger["bedingung_typ"] != "tageszeit":
            continue
        if trigger["bedingung_wert"] != jetzt:
            continue
        if trigger.get("aktion_typ") != "nachricht":
            continue
        for guild in bot.guilds:
            kanal = guild.system_channel
            if kanal:
                try:
                    await kanal.send(trigger["aktion_wert"])
                except Exception as e:
                    print(f"[Trigger] Konnte Tageszeit-Nachricht nicht senden: {e}")

@bot.event
async def on_member_join(member):
    daten = lade_daten()
    if daten.get("maintenance") and not ist_owner(member.id): return

    # ═══════════════════════════════════════════════════════════
    # ANTI-RAID: Mass-Join-Erkennung + Account-Alter-Check
    # Läuft VOR Auto-Rollen, damit verdächtige Accounts diese nicht bekommen.
    # ═══════════════════════════════════════════════════════════
    if daten.get("antiraid_aktiv"):
        now_ts = datetime.datetime.utcnow().timestamp()
        gid = member.guild.id
        join_tracker.setdefault(gid, [])
        fenster = daten.get("antiraid_join_zeitfenster", 10)
        join_tracker[gid] = [t for t in join_tracker[gid] if now_ts - t < fenster]
        join_tracker[gid].append(now_ts)

        schwelle = daten.get("antiraid_join_schwelle", 5)
        if len(join_tracker[gid]) >= schwelle and not daten.get("antiraid_lockdown_aktiv"):
            await raid_lockdown_aktivieren(member.guild, grund=f"{len(join_tracker[gid])} Joins innerhalb von {fenster}s erkannt")

        # Account-Alter prüfen — sehr neue Accounts sind ein typisches Raid-Muster
        account_alter_tage = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
        min_alter = daten.get("antiraid_min_account_alter_tage", 7)
        if account_alter_tage < min_alter or daten.get("antiraid_lockdown_aktiv"):
            quarantaene_name = daten.get("quarantaene_rolle")
            if quarantaene_name:
                rolle = discord.utils.get(member.guild.roles, name=quarantaene_name)
                if rolle:
                    try:
                        await member.add_roles(rolle)
                        log_embed = discord.Embed(
                            title="🛡️ Mitglied in Quarantäne",
                            description=f"{member.mention} ({member.id})\nAccount-Alter: {account_alter_tage} Tage",
                            color=0xff6600,
                            timestamp=datetime.datetime.utcnow()
                        )
                        await log_event(member.guild, "join", log_embed)
                    except Exception as e:
                        print(f"[Anti-Raid] Konnte Quarantäne-Rolle nicht vergeben: {e}")
                return  # Keine Auto-Rollen, keine Willkommensnachricht für Quarantäne-Fälle

    # Auto-Rollen vergeben
    for rollen_name in daten.get("auto_roles", []):
        rolle = discord.utils.get(member.guild.roles, name=rollen_name)
        if rolle:
            try: await member.add_roles(rolle)
            except: pass

    # Log-Eintrag (unabhängig vom Willkommens-Kanal, daher VOR dem early return)
    log_embed = discord.Embed(title="📥 Mitglied beigetreten", color=0x00ff88, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{member} ({member.id})")
    log_embed.add_field(name="Account erstellt", value=member.created_at.strftime("%d.%m.%Y"))
    await log_event(member.guild, "join", log_embed)

    # Automatisierungs-Trigger: Mitgliederzahl-Schwellen prüfen
    await pruefe_mitgliederzahl_trigger(member.guild)

    # Willkommens-Nachricht
    ch_id = daten.get("welcome_channel")
    kanal = member.guild.get_channel(int(ch_id)) if ch_id else member.guild.system_channel
    if not kanal: return

    willkommen_text = f"Willkommen auf dem Server, {member.display_name}!"
    if GEMINI_KEY:
        ai_text = await frage_gemini(
            "Du bist ein freundlicher Discord-Bot. Schreibe eine kurze herzliche Willkommensnachricht (max 2 Sätze) auf Deutsch.",
            f"Neues Mitglied: {member.display_name} ist dem Server {member.guild.name} beigetreten."
        )
        if not ai_text.startswith("❌"):
            willkommen_text = ai_text

    embed = discord.Embed(
        title=f"👋 Willkommen, {member.display_name}!",
        description=willkommen_text,
        color=0x00f5ff
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👥 Mitglied #", value=str(member.guild.member_count))
    embed.set_footer(text=member.guild.name)
    await kanal.send(embed=embed)

@bot.event
async def on_member_remove(member):
    """Mitglied hat den Server verlassen (oder wurde entfernt) — separates Event von on_member_join."""
    daten = lade_daten()
    log_embed = discord.Embed(title="📤 Mitglied hat den Server verlassen", color=0xff6600, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{member} ({member.id})")
    if member.joined_at:
        log_embed.add_field(name="War Mitglied seit", value=member.joined_at.strftime("%d.%m.%Y"))
    await log_event(member.guild, "leave", log_embed)

# ═══════════════════════════════════════════════════════════════
#  ANTI-NUKE — Schutz gegen Massen-Löschung durch kompromittierte
#  Mod-Accounts. Trackt destruktive Aktionen pro Person via Audit-Log
#  und entzieht bei Überschreiten der Schwelle automatisch alle Rollen.
# ═══════════════════════════════════════════════════════════════
nuke_aktion_tracker = {}  # {guild_id: {user_id: [timestamp, ...]}}

async def pruefe_antinuke(guild: discord.Guild, audit_action, aktions_name: str):
    daten = lade_daten()
    if not daten.get("antinuke_aktiv"):
        return

    try:
        async for eintrag in guild.audit_logs(action=audit_action, limit=1):
            verursacher = eintrag.user
            break
        else:
            return
    except discord.Forbidden:
        print("[Anti-Nuke] Keine Berechtigung für Audit-Log — 'View Audit Log' Permission fehlt dem Bot.")
        return
    except Exception as e:
        print(f"[Anti-Nuke] Audit-Log-Fehler: {e}")
        return

    if verursacher is None or verursacher.bot or ist_owner(verursacher.id):
        return  # Bots (inkl. uns selbst) und der Owner sind ausgenommen

    now_ts = datetime.datetime.utcnow().timestamp()
    gid = guild.id
    nuke_aktion_tracker.setdefault(gid, {})
    nuke_aktion_tracker[gid].setdefault(verursacher.id, [])

    fenster = daten.get("antinuke_zeitfenster", 30)
    nuke_aktion_tracker[gid][verursacher.id] = [t for t in nuke_aktion_tracker[gid][verursacher.id] if now_ts - t < fenster]
    nuke_aktion_tracker[gid][verursacher.id].append(now_ts)

    anzahl = len(nuke_aktion_tracker[gid][verursacher.id])
    schwelle = daten.get("antinuke_max_aktionen", 3)

    if anzahl >= schwelle:
        member = guild.get_member(verursacher.id)
        embed = discord.Embed(
            title="🚨 ANTI-NUKE AUSGELÖST",
            description=(
                f"**{verursacher}** hat {anzahl}x '{aktions_name}' innerhalb von {fenster}s durchgeführt.\n"
                f"{'Alle Rollen wurden entzogen.' if member else 'Nutzer ist nicht mehr im Server.'}"
            ),
            color=0xff0000,
            timestamp=datetime.datetime.utcnow()
        )
        if member:
            try:
                rollen_zu_entfernen = [r for r in member.roles if r.name != "@everyone"]
                await member.remove_roles(*rollen_zu_entfernen, reason="Anti-Nuke: zu viele destruktive Aktionen")
            except Exception as e:
                print(f"[Anti-Nuke] Konnte Rollen nicht entziehen: {e}")
                embed.add_field(name="⚠️ Fehler", value=f"Konnte Rollen nicht automatisch entziehen: {e}", inline=False)

        if OWNER_ID:
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(embed=embed)
            except Exception as e:
                print(f"[Anti-Nuke] Konnte Owner nicht per DM benachrichtigen: {e}")

        log_kanal_id = daten.get("antinuke_log_kanal") or daten.get("log_channel")
        if log_kanal_id:
            kanal = guild.get_channel(int(log_kanal_id))
            if kanal:
                try:
                    await kanal.send(embed=embed)
                except Exception as e:
                    print(f"[Anti-Nuke] Konnte Log nicht senden: {e}")

        nuke_aktion_tracker[gid][verursacher.id] = []  # Zähler zurücksetzen nach Reaktion

@bot.event
async def on_guild_channel_delete(channel):
    await pruefe_antinuke(channel.guild, discord.AuditLogAction.channel_delete, "Kanal gelöscht")

@bot.event
async def on_guild_role_delete(role):
    await pruefe_antinuke(role.guild, discord.AuditLogAction.role_delete, "Rolle gelöscht")

@bot.event
async def on_member_ban(guild, user):
    await pruefe_antinuke(guild, discord.AuditLogAction.ban, "Mitglied gebannt")

@bot.event
async def on_message(message):
    if message.author.bot: return

    # ═══════════════════════════════════════════════════════════
    # DM-HANDLING — komplett eigener Pfad, da DMs kein message.guild,
    # keine Member-Methoden (timeout etc.) und keinen XP-Sinn haben.
    # Muss VOR jeglichem Guild-Code abzweigen, sonst crasht z.B. gib_xp().
    # ═══════════════════════════════════════════════════════════
    if message.guild is None:
        daten = lade_daten()
        if daten.get("maintenance") and not ist_owner(message.author.id):
            return

        # Custom Commands funktionieren auch per DM
        custom = daten.get("custom_commands", {})
        erster_begriff = message.content.strip().split(" ")[0].lower() if message.content.strip() else ""
        if erster_begriff in custom:
            await message.channel.send(custom[erster_begriff][:2000])
            await bot.process_commands(message)
            return

        # Jede normale Textnachricht per DM wird direkt beantwortet — kein @-Ping nötig
        if message.content.strip():
            async with message.channel.typing():
                brain = lade_brain()
                uid = str(message.author.id)
                persoenliche_notiz = brain.get("user_memory", {}).get(uid, "")
                wissen = knowledge_als_kontext()
                system = f"""{brain['personality']}
Dies ist eine private Direktnachricht (DM), kein Server-Kanal.
Antworte auf Deutsch, freundlich und kurz (max 3 Sätze).
Datum: {datetime.datetime.utcnow().strftime('%d.%m.%Y')}"""
                if persoenliche_notiz:
                    system += f"\nDas merkst du dir über diesen Nutzer: {persoenliche_notiz}"
                if wissen:
                    system += f"\n\nWissensdatenbank (nutze dies für Fakten, falls relevant):\n{wissen}"
                antwort = await frage_gemini(system, message.content, brain["conversation_history"])
                await lerne(message.content, antwort, uid=uid, channel=message.channel)
                await message.channel.send(antwort[:2000])

        await bot.process_commands(message)
        return  # Ab hier nie in den Guild-Code weiterlaufen

    # ═══════════════════════════════════════════════════════════
    # AB HIER: NUR NOCH GUILD-NACHRICHTEN (message.guild ist garantiert gesetzt)
    # ═══════════════════════════════════════════════════════════
    daten = lade_daten()
    if daten.get("maintenance") and not ist_owner(message.author.id): return

    # Anti-Spam
    uid = message.author.id
    now = datetime.datetime.utcnow()
    spam_tracker.setdefault(uid, {"count": 0, "last": now})
    if (now - spam_tracker[uid]["last"]).total_seconds() > 5:
        spam_tracker[uid] = {"count": 0, "last": now}
    spam_tracker[uid]["count"] += 1
    spam_tracker[uid]["last"] = now
    if spam_tracker[uid]["count"] >= 6 and not ist_owner(uid):
        try:
            await message.author.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=5), reason="Spam")
            await message.channel.send(f"🚫 {message.author.mention} wegen Spam getimeoutet.")
        except: pass
        spam_tracker[uid]["count"] = 0

    # TikTok-Link-Automod (regelbasiert, kein KI-Aufruf nötig)
    daten_tiktok_check = daten.get("tiktok_link_automod_aktiv", False)
    if daten_tiktok_check and not ist_owner(uid):
        enthaelt_tiktok_link = "tiktok.com" in message.content.lower()
        kanal_erlaubt = message.channel.name in daten.get("tiktok_link_erlaubte_kanaele", [])
        if enthaelt_tiktok_link and not kanal_erlaubt:
            try:
                await message.delete()
                hinweis = await message.channel.send(
                    f"🚫 {message.author.mention} TikTok-Links sind in diesem Kanal nicht erlaubt.",
                    delete_after=8
                )
            except Exception as e:
                print(f"[TikTok-Automod] Konnte Nachricht nicht entfernen: {e}")
            return

    # KI-Moderation (opt-in, /ki-moderation-an) — prüft längere Nachrichten
    if daten.get("ki_moderation_enabled") and not ist_owner(uid) and len(message.content) >= 15:
        check = await ki_moderation_check(message.content)
        if check.get("toxic"):
            try:
                await message.delete()
                warn_embed = discord.Embed(
                    title="⚠️ Nachricht entfernt",
                    description=f"Deine Nachricht wurde von der KI-Moderation als problematisch eingestuft.\n**Grund:** {check.get('grund','—')}",
                    color=0xff3333
                )
                await message.author.send(embed=warn_embed)
            except Exception as e:
                print(f"[KI-Mod] Konnte Nachricht nicht entfernen/DM senden: {e}")
            return  # Nachricht ist gelöscht, keine weitere Verarbeitung (kein XP etc.)

    # XP vergeben
    await gib_xp(message)

    # Custom Commands (vom Owner über /custom-command-hinzufügen definiert)
    custom = daten.get("custom_commands", {})
    erster_begriff = message.content.strip().split(" ")[0].lower() if message.content.strip() else ""
    if erster_begriff in custom:
        await message.channel.send(custom[erster_begriff][:2000])
        await bot.process_commands(message)
        return

    # KI-Ticket-Auto-Antwort: in aktiven Ticket-Kanälen antwortet die KI auf jede
    # normale Nachricht, ohne dass ein @-Ping nötig ist (analog zum DM-Verhalten).
    ticket_eintrag = daten.get("aktive_tickets", {}).get(str(message.channel.id))
    ist_ticket_ki_antwort = False
    if ticket_eintrag and ticket_eintrag.get("ki_aktiv", True) and message.content.strip() and bot.user not in message.mentions:
        ist_ticket_ki_antwort = True
        async with message.channel.typing():
            brain = lade_brain()
            await ki_ticket_antworten(message.channel, message.content, str(message.author.id), brain["conversation_history"])

    # Bot erwähnt → KI antwortet (überspringen, falls Ticket-Auto-Antwort schon gefeuert hat)
    if bot.user in message.mentions and not ist_ticket_ki_antwort:
        frage = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if frage:
            async with message.channel.typing():
                brain = lade_brain()
                persoenliche_notiz = brain.get("user_memory", {}).get(str(message.author.id), "")
                wissen = knowledge_als_kontext()
                system = f"""{brain['personality']}
Du bist auf dem Discord-Server '{message.guild.name if message.guild else 'DM'}'.
Antworte auf Deutsch, freundlich und kurz (max 3 Sätze).
Datum: {datetime.datetime.utcnow().strftime('%d.%m.%Y')}"""
                if persoenliche_notiz:
                    system += f"\nDas merkst du dir über diesen Nutzer: {persoenliche_notiz}"
                if wissen:
                    system += f"\n\nWissensdatenbank (nutze dies für Fakten, falls relevant):\n{wissen}"
                antwort = await frage_gemini(system, frage, brain["conversation_history"])
                await lerne(frage, antwort, uid=str(message.author.id), channel=message.channel)
                await message.reply(antwort[:2000])

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════════
#  LEVEL BEFEHLE
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="rang", description="Deinen aktuellen Rang und XP anzeigen")
async def rang(interaction: discord.Interaction, mitglied: discord.Member = None):
    ziel = mitglied or interaction.user
    daten = lade_daten()
    uid = str(ziel.id)
    xp = daten["xp"].get(uid, 0)
    level = get_level(xp)

    embed = discord.Embed(title=f"📊 {ziel.display_name}", color=0x00f5ff)
    embed.set_thumbnail(url=ziel.display_avatar.url)
    embed.add_field(name="⭐ Level", value=str(level), inline=True)
    embed.add_field(name="✨ XP gesamt", value=str(xp), inline=True)
    embed.add_field(name="📈 Fortschritt", value=xp_bar(xp, level), inline=False)

    # Ranglisten-Position
    alle_xp = sorted(daten["xp"].items(), key=lambda x: x[1], reverse=True)
    pos = next((i+1 for i, (uid2, _) in enumerate(alle_xp) if uid2 == uid), "?")
    embed.add_field(name="🏆 Serverrang", value=f"#{pos}", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="top", description="Top 10 Rangliste anzeigen")
async def top(interaction: discord.Interaction):
    daten = lade_daten()
    alle_xp = sorted(daten["xp"].items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(title="🏆 SERVER RANGLISTE", color=0xffd700)
    medals = ["🥇","🥈","🥉"] + ["🔹"]*7

    beschreibung = ""
    for i, (uid, xp) in enumerate(alle_xp):
        try:
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User#{uid[:4]}"
        except: name = f"User#{uid[:4]}"
        level = get_level(xp)
        beschreibung += f"{medals[i]} **{name}** — Level {level} ({xp} XP)\n"

    embed.description = beschreibung or "Noch keine XP vergeben."
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="xp-geben", description="[OWNER] Einem Mitglied XP geben")
@owner_only()
async def xp_geben(interaction: discord.Interaction, mitglied: discord.Member, menge: int):
    daten = lade_daten()
    uid = str(mitglied.id)
    daten["xp"].setdefault(uid, 0)
    daten["xp"][uid] += menge
    daten["levels"][uid] = get_level(daten["xp"][uid])
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ {mitglied.mention} hat **+{menge} XP** bekommen!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  GIVEAWAY SYSTEM
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="giveaway", description="Ein Giveaway starten")
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, preis: str, dauer_minuten: int, gewinner: int = 1):
    ende = datetime.datetime.utcnow() + datetime.timedelta(minutes=dauer_minuten)

    embed = discord.Embed(
        title="🎉 GIVEAWAY!",
        description=f"**Preis:** {preis}\n\nReagiere mit 🎉 um teilzunehmen!\n\n**Gewinner:** {gewinner}\n**Endet:** <t:{int(ende.timestamp())}:R>",
        color=0xff69b4
    )
    embed.set_footer(text=f"Startet von {interaction.user.display_name}")

    await interaction.response.send_message("✅ Giveaway gestartet!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")

    daten = lade_daten()
    daten["giveaways"][str(msg.id)] = {
        "preis": preis,
        "gewinner": gewinner,
        "ende": ende.isoformat(),
        "kanal_id": str(interaction.channel_id),
        "aktiv": True
    }
    speichere_daten(daten)

@bot.tree.command(name="giveaway-beenden", description="Giveaway manuell beenden")
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_beenden(interaction: discord.Interaction, nachrichten_id: str):
    await interaction.response.defer(ephemeral=True)
    await beende_giveaway(nachrichten_id, interaction.guild)
    await interaction.followup.send("✅ Giveaway beendet!", ephemeral=True)

async def beende_giveaway(msg_id: str, guild: discord.Guild):
    daten = lade_daten()
    gw = daten["giveaways"].get(msg_id)
    if not gw or not gw["aktiv"]: return

    try:
        kanal = guild.get_channel(int(gw["kanal_id"]))
        msg = await kanal.fetch_message(int(msg_id))
        reaktion = discord.utils.get(msg.reactions, emoji="🎉")
        teilnehmer = [u async for u in reaktion.users() if not u.bot] if reaktion else []

        if not teilnehmer:
            await kanal.send("❌ Keine Teilnehmer — Giveaway ohne Gewinner beendet.")
        else:
            anzahl = min(gw["gewinner"], len(teilnehmer))
            gewinner_liste = random.sample(teilnehmer, anzahl)
            mentions = " ".join(w.mention for w in gewinner_liste)
            embed = discord.Embed(title="🎊 GIVEAWAY BEENDET!", description=f"**Preis:** {gw['preis']}\n\n🏆 **Gewinner:** {mentions}", color=0x00ff88)
            await kanal.send(embed=embed)
            for gewinner_user in gewinner_liste:
                await schalte_achievement_frei(str(gewinner_user.id), "giveaway_win", kanal)

        daten["giveaways"][msg_id]["aktiv"] = False
        speichere_daten(daten)
    except Exception as e:
        print(f"Giveaway Fehler: {e}")

@tasks.loop(minutes=1)
async def check_giveaways():
    daten = lade_daten()
    now = datetime.datetime.utcnow()
    for msg_id, gw in list(daten["giveaways"].items()):
        if not gw["aktiv"]: continue
        ende = datetime.datetime.fromisoformat(gw["ende"])
        if now >= ende:
            for guild in bot.guilds:
                ch = guild.get_channel(int(gw["kanal_id"]))
                if ch:
                    await beende_giveaway(msg_id, guild)
                    break

@tasks.loop(minutes=1)
async def check_erinnerungen():
    """Prüft jede Minute ob eine Erinnerung fällig ist. Wiederholende Erinnerungen
    (z.B. jährliche Geburtstage) werden danach automatisch auf den nächsten Termin
    verschoben statt gelöscht."""
    daten = lade_daten()
    now = datetime.datetime.utcnow()
    geaendert = False

    for erinnerung in list(daten.get("erinnerungen", [])):
        faellig = datetime.datetime.fromisoformat(erinnerung["datum"])
        if now < faellig:
            continue

        for guild in bot.guilds:
            kanal = guild.get_channel(int(erinnerung["kanal_id"]))
            if kanal:
                embed = discord.Embed(
                    title="⏰ Erinnerung!",
                    description=erinnerung["text"],
                    color=0xffb400,
                    timestamp=now
                )
                embed.set_footer(text=f"Erstellt von {erinnerung.get('erstellt_von', 'Owner')}")
                try:
                    await kanal.send(embed=embed)
                except Exception as e:
                    print(f"[Erinnerung] Konnte nicht senden: {e}")
                break

        if erinnerung.get("wiederholend"):
            # Jährlich wiederholen (z.B. für Geburtstage) — ein Jahr addieren.
            # Schutz gegen 29. Februar in Nicht-Schaltjahren (ValueError sonst).
            try:
                naechstes_jahr = faellig.replace(year=faellig.year + 1)
            except ValueError:
                naechstes_jahr = faellig.replace(year=faellig.year + 1, day=28)
            erinnerung["datum"] = naechstes_jahr.isoformat()
        else:
            daten["erinnerungen"].remove(erinnerung)
        geaendert = True

    if geaendert:
        speichere_daten(daten)

@tasks.loop(minutes=5)
async def check_tiktok_live():
    """Prüft alle 5 Minuten ob überwachte TikTok-Creator live sind.
    Bewusst kein kürzeres Intervall — TikTokLive ist ein inoffizielles,
    reverse-engineertes Paket; zu häufige Anfragen können zu IP-Sperren führen.
    Postet nur EINMAL pro Live-Start eine Ankündigung (kein Spam bei jedem Check)."""
    if not TIKTOK_VERFUEGBAR:
        return

    daten = lade_daten()
    ueberwacht = daten.get("tiktok_ueberwachte_creator", {})
    if not ueberwacht:
        return

    geaendert = False
    for username, info in list(ueberwacht.items()):
        try:
            client = TikTokLiveClient(unique_id=f"@{username}")
            ist_live = await client.is_live()
        except Exception as e:
            print(f"[TikTok] Konnte Live-Status für @{username} nicht prüfen: {e}")
            continue

        war_live = info.get("zuletzt_live", False)

        if ist_live and not war_live:
            # Creator ist neu live gegangen — Ankündigung posten
            kanal_id = info.get("kanal_id")
            for guild in bot.guilds:
                kanal = guild.get_channel(int(kanal_id)) if kanal_id else None
                if kanal:
                    embed = discord.Embed(
                        title="🔴 LIVE auf TikTok!",
                        description=f"**@{username}** ist jetzt live auf TikTok!\nhttps://www.tiktok.com/@{username}/live",
                        color=0xff0050,
                        timestamp=datetime.datetime.utcnow()
                    )
                    embed.set_footer(text="TikTok Live-Benachrichtigung")
                    try:
                        await kanal.send(embed=embed)
                    except Exception as e:
                        print(f"[TikTok] Konnte Ankündigung nicht senden: {e}")
                    break

        info["zuletzt_live"] = ist_live
        geaendert = True

    if geaendert:
        speichere_daten(daten)

# ═══════════════════════════════════════════════════════════════
#  DASHBOARD-LOGIN — Verifizierungs-Codes per DM an den Owner
#  api.py legt Anfragen in login_requests.json ab, bot.py verschickt
#  die DM (nur der Discord-Client kann das, api.py ist kein Bot-Client)
# ═══════════════════════════════════════════════════════════════
LOGIN_QUEUE_FILE = "login_requests.json"

def lade_login_queue():
    return _robust_json_lesen(LOGIN_QUEUE_FILE, {"requests": []})

def speichere_login_queue(q):
    _atomar_json_schreiben(LOGIN_QUEUE_FILE, q)

@tasks.loop(seconds=5)
async def verarbeite_login_queue():
    """Prüft alle 5s ob api.py einen neuen Verifizierungs-Code per DM verschicken will."""
    q = lade_login_queue()
    offen = [r for r in q["requests"] if r.get("status") == "pending_dm"]
    if not offen:
        return
    for r in offen:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            embed = discord.Embed(
                title="🔑 Dashboard-Login-Anfrage",
                description=(
                    f"Jemand versucht sich mit dem Bot-Token im NEXUS-Dashboard anzumelden.\n\n"
                    f"**Verifizierungs-Code:** `{r['code']}`\n\n"
                    f"Gib diesen Code an die Person weiter, **nur wenn du den Zugriff erlauben willst**.\n"
                    f"Der Code läuft in 5 Minuten ab."
                ),
                color=0xffb400,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text=f"Anfrage-ID: {r['id'][:8]}")
            await owner.send(embed=embed)
            r["status"] = "sent"
        except Exception as e:
            print(f"[Login-Queue] DM-Fehler: {e}")
            r["status"] = "dm_failed"
    speichere_login_queue(q)

@tasks.loop(seconds=30)
async def verarbeite_announce_queue():
    """Verschickt Ankündigungen, die über das Dashboard (api.py) in die Queue gelegt wurden."""
    queue = {}
    if os.path.exists("announce_queue.json"):
        with open("announce_queue.json", "r", encoding="utf-8") as f:
            queue = json.load(f)
    offen = [m for m in queue.get("messages", []) if not m.get("gesendet")]
    if not offen:
        return

    farben = {"info": 0x00f5ff, "warn": 0xff6600, "success": 0x00ff88, "error": 0xff3333}
    icons  = {"info": "📢", "warn": "⚠️", "success": "✅", "error": "🚨"}

    for m in offen:
        embed = discord.Embed(
            title=f"{icons.get(m.get('typ','info'), '📢')} Bot-Ankündigung",
            description=m.get("nachricht", ""),
            color=farben.get(m.get("typ","info"), 0x00f5ff),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text="NEXUS Bot System")
        for guild in bot.guilds:
            ch = guild.system_channel
            if ch:
                try: await ch.send(embed=embed)
                except: pass
        m["gesendet"] = True

    with open("announce_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

@tasks.loop(seconds=15)
async def verarbeite_tikfinity_queue():
    """Liest TikFinity-Webhook-Events (Geschenke, Follows, Kommentare während eines
    TikTok LIVE-Streams) aus der Queue, die api.py befüllt, und postet sie in den
    konfigurierten Discord-Kanal. 15s-Intervall, da Live-Events zeitnah wirken sollen."""
    queue = _robust_json_lesen("tikfinity_queue.json", {"events": []})
    offen = [e for e in queue.get("events", []) if not e.get("verarbeitet")]
    if not offen:
        return

    daten = lade_daten()
    kanal_id = daten.get("tikfinity_kanal")
    if not kanal_id:
        return  # Noch kein Kanal eingerichtet — Events bleiben in der Queue, gehen nicht verloren

    kanal = None
    for guild in bot.guilds:
        kanal = guild.get_channel(int(kanal_id))
        if kanal:
            break

    if not kanal:
        return  # Kanal (noch) nicht erreichbar, beim nächsten Durchlauf erneut versuchen

    icons = {"gift": "🎁", "follow": "➕", "like": "❤️", "comment": "💬", "share": "🔁"}

    for event in offen:
        typ = event.get("event_typ", "unbekannt").lower()
        icon = icons.get(typ, "📺")
        beschreibung = f"**{event.get('spender', 'Jemand')}**"
        if event.get("geschenk"):
            beschreibung += f" hat **{event['geschenk']}** x{event.get('menge', 1)} geschickt!"
        elif event.get("kommentar"):
            beschreibung += f": {event['kommentar'][:300]}"
        else:
            beschreibung += f" — Event: {typ}"

        embed = discord.Embed(description=f"{icon} {beschreibung}", color=0xff0050, timestamp=datetime.datetime.utcnow())
        embed.set_author(name="🔴 TikTok LIVE")
        try:
            await kanal.send(embed=embed)
        except Exception as e:
            print(f"[TikFinity] Konnte Event nicht posten: {e}")
        event["verarbeitet"] = True

    _atomar_json_schreiben("tikfinity_queue.json", queue)

# ═══════════════════════════════════════════════════════════════
#  UMFRAGE SYSTEM
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="umfrage", description="Eine Umfrage erstellen")
async def umfrage(interaction: discord.Interaction, frage: str, option1: str, option2: str, option3: str = None, option4: str = None):
    optionen = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]

    embed = discord.Embed(title=f"📊 {frage}", color=0x5865f2)
    beschreibung = ""
    for i, opt in enumerate(optionen):
        beschreibung += f"{emojis[i]} {opt}\n"
    embed.description = beschreibung
    embed.set_footer(text=f"Umfrage von {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    for i in range(len(optionen)):
        await msg.add_reaction(emojis[i])

@bot.tree.command(name="schnell-umfrage", description="Schnelle Ja/Nein Umfrage")
async def schnell_umfrage(interaction: discord.Interaction, frage: str):
    embed = discord.Embed(title=f"❓ {frage}", color=0x5865f2)
    embed.set_footer(text=f"von {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

# ═══════════════════════════════════════════════════════════════
#  KI BEFEHLE
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="ki-chat", description="Mit der NEXUS KI chatten")
async def ki_chat(interaction: discord.Interaction, nachricht: str):
    daten = lade_daten()
    if daten.get("maintenance") and not ist_owner(interaction.user.id):
        await interaction.response.send_message("🔧 Wartungsmodus.", ephemeral=True); return
    await interaction.response.defer()
    brain = lade_brain()
    uid = str(interaction.user.id)
    persoenliche_notiz = brain.get("user_memory", {}).get(uid, "")
    wissen = knowledge_als_kontext()
    system = f"{brain['personality']}\nServer: {interaction.guild.name if interaction.guild else 'DM'}\nAntworte auf Deutsch."
    if persoenliche_notiz:
        system += f"\nDas merkst du dir über diesen Nutzer: {persoenliche_notiz}"
    if wissen:
        system += f"\n\nWissensdatenbank (nutze dies für Fakten, falls relevant):\n{wissen}"
    antwort = await frage_gemini(system, nachricht, brain["conversation_history"])
    await lerne(nachricht, antwort, uid=uid, channel=interaction.channel)
    embed = discord.Embed(description=antwort[:4096], color=0xbf5fff)
    embed.set_author(name="🧠 NEXUS KI (Groq Llama 3.1)", icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=f"Gespräch #{brain['stats']['total_conversations']}")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="ki-merke", description="Der KI etwas über dich merken lassen (für persönlichere Antworten)")
async def ki_merke(interaction: discord.Interaction, notiz: str):
    brain = lade_brain()
    brain.setdefault("user_memory", {})
    uid = str(interaction.user.id)
    brain["user_memory"][uid] = notiz[:300]
    speichere_brain(brain)
    await interaction.response.send_message(f"✅ Gemerkt! Die KI weiß jetzt: *{notiz[:300]}*", ephemeral=True)

@bot.tree.command(name="ki-vergiss", description="Die gemerkten Infos über dich löschen")
async def ki_vergiss(interaction: discord.Interaction):
    brain = lade_brain()
    uid = str(interaction.user.id)
    if uid in brain.get("user_memory", {}):
        del brain["user_memory"][uid]
        speichere_brain(brain)
        await interaction.response.send_message("✅ Gelöscht — die KI merkt sich nichts mehr über dich.", ephemeral=True)
    else:
        await interaction.response.send_message("Es war nichts gespeichert.", ephemeral=True)

@bot.tree.command(name="ki-frage", description="KI eine Frage stellen (kurze Antwort)")
async def ki_frage(interaction: discord.Interaction, frage: str):
    await interaction.response.defer()
    antwort = await frage_gemini("Antworte kurz und präzise auf Deutsch (max 2 Sätze).", frage)
    await interaction.followup.send(f"🤖 **{frage}**\n\n{antwort[:1000]}")

@bot.tree.command(name="ki-idee", description="Lass die KI eine Idee generieren")
async def ki_idee(interaction: discord.Interaction, thema: str):
    await interaction.response.defer()
    antwort = await frage_gemini(
        "Du bist kreativ und hilfreich. Generiere eine einzigartige Idee auf Deutsch. Sei konkret und begeistert.",
        f"Generiere eine kreative Idee zum Thema: {thema}"
    )
    embed = discord.Embed(title=f"💡 Idee: {thema}", description=antwort[:2000], color=0xffb400)
    await interaction.followup.send(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  SERVER SETUP BEFEHLE
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="setup-willkommen", description="[OWNER] Willkommens-Kanal setzen")
@owner_only()
async def setup_willkommen(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten["welcome_channel"] = str(kanal.id)
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Willkommens-Kanal: {kanal.mention}", ephemeral=True)

@bot.tree.command(name="setup-level-kanal", description="[OWNER] Level-Up Kanal setzen")
@owner_only()
async def setup_level_kanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten["level_channel"] = str(kanal.id)
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Level-Up Kanal: {kanal.mention}", ephemeral=True)

@bot.tree.command(name="setup-log-kanal", description="[OWNER] Mod-Log-Kanal setzen (Joins, Bans, Warns, etc.)")
@owner_only()
async def setup_log_kanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten["log_channel"] = str(kanal.id)
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Log-Kanal gesetzt: {kanal.mention}", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  ANTI-RAID / ANTI-NUKE — Slash-Commands
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="antiraid-an", description="[OWNER] Anti-Raid-Schutz aktivieren (Mass-Join-Erkennung)")
@owner_only()
@discord.app_commands.describe(join_schwelle="Wie viele Joins gelten als Raid-Verdacht?", zeitfenster_sekunden="Innerhalb welcher Zeitspanne?")
async def antiraid_an(interaction: discord.Interaction, join_schwelle: int = 5, zeitfenster_sekunden: int = 10):
    daten = lade_daten()
    daten["antiraid_aktiv"] = True
    daten["antiraid_join_schwelle"] = max(2, join_schwelle)
    daten["antiraid_join_zeitfenster"] = max(5, zeitfenster_sekunden)
    speichere_daten(daten)
    await interaction.response.send_message(
        f"✅ Anti-Raid aktiv: **{daten['antiraid_join_schwelle']} Joins** innerhalb von **{daten['antiraid_join_zeitfenster']}s** lösen automatischen Lockdown aus.\n"
        f"Tipp: `/setup-quarantaene-rolle` einrichten, damit verdächtige neue Mitglieder isoliert werden.",
        ephemeral=True
    )

@bot.tree.command(name="antiraid-aus", description="[OWNER] Anti-Raid-Schutz deaktivieren")
@owner_only()
async def antiraid_aus(interaction: discord.Interaction):
    daten = lade_daten()
    daten["antiraid_aktiv"] = False
    speichere_daten(daten)
    await interaction.response.send_message("✅ Anti-Raid deaktiviert.", ephemeral=True)

@bot.tree.command(name="antiraid-lockdown-aufheben", description="[OWNER] Manuell ausgelösten Lockdown wieder aufheben")
@owner_only()
async def antiraid_lockdown_aufheben(interaction: discord.Interaction):
    daten = lade_daten()
    daten["antiraid_lockdown_aktiv"] = False
    speichere_daten(daten)
    try:
        await interaction.guild.edit(verification_level=discord.VerificationLevel.medium)
    except Exception as e:
        print(f"[Anti-Raid] Konnte Verifizierungslevel nicht zurücksetzen: {e}")
    await interaction.response.send_message("✅ Lockdown aufgehoben. Verifizierungslevel auf Mittel zurückgesetzt.", ephemeral=True)

@bot.tree.command(name="setup-quarantaene-rolle", description="[OWNER] Rolle für verdächtige neue Mitglieder bei aktivem Raid-Schutz")
@owner_only()
async def setup_quarantaene_rolle(interaction: discord.Interaction, rolle: discord.Role):
    daten = lade_daten()
    daten["quarantaene_rolle"] = rolle.name
    speichere_daten(daten)
    await interaction.response.send_message(
        f"✅ Quarantäne-Rolle: {rolle.mention}\n"
        f"⚠️ Stelle sicher, dass diese Rolle in den Kanal-Berechtigungen eingeschränkt ist (z.B. kein Schreibrecht in normalen Kanälen)!",
        ephemeral=True
    )

@bot.tree.command(name="antinuke-an", description="[OWNER] Anti-Nuke-Schutz aktivieren (Schutz vor Massen-Löschung)")
@owner_only()
@discord.app_commands.describe(max_aktionen="Wie viele destruktive Aktionen lösen die Reaktion aus?", zeitfenster_sekunden="Innerhalb welcher Zeitspanne?")
async def antinuke_an(interaction: discord.Interaction, max_aktionen: int = 3, zeitfenster_sekunden: int = 30):
    daten = lade_daten()
    daten["antinuke_aktiv"] = True
    daten["antinuke_max_aktionen"] = max(1, max_aktionen)
    daten["antinuke_zeitfenster"] = max(5, zeitfenster_sekunden)
    speichere_daten(daten)
    await interaction.response.send_message(
        f"✅ Anti-Nuke aktiv: **{daten['antinuke_max_aktionen']} destruktive Aktionen** (Kanal/Rolle löschen, Bannen) "
        f"innerhalb von **{daten['antinuke_zeitfenster']}s** entziehen automatisch alle Rollen des Verursachers.\n\n"
        f"⚠️ **Wichtig:** Der Bot braucht die Berechtigung **'View Audit Log'**, sonst kann er nicht erkennen, wer die Aktion ausgeführt hat!",
        ephemeral=True
    )

@bot.tree.command(name="antinuke-aus", description="[OWNER] Anti-Nuke-Schutz deaktivieren")
@owner_only()
async def antinuke_aus(interaction: discord.Interaction):
    daten = lade_daten()
    daten["antinuke_aktiv"] = False
    speichere_daten(daten)
    await interaction.response.send_message("✅ Anti-Nuke deaktiviert.", ephemeral=True)

@bot.tree.command(name="security-status", description="[OWNER] Übersicht über alle aktiven Sicherheitsfunktionen")
@owner_only()
async def security_status(interaction: discord.Interaction):
    daten = lade_daten()
    embed = discord.Embed(title="🛡️ Security-Status", color=0x00f5ff)
    embed.add_field(name="Anti-Raid", value="🟢 AN" if daten.get("antiraid_aktiv") else "🔴 AUS", inline=True)
    embed.add_field(name="Lockdown", value="🚨 AKTIV" if daten.get("antiraid_lockdown_aktiv") else "✅ Normal", inline=True)
    embed.add_field(name="Anti-Nuke", value="🟢 AN" if daten.get("antinuke_aktiv") else "🔴 AUS", inline=True)
    embed.add_field(name="KI-Moderation", value="🟢 AN" if daten.get("ki_moderation_enabled") else "🔴 AUS", inline=True)
    embed.add_field(name="Quarantäne-Rolle", value=daten.get("quarantaene_rolle") or "❌ Nicht gesetzt", inline=True)
    embed.add_field(name="Log-Kanal", value=f"<#{daten['log_channel']}>" if daten.get("log_channel") else "❌ Nicht gesetzt", inline=True)

    bot_member = interaction.guild.me
    hat_audit_log_recht = bot_member.guild_permissions.view_audit_log
    embed.add_field(
        name="Audit-Log-Berechtigung",
        value="✅ Vorhanden" if hat_audit_log_recht else "❌ FEHLT — Anti-Nuke kann ohne diese Berechtigung nicht funktionieren!",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="log-event-umschalten", description="[OWNER] Einen Log-Event-Typ an/aus schalten")
@owner_only()
@discord.app_commands.choices(event_typ=[
    discord.app_commands.Choice(name="Beitritte (join)", value="join"),
    discord.app_commands.Choice(name="Verlassen (leave)", value="leave"),
    discord.app_commands.Choice(name="Bans", value="ban"),
    discord.app_commands.Choice(name="Kicks", value="kick"),
    discord.app_commands.Choice(name="Verwarnungen", value="warn"),
    discord.app_commands.Choice(name="Timeouts", value="timeout"),
])
async def log_event_umschalten(interaction: discord.Interaction, event_typ: str):
    daten = lade_daten()
    daten.setdefault("log_events", {})
    aktuell = daten["log_events"].get(event_typ, True)
    daten["log_events"][event_typ] = not aktuell
    speichere_daten(daten)
    status = "AN ✅" if not aktuell else "AUS ❌"
    await interaction.response.send_message(f"Log-Event **{event_typ}** ist jetzt **{status}**", ephemeral=True)

@bot.tree.command(name="custom-command-hinzufügen", description="[OWNER] Eigenen Text-Befehl hinzufügen (z.B. !regeln)")
@owner_only()
async def custom_command_hinzufuegen(interaction: discord.Interaction, trigger: str, antwort: str):
    trigger = trigger.strip().lower()
    if not trigger.startswith(("!", "?", ".")):
        await interaction.response.send_message("❌ Trigger sollte mit `!`, `?` oder `.` beginnen, z.B. `!regeln`", ephemeral=True)
        return
    daten = lade_daten()
    daten.setdefault("custom_commands", {})
    daten["custom_commands"][trigger] = antwort
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Custom Command gespeichert: `{trigger}` → {antwort[:100]}", ephemeral=True)

@bot.tree.command(name="custom-command-entfernen", description="[OWNER] Eigenen Text-Befehl entfernen")
@owner_only()
async def custom_command_entfernen(interaction: discord.Interaction, trigger: str):
    trigger = trigger.strip().lower()
    daten = lade_daten()
    if trigger in daten.get("custom_commands", {}):
        del daten["custom_commands"][trigger]
        speichere_daten(daten)
        await interaction.response.send_message(f"✅ `{trigger}` entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ `{trigger}` existiert nicht.", ephemeral=True)

@bot.tree.command(name="custom-commands-liste", description="Alle eigenen Text-Befehle anzeigen")
async def custom_commands_liste(interaction: discord.Interaction):
    daten = lade_daten()
    custom = daten.get("custom_commands", {})
    if not custom:
        await interaction.response.send_message("Keine Custom Commands definiert.", ephemeral=True)
        return
    embed = discord.Embed(title="📋 Custom Commands", color=0x00f5ff)
    embed.description = "\n".join([f"`{k}` → {v[:60]}" for k, v in custom.items()])
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  WISSENSDATENBANK — Slash-Commands
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="wissen-hinzufügen", description="[OWNER] Einen Fakt zur KI-Wissensdatenbank hinzufügen")
@owner_only()
async def wissen_hinzufuegen(interaction: discord.Interaction, schluessel: str, inhalt: str):
    k = lade_knowledge()
    k["entries"][schluessel.strip()] = inhalt.strip()
    speichere_knowledge(k)
    await interaction.response.send_message(f"✅ Wissen gespeichert: **{schluessel}** → {inhalt[:150]}", ephemeral=True)

@bot.tree.command(name="wissen-entfernen", description="[OWNER] Einen Fakt aus der Wissensdatenbank entfernen")
@owner_only()
async def wissen_entfernen(interaction: discord.Interaction, schluessel: str):
    k = lade_knowledge()
    schluessel = schluessel.strip()
    if schluessel in k["entries"]:
        del k["entries"][schluessel]
        speichere_knowledge(k)
        await interaction.response.send_message(f"✅ **{schluessel}** entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{schluessel}** existiert nicht.", ephemeral=True)

@bot.tree.command(name="wissen-liste", description="Alle Einträge der KI-Wissensdatenbank anzeigen")
async def wissen_liste(interaction: discord.Interaction):
    k = lade_knowledge()
    if not k["entries"]:
        await interaction.response.send_message("Die Wissensdatenbank ist leer.", ephemeral=True)
        return
    embed = discord.Embed(title="🗄️ KI-Wissensdatenbank", color=0x00f5ff)
    embed.description = "\n".join([f"**{s}**: {v[:80]}" for s, v in k["entries"].items()])[:4000]
    embed.set_footer(text=f"{len(k['entries'])} Einträge — die KI nutzt das in jedem Gespräch")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  GITHUB SELF-COMMIT — Slash-Commands
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="github-datei-erstellen", description="[OWNER] Eine Datei direkt im GitHub-Repo anlegen/überschreiben")
@owner_only()
async def github_datei_erstellen_cmd(interaction: discord.Interaction, pfad: str, inhalt: str, commit_nachricht: str = "Update via NEXUS Bot"):
    await interaction.response.defer(ephemeral=True)
    ergebnis = await github_datei_erstellen(pfad, inhalt, commit_nachricht)
    if ergebnis["ok"]:
        art = "erstellt" if ergebnis.get("neu_erstellt") else "aktualisiert"
        embed = discord.Embed(title=f"✅ Datei {art}", color=0x00ff88)
        embed.add_field(name="Pfad", value=f"`{pfad}`")
        embed.add_field(name="Branch", value=GITHUB_BRANCH)
        if ergebnis.get("url"):
            embed.add_field(name="GitHub-Link", value=ergebnis["url"], inline=False)
        embed.set_footer(text="⚠️ Railway deployed jetzt automatisch neu, falls relevant.")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Fehler: {ergebnis['error']}", ephemeral=True)

@bot.tree.command(name="github-funktion-generieren", description="[OWNER] KI schreibt Code UND committed ihn direkt als neue Datei in GitHub")
@owner_only()
async def github_funktion_generieren(interaction: discord.Interaction, dateiname: str, beschreibung: str):
    await interaction.response.defer(ephemeral=True)

    code = await ki_code_hilfe(f"Schreibe vollständigen, eigenständigen Python-Code für: {beschreibung}", "", "schreib")
    if code.startswith("❌"):
        await interaction.followup.send(code, ephemeral=True)
        return

    commit_msg = f"NEXUS: {dateiname} generiert — {beschreibung[:80]}"
    ergebnis = await github_datei_erstellen(dateiname, code, commit_msg)

    if ergebnis["ok"]:
        embed = discord.Embed(title="⚡ KI-Code generiert & committed", color=0xbf5fff)
        embed.add_field(name="Datei", value=f"`{dateiname}`", inline=False)
        embed.add_field(name="Beschreibung", value=beschreibung, inline=False)
        embed.add_field(name="Code-Vorschau", value=f"```python\n{code[:800]}\n```", inline=False)
        if ergebnis.get("url"):
            embed.add_field(name="GitHub-Link", value=ergebnis["url"], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Code wurde generiert, aber Commit fehlgeschlagen: {ergebnis['error']}", ephemeral=True)

@bot.tree.command(name="auto-rolle-hinzufügen", description="[OWNER] Rolle automatisch bei Beitritt vergeben")
@owner_only()
async def auto_rolle_hinzufuegen(interaction: discord.Interaction, rolle: discord.Role):
    daten = lade_daten()
    if rolle.name not in daten["auto_roles"]:
        daten["auto_roles"].append(rolle.name)
        speichere_daten(daten)
        await interaction.response.send_message(f"✅ Auto-Rolle hinzugefügt: {rolle.mention}", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Rolle ist bereits als Auto-Rolle gesetzt.", ephemeral=True)

@bot.tree.command(name="rolle-geben", description="Einem Mitglied eine Rolle geben")
@discord.app_commands.checks.has_permissions(manage_roles=True)
async def rolle_geben(interaction: discord.Interaction, mitglied: discord.Member, rolle: discord.Role):
    await mitglied.add_roles(rolle)
    await interaction.response.send_message(f"✅ {mitglied.mention} hat die Rolle {rolle.mention} bekommen.")

@bot.tree.command(name="rolle-entfernen", description="Einem Mitglied eine Rolle entfernen")
@discord.app_commands.checks.has_permissions(manage_roles=True)
async def rolle_entfernen(interaction: discord.Interaction, mitglied: discord.Member, rolle: discord.Role):
    await mitglied.remove_roles(rolle)
    await interaction.response.send_message(f"✅ Rolle {rolle.mention} von {mitglied.mention} entfernt.")

# ═══════════════════════════════════════════════════════════════
#  MODERATION
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="warn", description="Mitglied verwarnen")
@discord.app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Kein Grund"):
    daten = lade_daten()
    uid = str(mitglied.id)
    daten["warnings"].setdefault(uid, [])
    daten["warnings"][uid].append({"grund": grund, "datum": str(datetime.datetime.utcnow()), "mod": str(interaction.user)})
    speichere_daten(daten)
    embed = discord.Embed(title="⚠️ Verwarnung", color=0xff9900)
    embed.add_field(name="Mitglied", value=mitglied.mention)
    embed.add_field(name="Grund", value=grund)
    embed.add_field(name="Gesamt", value=str(len(daten["warnings"][uid])))
    await interaction.response.send_message(embed=embed)

    log_embed = discord.Embed(title="⚠️ Verwarnung erteilt", color=0xff9900, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{mitglied.mention} ({mitglied.id})")
    log_embed.add_field(name="Mod", value=interaction.user.mention)
    log_embed.add_field(name="Grund", value=grund, inline=False)
    await log_event(interaction.guild, "warn", log_embed)

@bot.tree.command(name="warnings", description="Verwarnungen eines Mitglieds anzeigen")
async def warnings(interaction: discord.Interaction, mitglied: discord.Member):
    daten = lade_daten()
    warns = daten["warnings"].get(str(mitglied.id), [])
    embed = discord.Embed(title=f"⚠️ Verwarnungen — {mitglied.display_name}", color=0xff9900)
    embed.description = "\n".join([f"**#{i+1}** {w['grund']} ({w['datum'][:10]})" for i, w in enumerate(warns)]) or "Keine."
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Mitglied kicken")
@discord.app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Kein Grund"):
    await mitglied.kick(reason=grund)
    await interaction.response.send_message(embed=discord.Embed(title="👢 Gekickt", description=f"{mitglied.mention} — {grund}", color=0xff3333))

    log_embed = discord.Embed(title="👢 Mitglied gekickt", color=0xff3333, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{mitglied} ({mitglied.id})")
    log_embed.add_field(name="Mod", value=interaction.user.mention)
    log_embed.add_field(name="Grund", value=grund, inline=False)
    await log_event(interaction.guild, "kick", log_embed)

@bot.tree.command(name="ban", description="Mitglied bannen")
@discord.app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Kein Grund"):
    await mitglied.ban(reason=grund)
    await interaction.response.send_message(embed=discord.Embed(title="🔨 Gebannt", description=f"{mitglied.mention} — {grund}", color=0xff0000))

    log_embed = discord.Embed(title="🔨 Mitglied gebannt", color=0xff0000, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{mitglied} ({mitglied.id})")
    log_embed.add_field(name="Mod", value=interaction.user.mention)
    log_embed.add_field(name="Grund", value=grund, inline=False)
    await log_event(interaction.guild, "ban", log_embed)

@bot.tree.command(name="timeout", description="Mitglied timeouten")
@discord.app_commands.checks.has_permissions(moderate_members=True)
async def timeout_cmd(interaction: discord.Interaction, mitglied: discord.Member, minuten: int = 10, grund: str = "Kein Grund"):
    await mitglied.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=minuten), reason=grund)
    await interaction.response.send_message(embed=discord.Embed(title="⏱️ Timeout", description=f"{mitglied.mention} für {minuten}min — {grund}", color=0xff9900))

    log_embed = discord.Embed(title="⏱️ Timeout vergeben", color=0xff9900, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Mitglied", value=f"{mitglied} ({mitglied.id})")
    log_embed.add_field(name="Mod", value=interaction.user.mention)
    log_embed.add_field(name="Dauer", value=f"{minuten} Minuten")
    log_embed.add_field(name="Grund", value=grund, inline=False)
    await log_event(interaction.guild, "timeout", log_embed)

async def ki_ticket_antworten(kanal: discord.TextChannel, nachricht: str, uid: str, history: list = None) -> bool:
    """Zentrale Funktion für KI-Antworten in Tickets — nutzt Wissensdatenbank,
    Ticket-Kategorie und Supporter-Bewerbungsnotizen als Kontext, damit die KI
    fundierter antworten kann. Gibt True zurück, falls eine Eskalation ans Team nötig war."""
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(kanal.id), {})
    kategorie = eintrag.get("kategorie", "Allgemein")
    bewerbung_notizen = eintrag.get("bewerbung_notizen", "")
    wissen = knowledge_als_kontext()

    system = (
        "Du bist ein hilfreicher Support-Assistent für einen Discord-Server. "
        f"Dieses Ticket hat die Kategorie '{kategorie}'. "
        "Antworte kurz (max 3 Sätze) und hilfreich auf Deutsch. "
        "Falls du das Problem nicht lösen kannst oder unsicher bist, sag das ehrlich "
        "und schreibe am Ende GENAU das Wort 'ESKALIEREN' in Großbuchstaben, damit ein Mensch hinzugerufen wird."
    )
    if wissen:
        system += f"\n\nWissensdatenbank (nutze dies für Fakten, falls relevant):\n{wissen}"
    if bewerbung_notizen:
        system += (
            f"\n\nBisherige Supporter-Notizen zu diesem Fall (z.B. bei Bewerbungs-Tickets):\n{bewerbung_notizen}\n"
            "Nutze diese Notizen NUR als internen Kontext — wiederhole sie nicht wörtlich gegenüber dem Bewerber."
        )

    antwort = await frage_gemini(system, nachricht, history)
    if antwort.startswith("❌") or antwort.startswith("🕐"):
        return False

    muss_eskalieren = "ESKALIEREN" in antwort
    antwort_ohne_marker = antwort.replace("ESKALIEREN", "").strip()
    ki_embed = discord.Embed(description=antwort_ohne_marker[:2000], color=0xbf5fff)
    ki_embed.set_author(name="🧠 NEXUS Support-KI")
    await kanal.send(embed=ki_embed)
    await lerne(nachricht, antwort, uid=uid, channel=kanal)

    if muss_eskalieren:
        await team_pingen(kanal, "Die KI ist sich unsicher und bittet um menschliche Hilfe.")
    return muss_eskalieren

async def ki_ticket_kategorisieren(beschreibung: str) -> str:
    """Lässt die KI ein Ticket grob kategorisieren. Fällt auf 'Allgemein' zurück,
    falls die KI nicht erreichbar ist oder eine unerwartete Antwort liefert."""
    erlaubte_kategorien = ["Bug", "Frage", "Beschwerde", "Vorschlag", "Allgemein"]
    if not GROQ_KEY:
        return "Allgemein"
    system = (
        "Du kategorisierst ein Support-Ticket. Antworte NUR mit genau einem Wort aus dieser Liste: "
        f"{', '.join(erlaubte_kategorien)}. Kein Satz, keine Erklärung, nur das eine Wort."
    )
    antwort = await frage_gemini(system, beschreibung[:500])
    antwort_clean = antwort.strip().split()[0].rstrip(".,!") if antwort and not antwort.startswith("❌") else "Allgemein"
    for kategorie in erlaubte_kategorien:
        if kategorie.lower() == antwort_clean.lower():
            return kategorie
    return "Allgemein"

async def ki_ticket_zusammenfassen(verlauf: list[str]) -> str:
    """Fasst den Nachrichtenverlauf eines Tickets in 2-3 Sätzen zusammen."""
    if not GROQ_KEY or not verlauf:
        return "Keine Zusammenfassung verfügbar (KI nicht erreichbar oder Ticket war leer)."
    system = "Fasse dieses Support-Ticket in 2-3 Sätzen auf Deutsch zusammen: Worum ging es, wurde es gelöst?"
    text = "\n".join(verlauf[-40:])  # Letzte 40 Nachrichten reichen für eine gute Zusammenfassung
    zusammenfassung = await frage_gemini(system, text[:3000])
    return zusammenfassung if not zusammenfassung.startswith("❌") else "Zusammenfassung konnte nicht erstellt werden."

class TicketControlView(discord.ui.View):
    """Persistente Button-Leiste in jedem Ticket-Kanal: Schließen, Team rufen, KI an/aus.
    timeout=None + feste custom_id, damit die Buttons auch nach einem Bot-Neustart
    noch reagieren (siehe bot.add_view() in on_ready)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Schließen", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def schliessen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ticket_schliessen_ablauf(interaction)

    @discord.ui.button(label="Team rufen", emoji="🆘", style=discord.ButtonStyle.secondary, custom_id="ticket_team_btn")
    async def team_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        daten = lade_daten()
        if str(interaction.channel_id) not in daten.get("aktive_tickets", {}):
            await interaction.response.send_message("❌ Das ist kein aktiver Ticket-Kanal.", ephemeral=True)
            return
        await team_pingen(interaction.channel, f"{interaction.user.mention} hat über den Button um menschliche Unterstützung gebeten.")
        await interaction.response.send_message("✅ Team wurde benachrichtigt.", ephemeral=True)

    @discord.ui.button(label="KI an/aus", emoji="🧠", style=discord.ButtonStyle.secondary, custom_id="ticket_ki_toggle_btn")
    async def ki_toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        daten = lade_daten()
        eintrag = daten.get("aktive_tickets", {}).get(str(interaction.channel_id))
        if not eintrag:
            await interaction.response.send_message("❌ Das ist kein aktiver Ticket-Kanal.", ephemeral=True)
            return
        eintrag["ki_aktiv"] = not eintrag.get("ki_aktiv", True)
        speichere_daten(daten)
        await interaction.response.send_message(f"🧠 KI-Antworten sind jetzt **{'AN' if eintrag['ki_aktiv'] else 'AUS'}**.", ephemeral=True)

async def erstelle_ticket_kanal(guild: discord.Guild, ersteller: discord.Member, kategorie_label: str, beschreibung: str = "") -> discord.TextChannel | None:
    """Zentrale Funktion zum Anlegen eines Ticket-Kanals — wird sowohl vom /ticket
    Befehl als auch vom Dropdown-Panel genutzt, damit beide Wege identisch funktionieren."""
    existing = discord.utils.get(guild.text_channels, name=f"ticket-{ersteller.name.lower()}")
    if existing:
        return None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ersteller: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    daten = lade_daten()
    team_rolle_name = daten.get("ticket_team_rolle")
    if team_rolle_name:
        team_rolle = discord.utils.get(guild.roles, name=team_rolle_name)
        if team_rolle:
            overwrites[team_rolle] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    kanal = await guild.create_text_channel(f"ticket-{ersteller.name.lower()}", overwrites=overwrites)

    daten["tickets"] = daten.get("tickets", 0) + 1
    daten.setdefault("aktive_tickets", {})
    daten["aktive_tickets"][str(kanal.id)] = {
        "ersteller_id": str(ersteller.id),
        "kategorie": kategorie_label,
        "erstellt_am": str(datetime.datetime.utcnow()),
        "ki_aktiv": daten.get("ticket_ki_aktiv", True),
        "team_gepingt": False,
    }
    speichere_daten(daten)

    embed = discord.Embed(
        title=f"🎫 Ticket — {kategorie_label}",
        description=f"{ersteller.mention} — Beschreibe dein Anliegen, die KI antwortet automatisch wenn möglich.",
        color=0x00f5ff
    )
    if beschreibung:
        embed.add_field(name="Beschreibung", value=beschreibung[:500], inline=False)
    await kanal.send(embed=embed, view=TicketControlView())

    if beschreibung and daten.get("ticket_ki_aktiv", True) and GROQ_KEY:
        await ki_ticket_antworten(kanal, beschreibung, str(ersteller.id))

    return kanal

async def team_pingen(kanal: discord.TextChannel, grund: str):
    """Pingt die konfigurierte Team-Rolle in einem Ticket-Kanal — z.B. wenn die KI
    nicht weiterweiß. Merkt sich pro Ticket, ob schon gepingt wurde, um Spam zu vermeiden."""
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(kanal.id))
    if eintrag and eintrag.get("team_gepingt"):
        return  # Schon einmal gepingt, nicht erneut spammen
    team_rolle_name = daten.get("ticket_team_rolle")
    rolle_mention = ""
    if team_rolle_name:
        rolle = discord.utils.get(kanal.guild.roles, name=team_rolle_name)
        if rolle:
            rolle_mention = rolle.mention
    embed = discord.Embed(
        title="🆘 Team-Unterstützung angefordert",
        description=f"{grund}\n\n{rolle_mention or '⚠️ Keine Team-Rolle konfiguriert — nutze `/setup-ticket-team` um eine festzulegen.'}",
        color=0xff6600
    )
    await kanal.send(content=rolle_mention or None, embed=embed)
    if eintrag:
        eintrag["team_gepingt"] = True
        speichere_daten(daten)

class TicketKategorieSelect(discord.ui.Select):
    """Dropdown-Menü mit den vom Owner konfigurierten Ticket-Kategorien (wie bei GalaxyBot)."""
    def __init__(self):
        daten = lade_daten()
        kategorien = daten.get("ticket_kategorien", [])
        options = [
            discord.SelectOption(label=k["label"][:100], value=k["value"], description=k.get("beschreibung", "")[:100])
            for k in kategorien
        ]
        super().__init__(placeholder="Wähle eine Kategorie für dein Ticket...", options=options, custom_id="ticket_kategorie_select")

    async def callback(self, interaction: discord.Interaction):
        kategorie_label = next((o.label for o in self.options if o.value == self.values[0]), self.values[0])
        kanal = await erstelle_ticket_kanal(interaction.guild, interaction.user, kategorie_label)
        if kanal is None:
            await interaction.response.send_message("❌ Du hast bereits ein offenes Ticket.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Ticket erstellt: {kanal.mention}", ephemeral=True)

class TicketPanelView(discord.ui.View):
    """Permanente View für das Ticket-Panel — timeout=None, damit das Dropdown
    auch nach einem Bot-Neustart noch funktioniert (über custom_id-Wiederherstellung)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketKategorieSelect())

@bot.tree.command(name="ticket-panel-erstellen", description="[OWNER] Ticket-Panel mit Dropdown-Auswahl in diesen Kanal posten")
@owner_only()
async def ticket_panel_erstellen(interaction: discord.Interaction, titel: str = "🎫 Support-Ticket erstellen", beschreibung: str = "Wähle unten eine Kategorie aus, um ein Ticket zu öffnen."):
    embed = discord.Embed(title=titel, description=beschreibung, color=0x00f5ff)
    daten = lade_daten()
    kategorien_text = "\n".join([f"{k['label']} — {k.get('beschreibung','')}" for k in daten.get("ticket_kategorien", [])])
    if kategorien_text:
        embed.add_field(name="Kategorien", value=kategorien_text[:1024], inline=False)
    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("✅ Ticket-Panel gepostet.", ephemeral=True)

@bot.tree.command(name="ticket-kategorie-hinzufügen", description="[OWNER] Eine Kategorie zum Ticket-Dropdown hinzufügen")
@owner_only()
async def ticket_kategorie_hinzufuegen(interaction: discord.Interaction, label: str, beschreibung: str = ""):
    daten = lade_daten()
    daten.setdefault("ticket_kategorien", [])
    if len(daten["ticket_kategorien"]) >= 25:
        await interaction.response.send_message("❌ Discord erlaubt maximal 25 Optionen pro Dropdown — lösche erst eine Kategorie.", ephemeral=True)
        return
    wert = label.lower().replace(" ", "_")[:90]
    daten["ticket_kategorien"].append({"label": label[:100], "value": wert, "beschreibung": beschreibung[:100]})
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Kategorie **{label}** hinzugefügt. Erstelle das Panel neu mit `/ticket-panel-erstellen`, damit die Änderung sichtbar wird.", ephemeral=True)

@bot.tree.command(name="ticket-kategorie-entfernen", description="[OWNER] Eine Kategorie aus dem Ticket-Dropdown entfernen")
@owner_only()
async def ticket_kategorie_entfernen(interaction: discord.Interaction, label: str):
    daten = lade_daten()
    vorher = len(daten.get("ticket_kategorien", []))
    daten["ticket_kategorien"] = [k for k in daten.get("ticket_kategorien", []) if k["label"] != label]
    if len(daten["ticket_kategorien"]) == vorher:
        await interaction.response.send_message("❌ Keine Kategorie mit diesem exakten Namen gefunden.", ephemeral=True)
        return
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Kategorie entfernt. Panel mit `/ticket-panel-erstellen` neu posten.", ephemeral=True)

@bot.tree.command(name="setup-ticket-team", description="[OWNER] Team-Rolle festlegen, die bei Bedarf in Tickets gepingt wird")
@owner_only()
async def setup_ticket_team(interaction: discord.Interaction, rolle: discord.Role):
    daten = lade_daten()
    daten["ticket_team_rolle"] = rolle.name
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Team-Rolle für Tickets: {rolle.mention}", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  TIKTOK LIVE-BENACHRICHTIGUNGEN + LINK-AUTOMOD
#  Nutzt das inoffizielle TikTokLive-Paket — kein offizielles TikTok-API
#  verfügbar dafür. Kann jederzeit von TikTok-seitigen Änderungen betroffen sein.
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="tiktok-überwachen", description="[OWNER] TikTok-Creator überwachen — postet Ankündigung wenn live")
@owner_only()
@discord.app_commands.describe(username="TikTok-Username OHNE @, z.B. 'charlidamelio'", kanal="Wo soll die Live-Ankündigung gepostet werden?")
async def tiktok_ueberwachen(interaction: discord.Interaction, username: str, kanal: discord.TextChannel):
    if not TIKTOK_VERFUEGBAR:
        await interaction.response.send_message("❌ TikTokLive-Paket ist nicht installiert (requirements.txt prüfen).", ephemeral=True)
        return
    username = username.strip().lstrip("@")
    daten = lade_daten()
    daten.setdefault("tiktok_ueberwachte_creator", {})
    daten["tiktok_ueberwachte_creator"][username] = {"kanal_id": str(kanal.id), "zuletzt_live": False}
    speichere_daten(daten)
    await interaction.response.send_message(
        f"✅ Überwache jetzt **@{username}** — Ankündigung geht an {kanal.mention} sobald live.\n"
        f"⚠️ Hinweis: nutzt ein inoffizielles TikTok-Paket, Prüfung läuft alle 5 Minuten (nicht in Echtzeit).",
        ephemeral=True
    )

@bot.tree.command(name="tiktok-nicht-mehr-überwachen", description="[OWNER] Einen TikTok-Creator nicht mehr überwachen")
@owner_only()
async def tiktok_nicht_mehr_ueberwachen(interaction: discord.Interaction, username: str):
    username = username.strip().lstrip("@")
    daten = lade_daten()
    if username in daten.get("tiktok_ueberwachte_creator", {}):
        del daten["tiktok_ueberwachte_creator"][username]
        speichere_daten(daten)
        await interaction.response.send_message(f"✅ @{username} wird nicht mehr überwacht.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ @{username} wird aktuell nicht überwacht.", ephemeral=True)

@bot.tree.command(name="tiktok-liste", description="Alle überwachten TikTok-Creator anzeigen")
async def tiktok_liste(interaction: discord.Interaction):
    daten = lade_daten()
    ueberwacht = daten.get("tiktok_ueberwachte_creator", {})
    if not ueberwacht:
        await interaction.response.send_message("Keine TikTok-Creator werden überwacht.", ephemeral=True)
        return
    embed = discord.Embed(title="📱 Überwachte TikTok-Creator", color=0xff0050)
    for username, info in ueberwacht.items():
        status = "🔴 Live" if info.get("zuletzt_live") else "⚫ Offline"
        embed.add_field(name=f"@{username}", value=status, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="tiktok-automod-an", description="[OWNER] TikTok-Link-Filter aktivieren (löscht Links außerhalb erlaubter Kanäle)")
@owner_only()
async def tiktok_automod_an(interaction: discord.Interaction):
    daten = lade_daten()
    daten["tiktok_link_automod_aktiv"] = True
    speichere_daten(daten)
    await interaction.response.send_message(
        "✅ TikTok-Link-Automod aktiv. Links werden außerhalb erlaubter Kanäle gelöscht.\n"
        "Nutze `/tiktok-kanal-erlauben` um Ausnahme-Kanäle festzulegen.",
        ephemeral=True
    )

@bot.tree.command(name="tiktok-automod-aus", description="[OWNER] TikTok-Link-Filter deaktivieren")
@owner_only()
async def tiktok_automod_aus(interaction: discord.Interaction):
    daten = lade_daten()
    daten["tiktok_link_automod_aktiv"] = False
    speichere_daten(daten)
    await interaction.response.send_message("✅ TikTok-Link-Automod deaktiviert.", ephemeral=True)

@bot.tree.command(name="tiktok-kanal-erlauben", description="[OWNER] In diesem Kanal sollen TikTok-Links erlaubt bleiben")
@owner_only()
async def tiktok_kanal_erlauben(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten.setdefault("tiktok_link_erlaubte_kanaele", [])
    if kanal.name not in daten["tiktok_link_erlaubte_kanaele"]:
        daten["tiktok_link_erlaubte_kanaele"].append(kanal.name)
        speichere_daten(daten)
    await interaction.response.send_message(f"✅ TikTok-Links sind in {kanal.mention} weiterhin erlaubt.", ephemeral=True)

@bot.tree.command(name="setup-tiktok-account", description="[OWNER] Den offiziellen TikTok-Account des Servers/Bots hinterlegen")
@owner_only()
@discord.app_commands.describe(username="TikTok-Username OHNE @ (den Account musst du selbst bei TikTok erstellt haben)", beschreibung="Kurzer Text, z.B. 'Folgt uns für Server-Clips!'")
async def setup_tiktok_account(interaction: discord.Interaction, username: str, beschreibung: str = ""):
    username = username.strip().lstrip("@")
    daten = lade_daten()
    daten["tiktok_eigener_account"] = username
    daten["tiktok_eigener_account_beschreibung"] = beschreibung[:200]
    speichere_daten(daten)
    await interaction.response.send_message(
        f"✅ Offizieller TikTok-Account hinterlegt: **@{username}**\n\n"
        f"Nutze `/tiktok-profil`, um ihn allen anzuzeigen. Falls der Bot auch automatisch melden soll wenn dieser "
        f"Account live geht, nutze zusätzlich `/tiktok-überwachen username:{username} kanal:#dein-kanal`.\n\n"
        f"⚠️ Hinweis: TikTok bietet keine offizielle API zum automatischen Video-Posten für normale Accounts — "
        f"das bleibt also weiterhin manuell.",
        ephemeral=True
    )

@bot.tree.command(name="setup-tikfinity-webhook", description="[OWNER] TikFinity-Webhook-URL für diesen Bot anzeigen + Zielkanal festlegen")
@owner_only()
async def setup_tikfinity_webhook(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten["tikfinity_kanal"] = str(kanal.id)
    speichere_daten(daten)

    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

    fehlende_schritte = []
    if not webhook_secret:
        fehlende_schritte.append("`WEBHOOK_SECRET` Variable in Railway setzen (beliebiger geheimer Text)")
    if not railway_url:
        fehlende_schritte.append(
            "Railway → dein Service → **Settings** → **Networking** → **Generate Domain** klicken "
            "(Railway vergibt erst dann eine `*.up.railway.app`-URL — ohne das bleibt `RAILWAY_PUBLIC_DOMAIN` leer)"
        )

    if fehlende_schritte:
        liste = "\n".join(f"{i+1}. {s}" for i, s in enumerate(fehlende_schritte))
        await interaction.response.send_message(
            f"⚠️ Zielkanal ({kanal.mention}) gespeichert, aber es fehlt noch:\n\n{liste}\n\n"
            "Danach diesen Befehl einfach nochmal ausführen, um die fertige Webhook-URL zu sehen.",
            ephemeral=True
        )
        return

    webhook_url = f"https://{railway_url}/webhook/tikfinity/{webhook_secret}"

    embed = discord.Embed(
        title="🔗 TikFinity-Webhook eingerichtet",
        description=(
            f"Live-Events (Geschenke, Follows, Kommentare) gehen jetzt an {kanal.mention}.\n\n"
            "**So richtest du TikFinity ein:**\n"
            "1. Öffne TikFinity → Einstellungen → Webhooks\n"
            "2. Füge eine neue Webhook-URL hinzu:\n"
            f"```{webhook_url}```\n"
            "3. Wähle die Events aus, die du weiterleiten willst (Geschenke, Follows, etc.)\n"
            "4. Speichern — fertig!"
        ),
        color=0xff0050
    )
    embed.set_footer(text="⚠️ Die Webhook-URL enthält dein Geheimnis — nicht öffentlich teilen!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="tiktok-profil", description="Zeigt den offiziellen TikTok-Account des Servers")
async def tiktok_profil(interaction: discord.Interaction):
    daten = lade_daten()
    username = daten.get("tiktok_eigener_account")
    if not username:
        await interaction.response.send_message("❌ Noch kein TikTok-Account hinterlegt. Ein Owner kann das mit `/setup-tiktok-account` einrichten.", ephemeral=True)
        return

    beschreibung = daten.get("tiktok_eigener_account_beschreibung", "")
    embed = discord.Embed(
        title=f"📱 @{username} auf TikTok",
        description=beschreibung or "Folgt uns auf TikTok!",
        url=f"https://www.tiktok.com/@{username}",
        color=0xff0050
    )
    embed.add_field(name="🔗 Profil-Link", value=f"https://www.tiktok.com/@{username}", inline=False)

    # Falls der Account zufällig auch überwacht wird, zeigen wir den Live-Status mit an
    ueberwacht_info = daten.get("tiktok_ueberwachte_creator", {}).get(username)
    if ueberwacht_info is not None:
        status = "🔴 Gerade LIVE!" if ueberwacht_info.get("zuletzt_live") else "⚫ Aktuell offline"
        embed.add_field(name="Status", value=status, inline=False)

    embed.set_footer(text="NEXUS Community Bot")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="team-rufen", description="Das Support-Team in dieses Ticket rufen")
async def team_rufen(interaction: discord.Interaction):
    daten = lade_daten()
    if str(interaction.channel_id) not in daten.get("aktive_tickets", {}):
        await interaction.response.send_message("❌ Das ist kein aktiver Ticket-Kanal.", ephemeral=True)
        return
    await team_pingen(interaction.channel, f"{interaction.user.mention} hat um menschliche Unterstützung gebeten.")
    await interaction.response.send_message("✅ Team wurde benachrichtigt.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  VOICE SUPPORT — TTS (Bot redet) + begrenztes STT (Bot transkribiert)
#  WICHTIG: Das hier ist befehlsbasiert, KEIN fließendes Gespräch.
#  "Bot, sag etwas" und "Bot, zeichne 10s auf und transkribiere" — keine
#  Echtzeit-Konversation, das ist mit Discord/kostenlosen APIs nicht robust machbar.
# ═══════════════════════════════════════════════════════════════
VOICE_VERFUEGBARE_STIMMEN = {
    "de-weiblich": "de-DE-KatjaNeural",
    "de-männlich": "de-DE-ConradNeural",
    "en-weiblich": "en-US-AriaNeural",
    "en-männlich": "en-US-GuyNeural",
}

async def voice_text_zu_sprache(text: str, stimme: str) -> tuple[str, str]:
    """Wandelt Text in eine MP3-Datei um (temporäre Datei) und gibt (pfad, fehler) zurück.
    pfad ist None bei Fehlern, fehler enthält dann die Fehlermeldung im Klartext,
    damit sie dem Owner in Discord angezeigt werden kann statt nur in den Server-Logs zu verschwinden."""
    if not VOICE_TTS_VERFUEGBAR:
        return None, "edge_tts ist nicht installiert (requirements.txt prüfen)."
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        communicate = edge_tts.Communicate(text[:500], stimme)
        await communicate.save(tmp.name)
        return tmp.name, None
    except Exception as e:
        print(f"[Voice-TTS] Fehler: {e}")
        return None, str(e)

@bot.tree.command(name="voice-join", description="Bot tritt deinem aktuellen Voice-Channel bei")
async def voice_join(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Du musst selbst in einem Voice-Channel sein.", ephemeral=True)
        return
    kanal = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(kanal)
    else:
        try:
            await kanal.connect()
        except discord.ClientException as e:
            await interaction.response.send_message(f"❌ Konnte nicht verbinden: {e}", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ Voice-Verbindung fehlgeschlagen (fehlt PyNaCl/FFmpeg auf dem Server?): {e}", ephemeral=True)
            return
    await interaction.response.send_message(f"✅ Beigetreten: **{kanal.name}**")

@bot.tree.command(name="voice-leave", description="Bot verlässt den Voice-Channel")
async def voice_leave(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("❌ Bot ist in keinem Voice-Channel.", ephemeral=True)
        return
    await interaction.guild.voice_client.disconnect(force=True)
    await interaction.response.send_message("👋 Voice-Channel verlassen.")

@bot.tree.command(name="voice-sag", description="Bot sagt einen Text im Voice-Channel (Text-to-Speech)")
@discord.app_commands.describe(text="Was soll der Bot sagen? (max 500 Zeichen)")
async def voice_sag(interaction: discord.Interaction, text: str):
    if not VOICE_TTS_VERFUEGBAR:
        await interaction.response.send_message("❌ Voice-TTS ist auf diesem Server nicht installiert (edge-tts fehlt in requirements.txt).", ephemeral=True)
        return
    vc = interaction.guild.voice_client
    if not vc:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bot ist in keinem Voice-Channel und du auch nicht. Nutze `/voice-join` zuerst.", ephemeral=True)
            return
        try:
            vc = await interaction.user.voice.channel.connect()
        except Exception as e:
            await interaction.response.send_message(f"❌ Konnte nicht verbinden: {e}", ephemeral=True)
            return

    if vc.is_playing():
        await interaction.response.send_message("⏳ Bot spricht gerade schon etwas anderes — kurz warten.", ephemeral=True)
        return

    await interaction.response.defer()

    # FFmpeg-Verfügbarkeit VOR der Wiedergabe prüfen, statt erst beim Abspielen zu scheitern
    ffmpeg_pfad = shutil.which("ffmpeg")
    if not ffmpeg_pfad:
        await interaction.followup.send(
            "❌ **FFmpeg ist auf dem Server nicht installiert/auffindbar.**\n"
            "Railway → Variables → `RAILPACK_PACKAGES=ffmpeg` setzen und neu deployen.\n"
            "Falls die Variable schon gesetzt ist: prüfe in den Build-Logs, ob beim Installieren ein Fehler auftrat."
        )
        return

    daten = lade_daten()
    stimme = daten.get("voice_stimme", "de-DE-KatjaNeural")
    mp3_pfad, tts_fehler = await voice_text_zu_sprache(text, stimme)
    if not mp3_pfad:
        await interaction.followup.send(f"❌ Sprachsynthese fehlgeschlagen: `{tts_fehler}`")
        return

    if not os.path.exists(mp3_pfad) or os.path.getsize(mp3_pfad) == 0:
        await interaction.followup.send("❌ Sprachdatei wurde nicht korrekt erzeugt (0 Bytes oder fehlt) — edge-tts-Problem, nicht FFmpeg.")
        if os.path.exists(mp3_pfad):
            os.remove(mp3_pfad)
        return

    wiedergabe_fehler = {}
    def nach_wiedergabe(fehler):
        # WICHTIG: Dieser Callback läuft in Discord.py's eigenem Thread, NICHT im Event-Loop.
        # Der Fehler wird hier nur zwischengespeichert, nicht direkt nach Discord gesendet
        # (das wäre in diesem Thread nicht sicher möglich).
        if fehler:
            wiedergabe_fehler["e"] = str(fehler)
            print(f"[Voice-TTS] Wiedergabe-Fehler (after-Callback): {fehler}")
        if os.path.exists(mp3_pfad):
            try:
                os.remove(mp3_pfad)
            except Exception as cleanup_err:
                print(f"[Voice-TTS] Konnte temp. MP3 nicht löschen: {cleanup_err}")

    try:
        quelle = discord.FFmpegPCMAudio(mp3_pfad, executable=ffmpeg_pfad)
        vc.play(quelle, after=nach_wiedergabe)
        await interaction.followup.send(f"🔊 Sage: *{text[:200]}*")
    except Exception as e:
        await interaction.followup.send(f"❌ Wiedergabe-Start fehlgeschlagen: `{e}`")
        if os.path.exists(mp3_pfad):
            os.remove(mp3_pfad)

@bot.tree.command(name="voice-stimme-wählen", description="[OWNER] Welche Stimme der Bot für TTS nutzt")
@owner_only()
@discord.app_commands.choices(stimme=[
    discord.app_commands.Choice(name="Deutsch — weiblich", value="de-weiblich"),
    discord.app_commands.Choice(name="Deutsch — männlich", value="de-männlich"),
    discord.app_commands.Choice(name="Englisch — weiblich", value="en-weiblich"),
    discord.app_commands.Choice(name="Englisch — männlich", value="en-männlich"),
])
async def voice_stimme_waehlen(interaction: discord.Interaction, stimme: str):
    daten = lade_daten()
    daten["voice_stimme"] = VOICE_VERFUEGBARE_STIMMEN.get(stimme, "de-DE-KatjaNeural")
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Stimme gesetzt: **{stimme}**", ephemeral=True)


@bot.tree.command(name="voice-zuhören", description="Spracherkennung im Voice-Channel (aktuell nicht verfügbar)")
async def voice_zuhoeren(interaction: discord.Interaction):
    await interaction.response.send_message(
        "❌ **Sprach-Aufnahme (STT) ist mit der aktuellen Bot-Bibliothek nicht verfügbar.**\n\n"
        "discord.py (das dieser Bot nutzt) unterstützt das Empfangen von Voice-Audio offiziell nicht — "
        "Discord behandelt das als inoffizielles Feature, das jederzeit ohne Vorwarnung kaputt gehen kann. "
        "Es gäbe experimentelle Drittanbieter-Erweiterungen dafür, aber die sind nicht stabil genug für einen "
        "zuverlässigen Produktions-Bot.\n\n"
        "✅ Was funktioniert: `/voice-sag` — der Bot kann im Voice-Channel sprechen (Text-to-Speech).",
        ephemeral=True
    )

@bot.tree.command(name="ticket", description="Support-Ticket erstellen — die KI kategorisiert es automatisch")
@discord.app_commands.describe(beschreibung="Kurz beschreiben, worum es geht (hilft der KI beim Einordnen)")
async def ticket(interaction: discord.Interaction, beschreibung: str = ""):
    await interaction.response.defer(ephemeral=True)
    kategorie = await ki_ticket_kategorisieren(beschreibung) if beschreibung else "Allgemein"
    kanal = await erstelle_ticket_kanal(interaction.guild, interaction.user, kategorie, beschreibung)
    if kanal is None:
        await interaction.followup.send("❌ Du hast bereits ein offenes Ticket.", ephemeral=True)
        return
    await interaction.followup.send(f"✅ {kanal.mention} (Kategorie: **{kategorie}**)", ephemeral=True)

@bot.tree.command(name="ticket-ki-umschalten", description="Automatische KI-Antworten in DIESEM Ticket an/aus schalten")
async def ticket_ki_umschalten(interaction: discord.Interaction):
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(interaction.channel_id))
    if not eintrag:
        await interaction.response.send_message("❌ Das ist kein aktiver Ticket-Kanal.", ephemeral=True)
        return
    eintrag["ki_aktiv"] = not eintrag.get("ki_aktiv", True)
    speichere_daten(daten)
    await interaction.response.send_message(f"🧠 KI-Antworten in diesem Ticket sind jetzt **{'AN' if eintrag['ki_aktiv'] else 'AUS'}**.")

@bot.tree.command(name="bewerbung-notiz", description="[Supporter] Notiz zu einer Bewerbung in diesem Ticket hinterlegen")
@discord.app_commands.describe(notiz="z.B. Eindruck vom Bewerber, Entscheidung, offene Fragen")
async def bewerbung_notiz(interaction: discord.Interaction, notiz: str):
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(interaction.channel_id))
    if not eintrag:
        await interaction.response.send_message("❌ Das ist kein aktiver Ticket-Kanal.", ephemeral=True)
        return

    eintrag.setdefault("bewerbung_notizen", "")
    zeitstempel = datetime.datetime.utcnow().strftime("%d.%m. %H:%M")
    neuer_eintrag = f"[{zeitstempel} — {interaction.user.display_name}]: {notiz}"
    eintrag["bewerbung_notizen"] = (eintrag["bewerbung_notizen"] + "\n" + neuer_eintrag).strip()[-1500:]
    speichere_daten(daten)

    embed = discord.Embed(title="📝 Bewerbungs-Notiz hinzugefügt", description=notiz[:1000], color=0xffb400)
    embed.set_footer(text=f"Von {interaction.user.display_name} — sichtbar für die KI in diesem Ticket")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="bewerbung-notizen-anzeigen", description="[Supporter] Alle Bewerbungs-Notizen in diesem Ticket anzeigen")
async def bewerbung_notizen_anzeigen(interaction: discord.Interaction):
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(interaction.channel_id))
    if not eintrag or not eintrag.get("bewerbung_notizen"):
        await interaction.response.send_message("Keine Bewerbungs-Notizen in diesem Ticket vorhanden.", ephemeral=True)
        return
    embed = discord.Embed(title="📝 Bewerbungs-Notizen", description=eintrag["bewerbung_notizen"][:4000], color=0xffb400)
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def ticket_schliessen_ablauf(interaction: discord.Interaction):
    """Zentrale Schließ-Logik — wird vom 🔒-Button UND vom /close-Befehl genutzt,
    damit beide Wege exakt gleich funktionieren (keine doppelte Logik zu pflegen)."""
    daten = lade_daten()
    eintrag = daten.get("aktive_tickets", {}).get(str(interaction.channel_id))
    if not eintrag and not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Kein Ticket-Kanal.", ephemeral=True); return

    await interaction.response.send_message("🔒 Erstelle Zusammenfassung und schließe in einigen Sekunden...")

    # Nachrichtenverlauf für die Zusammenfassung sammeln
    verlauf = []
    try:
        async for msg in interaction.channel.history(limit=100, oldest_first=True):
            if msg.content:
                verlauf.append(f"{msg.author.display_name}: {msg.content}")
    except Exception as e:
        print(f"[Ticket-Close] Konnte Verlauf nicht laden: {e}")

    zusammenfassung = await ki_ticket_zusammenfassen(verlauf)
    kategorie = eintrag.get("kategorie", "Unbekannt") if eintrag else "Unbekannt"

    log_embed = discord.Embed(title=f"📋 Ticket geschlossen — {kategorie}", color=0x00ff88, timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Kanal", value=interaction.channel.name, inline=True)
    log_embed.add_field(name="Geschlossen von", value=interaction.user.mention, inline=True)
    log_embed.add_field(name="KI-Zusammenfassung", value=zusammenfassung[:1000], inline=False)

    # Bewerbungs-Notizen vom Supporter-Team mit ins Log aufnehmen, falls vorhanden
    bewerbung_notizen = eintrag.get("bewerbung_notizen") if eintrag else None
    if bewerbung_notizen:
        log_embed.add_field(name="📝 Supporter-Notizen (Bewerbung)", value=bewerbung_notizen[:1000], inline=False)

    log_kanal_id = daten.get("ticket_log_channel")
    if log_kanal_id:
        log_kanal = interaction.guild.get_channel(int(log_kanal_id))
        if log_kanal:
            try:
                await log_kanal.send(embed=log_embed)
            except Exception as e:
                print(f"[Ticket-Close] Konnte Log nicht senden: {e}")

    # Ticket aus den aktiven Tickets entfernen
    daten.get("aktive_tickets", {}).pop(str(interaction.channel_id), None)
    speichere_daten(daten)

    await asyncio.sleep(5)
    try:
        await interaction.channel.delete()
    except Exception as e:
        print(f"[Ticket-Close] Konnte Kanal nicht löschen: {e}")

@bot.tree.command(name="close", description="Ticket schließen — KI erstellt vorher eine Zusammenfassung")
async def close(interaction: discord.Interaction):
    await ticket_schliessen_ablauf(interaction)

@bot.tree.command(name="setup-ticket-log", description="[OWNER] Kanal für Ticket-Zusammenfassungen festlegen")
@owner_only()
async def setup_ticket_log(interaction: discord.Interaction, kanal: discord.TextChannel):
    daten = lade_daten()
    daten["ticket_log_channel"] = str(kanal.id)
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ Ticket-Zusammenfassungen gehen jetzt an {kanal.mention}", ephemeral=True)

@bot.tree.command(name="ticket-ki-global-umschalten", description="[OWNER] KI-Auto-Antworten für ALLE neuen Tickets an/aus")
@owner_only()
async def ticket_ki_global_umschalten(interaction: discord.Interaction):
    daten = lade_daten()
    daten["ticket_ki_aktiv"] = not daten.get("ticket_ki_aktiv", True)
    speichere_daten(daten)
    await interaction.response.send_message(f"🧠 KI-Auto-Antworten für neue Tickets sind jetzt **{'AN' if daten['ticket_ki_aktiv'] else 'AUS'}**.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  OWNER CONTROLS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="wartung-an", description="[OWNER] Wartungsmodus AN")
@owner_only()
async def wartung_an(interaction: discord.Interaction, grund: str = "Wartungsarbeiten"):
    daten = lade_daten()
    daten["maintenance"] = True
    speichere_daten(daten)
    await bot.change_presence(status=discord.Status.dnd, activity=discord.Activity(type=discord.ActivityType.watching, name="🔧 Wartung"))
    embed = discord.Embed(title="🔧 WARTUNGSMODUS AN", description=f"**Grund:** {grund}", color=0xff6600)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wartung-aus", description="[OWNER] Wartungsmodus AUS")
@owner_only()
async def wartung_aus(interaction: discord.Interaction):
    daten = lade_daten()
    daten["maintenance"] = False
    speichere_daten(daten)
    await bot.change_presence(status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="die Community 👀"))
    embed = discord.Embed(title="✅ WARTUNGSMODUS AUS", description="Bot ist wieder online!", color=0x00ff88)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="bot-neustart", description="[OWNER] Bot neu starten")
@owner_only()
async def bot_neustart(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Neustart in 3s...")
    await asyncio.sleep(3)
    await bot.close()
    os._exit(0)

@bot.tree.command(name="bot-status", description="[OWNER] System-Status")
@owner_only()
async def bot_status(interaction: discord.Interaction):
    daten = lade_daten()
    brain = lade_brain()
    embed = discord.Embed(title="📊 NEXUS — System Status", color=0x00f5ff)
    embed.add_field(name="🔧 Wartung", value="AN" if daten.get("maintenance") else "AUS", inline=True)
    embed.add_field(name="🔁 Boots", value=str(daten.get("boot_count", 0)), inline=True)
    embed.add_field(name="📡 Latenz", value=f"{round(bot.latency*1000)}ms", inline=True)
    embed.add_field(name="🌐 Server", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="🧠 KI-Gespräche", value=str(brain["stats"]["total_conversations"]), inline=True)
    embed.add_field(name="🎉 Giveaways", value=str(len(daten["giveaways"])), inline=True)
    embed.add_field(name="🛡️ KI-Moderation", value="AN" if daten.get("ki_moderation_enabled") else "AUS", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ki-moderation-an", description="[OWNER] KI-Moderation aktivieren (löscht toxische Nachrichten automatisch)")
@owner_only()
async def ki_moderation_an(interaction: discord.Interaction):
    daten = lade_daten()
    daten["ki_moderation_enabled"] = True
    speichere_daten(daten)
    embed = discord.Embed(
        title="🛡️ KI-Moderation AKTIV",
        description="Nachrichten ab 15 Zeichen werden von der KI auf Beleidigungen/Hassrede/Drohungen geprüft und bei Verstoß automatisch gelöscht. Betroffene Nutzer erhalten eine DM mit Begründung.",
        color=0x00ff88
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ki-moderation-aus", description="[OWNER] KI-Moderation deaktivieren")
@owner_only()
async def ki_moderation_aus(interaction: discord.Interaction):
    daten = lade_daten()
    daten["ki_moderation_enabled"] = False
    speichere_daten(daten)
    await interaction.response.send_message("✅ KI-Moderation deaktiviert.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  FUN + UTILITY
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="münzwurf", description="Kopf oder Zahl?")
async def muenzwurf(interaction: discord.Interaction):
    ergebnis = random.choice(["🪙 **Kopf!**", "🪙 **Zahl!**"])
    await interaction.response.send_message(ergebnis)

@bot.tree.command(name="würfeln", description="Einen Würfel werfen")
async def wuerfeln(interaction: discord.Interaction, seiten: int = 6):
    ergebnis = random.randint(1, max(2, seiten))
    await interaction.response.send_message(f"🎲 Du hast eine **{ergebnis}** gewürfelt! (W{seiten})")

@bot.tree.command(name="8ball", description="Frag die magische 8-Ball KI")
async def achtball(interaction: discord.Interaction, frage: str):
    await interaction.response.defer()
    antwort = await frage_gemini(
        "Du bist eine mystische 8-Ball Weissagerin. Antworte auf Deutsch mit einer kurzen mystischen Antwort (max 1 Satz). Sei manchmal positiv, manchmal negativ, manchmal ausweichend.",
        f"Die Frage lautet: {frage}"
    )
    embed = discord.Embed(title="🎱 Magische 8-Ball", color=0x000000)
    embed.add_field(name="❓ Frage", value=frage)
    embed.add_field(name="🔮 Antwort", value=antwort[:200] if not antwort.startswith("❌") else random.choice(["Ja!", "Nein!", "Vielleicht...", "Die Sterne schweigen."]))
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="roast", description="Jemanden freundschaftlich aufziehen (nur Spaß, kein echter Hass)")
@discord.app_commands.describe(mitglied="Wer soll aufgezogen werden?")
async def roast(interaction: discord.Interaction, mitglied: discord.Member):
    await interaction.response.defer()

    system = (
        "Du schreibst einen freundschaftlichen, harmlosen Neck-Spruch auf Deutsch für einen Discord-Server. "
        "WICHTIGE REGELN: Maximal 2 Sätze. Niemals Aussagen zu Aussehen des Körpers, Herkunft, Religion, "
        "sexueller Orientierung, Geschlecht, Behinderung, Gewicht oder anderen persönlichen/diskriminierenden Merkmalen. "
        "Niemals echte Beleidigungen, Beschimpfungen oder verletzende Sprache. "
        "Der Ton ist wie unter guten Freunden auf einem Discord-Server: witzig-übertrieben, nie bösartig. "
        "Beispiel-Stil: 'Du brauchst länger zum Laden als mein Internet im Funkloch.' "
        "Wenn dir kein harmloser Witz einfällt, schreibe stattdessen ein liebevolles Compliment."
    )
    spruch = await frage_gemini(system, f"Schreibe einen freundlichen Neck-Spruch für jemanden mit dem Servernamen '{mitglied.display_name}'.")

    if spruch.startswith("❌") or spruch.startswith("🕐"):
        # Fallback falls die KI nicht erreichbar ist — vorgefertigte harmlose Sprüche
        spruch = random.choice([
            "Du bist wie ein Software-Update — alle wissen du bist wichtig, aber keiner will dich gerade jetzt.",
            "Du hast das Charisma von einem Ladebildschirm — alle warten gespannt, aber es tut sich nix.",
            "Deine Internetverbindung ist schneller als deine Comebacks.",
        ])

    embed = discord.Embed(
        title="🔥 Roast!",
        description=f"{mitglied.mention}\n\n*{spruch[:300]}*",
        color=0xff6600
    )
    embed.set_footer(text="Nur Spaß unter Freunden 😄 — kein Mobbing!")
    await interaction.followup.send(embed=embed)

class QuizView(discord.ui.View):
    """Interaktives Quiz mit 4 Antwort-Buttons. Mehrere Leute können gleichzeitig klicken,
    nur der erste richtige Klick pro Person zählt (via beantwortet-Set)."""
    def __init__(self, richtige_antwort_index: int, optionen: list[str], punkte: int = 50):
        super().__init__(timeout=30)
        self.richtige_antwort_index = richtige_antwort_index
        self.punkte = punkte
        self.beantwortet = set()  # User-IDs, die schon geklickt haben
        for i, opt in enumerate(optionen):
            self.add_item(self.QuizButton(opt, i, self))

    class QuizButton(discord.ui.Button):
        def __init__(self, label: str, index: int, parent_view: "QuizView"):
            super().__init__(label=label[:80], style=discord.ButtonStyle.secondary)
            self.index = index
            self.parent_view = parent_view

        async def callback(self, interaction: discord.Interaction):
            view = self.parent_view
            uid = str(interaction.user.id)
            if uid in view.beantwortet:
                await interaction.response.send_message("Du hast schon geantwortet!", ephemeral=True)
                return
            view.beantwortet.add(uid)

            daten = lade_daten()
            daten.setdefault("quiz_scores", {})
            daten["quiz_scores"].setdefault(uid, 0)

            if self.index == view.richtige_antwort_index:
                daten["quiz_scores"][uid] += view.punkte
                speichere_daten(daten)
                await interaction.response.send_message(f"✅ Richtig! +{view.punkte} Quiz-Punkte", ephemeral=True)
            else:
                speichere_daten(daten)
                await interaction.response.send_message("❌ Leider falsch!", ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

@bot.tree.command(name="quiz", description="Ein KI-generiertes Quiz starten")
@discord.app_commands.describe(thema="Themenbereich (optional, z.B. Geschichte, Gaming, Allgemeinwissen)")
async def quiz(interaction: discord.Interaction, thema: str = "Allgemeinwissen"):
    await interaction.response.defer()

    system = (
        "Du erstellst eine Multiple-Choice-Quizfrage auf Deutsch. "
        "Antworte AUSSCHLIESSLICH als JSON-Objekt ohne Markdown-Backticks, exakt in diesem Format: "
        '{"frage": "...", "optionen": ["A", "B", "C", "D"], "richtig": 0}\n'
        "richtig ist der Index (0-3) der korrekten Antwort in optionen. Die Frage muss eindeutig lösbar sein."
    )
    antwort = await frage_gemini(system, f"Erstelle eine Quizfrage zum Thema: {thema}")

    try:
        import re as _re
        match = _re.search(r'\{.*\}', antwort, _re.DOTALL)
        quiz_data = json.loads(match.group()) if match else None
    except Exception:
        quiz_data = None

    if not quiz_data or "frage" not in quiz_data or "optionen" not in quiz_data:
        await interaction.followup.send("❌ Konnte keine Quizfrage generieren — versuch's gleich nochmal.")
        return

    optionen = quiz_data["optionen"]
    richtig_index = quiz_data.get("richtig", 0)
    if not isinstance(optionen, list) or len(optionen) < 2 or not isinstance(richtig_index, int) or not (0 <= richtig_index < len(optionen)):
        await interaction.followup.send("❌ Die KI hat eine ungültige Quizfrage erzeugt — versuch's gleich nochmal.")
        return

    view = QuizView(richtig_index, optionen)
    embed = discord.Embed(title=f"🧠 Quiz: {thema}", description=quiz_data["frage"], color=0xbf5fff)
    embed.set_footer(text="30 Sekunden Zeit — klick auf eine Antwort!")
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="quiz-rangliste", description="Top 10 Quiz-Punkte anzeigen")
async def quiz_rangliste(interaction: discord.Interaction):
    daten = lade_daten()
    scores = sorted(daten.get("quiz_scores", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title="🏆 Quiz-Rangliste", color=0xbf5fff)
    medals = ["🥇","🥈","🥉"] + ["🔹"]*7
    embed.description = "\n".join([f"{medals[i]} <@{uid}> — {pts} Punkte" for i, (uid, pts) in enumerate(scores)]) or "Noch keine Quiz-Punkte."
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  ERINNERUNGEN — einmalig oder jährlich wiederkehrend (z.B. Geburtstage)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="erinnerung-erstellen", description="Eine Erinnerung erstellen (z.B. Geburtstag, Event)")
@discord.app_commands.describe(
    datum="Format: TT.MM.JJJJ oder TT.MM.JJJJ HH:MM",
    text="Was soll die Erinnerung sagen?",
    wiederholend="Jedes Jahr wiederholen? (z.B. für Geburtstage)"
)
async def erinnerung_erstellen(interaction: discord.Interaction, datum: str, text: str, wiederholend: bool = False):
    datum = datum.strip()
    geparst = None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            geparst = datetime.datetime.strptime(datum, fmt)
            break
        except ValueError:
            continue

    if not geparst:
        await interaction.response.send_message("❌ Datum-Format ungültig. Nutze `TT.MM.JJJJ` oder `TT.MM.JJJJ HH:MM`, z.B. `25.12.2026` oder `25.12.2026 18:00`.", ephemeral=True)
        return

    daten = lade_daten()
    daten.setdefault("erinnerungen", [])
    neue_erinnerung = {
        "id": secrets.token_hex(6),
        "datum": geparst.isoformat(),
        "text": text[:500],
        "kanal_id": str(interaction.channel_id),
        "wiederholend": wiederholend,
        "erstellt_von": str(interaction.user),
    }
    daten["erinnerungen"].append(neue_erinnerung)
    speichere_daten(daten)

    embed = discord.Embed(title="⏰ Erinnerung erstellt", color=0xffb400)
    embed.add_field(name="Datum", value=geparst.strftime("%d.%m.%Y %H:%M"))
    embed.add_field(name="Wiederholend", value="✅ Jährlich" if wiederholend else "❌ Einmalig")
    embed.add_field(name="Text", value=text[:500], inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="erinnerungen-liste", description="Alle anstehenden Erinnerungen in diesem Kanal anzeigen")
async def erinnerungen_liste(interaction: discord.Interaction):
    daten = lade_daten()
    eintraege = [e for e in daten.get("erinnerungen", []) if e["kanal_id"] == str(interaction.channel_id)]
    if not eintraege:
        await interaction.response.send_message("Keine anstehenden Erinnerungen in diesem Kanal.", ephemeral=True)
        return
    eintraege.sort(key=lambda e: e["datum"])
    embed = discord.Embed(title="⏰ Anstehende Erinnerungen", color=0xffb400)
    for e in eintraege[:15]:
        dt = datetime.datetime.fromisoformat(e["datum"])
        wiederholend_text = " 🔁" if e.get("wiederholend") else ""
        embed.add_field(name=f"{dt.strftime('%d.%m.%Y %H:%M')}{wiederholend_text} (ID: {e['id']})", value=e["text"][:200], inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="erinnerung-löschen", description="Eine Erinnerung per ID löschen")
async def erinnerung_loeschen(interaction: discord.Interaction, erinnerung_id: str):
    daten = lade_daten()
    vorher = len(daten.get("erinnerungen", []))
    daten["erinnerungen"] = [e for e in daten.get("erinnerungen", []) if e["id"] != erinnerung_id.strip()]
    if len(daten["erinnerungen"]) == vorher:
        await interaction.response.send_message("❌ Keine Erinnerung mit dieser ID gefunden.", ephemeral=True)
        return
    speichere_daten(daten)
    await interaction.response.send_message("✅ Erinnerung gelöscht.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  AUTOMATISIERUNG / TRIGGER — "wenn X passiert, mach Y"
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="trigger-erstellen", description="[OWNER] Automatisierungs-Regel erstellen (wenn X, dann Y)")
@owner_only()
@discord.app_commands.describe(
    bedingung_typ="Wann soll der Trigger feuern?",
    bedingung_wert="Bei 'mitglieder_anzahl': eine Zahl. Bei 'tageszeit': HH:MM (z.B. 09:00)",
    nachricht="Die Nachricht, die gepostet wird (in den System-Kanal des Servers)"
)
@discord.app_commands.choices(bedingung_typ=[
    discord.app_commands.Choice(name="Mitgliederzahl erreicht", value="mitglieder_anzahl"),
    discord.app_commands.Choice(name="Tageszeit (täglich, UTC)", value="tageszeit"),
])
async def trigger_erstellen(interaction: discord.Interaction, bedingung_typ: str, bedingung_wert: str, nachricht: str):
    if bedingung_typ == "mitglieder_anzahl":
        try:
            int(bedingung_wert)
        except ValueError:
            await interaction.response.send_message("❌ Bei 'mitglieder_anzahl' muss der Wert eine Zahl sein, z.B. `100`.", ephemeral=True)
            return
    elif bedingung_typ == "tageszeit":
        try:
            datetime.datetime.strptime(bedingung_wert.strip(), "%H:%M")
        except ValueError:
            await interaction.response.send_message("❌ Bei 'tageszeit' muss der Wert im Format HH:MM sein, z.B. `09:00` (UTC-Zeit, nicht deine Ortszeit!).", ephemeral=True)
            return

    daten = lade_daten()
    daten.setdefault("trigger", [])
    daten["trigger"].append({
        "id": secrets.token_hex(6),
        "bedingung_typ": bedingung_typ,
        "bedingung_wert": bedingung_wert.strip(),
        "aktion_typ": "nachricht",
        "aktion_wert": nachricht[:1000],
        "aktiv": True,
    })
    speichere_daten(daten)

    hinweis = " (Tipp: nutze {anzahl} in der Nachricht, um die aktuelle Mitgliederzahl einzufügen)" if bedingung_typ == "mitglieder_anzahl" else ""
    await interaction.response.send_message(f"✅ Trigger erstellt: **{bedingung_typ}** = `{bedingung_wert}` → Nachricht wird gepostet.{hinweis}", ephemeral=True)

@bot.tree.command(name="trigger-liste", description="Alle Automatisierungs-Regeln anzeigen")
async def trigger_liste(interaction: discord.Interaction):
    daten = lade_daten()
    trigger = daten.get("trigger", [])
    if not trigger:
        await interaction.response.send_message("Keine Automatisierungs-Regeln definiert.", ephemeral=True)
        return
    embed = discord.Embed(title="⚡ Automatisierungs-Regeln", color=0x00f5ff)
    for t in trigger:
        status = "✅ Aktiv" if t.get("aktiv", True) else "⏸️ Pausiert"
        embed.add_field(
            name=f"{t['bedingung_typ']} = {t['bedingung_wert']} (ID: {t['id']})",
            value=f"{status} — \"{t['aktion_wert'][:100]}\"",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="trigger-löschen", description="[OWNER] Eine Automatisierungs-Regel löschen")
@owner_only()
async def trigger_loeschen(interaction: discord.Interaction, trigger_id: str):
    daten = lade_daten()
    vorher = len(daten.get("trigger", []))
    daten["trigger"] = [t for t in daten.get("trigger", []) if t["id"] != trigger_id.strip()]
    if len(daten["trigger"]) == vorher:
        await interaction.response.send_message("❌ Kein Trigger mit dieser ID gefunden.", ephemeral=True)
        return
    speichere_daten(daten)
    await interaction.response.send_message("✅ Trigger gelöscht.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  REACTION ROLES — Reaktion klicken, Rolle bekommen
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="reaction-role-erstellen", description="[OWNER] Reaction-Role-Nachricht erstellen")
@owner_only()
@discord.app_commands.describe(emoji="Standard-Emoji wie ✅ oder 🎉 (für Server-Custom-Emojis: exakt <:name:id> eintippen)", rolle="Die Rolle, die vergeben wird", text="Text der Nachricht")
async def reaction_role_erstellen(interaction: discord.Interaction, emoji: str, rolle: discord.Role, text: str = "Reagiere mit dem Emoji, um die Rolle zu bekommen!"):
    embed = discord.Embed(title="🎭 Reaction Role", description=f"{text}\n\n{emoji} → {rolle.mention}", color=0x00f5ff)
    await interaction.response.send_message(embed=embed)
    nachricht = await interaction.original_response()
    try:
        await nachricht.add_reaction(emoji)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Konnte das Emoji nicht hinzufügen (ungültiges Emoji?): {e}", ephemeral=True)
        return

    daten = lade_daten()
    daten.setdefault("reaction_roles", {})
    daten["reaction_roles"][str(nachricht.id)] = {emoji: rolle.name}
    speichere_daten(daten)

@bot.tree.command(name="reaction-role-hinzufügen", description="[OWNER] Weiteres Emoji zu einer bestehenden Reaction-Role-Nachricht hinzufügen")
@owner_only()
async def reaction_role_hinzufuegen(interaction: discord.Interaction, nachrichten_id: str, emoji: str, rolle: discord.Role):
    try:
        nachricht = await interaction.channel.fetch_message(int(nachrichten_id.strip()))
    except (ValueError, discord.NotFound):
        await interaction.response.send_message("❌ Nachricht nicht gefunden — ID korrekt und im richtigen Kanal?", ephemeral=True)
        return

    try:
        await nachricht.add_reaction(emoji)
    except Exception as e:
        await interaction.response.send_message(f"❌ Konnte Emoji nicht hinzufügen: {e}", ephemeral=True)
        return

    daten = lade_daten()
    daten.setdefault("reaction_roles", {})
    daten["reaction_roles"].setdefault(nachrichten_id.strip(), {})
    daten["reaction_roles"][nachrichten_id.strip()][emoji] = rolle.name
    speichere_daten(daten)
    await interaction.response.send_message(f"✅ {emoji} → {rolle.mention} hinzugefügt.", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.member is None or payload.member.bot:
        return
    daten = lade_daten()
    eintrag = daten.get("reaction_roles", {}).get(str(payload.message_id))
    if not eintrag:
        return
    rollen_name = eintrag.get(str(payload.emoji))
    if not rollen_name:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    rolle = discord.utils.get(guild.roles, name=rollen_name)
    if rolle:
        try:
            await payload.member.add_roles(rolle)
        except Exception as e:
            print(f"[ReactionRole] Konnte Rolle nicht vergeben: {e}")

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    daten = lade_daten()
    eintrag = daten.get("reaction_roles", {}).get(str(payload.message_id))
    if not eintrag:
        return
    rollen_name = eintrag.get(str(payload.emoji))
    if not rollen_name:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        return
    rolle = discord.utils.get(guild.roles, name=rollen_name)
    if rolle:
        try:
            await member.remove_roles(rolle)
        except Exception as e:
            print(f"[ReactionRole] Konnte Rolle nicht entfernen: {e}")

@bot.tree.command(name="serverinfo", description="Server-Informationen anzeigen")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"ℹ️ {g.name}", color=0x00f5ff)
    embed.add_field(name="👑 Owner", value=g.owner.mention if g.owner else "?")
    embed.add_field(name="👥 Mitglieder", value=str(g.member_count))
    embed.add_field(name="📅 Erstellt", value=g.created_at.strftime("%d.%m.%Y"))
    embed.add_field(name="💬 Kanäle", value=str(len(g.text_channels)))
    embed.add_field(name="🎭 Rollen", value=str(len(g.roles)))
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="profilinfo", description="Infos über ein Mitglied anzeigen")
async def profilinfo(interaction: discord.Interaction, mitglied: discord.Member = None):
    m = mitglied or interaction.user
    daten = lade_daten()
    uid = str(m.id)
    xp = daten["xp"].get(uid, 0)
    level = get_level(xp)
    embed = discord.Embed(title=m.display_name, color=m.color)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="📅 Beigetreten", value=m.joined_at.strftime("%d.%m.%Y") if m.joined_at else "?")
    embed.add_field(name="⭐ Level", value=str(level))
    embed.add_field(name="✨ XP", value=str(xp))
    embed.add_field(name="🎭 Rollen", value=str(len(m.roles)-1))
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Bot-Latenz anzeigen")
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    farbe = 0x00ff88 if ms < 100 else 0xff9900 if ms < 200 else 0xff3333
    await interaction.response.send_message(embed=discord.Embed(title="🏓 Pong!", description=f"**{ms}ms**", color=farbe))

@bot.tree.command(name="hilfe", description="Alle Befehle anzeigen")
async def hilfe(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 NEXUS COMMUNITY BOT v19.0 — Befehle", color=0x00f5ff)
    embed.add_field(name="⭐ Level & XP", value="`/rang` `/top` `/xp-geben`", inline=False)
    embed.add_field(name="💰 Economy", value="`/balance` `/daily` `/coinflip` `/shop` `/kaufen` `/top-reich`", inline=False)
    embed.add_field(name="🏆 Achievements", value="`/achievements` `/profil-komplett`", inline=False)
    embed.add_field(name="🎉 Giveaways", value="`/giveaway` `/giveaway-beenden`", inline=False)
    embed.add_field(name="📊 Umfragen", value="`/umfrage` `/schnell-umfrage`", inline=False)
    embed.add_field(name="⏰ Erinnerungen", value="`/erinnerung-erstellen` `/erinnerungen-liste` `/erinnerung-löschen`", inline=False)
    embed.add_field(name="🎭 Reaction Roles", value="`/reaction-role-erstellen` `/reaction-role-hinzufügen` *(Owner)*", inline=False)
    embed.add_field(name="🔊 Voice", value="`/voice-join` `/voice-sag [text]` `/voice-leave`\n⚠️ Zuhören/Transkribieren ist technisch nicht zuverlässig möglich (siehe `/voice-zuhören`)", inline=False)
    embed.add_field(name="📱 TikTok", value="`/tiktok-profil` — unser offizieller Account\n`/tiktok-liste` — wer wird überwacht\n🔴 Live-Events via TikFinity-Webhook\nVerwaltung: `/setup-tiktok-account` `/tiktok-überwachen` `/setup-tikfinity-webhook` *(Owner)*", inline=False)
    embed.add_field(name="🧠 KI (Groq)", value="`/ki-chat` `/ki-frage` `/ki-idee` `/8ball` `/ki-merke` `/ki-vergiss`\n💬 Schreib dem Bot auch einfach eine DM — kein Befehl, kein Ping nötig!", inline=False)
    embed.add_field(name="🗄️ Wissensdatenbank", value="`/wissen-liste` (Verwaltung: Owner-Bereich)", inline=False)
    embed.add_field(name="🧩 Quiz", value="`/quiz` `/quiz-rangliste`", inline=False)
    embed.add_field(name="💻 Coding Studio", value="`/code` `/erklaer` `/fix` `/schreib-code` `/optimiere` `/code-hilfe`", inline=False)
    embed.add_field(name="🎭 Rollen", value="`/rolle-geben` `/rolle-entfernen`", inline=False)
    embed.add_field(name="🛡️ Moderation", value="`/warn` `/warnings` `/kick` `/ban` `/timeout`", inline=False)
    embed.add_field(name="🚨 Security", value="`/security-status` *(Owner)*\nAnti-Raid & Anti-Nuke: `/antiraid-an` `/antinuke-an` *(Owner)*", inline=False)
    embed.add_field(name="🔧 Custom Commands & Trigger", value="`/custom-commands-liste` `/trigger-liste` (Verwaltung: Owner-Bereich)", inline=False)
    embed.add_field(name="🎫 KI-Tickets", value="`/ticket [beschreibung]` oder Dropdown-Panel nutzen\n🔒 🆘 🧠 Buttons direkt im Ticket — kein Befehl nötig\n`/bewerbung-notiz` `/bewerbung-notizen-anzeigen` *(Supporter)*", inline=False)
    embed.add_field(name="🎮 Fun", value="`/münzwurf` `/würfeln` `/8ball` `/roast`", inline=False)
    embed.add_field(name="ℹ️ Info", value="`/serverinfo` `/profilinfo` `/ping`", inline=False)
    if ist_owner(interaction.user.id):
        embed.add_field(
            name="👑 Owner (1/2)",
            value=(
                "`/wartung-an` `/wartung-aus` `/bot-neustart` `/bot-status` `/discord-funktion`\n"
                "`/ki-moderation-an` `/ki-moderation-aus`\n"
                "`/setup-log-kanal` `/log-event-umschalten`\n"
                "`/custom-command-hinzufügen` `/custom-command-entfernen`\n"
                "`/wissen-hinzufügen` `/wissen-entfernen`\n"
                "`/github-datei-erstellen` `/github-funktion-generieren`\n"
                "`/trigger-erstellen` `/trigger-löschen`\n"
                "`/ticket-panel-erstellen` `/ticket-kategorie-hinzufügen` `/ticket-kategorie-entfernen`"
            ),
            inline=False
        )
        embed.add_field(
            name="👑 Owner (2/2)",
            value=(
                "`/setup-ticket-team` `/setup-ticket-log` `/ticket-ki-global-umschalten`\n"
                "`/reaction-role-erstellen` `/reaction-role-hinzufügen`\n"
                "`/voice-stimme-wählen`\n"
                "`/tiktok-überwachen` `/tiktok-nicht-mehr-überwachen` `/setup-tiktok-account`\n"
                "`/tiktok-automod-an` `/tiktok-automod-aus` `/tiktok-kanal-erlauben`"
            ),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════════════════
@bot.tree.error
async def on_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.MissingPermissions):
        msg = "❌ Keine Berechtigung."
    elif isinstance(error, discord.app_commands.CheckFailure):
        msg = "❌ Zugriff verweigert."
    else:
        msg = f"❌ Fehler: `{str(error)[:200]}`"
        print(f"[ERROR] {error}")
    try:
        await interaction.response.send_message(msg, ephemeral=True)
    except:
        try: await interaction.followup.send(msg, ephemeral=True)
        except: pass

# ═══════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════
import os as _os
if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN fehlt!")
    else:
        print(f"✅ Starte NEXUS Community Bot...")
        bot.run(TOKEN)

# ═══════════════════════════════════════════════════════════════
#  CODING STUDIO — Mit dem Bot programmieren
#  /code, /erklaer, /fix, /chat-code, /bot-code-hinzufügen
# ═══════════════════════════════════════════════════════════════

import subprocess, sys, tempfile, textwrap

# ── Sicherheits-Filter: Diese Befehle darf Python nicht ausführen ──
BLOCKED = [
    "os.system","subprocess","__import__","open(",
    "shutil","rmdir","remove","exec(","eval(",
    "socket","requests","urllib","aiohttp",
    "import os","import sys"
]

def ist_sicher(code: str) -> tuple[bool, str]:
    """Prüft ob Code sicher ausgeführt werden kann"""
    code_lower = code.lower()
    for b in BLOCKED:
        if b.lower() in code_lower:
            return False, f"❌ Blockierter Befehl: `{b}`"
    return True, ""

async def fuehre_code_aus(code: str) -> str:
    """Führt Python-Code in einer Sandbox aus"""
    ok, grund = ist_sicher(code)
    if not ok:
        return grund

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Begrenzte Imports erlauben
            safe_code = "import math, random, datetime, json, re, itertools, collections\n" + code
            f.write(safe_code)
            tmpfile = f.name

        result = subprocess.run(
            [sys.executable, tmpfile],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(tmpfile)

        if result.stdout:
            output = result.stdout.strip()[:1500]
            return f"```\n{output}\n```"
        if result.stderr:
            error = result.stderr.strip()[:800]
            return f"```\n❌ Fehler:\n{error}\n```"
        return "```\n(Kein Output)\n```"

    except subprocess.TimeoutExpired:
        return "```\n⏱️ Timeout — Code hat zu lange gebraucht (max 10s)\n```"
    except Exception as e:
        return f"```\n❌ {str(e)}\n```"

async def ki_code_hilfe(aufgabe: str, code: str = "", modus: str = "erklaer") -> str:
    """Groq AI für Code-Hilfe"""
    system_prompts = {
        "erklaer": "Du bist ein erfahrener Python-Entwickler. Erkläre den Code einfach und klar auf Deutsch. Benutze Emojis. Max 300 Wörter.",
        "fix":     "Du bist ein Python-Debugger. Finde und fixe den Fehler. Zeige den korrigierten Code mit ```python Block. Erkläre was falsch war.",
        "schreib": "Du bist ein Python-Entwickler. Schreibe sauberen, kommentierten Python-Code für die Aufgabe. Nur Code in ```python Block, dann kurze Erklärung.",
        "optimiere":"Du bist ein Python-Experte. Optimiere den Code für bessere Performance und Lesbarkeit. Zeige vorher/nachher.",
        "discord": "Du bist ein discord.py 2.x Experte. Schreibe eine neue Bot-Funktion als Slash-Command. Nur fertigen Code, keine Imports nötig (schon vorhanden).",
    }

    system = system_prompts.get(modus, system_prompts["erklaer"])
    user_msg = f"{aufgabe}\n\n```python\n{code}\n```" if code else aufgabe

    return await frage_gemini(system, user_msg)

# ── /code — Code ausführen ──────────────────────────────────────
@bot.tree.command(name="code", description="Python-Code direkt im Discord ausführen")
@discord.app_commands.describe(code="Python-Code der ausgeführt werden soll")
async def code_run(interaction: discord.Interaction, code: str):
    daten = lade_daten()
    if daten.get("maintenance") and not ist_owner(interaction.user.id):
        await interaction.response.send_message("🔧 Wartungsmodus.", ephemeral=True); return

    await interaction.response.defer()

    embed = discord.Embed(title="💻 Code Ausführung", color=0x00f5ff)
    embed.add_field(name="📝 Code", value=f"```python\n{code[:500]}\n```", inline=False)

    result = await fuehre_code_aus(code)
    embed.add_field(name="📤 Output", value=result[:1000], inline=False)
    embed.set_footer(text=f"Ausgeführt von {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)

# ── /erklaer — Code erklären lassen ────────────────────────────
@bot.tree.command(name="erklaer", description="Lass die KI deinen Code erklären")
@discord.app_commands.describe(code="Der Code der erklärt werden soll")
async def erklaer_code(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    erklaerung = await ki_code_hilfe("Erkläre diesen Code:", code, "erklaer")
    embed = discord.Embed(title="🔍 Code-Erklärung", color=0xbf5fff)
    embed.add_field(name="📝 Code", value=f"```python\n{code[:400]}\n```", inline=False)
    embed.add_field(name="🧠 Erklärung", value=erklaerung[:1000], inline=False)
    embed.set_footer(text="NEXUS Code-KI // Groq Llama 3.1")
    await interaction.followup.send(embed=embed)

# ── /fix — Fehler finden und beheben ───────────────────────────
@bot.tree.command(name="fix", description="KI findet und behebt Fehler in deinem Code")
@discord.app_commands.describe(code="Dein fehlerhafter Code", fehler="Die Fehlermeldung (optional)")
async def fix_code(interaction: discord.Interaction, code: str, fehler: str = ""):
    await interaction.response.defer()
    aufgabe = f"Fehlermeldung: {fehler}\n\nFixe diesen Code:" if fehler else "Fixe diesen Code:"
    fix = await ki_code_hilfe(aufgabe, code, "fix")
    embed = discord.Embed(title="🔧 Code-Fix", color=0x00ff88)
    embed.add_field(name="❌ Dein Code", value=f"```python\n{code[:350]}\n```", inline=False)
    if fehler:
        embed.add_field(name="⚠️ Fehler", value=f"```\n{fehler[:200]}\n```", inline=False)
    embed.add_field(name="✅ Fix", value=fix[:1000], inline=False)
    embed.set_footer(text="NEXUS Debug-KI // Groq Llama 3.1")
    await interaction.followup.send(embed=embed)

# ── /schreib-code — Code schreiben lassen ──────────────────────
@bot.tree.command(name="schreib-code", description="KI schreibt Python-Code für deine Aufgabe")
@discord.app_commands.describe(aufgabe="Was soll der Code machen?")
async def schreib_code(interaction: discord.Interaction, aufgabe: str):
    await interaction.response.defer()
    code = await ki_code_hilfe(aufgabe, "", "schreib")
    embed = discord.Embed(title="✨ Code geschrieben", color=0x00f5ff)
    embed.add_field(name="📋 Aufgabe", value=aufgabe, inline=False)
    embed.add_field(name="💻 Code", value=code[:1500], inline=False)
    embed.set_footer(text="NEXUS Code-KI // Groq Llama 3.1")
    await interaction.followup.send(embed=embed)

# ── /optimiere — Code verbessern ───────────────────────────────
@bot.tree.command(name="optimiere", description="KI optimiert und verbessert deinen Code")
@discord.app_commands.describe(code="Code der optimiert werden soll")
async def optimiere_code(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    optimiert = await ki_code_hilfe("Optimiere und verbessere diesen Code:", code, "optimiere")
    embed = discord.Embed(title="⚡ Code optimiert", color=0xffb400)
    embed.add_field(name="📝 Original", value=f"```python\n{code[:300]}\n```", inline=False)
    embed.add_field(name="🚀 Optimiert", value=optimiert[:1200], inline=False)
    embed.set_footer(text="NEXUS Code-KI // Groq Llama 3.1")
    await interaction.followup.send(embed=embed)

# ── /discord-funktion — Neue Bot-Funktion schreiben ────────────
@bot.tree.command(name="discord-funktion", description="[OWNER] KI schreibt eine neue Discord-Bot-Funktion")
@owner_only()
async def discord_funktion(interaction: discord.Interaction, beschreibung: str):
    await interaction.response.defer()

    funktion = await ki_code_hilfe(
        f"Schreibe einen neuen discord.py Slash-Command für: {beschreibung}\n"
        f"Bot-Variablen die verfügbar sind: bot, lade_daten(), speichere_daten(), frage_gemini(), ist_owner()",
        "", "discord"
    )

    # In Codelog speichern
    cl = {}
    if os.path.exists("codelog.json"):
        with open("codelog.json") as f:
            cl = json.load(f)
    cl.setdefault("extensions", [])
    cl.setdefault("total_written", 0)
    cl["total_written"] += 1
    cl["extensions"].append({
        "id": cl["total_written"],
        "aufgabe": beschreibung,
        "code": funktion,
        "timestamp": str(datetime.datetime.utcnow())
    })
    with open("codelog.json", "w") as f:
        json.dump(cl, f, indent=2)

    embed = discord.Embed(title="⚡ Neue Bot-Funktion", color=0xbf5fff)
    embed.add_field(name="📋 Beschreibung", value=beschreibung, inline=False)
    embed.add_field(name="💻 Generierter Code", value=funktion[:1500], inline=False)
    embed.add_field(name="💾 Gespeichert", value=f"Extension #{cl['total_written']} in codelog.json", inline=False)
    embed.set_footer(text="⚠️ Code prüfen bevor du ihn in bot.py einfügst!")
    await interaction.followup.send(embed=embed)

# ── /code-hilfe — Alle Code-Befehle anzeigen ───────────────────
@bot.tree.command(name="code-hilfe", description="Zeigt alle Coding-Befehle des Bots")
async def code_hilfe(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💻 NEXUS Coding Studio",
        description="Programmiere direkt in Discord!",
        color=0x00f5ff
    )
    embed.add_field(name="⚡ `/code [code]`", value="Python-Code direkt ausführen\n`/code print('Hello World')`", inline=False)
    embed.add_field(name="🔍 `/erklaer [code]`", value="KI erklärt deinen Code\n`/erklaer def fibonacci(n): ...`", inline=False)
    embed.add_field(name="🔧 `/fix [code]`", value="KI findet und behebt Fehler\n`/fix def add(a,b): return a-b`", inline=False)
    embed.add_field(name="✨ `/schreib-code [aufgabe]`", value="KI schreibt Code für dich\n`/schreib-code Fibonacci-Folge berechnen`", inline=False)
    embed.add_field(name="🚀 `/optimiere [code]`", value="KI optimiert deinen Code\n`/optimiere for i in range(len(liste)): ...`", inline=False)
    embed.add_field(name="🤖 `/discord-funktion [beschreibung]`", value="[Owner] Neue Bot-Funktion generieren\n`/discord-funktion /würfel Befehl mit animiertem Embed`", inline=False)
    embed.set_footer(text="NEXUS Coding Studio // Powered by Groq Llama 3.1")
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  NEXUS v9.0 — EXTENDED FEATURES
#  Economy, Achievements, AI-Moderation, Stats Dashboard
# ═══════════════════════════════════════════════════════════════

# ── Economy Helpers ──────────────────────────────────────────────
def lade_economy():
    default = {"balances": {}, "daily_claimed": {}, "shop_items": {
        "vip_rolle": {"preis": 5000, "name": "🌟 VIP Rolle"},
        "custom_color": {"preis": 2500, "name": "🎨 Eigene Farbe"},
        "boost_xp": {"preis": 1000, "name": "⚡ 2x XP für 1 Tag"},
    }}
    return _robust_json_lesen("economy.json", default)

def speichere_economy(e):
    _atomar_json_schreiben("economy.json", e)

def lade_achievements():
    default = {"unlocked": {}, "definitions": {
        "first_message": {"name": "👋 Erste Schritte", "desc": "Erste Nachricht gesendet"},
        "level_10": {"name": "⭐ Aufsteiger", "desc": "Level 10 erreicht"},
        "level_25": {"name": "🌟 Veteran", "desc": "Level 25 erreicht"},
        "rich_10k": {"name": "💰 Wohlhabend", "desc": "10.000 Coins gesammelt"},
        "ki_chatter": {"name": "🧠 KI-Freund", "desc": "50 mal mit der KI gechattet"},
        "giveaway_win": {"name": "🎉 Glückspilz", "desc": "Ein Giveaway gewonnen"},
    }}
    return _robust_json_lesen("achievements.json", default)

def speichere_achievements(a):
    _atomar_json_schreiben("achievements.json", a)

async def schalte_achievement_frei(uid: str, key: str, channel=None):
    a = lade_achievements()
    a["unlocked"].setdefault(uid, [])
    if key in a["unlocked"][uid]:
        return False
    a["unlocked"][uid].append(key)
    speichere_achievements(a)
    if channel and key in a["definitions"]:
        d = a["definitions"][key]
        embed = discord.Embed(
            title="🏆 ACHIEVEMENT FREIGESCHALTET!",
            description=f"**{d['name']}**\n{d['desc']}",
            color=0xffd700
        )
        try: await channel.send(embed=embed)
        except: pass
    return True

# ── AI Moderation Filter ─────────────────────────────────────────
async def ki_moderation_check(text: str) -> dict:
    """Lässt die KI prüfen ob eine Nachricht toxisch/problematisch ist"""
    if not GEMINI_KEY or len(text) < 5:
        return {"toxic": False}
    system = """Du bist ein Moderations-Filter für einen Discord-Server.
Antworte NUR mit JSON: {"toxic": true/false, "grund": "kurzer grund"}
toxic=true nur bei: Beleidigungen, Hassrede, Drohungen, extremer Spam.
toxic=false bei: normalen Gesprächen, Meinungen, Kritik, Humor."""
    antwort = await frage_gemini(system, f"Nachricht: {text}")
    try:
        import re as _re
        match = _re.search(r'\{.*\}', antwort, _re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return {"toxic": False}

# ═══════════════════════════════════════════════════════════════
#  ECONOMY COMMANDS
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="balance", description="Dein Coin-Guthaben anzeigen")
async def balance(interaction: discord.Interaction, mitglied: discord.Member = None):
    ziel = mitglied or interaction.user
    e = lade_economy()
    bal = e["balances"].get(str(ziel.id), 0)
    embed = discord.Embed(title="💰 Kontostand", color=0xffd700)
    embed.set_thumbnail(url=ziel.display_avatar.url)
    embed.add_field(name="Nutzer", value=ziel.mention)
    embed.add_field(name="Coins", value=f"🪙 {bal:,}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="daily", description="Tägliche Coins abholen")
async def daily(interaction: discord.Interaction):
    e = lade_economy()
    uid = str(interaction.user.id)
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    if e["daily_claimed"].get(uid) == today:
        await interaction.response.send_message("⏰ Du hast deinen täglichen Bonus bereits abgeholt! Komm morgen wieder.", ephemeral=True)
        return

    reward = random.randint(100, 500)
    e["balances"].setdefault(uid, 0)
    e["balances"][uid] += reward
    e["daily_claimed"][uid] = today
    speichere_economy(e)

    embed = discord.Embed(title="🎁 Täglicher Bonus!", description=f"Du hast **🪙 {reward} Coins** erhalten!", color=0x00ff88)
    embed.add_field(name="Neuer Kontostand", value=f"🪙 {e['balances'][uid]:,}")
    await interaction.response.send_message(embed=embed)

    if e["balances"][uid] >= 10000:
        await schalte_achievement_frei(uid, "rich_10k", interaction.channel)

@bot.tree.command(name="coinflip", description="Wette Coins auf Kopf oder Zahl")
@discord.app_commands.describe(einsatz="Wie viele Coins setzt du?", wahl="Kopf oder Zahl")
@discord.app_commands.choices(wahl=[
    discord.app_commands.Choice(name="Kopf", value="kopf"),
    discord.app_commands.Choice(name="Zahl", value="zahl"),
])
async def coinflip(interaction: discord.Interaction, einsatz: int, wahl: str):
    e = lade_economy()
    uid = str(interaction.user.id)
    bal = e["balances"].get(uid, 0)

    if einsatz <= 0 or einsatz > bal:
        await interaction.response.send_message(f"❌ Ungültiger Einsatz! Dein Guthaben: 🪙 {bal:,}", ephemeral=True)
        return

    ergebnis = random.choice(["kopf", "zahl"])
    gewonnen = ergebnis == wahl

    if gewonnen:
        e["balances"][uid] += einsatz
        farbe, text = 0x00ff88, f"🎉 Gewonnen! +🪙 {einsatz}"
    else:
        e["balances"][uid] -= einsatz
        farbe, text = 0xff3333, f"💸 Verloren! -🪙 {einsatz}"

    speichere_economy(e)
    embed = discord.Embed(title="🪙 Münzwurf", description=f"Ergebnis: **{ergebnis.upper()}**\n\n{text}", color=farbe)
    embed.set_footer(text=f"Neuer Kontostand: 🪙 {e['balances'][uid]:,}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="shop", description="Den Coin-Shop anzeigen")
async def shop(interaction: discord.Interaction):
    e = lade_economy()
    embed = discord.Embed(title="🛒 NEXUS Shop", description="Kaufe mit `/kaufen [item]`", color=0xbf5fff)
    for key, item in e["shop_items"].items():
        embed.add_field(name=item["name"], value=f"🪙 {item['preis']:,} Coins\n`/kaufen {key}`", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kaufen", description="Ein Item aus dem Shop kaufen")
async def kaufen(interaction: discord.Interaction, item: str):
    e = lade_economy()
    uid = str(interaction.user.id)

    if item not in e["shop_items"]:
        await interaction.response.send_message("❌ Item nicht gefunden. Nutze `/shop` für die Liste.", ephemeral=True)
        return

    preis = e["shop_items"][item]["preis"]
    bal = e["balances"].get(uid, 0)

    if bal < preis:
        await interaction.response.send_message(f"❌ Nicht genug Coins! Du brauchst 🪙 {preis:,}, hast aber nur 🪙 {bal:,}", ephemeral=True)
        return

    e["balances"][uid] -= preis
    speichere_economy(e)
    embed = discord.Embed(title="✅ Kauf erfolgreich!", description=f"Du hast **{e['shop_items'][item]['name']}** gekauft!", color=0x00ff88)
    embed.set_footer(text=f"Verbleibend: 🪙 {e['balances'][uid]:,}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="top-reich", description="Die reichsten Mitglieder anzeigen")
async def top_reich(interaction: discord.Interaction):
    e = lade_economy()
    sortiert = sorted(e["balances"].items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title="💰 Reichste Mitglieder", color=0xffd700)
    medals = ["🥇","🥈","🥉"] + ["🔹"]*7
    beschreibung = "\n".join([f"{medals[i]} <@{uid}> — 🪙 {bal:,}" for i,(uid,bal) in enumerate(sortiert)]) or "Noch keine Daten."
    embed.description = beschreibung
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  ACHIEVEMENTS
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="achievements", description="Deine freigeschalteten Erfolge anzeigen")
async def achievements_cmd(interaction: discord.Interaction, mitglied: discord.Member = None):
    ziel = mitglied or interaction.user
    a = lade_achievements()
    unlocked = a["unlocked"].get(str(ziel.id), [])

    embed = discord.Embed(title=f"🏆 Erfolge — {ziel.display_name}", color=0xffd700)
    embed.set_thumbnail(url=ziel.display_avatar.url)

    for key, d in a["definitions"].items():
        status = "✅" if key in unlocked else "🔒"
        embed.add_field(name=f"{status} {d['name']}", value=d['desc'], inline=True)

    embed.set_footer(text=f"{len(unlocked)}/{len(a['definitions'])} freigeschaltet")
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  ENHANCED EVENT HOOKS (Achievement triggers + AI Mod)
# ═══════════════════════════════════════════════════════════════

# (Achievement-Checks für "erste Nachricht" und Level laufen direkt in
#  gib_xp() / level_up() weiter unten — siehe dort für den echten Hook.)

# ═══════════════════════════════════════════════════════════════
#  ENHANCED PROFILE — zeigt Economy + Achievements zusammen
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="profil-komplett", description="Vollständiges Profil mit XP, Coins & Achievements")
async def profil_komplett(interaction: discord.Interaction, mitglied: discord.Member = None):
    ziel = mitglied or interaction.user
    daten = lade_daten()
    e = lade_economy()
    a = lade_achievements()
    uid = str(ziel.id)

    xp = daten["xp"].get(uid, 0)
    level = get_level(xp)
    bal = e["balances"].get(uid, 0)
    unlocked_count = len(a["unlocked"].get(uid, []))
    total_achievements = len(a["definitions"])

    embed = discord.Embed(title=f"🎮 {ziel.display_name}", color=ziel.color if ziel.color.value else 0x00f5ff)
    embed.set_thumbnail(url=ziel.display_avatar.url)
    embed.add_field(name="⭐ Level", value=str(level), inline=True)
    embed.add_field(name="✨ XP", value=f"{xp:,}", inline=True)
    embed.add_field(name="💰 Coins", value=f"🪙 {bal:,}", inline=True)
    embed.add_field(name="🏆 Erfolge", value=f"{unlocked_count}/{total_achievements}", inline=True)
    embed.add_field(name="📈 Fortschritt", value=xp_bar(xp, level), inline=False)
    embed.set_footer(text=f"Mitglied seit {ziel.joined_at.strftime('%d.%m.%Y') if ziel.joined_at else '?'}")
    await interaction.response.send_message(embed=embed)

print("✅ NEXUS v9.0 Extensions geladen: Economy, Achievements, AI-Mod")

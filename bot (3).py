import discord
from discord.ext import commands, tasks
import json
import os
import datetime
import asyncio
import aiohttp
import random

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
    }
    if not os.path.exists(DATA_FILE):
        speichere_daten(default); return default
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    for k, v in default.items():
        d.setdefault(k, v)
    return d

def speichere_daten(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4, ensure_ascii=False)

def lade_brain():
    default = {
        "conversation_history": [],
        "personality": "Ich bin NEXUS, ein freundlicher Community-Bot. Ich helfe gerne und bin immer positiv.",
        "stats": {"total_conversations": 0},
        "user_chat_counts": {},
        "user_memory": {}  # {uid: "Notizen die die KI sich über diesen Nutzer merkt"}
    }
    if not os.path.exists(BRAIN_FILE):
        with open(BRAIN_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    with open(BRAIN_FILE, "r", encoding="utf-8") as f:
        b = json.load(f)
    for k, v in default.items():
        b.setdefault(k, v)
    return b

def speichere_brain(b):
    with open(BRAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(b, f, indent=4, ensure_ascii=False)

# ═══════════════════════════════════════════════════════════════
#  WISSENSDATENBANK — Owner-gepflegte Fakten/FAQ, die die KI in
#  JEDEM Gespräch (DM, @-Mention, /ki-chat) als Kontext mitbekommt.
# ═══════════════════════════════════════════════════════════════
KNOWLEDGE_FILE = "knowledge.json"

def lade_knowledge():
    default = {"entries": {}}  # {"schlüssel": "Fakteninhalt"}
    if not os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        k = json.load(f)
    k.setdefault("entries", {})
    return k

def speichere_knowledge(k):
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(k, f, indent=4, ensure_ascii=False)

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

@bot.event
async def on_member_join(member):
    daten = lade_daten()
    if daten.get("maintenance") and not ist_owner(member.id): return

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

    # Bot erwähnt → KI antwortet
    if bot.user in message.mentions:
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

# ═══════════════════════════════════════════════════════════════
#  DASHBOARD-LOGIN — Verifizierungs-Codes per DM an den Owner
#  api.py legt Anfragen in login_requests.json ab, bot.py verschickt
#  die DM (nur der Discord-Client kann das, api.py ist kein Bot-Client)
# ═══════════════════════════════════════════════════════════════
LOGIN_QUEUE_FILE = "login_requests.json"

def lade_login_queue():
    if not os.path.exists(LOGIN_QUEUE_FILE):
        return {"requests": []}
    with open(LOGIN_QUEUE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere_login_queue(q):
    with open(LOGIN_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)

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

@bot.tree.command(name="ticket", description="Support-Ticket erstellen")
async def ticket(interaction: discord.Interaction):
    guild = interaction.guild
    existing = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name.lower()}")
    if existing:
        await interaction.response.send_message(f"❌ Bereits offen: {existing.mention}", ephemeral=True); return
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    kanal = await guild.create_text_channel(f"ticket-{interaction.user.name.lower()}", overwrites=overwrites)
    embed = discord.Embed(title="🎫 Ticket", description=f"{interaction.user.mention} — Beschreibe dein Anliegen.\n`/close` zum Schließen.", color=0x00f5ff)
    await kanal.send(embed=embed)
    await interaction.response.send_message(f"✅ {kanal.mention}", ephemeral=True)

@bot.tree.command(name="close", description="Ticket schließen")
async def close(interaction: discord.Interaction):
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Kein Ticket-Kanal.", ephemeral=True); return
    await interaction.response.send_message("🔒 Schließe in 3s...")
    await asyncio.sleep(3)
    await interaction.channel.delete()

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
    embed = discord.Embed(title="📖 NEXUS COMMUNITY BOT v12.0 — Befehle", color=0x00f5ff)
    embed.add_field(name="⭐ Level & XP", value="`/rang` `/top` `/xp-geben`", inline=False)
    embed.add_field(name="💰 Economy", value="`/balance` `/daily` `/coinflip` `/shop` `/kaufen` `/top-reich`", inline=False)
    embed.add_field(name="🏆 Achievements", value="`/achievements` `/profil-komplett`", inline=False)
    embed.add_field(name="🎉 Giveaways", value="`/giveaway` `/giveaway-beenden`", inline=False)
    embed.add_field(name="📊 Umfragen", value="`/umfrage` `/schnell-umfrage`", inline=False)
    embed.add_field(name="🧠 KI (Groq)", value="`/ki-chat` `/ki-frage` `/ki-idee` `/8ball` `/ki-merke` `/ki-vergiss`\n💬 Schreib dem Bot auch einfach eine DM — kein Befehl, kein Ping nötig!", inline=False)
    embed.add_field(name="🗄️ Wissensdatenbank", value="`/wissen-liste` (Verwaltung: Owner-Bereich)", inline=False)
    embed.add_field(name="🧩 Quiz", value="`/quiz` `/quiz-rangliste`", inline=False)
    embed.add_field(name="💻 Coding Studio", value="`/code` `/erklaer` `/fix` `/schreib-code` `/optimiere` `/code-hilfe`", inline=False)
    embed.add_field(name="🎭 Rollen", value="`/rolle-geben` `/rolle-entfernen`", inline=False)
    embed.add_field(name="🛡️ Moderation", value="`/warn` `/warnings` `/kick` `/ban` `/timeout`", inline=False)
    embed.add_field(name="🔧 Custom Commands", value="`/custom-commands-liste` (Verwaltung: Owner-Bereich)", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket` `/close`", inline=False)
    embed.add_field(name="🎮 Fun", value="`/münzwurf` `/würfeln` `/8ball` `/roast`", inline=False)
    embed.add_field(name="ℹ️ Info", value="`/serverinfo` `/profilinfo` `/ping`", inline=False)
    if ist_owner(interaction.user.id):
        embed.add_field(
            name="👑 Owner",
            value=(
                "`/wartung-an` `/wartung-aus` `/bot-neustart` `/bot-status` `/discord-funktion`\n"
                "`/ki-moderation-an` `/ki-moderation-aus`\n"
                "`/setup-log-kanal` `/log-event-umschalten`\n"
                "`/custom-command-hinzufügen` `/custom-command-entfernen`\n"
                "`/wissen-hinzufügen` `/wissen-entfernen`\n"
                "`/github-datei-erstellen` `/github-funktion-generieren`"
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
    if not os.path.exists("economy.json"):
        with open("economy.json","w") as f: json.dump(default, f, indent=2)
        return default
    with open("economy.json") as f:
        e = json.load(f)
    for k,v in default.items(): e.setdefault(k,v)
    return e

def speichere_economy(e):
    with open("economy.json","w") as f:
        json.dump(e, f, indent=2, ensure_ascii=False)

def lade_achievements():
    default = {"unlocked": {}, "definitions": {
        "first_message": {"name": "👋 Erste Schritte", "desc": "Erste Nachricht gesendet"},
        "level_10": {"name": "⭐ Aufsteiger", "desc": "Level 10 erreicht"},
        "level_25": {"name": "🌟 Veteran", "desc": "Level 25 erreicht"},
        "rich_10k": {"name": "💰 Wohlhabend", "desc": "10.000 Coins gesammelt"},
        "ki_chatter": {"name": "🧠 KI-Freund", "desc": "50 mal mit der KI gechattet"},
        "giveaway_win": {"name": "🎉 Glückspilz", "desc": "Ein Giveaway gewonnen"},
    }}
    if not os.path.exists("achievements.json"):
        with open("achievements.json","w") as f: json.dump(default, f, indent=2)
        return default
    with open("achievements.json") as f:
        a = json.load(f)
    for k,v in default.items(): a.setdefault(k,v)
    return a

def speichere_achievements(a):
    with open("achievements.json","w") as f:
        json.dump(a, f, indent=2, ensure_ascii=False)

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

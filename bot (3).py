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
#  Google Gemini AI + Level + XP + Rollen + Umfragen + Giveaways
# ═══════════════════════════════════════════════════════════════

TOKEN        = os.environ.get("DISCORD_TOKEN")
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY")   # Kostenlos: aistudio.google.com
OWNER_ID     = int(os.environ.get("OWNER_ID", "0"))
PREFIX       = "!"
DATA_FILE    = "data.json"
BRAIN_FILE   = "brain.json"

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
        }
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
        "user_chat_counts": {}
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
#  GOOGLE GEMINI AI
# ═══════════════════════════════════════════════════════════════
async def frage_gemini(system: str, user_msg: str, history: list = None) -> str:
    if not GEMINI_KEY:
        return "❌ Kein GEMINI_API_KEY gesetzt. Hol dir einen kostenlosen Key auf aistudio.google.com"

    clean_key = GEMINI_KEY.strip().replace("\n", "").replace(" ", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={clean_key}"

    # Konversations-History aufbauen
    contents = []
    if history:
        for h in history[-8:]:
            contents.append({"role": "user",  "parts": [{"text": h.get("frage", "")}]})
            contents.append({"role": "model", "parts": [{"text": h.get("antwort", "")}]})

    # System-Prompt + aktuelle Nachricht
    full_msg = f"{system}\n\nNutzer: {user_msg}"
    contents.append({"role": "user", "parts": [{"text": full_msg}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 1000,
        }
    }

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload) as r:
                if r.status == 200:
                    data = await r.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                err = await r.text()
                print(f"[Gemini] Fehler {r.status}: {err[:300]}")
                return f"❌ Gemini Fehler {r.status}: {err[:150]}"
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

    # Bonus-Text per Gemini
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
            embed.add_field(name="🤖 KI", value="Google Gemini 2.0 Flash")
            await owner.send(embed=embed)
        except: pass

    check_giveaways.start()

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
async def on_message(message):
    if message.author.bot: return
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

    # Bot erwähnt → KI antwortet
    if bot.user in message.mentions:
        frage = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if frage:
            async with message.channel.typing():
                brain = lade_brain()
                system = f"""{brain['personality']}
Du bist auf dem Discord-Server '{message.guild.name if message.guild else 'DM'}'.
Antworte auf Deutsch, freundlich und kurz (max 3 Sätze).
Datum: {datetime.datetime.utcnow().strftime('%d.%m.%Y')}"""
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
    system = f"{brain['personality']}\nServer: {interaction.guild.name if interaction.guild else 'DM'}\nAntworte auf Deutsch."
    antwort = await frage_gemini(system, nachricht, brain["conversation_history"])
    await lerne(nachricht, antwort, uid=str(interaction.user.id), channel=interaction.channel)
    embed = discord.Embed(description=antwort[:4096], color=0xbf5fff)
    embed.set_author(name="🧠 NEXUS KI (Gemini 2.0)", icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=f"Gespräch #{brain['stats']['total_conversations']}")
    await interaction.followup.send(embed=embed)

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

@bot.tree.command(name="ban", description="Mitglied bannen")
@discord.app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Kein Grund"):
    await mitglied.ban(reason=grund)
    await interaction.response.send_message(embed=discord.Embed(title="🔨 Gebannt", description=f"{mitglied.mention} — {grund}", color=0xff0000))

@bot.tree.command(name="timeout", description="Mitglied timeouten")
@discord.app_commands.checks.has_permissions(moderate_members=True)
async def timeout_cmd(interaction: discord.Interaction, mitglied: discord.Member, minuten: int = 10, grund: str = "Kein Grund"):
    await mitglied.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=minuten), reason=grund)
    await interaction.response.send_message(embed=discord.Embed(title="⏱️ Timeout", description=f"{mitglied.mention} für {minuten}min — {grund}", color=0xff9900))

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
        description="Nachrichten ab 15 Zeichen werden von Gemini auf Beleidigungen/Hassrede/Drohungen geprüft und bei Verstoß automatisch gelöscht. Betroffene Nutzer erhalten eine DM mit Begründung.",
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
    embed = discord.Embed(title="📖 NEXUS COMMUNITY BOT v9.0 — Befehle", color=0x00f5ff)
    embed.add_field(name="⭐ Level & XP", value="`/rang` `/top` `/xp-geben`", inline=False)
    embed.add_field(name="💰 Economy", value="`/balance` `/daily` `/coinflip` `/shop` `/kaufen` `/top-reich`", inline=False)
    embed.add_field(name="🏆 Achievements", value="`/achievements` `/profil-komplett`", inline=False)
    embed.add_field(name="🎉 Giveaways", value="`/giveaway` `/giveaway-beenden`", inline=False)
    embed.add_field(name="📊 Umfragen", value="`/umfrage` `/schnell-umfrage`", inline=False)
    embed.add_field(name="🧠 KI (Gemini)", value="`/ki-chat` `/ki-frage` `/ki-idee` `/8ball`", inline=False)
    embed.add_field(name="💻 Coding Studio", value="`/code` `/erklaer` `/fix` `/schreib-code` `/optimiere` `/code-hilfe`", inline=False)
    embed.add_field(name="🎭 Rollen", value="`/rolle-geben` `/rolle-entfernen`", inline=False)
    embed.add_field(name="🛡️ Moderation", value="`/warn` `/warnings` `/kick` `/ban` `/timeout`", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket` `/close`", inline=False)
    embed.add_field(name="🎮 Fun", value="`/münzwurf` `/würfeln` `/8ball`", inline=False)
    embed.add_field(name="ℹ️ Info", value="`/serverinfo` `/profilinfo` `/ping`", inline=False)
    if ist_owner(interaction.user.id):
        embed.add_field(name="👑 Owner", value="`/wartung-an` `/wartung-aus` `/bot-neustart` `/bot-status` `/discord-funktion` `/ki-moderation-an` `/ki-moderation-aus`", inline=False)
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
    """Gemini AI für Code-Hilfe"""
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
    embed.set_footer(text="NEXUS Code-KI // Gemini 2.0")
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
    embed.set_footer(text="NEXUS Debug-KI // Gemini 2.0")
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
    embed.set_footer(text="NEXUS Code-KI // Gemini 2.0")
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
    embed.set_footer(text="NEXUS Code-KI // Gemini 2.0")
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
    embed.set_footer(text="NEXUS Coding Studio // Powered by Gemini 2.0")
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
    """Lässt Gemini prüfen ob eine Nachricht toxisch/problematisch ist"""
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

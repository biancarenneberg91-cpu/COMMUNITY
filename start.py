# ═══════════════════════════════════════════════════════════════
#  NEXUS — Startet Bot + Dashboard API gleichzeitig
# ═══════════════════════════════════════════════════════════════
import threading, subprocess, sys, os, time

def run_bot():
    print("🤖 Starte Discord Bot...")
    subprocess.run([sys.executable, "bot.py"])

def run_api():
    print("🌐 Starte Dashboard API...")
    time.sleep(2)  # Bot zuerst starten lassen
    subprocess.run([sys.executable, "api.py"])

if __name__ == "__main__":
    t1 = threading.Thread(target=run_bot, daemon=True)
    t2 = threading.Thread(target=run_api)
    t1.start()
    t2.start()
    t2.join()

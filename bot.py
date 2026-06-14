import os
import json
import requests
from bs4 import BeautifulSoup

# ==========================
#  CONFIGURAZIONE
# ==========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Carica squadre dal secret TEAMS
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"


# ==========================
#  FUNZIONI TELEGRAM
# ==========================

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, json=payload)
        print(f"📨 Invio notifica: {text}")
        print(f"➡️ Risposta Telegram: {r.text}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")


# ==========================
#  CARICA / SALVA MATCHES
# ==========================

def load_matches():
    if not os.path.exists(MATCHES_FILE):
        print("⚠️ matches.json non trovato, creato nuovo file.")
        return {}
    try:
        with open(MATCHES_FILE, "r") as f:
            return json.load(f)
    except:
        print("❌ Errore lettura matches.json, ricreo file.")
        return {}


def save_matches(data):
    with open(MATCHES_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("💾 matches.json aggiornato")


# ==========================
#  PARSER DIRETTA.IT (NUOVO)
# ==========================

def extract_matches(url):
    print(f"🔎 Controllo partite per URL: {url}")

    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        print(f"❌ Errore richiesta HTTP: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # NUOVO SELETTORE 2026
    match_blocks = soup.find_all("div", class_="event_match")
    print(f"➡️ Trovati {len(match_blocks)} blocchi event_match")

    matches = []

    for block in match_blocks:
        # Orario
        time_el = block.find("div", class_="event_match--time")
        time_text = time_el.get_text(strip=True) if time_el else "N/D"

        # Squadre
        teams = block.find_all("div", class_="event_match--participant")
        if len(teams) < 2:
            continue

        home = teams[0].get_text(strip=True)
        away = teams[1].get_text(strip=True)

        match_str = f"{time_text} - {home} vs {away}"
        matches.append(match_str)

    print(f"✅ Partite estratte: {len(matches)}")
    return matches


# ==========================
#  MAIN BOT
# ==========================

def main():
    print("🚀 Avvio bot Diretta.it\n")

    stored_matches = load_matches()
    updated_matches = {}

    for team_name, url in TEAMS.items():
        print("\n==============================")
        print(f"👀 Squadra: {team_name}")

        new_list = extract_matches(url)
        old_list = stored_matches.get(team_name, [])

        print(f"📊 Vecchie partite: {len(old_list)}")

        # Trova partite nuove
        new_matches = [m for m in new_list if m not in old_list]

        print(f"📊 Nuove partite trovate: {len(new_matches)}")

        # Invia notifiche
        for match in new_matches:
            send_telegram_message(f"📅 Nuova partita per {team_name}:\n{match}")

        updated_matches[team_name] = new_list

    save_matches(updated_matches)
    print("✅ Fine esecuzione bot")


if __name__ == "__main__":
    main()

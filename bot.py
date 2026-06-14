import requests
from bs4 import BeautifulSoup
import json
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS"))

MATCHES_FILE = "matches.json"


def load_matches():
    if not os.path.exists(MATCHES_FILE):
        return {}
    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_matches(data):
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def send_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM_TOKEN o CHAT_ID mancanti")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"❌ Errore Telegram: {r.status_code} - {r.text}")
        else:
            print("✅ Messaggio Telegram inviato")
    except Exception as e:
        print(f"❌ Eccezione invio Telegram: {e}")


def check_team(url):
    print(f"🔎 Controllo partite per URL: {url}")
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=15)

    soup = BeautifulSoup(response.text, "html.parser")

    # Ogni partita è un blocco .event__match
    matches = soup.select("div.event__match")
    results = []

    print(f"➡️ Trovati {len(matches)} blocchi event__match")

    for m in matches:
        time_el = m.select_one(".event__time")
        home_el = m.select_one(".event__participant--home")
        away_el = m.select_one(".event__participant--away")

        if not (time_el and home_el and away_el):
            continue

        time = time_el.text.strip()
        home = home_el.text.strip()
        away = away_el.text.strip()

        text = f"{home} vs {away} - {time}"
        results.append(text)

    print(f"✅ Partite estratte: {len(results)}")
    return results


def main():
    print("🚀 Avvio bot Diretta.it")

    old_data = load_matches()
    new_data = {}

    for team, url in TEAMS.items():
        print(f"\n==============================")
        print(f"👀 Squadra: {team}")
        matches = check_team(url)
        new_data[team] = matches

        old_matches = old_data.get(team, [])

        # Nuove partite rispetto all'ultima esecuzione
        new_only = [m for m in matches if m not in old_matches]

        print(f"📊 Vecchie partite: {len(old_matches)}")
        print(f"📊 Nuove partite trovate: {len(new_only)}")

        for match in new_only:
            msg = f"Nuova partita trovata per {team}:\n{match}"
            print(f"📨 Invio notifica: {msg}")
            send_message(msg)

    save_matches(new_data)
    print("\n💾 matches.json aggiornato")
    print("✅ Fine esecuzione bot")


if __name__ == "__main__":
    main()

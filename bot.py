import requests
from bs4 import BeautifulSoup
import json
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Lista squadre: nome → URL Diretta.it (arriva dai secrets)
TEAMS = json.loads(os.getenv("TEAMS"))

DATA_FILE = "matches.json"

def load_seen():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_seen(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def fetch_matches(team_url):
    r = requests.get(team_url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    matches = []
    for row in soup.select(".event__match--scheduled"):
        home = row.select_one(".event__participant--home").text.strip()
        away = row.select_one(".event__participant--away").text.strip()
        date = row.select_one(".event__time").text.strip()
        matches.append(f"{home} - {away} | {date}")

    return matches

def main():
    seen = load_seen()

    for team_name, team_url in TEAMS.items():
        current = fetch_matches(team_url)
        old = seen.get(team_name, [])

        new_matches = [m for m in current if m not in old]

        if new_matches:
            for match in new_matches:
                send_alert(f"Nuova partita per {team_name}: {match}")

        seen[team_name] = current

    save_seen(seen)

if __name__ == "__main__":
    main()
import requests
from bs4 import BeautifulSoup
import json
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Lista squadre: nome → URL Diretta.it (arriva dai secrets)
TEAMS = json.loads(os.getenv("TEAMS"))

DATA_FILE = "matches.json"

def load_seen():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_seen(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def fetch_matches(team_url):
    r = requests.get(team_url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    matches = []
    for row in soup.select(".event__match--scheduled"):
        home = row.select_one(".event__participant--home").text.strip()
        away = row.select_one(".event__participant--away").text.strip()
        date = row.select_one(".event__time").text.strip()
        matches.append(f"{home} - {away} | {date}")

    return matches

def main():
    seen = load_seen()

    for team_name, team_url in TEAMS.items():
        current = fetch_matches(team_url)
        old = seen.get(team_name, [])

        new_matches = [m for m in current if m not in old]

        if new_matches:
            for match in new_matches:
                send_alert(f"Nuova partita per {team_name}: {match}")

        seen[team_name] = current

    save_seen(seen)

if __name__ == "__main__":
    main()

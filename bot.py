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
    with open(MATCHES_FILE, "r") as f:
        return json.load(f)


def save_matches(data):
    with open(MATCHES_FILE, "w") as f:
        json.dump(data, f, indent=4)


def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    requests.post(url, json=payload)


def check_team(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    matches = soup.select(".match-row")
    results = []

    for m in matches:
        home = m.select_one(".home-team").text.strip()
        away = m.select_one(".away-team").text.strip()
        time = m.select_one(".match-time").text.strip()

        # Estrazione data
        date_el = m.select_one(".match-date")
        date = date_el.text.strip() if date_el else "Data N/D"

        results.append(f"{home} vs {away} - {time} - {date}")

    return results


def main():
    old_data = load_matches()
    new_data = {}

    for team, url in TEAMS.items():
        matches = check_team(url)
        new_data[team] = matches

        old_matches = old_data.get(team, [])

        new_only = [m for m in matches if m not in old_matches]

        for match in new_only:
            send_message(f"Nuova partita trovata per {team}:\n{match}")

    save_matches(new_data)


if __name__ == "__main__":
    main()

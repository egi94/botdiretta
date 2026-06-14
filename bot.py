import os
import json
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime

# Carica il file .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"

# Tabelle italiane (compatibili con GitHub Actions)
ITALIAN_DAYS = [
    "Lunedì", "Martedì", "Mercoledì",
    "Giovedì", "Venerdì", "Sabato", "Domenica"
]

ITALIAN_MONTHS = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]


def format_match_date(raw_time: str):
    """
    Converte '05.04. 13:00' → ('Sabato 5 Aprile 2026', '13:00')
    Gestisce anche formati incompleti o anomali.
    """

    raw = raw_time.strip()

    # Se non contiene un punto, non è una data valida → ritorna grezzo
    if "." not in raw:
        return raw, ""

    parts = raw.split()

    # --- PARTE DATA ---
    date_part = parts[0].rstrip(".")  # rimuove eventuale punto finale
    date_bits = date_part.split(".")

    if len(date_bits) < 2:
        return raw, ""

    d = date_bits[0]
    m = date_bits[1]

    # Se c'è l'anno lo prendiamo, altrimenti anno corrente
    if len(date_bits) >= 3:
        year = date_bits[2]
    else:
        year = str(datetime.now().year)

    # --- PARTE ORARIO ---
    time_part = parts[1] if len(parts) > 1 else "00:00"

    # Crea datetime in modo sicuro
    try:
        dt = datetime.strptime(f"{d}.{m}.{year} {time_part}", "%d.%m.%Y %H:%M")
    except:
        return raw, time_part

    # Giorno e mese in italiano
    day_name = ITALIAN_DAYS[dt.weekday()]
    month_name = ITALIAN_MONTHS[dt.month - 1]

    formatted_date = f"{day_name} {dt.day} {month_name} {dt.year}"
    formatted_time = dt.strftime("%H:%M")

    return formatted_date, formatted_time


def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID mancanti, salto Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ Errore Telegram: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"⚠️ Eccezione Telegram: {e}")


def load_matches():
    if not os.path.exists(MATCHES_FILE):
        return {}
    try:
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_matches(data):
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


async def extract_matches(url: str):
    print(f"🔎 Carico pagina: {url}")

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="it-IT",
            timezone_id="Europe/Rome"
        )

        page = await context.new_page()
        await page.goto(url, timeout=60000, wait_until="networkidle")

        blocks = await page.query_selector_all("div.event__match")
        print(f"➡️ Trovati {len(blocks)} blocchi partita (event__match)")

        matches = []

        for block in blocks:
            time_el = await block.query_selector("div.event__time, span.eventTime")
            time_text = (await time_el.inner_text()).strip() if time_el else "N/D"

            team_els = await block.query_selector_all(
                'span[data-testid="wcl-scores-simple-text-01"]'
            )

            if len(team_els) < 2:
                continue

            home = (await team_els[0].inner_text()).strip()
            away = (await team_els[1].inner_text()).strip()

            formatted_date, formatted_time = format_match_date(time_text)

            match_str = (
                f"📅 {formatted_date}\n"
                f"🕒 {formatted_time}\n"
                f"⚽ {home} vs {away}"
            )

            matches.append(match_str)

        await browser.close()

        print(f"🧾 Partite estratte: {len(matches)}")
        for m in matches:
            print("   •", m)

        return matches


async def main():
    print("🚀 Avvio bot Diretta.it (Locale)")

    stored = load_matches()
    updated = {}

    for team_name, url in TEAMS.items():
        print("\n==============================")
        print(f"👀 Squadra: {team_name}")

        new_list = await extract_matches(url)
        old_list = stored.get(team_name, [])

        new_matches = [m for m in new_list if m not in old_list]

        print(f"🆕 Nuove partite trovate: {len(new_matches)}")
        for match in new_matches:
            print(f"📅 {match}")
            send_telegram_message(
                f"⚠️ *NUOVA PARTITA TROVATA!*\n"
                f"📣 Nuova partita trovate: *{team_name.upper()}*\n"
                f"{match}"
            )

        updated[team_name] = new_list

    save_matches(updated)
    print("✅ Fine esecuzione bot")


if __name__ == "__main__":
    asyncio.run(main())

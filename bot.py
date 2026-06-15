import os
import json
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime

# Carica .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"


# -------------------------------
#  FORMATTATORE DATA / ORA
# -------------------------------

ITALIAN_DAYS = [
    "Lunedì", "Martedì", "Mercoledì",
    "Giovedì", "Venerdì", "Sabato", "Domenica"
]

ITALIAN_MONTHS = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]


def format_match_date(raw_time: str):
    raw = raw_time.strip()

    if "." not in raw:
        return None, None

    parts = raw.split()

    date_part = parts[0].rstrip(".")
    date_bits = date_part.split(".")

    if len(date_bits) < 2:
        return None, None

    d = date_bits[0]
    m = date_bits[1]

    if len(date_bits) >= 3:
        year = date_bits[2]
    else:
        year = str(datetime.now().year)

    time_part = parts[1] if len(parts) > 1 else "00:00"

    try:
        dt = datetime.strptime(f"{d}.{m}.{year} {time_part}", "%d.%m.%Y %H:%M")
    except:
        return None, None

    formatted_date = f"{ITALIAN_DAYS[dt.weekday()]} {dt.day} {ITALIAN_MONTHS[dt.month - 1]} {dt.year}"
    formatted_time = dt.strftime("%H:%M")

    iso_date = dt.strftime("%Y-%m-%d")

    return iso_date, formatted_time, formatted_date


# -------------------------------
#  TELEGRAM
# -------------------------------

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TOKEN o CHAT_ID mancanti")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True
            },
            timeout=10
        )
        if r.status_code != 200:
            print(f"⚠️ Errore Telegram: {r.status_code} - {r.text}")

    except Exception as e:
        print(f"⚠️ Eccezione Telegram: {e}")


# -------------------------------
#  STORAGE
# -------------------------------

def load_matches():
    if not os.path.exists(MATCHES_FILE):
        return {}
    try:
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_matches(data):
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# -------------------------------
#  SCRAPING
# -------------------------------

async def extract_matches(url: str):
    print(f"🔎 Carico pagina: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="it-IT",
            timezone_id="Europe/Rome"
        )

        page = await context.new_page()
        await page.goto(url, timeout=60000, wait_until="networkidle")

        blocks = await page.query_selector_all("div.event__match")

        matches = []

        for block in blocks:
            # Tempo
            time_el = await block.query_selector("div.event__time, span.eventTime")
            time_text = (await time_el.inner_text()).strip() if time_el else None

            iso_date, match_time, formatted_date = format_match_date(time_text)

            if not iso_date:
                continue

            # Squadre
            team_els = await block.query_selector_all(
                'span[data-testid="wcl-scores-simple-text-01"]'
            )
            if len(team_els) < 2:
                continue

            home = (await team_els[0].inner_text()).strip()
            away = (await team_els[1].inner_text()).strip()

            # Link partita
            link_el = await block.query_selector("div.eventRowLink a")
            if link_el:
                href = await link_el.get_attribute("href")
                match_url = "https://www.diretta.it" + href if href.startswith("/") else href
            else:
                match_url = url

            matches.append({
                "home": home,
                "away": away,
                "date": iso_date,
                "time": match_time,
                "formatted_date": formatted_date,
                "url": match_url
            })

        await browser.close()
        return matches


# -------------------------------
#  MAIN LOGIC
# -------------------------------

async def main():
    print("🚀 Avvio bot Diretta.it (logica avanzata)")

    stored = load_matches()
    updated = {}

    for team_name, url in TEAMS.items():
        print(f"\n==============================")
        print(f"👀 Squadra: {team_name}")

        new_matches = await extract_matches(url)
        old_matches = stored.get(team_name, [])

        updated_matches = []

        for new in new_matches:
            # Cerca se la partita esiste già
            old = next((m for m in old_matches if m["url"] == new["url"]), None)

            if not old:
                # NUOVA PARTITA
                send_telegram_message(
                    f"⚠️ ! NUOVA PARTITA TROVATA ! ⚠️\n\n"
                    f"⚽ Nuova partita trovata: {team_name.upper()}\n"
                    f"📅 {new['formatted_date']}\n"
                    f"🕒 {new['time']}\n"
                    f"➡️ {new['home']} vs {new['away']}\n"
                    f"🔗 {new['url']}"
                )
                updated_matches.append(new)
                continue

            # PARTITA ESISTENTE → controlla variazioni
            if old["time"] != new["time"]:
                # VARIAZIONE ORARIO
                send_telegram_message(
                    f"⏰ ! VARIAZIONE ORARIO TROVATA ! ⏰\n\n"
                    f"⚽ Nuova partita trovata: {team_name.upper()}\n"
                    f"📅 {new['formatted_date']}\n"
                    f"🕒 {new['time']}\n"
                    f"➡️ {new['home']} vs {new['away']}\n"
                    f"🔗 {new['url']}"
                )

            if old["date"] != new["date"]:
                # VARIAZIONE DATA
                send_telegram_message(
                    f"📅 ! VARIAZIONE DATA TROVATA ! 📅\n\n"
                    f"⚽ Nuova partita trovata: {team_name.upper()}\n"
                    f"📅 {new['formatted_date']}\n"
                    f"🕒 {new['time']}\n"
                    f"➡️ {new['home']} vs {new['away']}\n"
                    f"🔗 {new['url']}"
                )

            updated_matches.append(new)

        updated[team_name] = updated_matches

    save_matches(updated)
    print("✅ Fine esecuzione bot")


if __name__ == "__main__":
    asyncio.run(main())

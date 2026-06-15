import os
import json
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Carica il file .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"

# Tabelle italiane
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
        return raw, ""

    parts = raw.split()

    date_part = parts[0].rstrip(".")
    date_bits = date_part.split(".")

    if len(date_bits) < 2:
        return raw, ""

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
        return raw, time_part

    day_name = ITALIAN_DAYS[dt.weekday()]
    month_name = ITALIAN_MONTHS[dt.month - 1]

    formatted_date = f"{day_name} {dt.day} {month_name} {dt.year}"
    formatted_time = dt.strftime("%H:%M")

    return formatted_date, formatted_time


def get_sport_emoji(team_name: str):
    name = team_name.lower()

    if "basket" in name:
        return "🏀"

    if (
        "pallanuoto" in name or
        "recco" in name or
        "quinto" in name or
        "bogliasco" in name or
        "savona" in name or
        "rapallo" in name
    ):
        return "🤽‍♂️"

    if "futsal" in name:
        return "🥅"

    return "⚽"


def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID mancanti, salto Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
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


def parse_stored_match(match_str):
    lines = match_str.split("\n")
    if len(lines) < 4:
        return None

    date_line = lines[0].replace("📅", "").strip()
    time_line = lines[1].replace("🕒", "").strip()
    teams_line = lines[2].replace("➡️", "").strip()
    url_line = lines[3].replace("🔗", "").strip()

    try:
        parts = date_line.split()
        day = int(parts[1])
        month_name = parts[2]
        year = int(parts[3])

        month = ITALIAN_MONTHS.index(month_name) + 1
        hour, minute = map(int, time_line.split(":"))

        dt = datetime(year, month, day, hour, minute)

        return dt, date_line, time_line, teams_line, url_line
    except:
        return None


async def list_next_matches_summary():
    stored = load_matches()
    now = datetime.now()
    limit = now + timedelta(days=7)

    start_date = f"{ITALIAN_DAYS[now.weekday()]} {now.day} {ITALIAN_MONTHS[now.month-1]} {now.year}"
    end_date = f"{ITALIAN_DAYS[limit.weekday()]} {limit.day} {ITALIAN_MONTHS[limit.month-1]} {limit.year}"

    days = {}
    for i in range(8):
        d = now + timedelta(days=i)
        key = d.date()
        days[key] = {
            "label": f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month-1]} {d.year}",
            "matches": []
        }

    for team, matches in stored.items():
        for m in matches:
            parsed = parse_stored_match(m)
            if not parsed:
                continue

            dt, date_line, time_line, teams_line, url_line = parsed

            if now.date() <= dt.date() <= limit.date():
                emoji = get_sport_emoji(team)
                days[dt.date()]["matches"].append(
                    f"{emoji} {team.upper()}\n"
                    f"📅 {date_line}\n"
                    f"🕒 {time_line}\n"
                    f"➡️ {teams_line}\n"
                    f"🔗 {url_line}\n"
                )

    msg = (
        f"📅 *Ecco le partite dei prossimi 7 giorni*\n"
        f"Intervallo: *{start_date}* → *{end_date}*\n\n"
    )

    for day_key in days:
        count = len(days[day_key]["matches"])
        part_word = "partita" if count == 1 else "partite"

        msg += f"📌 *{days[day_key]['label']}* ({count} {part_word})\n"

        if count > 0:
            for match in days[day_key]["matches"]:
                msg += match + "\n"
        else:
            msg += "Nessuna partita\n\n"

    send_telegram_message(msg)


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

            link_el = await block.query_selector('a[href*="/partita/"]')
            if not link_el:
                print("⚠️ Nessun link partita trovato, salto blocco")
                continue

            href = await link_el.get_attribute("href")
            match_url = "https://www.diretta.it" + href if href.startswith("/") else href

            if "SRF" in time_text:
                formatted_date = "DATA NON DISPONIBILE"
                formatted_time = ""
            else:
                formatted_date, formatted_time = format_match_date(time_text)

            match_str = (
                f"📅 {formatted_date}\n"
                f"🕒 {formatted_time}\n"
                f"➡️ {home} vs {away}\n"
                f"🔗 {match_url}"
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

    total_new_matches = 0

    for team_name, url in TEAMS.items():
        print("\n==============================")
        print(f"👀 Squadra: {team_name}")

        new_list = await extract_matches(url)
        old_list = stored.get(team_name, [])

        new_matches = [m for m in new

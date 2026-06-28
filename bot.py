import os
import json
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Carica .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"

ITALIAN_DAYS = [
    "Lunedì", "Martedì", "Mercoledì",
    "Giovedì", "Venerdì", "Sabato", "Domenica"
]

ITALIAN_MONTHS = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]

def normalize(name: str):
    return name.lower().replace("_", " ").strip()

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
    year = date_bits[2] if len(date_bits) >= 3 else str(datetime.now().year)
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
    if any(x in name for x in ["pallanuoto", "recco", "quinto", "bogliasco", "savona", "rapallo"]):
        return "🤽‍♂️"
    if "futsal" in name:
        return "🥅"
    return "⚽"

def send_telegram_message_with_button(text: str, url: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[{"text": "LIVESCORE", "url": url}]]
        }
    }
    requests.post(api_url, json=payload, timeout=10)

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
            "parse_mode": "Markdown"
        },
        timeout=10
    )

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})

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

def parse_italian_formatted_date(date_str: str, time_str: str):
    try:
        parts = date_str.split()
        day = int(parts[1])
        month_name = parts[2]
        year = int(parts[3])
        month = ITALIAN_MONTHS.index(month_name) + 1
        dt = datetime.strptime(time_str, "%H:%M")
        return datetime(year, month, day, dt.hour, dt.minute)
    except:
        return None

def create_ics_event(home, away, date_str, time_str, url, is_waterpolo):
    prefix = "[N][RTS]" if is_waterpolo else "[N][SD]"
    home_u = home.upper()
    away_u = away.upper()
    summary = f"{prefix} {home_u} {away_u}"

    dt = parse_italian_formatted_date(date_str, time_str)
    if dt is None:
        return None

    dt_end = dt + timedelta(hours=2)
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = dt_end.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{home_u}-{away_u}-{dtstart}@diretta"

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//DirettaNotifiche//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
SUMMARY:{summary}
DTSTART:{dtstart}
DTEND:{dtend}
CLASS:PUBLIC
TRANSP:OPAQUE
STATUS:CONFIRMED
DESCRIPTION:Livescore: {url}
BEGIN:VALARM
TRIGGER:-PT30M
ACTION:DISPLAY
DESCRIPTION:Promemoria
END:VALARM
END:VEVENT
END:VCALENDAR
"""

    filename = f"{home_u}_{away_u}_{dt.strftime('%Y%m%dT%H%M')}.ics"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ics_content)
    return filename

async def extract_matches(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="it-IT", timezone_id="Europe/Rome")
        page = await context.new_page()
        await page.goto(url, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        team_official_name = await page.inner_text("div.heading__name")
        team_official_norm = normalize(team_official_name.strip())

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']")
        if not blocks:
            blocks = await page.query_selector_all("div.event__match")

        matches = []
        for block in blocks:
            time_el = await block.query_selector("div.event__time")
            time_text = (await time_el.inner_text()).strip() if time_el else "N/D"

            home_el = await block.query_selector("div.event__homeParticipant span, div.event__homeParticipant")
            home = (await home_el.inner_text()).strip() if home_el else ""

            away_el = await block.query_selector("div.event__awayParticipant span, div.event__awayParticipant")
            away = (await away_el.inner_text()).strip() if away_el else ""

            link_el = await block.query_selector("a")
            if not link_el:
                continue
            href = await link_el.get_attribute("href")
            match_url = "https://www.diretta.it" + href if href.startswith("/") else href

            formatted_date, formatted_time = format_match_date(time_text)

            match_str = (
                f"📅 {formatted_date}\n"
                f"🕒 {formatted_time}\n"
                f"➡️ {home} vs {away}"
            )

            matches.append((team_official_norm, home, away, match_str, match_url))

        await browser.close()
        return matches

async def main():
    stored = load_matches()
    updated = {}
    total_new_matches = 0

    for team_name, url in TEAMS.items():
        extracted = await extract_matches(url)
        old_list = stored.get(team_name, [])
        new_list = []

        for team_official_norm, home, away, match_str, match_url in extracted:
            if team_official_norm not in normalize(home):
                continue
            new_list.append((match_str, match_url))

        for match_str, new_url in new_list:
            lines = match_str.split("\n")
            new_date = lines[0].replace("📅", "").strip()
            new_time = lines[1].replace("🕒", "").strip()
            new_vs = lines[2].replace("➡️", "").strip()

            old_match_found = None
            old_date = None
            old_time = None

            for old in old_list:
                o_lines = old.split("\n")
                o_date = o_lines[0].replace("📅", "").strip()
                o_time = o_lines[1].replace("🕒", "").strip()
                o_vs = o_lines[2].replace("➡️", "").strip()
                if o_vs == new_vs:
                    old_match_found = old
                    old_date = o_date
                    old_time = o_time
                    break

            emoji = get_sport_emoji(team_name)
            clean_name = team_name.upper().strip()

            if old_match_found is None:
                total_new_matches += 1
                send_telegram_message_with_button(
                    f"⚠️ NUOVA PARTITA TROVATA ⚠️\n\n{emoji} {clean_name}\n{match_str}",
                    new_url
                )
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)
                continue

            date_changed = (old_date != new_date)
            time_changed = (old_time != new_time)

            if date_changed or time_changed:
                total_new_matches += 1
                send_telegram_message_with_button(
                    f"⏰ VARIAZIONE ORARIO/DATA ⏰\n\n{emoji} {clean_name}\n{match_str}",
                    new_url
                )
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)

        updated[team_name] = [m[0] for m in new_list]

    save_matches(updated)

    # === CALENDARIO 28 GIORNI ===
    stored = load_matches()
    today = datetime.now()
    start_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = start_day + timedelta(days=28)

    days_list = [start_day + timedelta(days=i) for i in range(28)]
    matches_by_day = {d.date(): [] for d in days_list}

    for team_name, matches in stored.items():
        emoji = get_sport_emoji(team_name)
        for match in matches:
            lines = match.split("\n")
            raw_date = lines[0].replace("📅", "").strip()
            raw_time = lines[1].replace("🕒", "").strip()
            dt = parse_italian_formatted_date(raw_date, raw_time)
            if dt and start_day <= dt < end_day:
                matches_by_day[dt.date()].append((dt, team_name, emoji, match))

    def format_italian_date(d: datetime):
        return f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month - 1]} {d.year}"

    riepilogo = "📅 *Calendario partite prossimi 28 giorni:*\n\n"
    riepilogo += f"🌏 Dal *{format_italian_date(start_day)}* al *{format_italian_date(end_day - timedelta(days=1))}*\n\n"

    for d in days_list:
        day_key = d.date()
        riepilogo += "───────────────────────────────\n"
        riepilogo += f"📌 *{format_italian_date(d)}*\n"
        day_matches = sorted(matches_by_day[day_key], key=lambda x: x[0])
        if not day_matches:
            riepilogo += "• Nessuna partita in calendario\n\n"
            continue
        riepilogo += "\n"
        for dt, team_name, emoji, match in day_matches:
            lines = match.split("\n")
            time = lines[1].replace("🕒", "").strip()
            vs = lines[2].replace("➡️", "").strip()
            riepilogo += f"{emoji} *{team_name}*\n"
            riepilogo += f"• {time} — {vs}\n\n"

    timestamp_ita = datetime.now() + timedelta(hours=2)
    riepilogo += "───────────────────────────────\n"
    riepilogo += f"🔄 Scansione completata\n"
    riepilogo += f"Nuove partite trovate: {total_new_matches}\n"
    riepilogo += f"⏰ {timestamp_ita.strftime('%H:%M')} | {timestamp_ita.strftime('%A %d %B')}"

    send_telegram_message(riepilogo)

if __name__ == "__main__":
    asyncio.run(main())

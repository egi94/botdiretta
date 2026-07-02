import os
import json
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))
MATCHES_FILE = "matches.json"

ITALIAN_DAYS = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
ITALIAN_MONTHS = ["Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]

def normalize(name: str):
    return name.lower().replace("_"," ").strip()

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
    return f"{day_name} {dt.day} {month_name} {dt.year}", dt.strftime("%H:%M")

def get_sport_emoji(team_name: str):
    name = team_name.lower()
    if "basket" in name: return "🏀"
    if any(x in name for x in ["pallanuoto","recco","quinto","bogliasco","savona","rapallo"]): return "🤽‍♂️"
    if "futsal" in name: return "🥅"
    return "⚽"

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID mancanti, salto Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url,json={"chat_id":CHAT_ID,"text":text,"disable_web_page_preview":True,"parse_mode":"Markdown"})

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path,"rb") as f:
        requests.post(url,data={"chat_id":CHAT_ID},files={"document":f})

def load_matches():
    if not os.path.exists(MATCHES_FILE): return {}
    try:
        with open(MATCHES_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_matches(data):
    with open(MATCHES_FILE,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=4,ensure_ascii=False)

def parse_italian_formatted_date(date_str: str, time_str: str):
    try:
        parts = date_str.split()
        day = int(parts[1])
        month = ITALIAN_MONTHS.index(parts[2]) + 1
        year = int(parts[3])
        dt_time = datetime.strptime(time_str,"%H:%M")
        return datetime(year,month,day,dt_time.hour,dt_time.minute)
    except:
        return None

def create_ics_event(home,away,date_str,time_str,url,is_waterpolo):
    prefix = "[N][RTS]" if is_waterpolo else "[N][SD]"
    home_u, away_u = home.upper(), away.upper()
    summary = f"{prefix} {home_u} {away_u}"
    dt = parse_italian_formatted_date(date_str,time_str)
    if dt is None: return None
    dt_end = dt + timedelta(hours=2)
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = dt_end.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{home_u}-{away_u}-{dtstart}@diretta"
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
SUMMARY:{summary}
DTSTART:{dtstart}
DTEND:{dtend}
DESCRIPTION:Link diretta: {url}
END:VEVENT
END:VCALENDAR
"""
    filename = f"{home_u}_{away_u}_{dt.strftime('%Y%m%dT%H%M')}.ics"
    with open(filename,"w",encoding="utf-8") as f:
        f.write(ics)
    return filename

async def extract_matches(url: str):
    print(f"🔎 Carico pagina: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="it-IT",timezone_id="Europe/Rome")
        page = await context.new_page()
        await page.goto(url,timeout=60000,wait_until="networkidle")
        await page.wait_for_timeout(2000)

        team_official_name = await page.inner_text("div.heading__name")
        team_official_norm = normalize(team_official_name.strip())
        print(f"🏷️ Nome ufficiale squadra: {team_official_name}")

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']")
        if not blocks:
            blocks = await page.query_selector_all("div.event__match")

        print(f"➡️ Trovati {len(blocks)} blocchi partita")

        matches = []

        for block in blocks:

            # DATA
            date_el = await block.query_selector("span.wcl-dateContent_eEchT") \
                or await block.query_selector("div.wcl-MatchRow__date")
            raw_date = (await date_el.inner_text()).strip() if date_el else ""

            # ORA
            time_el = await block.query_selector("span.wcl-timeContent_xxx") \
                or await block.query_selector("div.wcl-MatchRow__time") \
                or await block.query_selector("span.wcl-scores-simple-text-01")
            raw_time = (await time_el.inner_text()).strip() if time_el else ""

            time_text = f"{raw_date} {raw_time}".strip()

            # HOME
            home_el = await block.query_selector("span.wcl-MatchRow__participantName") \
                or await block.query_selector("div.wcl-MatchRow__participant--home")
            home = (await home_el.inner_text()).strip() if home_el else ""

            # AWAY
            away_el = await block.query_selector_all("span.wcl-MatchRow__participantName")
            away = (await away_el[-1].inner_text()).strip() if away_el else ""

            # LINK
            link_el = await block.query_selector("a[href*='/partita/']")
            href = await link_el.get_attribute("href") if link_el else None
            match_url = "https://www.diretta.it" + href if href and href.startswith("/") else href

            formatted_date, formatted_time = format_match_date(time_text)

            match_str = (
                f"📅 {formatted_date}\n"
                f"🕒 {formatted_time}\n"
                f"➡️ {home} vs {away}\n"
                f"🔗 {match_url}"
            )

            matches.append((team_official_norm, home, away, match_str))

        await browser.close()
        return matches

async def main():
    print("🚀 Avvio bot Diretta.it (Locale)")
    stored = load_matches()
    updated = {}
    total_new_matches = 0

    for team_name, url in TEAMS.items():
        print("\n==============================")
        print(f"👀 Squadra: {team_name}")

        extracted = await extract_matches(url)
        old_list = stored.get(team_name, [])

        new_list = []

        for team_official_norm, home, away, match_str in extracted:
            if normalize(team_name) not in normalize(home) and normalize(team_name) not in normalize(away):
                continue
            new_list.append(match_str)

        for match_str in new_list:
            lines = match_str.split("\n")
            new_date = lines[0].replace("📅", "").strip()
            new_time = lines[1].replace("🕒", "").strip()
            new_vs = lines[2].replace("➡️", "").strip()
            new_url = lines[3].replace("🔗", "").strip()

            old_match_found = None
            old_date = None
            old_time = None

            for old in old_list:
                o_lines = old.split("\n")
                o_date = o_lines[0].replace("📅", "").strip()
                o_time = o_lines[1].replace("🕒", "").strip()
                o_vs = o_lines[2].replace("➡️", "").strip()
                o_url = o_lines[3].replace("🔗", "").strip()

                if o_vs == new_vs and o_url == new_url:
                    old_match_found = old
                    old_date = o_date
                    old_time = o_time
                    break

            emoji = get_sport_emoji(team_name)
            clean_name = team_name.upper().strip()

            if old_match_found is None:
                total_new_matches += 1
                send_telegram_message(
                    f"⚠️ ! NUOVA PARTITA TROVATA ! ⚠️\n\n"
                    f"{emoji} Nuova partita: {clean_name}\n"
                    f"{match_str}"
                )
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)
                continue

            if old_date != new_date or old_time != new_time:
                total_new_matches += 1
                send_telegram_message(
                    f"⏰ ! VARIAZIONE ORARIO/DATA ! ⏰\n\n"
                    f"{emoji} Squadra: {clean_name}\n"
                    f"{match_str}\n\n"
                    f"Vecchia data: {old_date} → Nuova: {new_date}\n"
                    f"Vecchio orario: {old_time} → Nuovo: {new_time}"
                )
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)

        updated[team_name] = new_list

    save_matches(updated)
    print("✅ Fine esecuzione bot")

if __name__ == "__main__":
    asyncio.run(main())

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
    bits = date_part.split(".")
    if len(bits) < 2:
        return raw, ""
    d, m = bits[0], bits[1]
    y = bits[2] if len(bits) == 3 else str(datetime.now().year)
    t = parts[1] if len(parts) > 1 else "00:00"
    try:
        dt = datetime.strptime(f"{d}.{m}.{y} {t}", "%d.%m.%Y %H:%M")
    except:
        return raw, t
    return f"{ITALIAN_DAYS[dt.weekday()]} {dt.day} {ITALIAN_MONTHS[dt.month-1]} {dt.year}", dt.strftime("%H:%M")

def get_sport_emoji(team_name: str):
    n = team_name.lower()
    if "basket" in n: return "🏀"
    if any(x in n for x in ["pallanuoto","recco","quinto","bogliasco","savona","rapallo"]): return "🤽‍♂️"
    if "futsal" in n: return "🥅"
    return "⚽"

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id":CHAT_ID,"text":text,"disable_web_page_preview":True,"parse_mode":"Markdown"}
    )

def send_ics_file(path):
    with open(path,"rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
            data={"chat_id":CHAT_ID},
            files={"document":f}
        )

def load_matches():
    if not os.path.exists(MATCHES_FILE): return {}
    try:
        return json.load(open(MATCHES_FILE,"r",encoding="utf-8"))
    except:
        return {}

def save_matches(data):
    json.dump(data,open(MATCHES_FILE,"w",encoding="utf-8"),indent=4,ensure_ascii=False)

def parse_italian_formatted_date(date_str: str, time_str: str):
    try:
        p = date_str.split()
        day = int(p[1])
        month = ITALIAN_MONTHS.index(p[2]) + 1
        year = int(p[3])
        tm = datetime.strptime(time_str,"%H:%M")
        return datetime(year,month,day,tm.hour,tm.minute)
    except:
        return None

def create_ics_event(home,away,date_str,time_str,url,is_waterpolo):
    prefix = "[N][RTS]" if is_waterpolo else "[N][SD]"
    hu, au = home.upper(), away.upper()
    dt = parse_italian_formatted_date(date_str,time_str)
    if dt is None: return None
    dt_end = dt + timedelta(hours=2)
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = dt_end.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{hu}-{au}-{dtstart}@diretta"
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
SUMMARY:{prefix} {hu} {au}
DTSTART:{dtstart}
DTEND:{dtend}
DESCRIPTION:Link diretta: {url}
END:VEVENT
END:VCALENDAR
"""
    fn = f"{hu}_{au}_{dt.strftime('%Y%m%dT%H%M')}.ics"
    open(fn,"w",encoding="utf-8").write(ics)
    return fn

async def extract_matches(url: str):
    print(f"🔎 Carico pagina: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="it-IT",timezone_id="Europe/Rome")
        page = await ctx.new_page()
        await page.goto(url,timeout=60000,wait_until="networkidle")
        await page.wait_for_timeout(2000)

        team_name = (await page.inner_text("div.heading__name")).strip()
        team_norm = normalize(team_name)
        print(f"🏷️ Squadra: {team_name}")

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']")
        if not blocks:
            blocks = await page.query_selector_all("div.event__match")

        print(f"➡️ Trovati {len(blocks)} blocchi")

        matches = []

        for block in blocks:

            # DATA
            d_el = await block.query_selector("span.wcl-dateContent_eEchT")
            raw_date = (await d_el.inner_text()).strip() if d_el else ""

            # ORA
            t_el = await block.query_selector("span.wcl-timeContent_xxx") \
                or await block.query_selector("span.wcl-scores-simple-text-01")
            raw_time = (await t_el.inner_text()).strip() if t_el else ""

            time_text = f"{raw_date} {raw_time}".strip()

            # SQUADRE
            parts = await block.query_selector_all("span.wcl-MatchRow__participantName")
            if len(parts) < 2:
                continue

            home = (await parts[0].inner_text()).strip()
            away = (await parts[1].inner_text()).strip()

            # LINK
            link_el = await block.query_selector("a[href*='/partita/']")
            href = await link_el.get_attribute("href") if link_el else None
            match_url = "https://www.diretta.it"+href if href and href.startswith("/") else href

            fd, ft = format_match_date(time_text)

            match_str = (
                f"📅 {fd}\n"
                f"🕒 {ft}\n"
                f"➡️ {home} vs {away}\n"
                f"🔗 {match_url}"
            )

            matches.append((team_norm,home,away,match_str))

        await browser.close()
        return matches

async def main():
    print("🚀 Avvio bot Diretta.it")
    stored = load_matches()
    updated = {}
    total_new = 0

    for team_name,url in TEAMS.items():
        print(f"\n👀 Squadra: {team_name}")
        extracted = await extract_matches(url)
        old_list = stored.get(team_name,[])
        new_list = []

        for team_norm,home,away,match_str in extracted:
            nt = normalize(team_name)
            if nt not in normalize(home) and nt not in normalize(away):
                continue
            new_list.append(match_str)

        for match_str in new_list:
            lines = match_str.split("\n")
            new_date = lines[0].replace("📅","").strip()
            new_time = lines[1].replace("🕒","").strip()
            new_vs = lines[2].replace("➡️","").strip()
            new_url = lines[3].replace("🔗","").strip()

            old_match = None
            old_date = None
            old_time = None

            for old in old_list:
                o_lines = old.split("\n")
                o_date = o_lines[0].replace("📅","").strip()
                o_time = o_lines[1].replace("🕒","").strip()
                o_vs = o_lines[2].replace("➡️","").strip()
                o_url = o_lines[3].replace("🔗","").strip()
                if o_vs == new_vs and o_url == new_url:
                    old_match = old
                    old_date = o_date
                    old_time = o_time
                    break

            emoji = get_sport_emoji(team_name)
            clean = team_name.upper()

            if old_match is None:
                total_new += 1
                send_telegram_message(
                    f"⚠️ NUOVA PARTITA TROVATA ⚠️\n\n"
                    f"{emoji} {clean}\n"
                    f"{match_str}"
                )
                home,away = new_vs.split(" vs ")
                wp = (emoji=="🤽‍♂️")
                fn = create_ics_event(home,away,new_date,new_time,new_url,wp)
                if fn:
                    send_ics_file(fn)
                    os.remove(fn)
                continue

            if old_date != new_date or old_time != new_time:
                total_new += 1
                send_telegram_message(
                    f"⏰ VARIAZIONE ORARIO/DATA ⏰\n\n"
                    f"{emoji} {clean}\n"
                    f"{match_str}\n\n"
                    f"Vecchia data: {old_date} → Nuova: {new_date}\n"
                    f"Vecchio orario: {old_time} → Nuovo: {new_time}"
                )
                home,away = new_vs.split(" vs ")
                wp = (emoji=="🤽‍♂️")
                fn = create_ics_event(home,away,new_date,new_time,new_url,wp)
                if fn:
                    send_ics_file(fn)
                    os.remove(fn)

        updated[team_name] = new_list

    save_matches(updated)
    print("✅ Fine esecuzione bot")

if __name__ == "__main__":
    asyncio.run(main())

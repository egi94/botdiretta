import os
import json
import asyncio
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# ============================
# CONFIGURAZIONE
# ============================

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))
MATCHES_FILE = "matches.json"

ITALIAN_DAYS = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
ITALIAN_MONTHS = ["Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]

# ============================
# FUNZIONI BASE
# ============================

def normalize(name: str):
    return name.lower().replace("_"," ").strip()

def format_match_date(raw_time: str):
    raw = raw_time.strip()
    if "." not in raw:
        return raw, ""
    parts = raw.split()
    date_part = parts[0].rstrip(".")
    d,m,y = date_part.split(".")
    time_part = parts[1] if len(parts)>1 else "00:00"
    try:
        dt = datetime.strptime(f"{d}.{m}.{y} {time_part}", "%d.%m.%Y %H:%M")
    except:
        return raw, time_part
    day_name = ITALIAN_DAYS[dt.weekday()]
    month_name = ITALIAN_MONTHS[dt.month-1]
    return f"{day_name} {dt.day} {month_name} {dt.year}", dt.strftime("%H:%M")

def get_sport_emoji(name: str):
    name = name.lower()
    if "basket" in name: return "🏀"
    if any(x in name for x in ["pallanuoto","recco","quinto","bogliasco","savona","rapallo"]): return "🤽‍♂️"
    if "futsal" in name: return "🥅"
    return "⚽"

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url,json={"chat_id":CHAT_ID,"text":text,"disable_web_page_preview":True,"parse_mode":"Markdown"})

def send_telegram_message_with_button(text: str, url: str):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard":[[{"text":"LIVESCORE","url":url}]]}
    }
    requests.post(api_url,json=payload)

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

# ============================
# ICS
# ============================

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
    with open(filename,"w",encoding="utf-8") as f:
        f.write(ics)
    return filename

def parse_match_str(match_str: str):
    lines = match_str.split("\n")
    date = lines[0].replace("📅","").strip()
    time = lines[1].replace("🕒","").strip()
    vs = lines[2].replace("➡️","").strip()
    return date,time,vs

# ============================
# SCRAPING AUTOMATICO
# ============================

async def extract_matches(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="it-IT",timezone_id="Europe/Rome")
        page = await context.new_page()

        await page.goto(url,timeout=60000,wait_until="networkidle")
        await page.wait_for_timeout(2000)

        team_name = await page.inner_text("div.heading__name")
        team_norm = normalize(team_name.strip())

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']")
        if not blocks:
            blocks = await page.query_selector_all("div.event__match")

        matches = []
        for block in blocks:
            time_el = await block.query_selector("div.event__time")
            time_text = (await time_el.inner_text()).strip() if time_el else "N/D"

            home_el = await block.query_selector("div.event__homeParticipant span, div.event__homeParticipant")
            away_el = await block.query_selector("div.event__awayParticipant span, div.event__awayParticipant")

            home = (await home_el.inner_text()).strip() if home_el else ""
            away = (await away_el.inner_text()).strip() if away_el else ""

            link_el = await block.query_selector("a")
            if not link_el: continue

            href = await link_el.get_attribute("href")
            match_url = "https://www.diretta.it"+href if href.startswith("/") else href

            formatted_date, formatted_time = format_match_date(time_text)
            match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}"

            matches.append((team_norm,home,away,match_str,match_url))

        await browser.close()
        return matches

# ============================
# /ADDMATCH SEMPLIFICATO
# ============================

def get_updates():
    if not TELEGRAM_TOKEN: return []
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url,timeout=10)
        return r.json().get("result",[])
    except:
        return []

async def process_addmatch_command_simple(text: str):
    try:
        parts = text.replace("/addmatch","").strip().split()

        if "vs" not in parts:
            send_telegram_message("❌ Formato non valido. Usa: /addmatch HOME vs AWAY DATA ORA SPORT URL")
            return

        vs_index = parts.index("vs")

        home = parts[vs_index-1]
        away = parts[vs_index+1]
        date_raw = parts[vs_index+2]
        time_raw = parts[vs_index+3]
        sport = parts[vs_index+4]
        url = parts[vs_index+5]

        formatted_date, formatted_time = format_match_date(f"{date_raw} {time_raw}")

        match_str = (
            f"📅 {formatted_date}\n"
            f"🕒 {formatted_time}\n"
            f"➡️ {home} vs {away}"
        )

        emoji = get_sport_emoji(sport)

        send_telegram_message_with_button(
            f"➕ *Partita aggiunta manualmente*\n\n{emoji} {match_str}",
            url
        )

        is_waterpolo = (emoji=="🤽‍♂️")
        ics_file = create_ics_event(home,away,formatted_date,formatted_time,url,is_waterpolo)
        if ics_file:
            send_ics_file(ics_file)
            os.remove(ics_file)

        stored = load_matches()
        manual = stored.get("MANUAL",[])
        manual.append(match_str)
        stored["MANUAL"] = manual
        save_matches(stored)

        send_telegram_message("✅ Partita aggiunta al riepilogo dei 28 giorni.")

    except Exception as e:
        send_telegram_message(f"❌ Errore nel comando /addmatch: {e}")

async def check_for_commands():
    updates = get_updates()
    for upd in updates:
        msg = upd.get("message",{})
        text = msg.get("text","")
        if not text: continue
        if text.startswith("/addmatch"):
            await process_addmatch_command_simple(text)

# ============================
# RIEPILOGO 28 GIORNI
# ============================

def create_and_send_ics_from_match(emoji,vs_str,date_str,time_str,url):
    home,away = vs_str.split(" vs ")
    is_waterpolo = (emoji=="🤽‍♂️")
    ics_file = create_ics_event(home,away,date_str,time_str,url,is_waterpolo)
    if ics_file:
        send_ics_file(ics_file)
        os.remove(ics_file)

def handle_match_change(event_type,emoji,team_name,match_str,url):
    clean = team_name.upper()
    title = "⚠️ NUOVA PARTITA TROVATA ⚠️" if event_type=="new" else "⏰ VARIAZIONE ORARIO/DATA ⏰"
    send_telegram_message_with_button(f"{title}\n\n{emoji} {clean}\n{match_str}",url)

def build_calendar_riepilogo(stored,total_new):
    today = datetime.now()
    start = today.replace(hour=0,minute=0,second=0,microsecond=0)
    end = start + timedelta(days=28)

    days = [start + timedelta(days=i) for i in range(28)]
    matches_by_day = {d.date():[] for d in days}

    for team_name,matches in stored.items():
        emoji = get_sport_emoji(team_name)
        for match in matches:
            date_str,time_str,vs_str = parse_match_str(match)
            dt = parse_italian_formatted_date(date_str,time_str)
            if dt and start <= dt < end:
                matches_by_day[dt.date()].append((dt,team_name,emoji,match))

    def fmt(d):
        return f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month-1]} {d.year}"

    r = "📅 *Calendario partite prossimi 28 giorni:*\n\n"
    r += f"🌏 Dal *{fmt(start)}* al *{fmt(end-timedelta(days=1))}*\n\n"

    for d in days:
        r += "───────────────────────────────\n"
        r += f"📌 *{fmt(d)}*\n"
        day_matches = sorted(matches_by_day[d.date()],key=lambda x:x[0])
        if not day_matches:
            r += "• Nessuna partita in calendario\n\n"
            continue
        r += "\n"
        for dt,team_name,emoji,match in day_matches:
            _,time_str,vs_str = parse_match_str(match)
            r += f"{emoji} *{team_name}*\n"
            r += f"• {time_str} — {vs_str}\n\n"

    ts = datetime.now() + timedelta(hours=2)
    r += "───────────────────────────────\n"
    r += "🔄 Scansione completata\n"
    r += f"Nuove partite trovate: {total_new}\n"
    r += f"⏰ {ts.strftime('%H:%M')} | {ts.strftime('%A %d %B')}"
    return r

# ============================
# MAIN
# ============================

async def main():
    await check_for_commands()

    stored = load_matches()
    updated = {}
    total_new = 0

    for team_name,url in TEAMS.items():
        extracted = await extract_matches(url)
        old_list = stored.get(team_name,[])
        new_list = []

        for team_norm,home,_,match_str,match_url in extracted:
            if team_norm not in normalize(home): continue
            new_list.append((match_str,match_url))

        for match_str,match_url in new_list:
            new_date,new_time,new_vs = parse_match_str(match_str)

            old_match = None
            old_date = None
            old_time = None

            for old in old_list:
                o_date,o_time,o_vs = parse_match_str(old)
                if o_vs == new_vs:
                    old_match = old
                    old_date = o_date
                    old_time = o_time
                    break

            emoji = get_sport_emoji(team_name)

            if old_match is None:
                total_new += 1
                handle_match_change("new",emoji,team_name,match_str,match_url)
                create_and_send_ics_from_match(emoji,new_vs,new_date,new_time,match_url)
                continue

            if old_date != new_date or old_time != new_time:
                total_new += 1
                handle_match_change("change",emoji,team_name,match_str,match_url)
                create_and_send_ics_from_match(emoji,new_vs,new_date,new_time,match_url)

        updated[team_name] = [m[0] for m in new_list]

    save_matches(updated)

    stored_after = load_matches()
    riepilogo = build_calendar_riepilogo(stored_after,total_new)
    send_telegram_message(riepilogo)

if __name__ == "__main__":
    asyncio.run(main())

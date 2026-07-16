import os, json, asyncio, requests
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"
ITALIAN_DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
ITALIAN_MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

def normalize(name: str): return name.lower().replace("_", " ").strip()

def format_match_date(raw_time: str):
    raw = raw_time.strip()
    if "." not in raw: return raw, ""
    parts = raw.split()
    date_part = parts[0].rstrip(".")
    date_bits = date_part.split(".")
    if len(date_bits) < 2: return raw, ""
    d, m = date_bits[0], date_bits[1]
    year = date_bits[2] if len(date_bits) >= 3 else str(datetime.now().year)
    time_part = parts[1] if len(parts) > 1 else "00:00"
    try:
        dt = datetime.strptime(f"{d}.{m}.{year} {time_part}", "%d.%m.%Y %H:%M")
        return f"{ITALIAN_DAYS[dt.weekday()]} {dt.day} {ITALIAN_MONTHS[dt.month-1]} {dt.year}", dt.strftime("%H:%M")
    except: return raw, time_part

def get_sport_emoji(team_name: str):
    name = team_name.lower()
    if "basket" in name: return "🏀"
    if any(x in name for x in ("pallanuoto","recco","quinto","bogliasco","savona","rapallo")): return "🤽‍♂️"
    if "futsal" in name: return "🥅"
    return "⚽"

def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID mancanti"); return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "disable_web_page_preview": True, "parse_mode": "Markdown"
        }, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ Errore Telegram: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"⚠️ Eccezione Telegram: {e}")

def send_long_message(text: str, max_len=3500):
    if len(text) <= max_len:
        send_telegram_message(text); return
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        if i + max_len < len(text) and "\n" in chunk:
            last_newline = chunk.rfind("\n")
            if last_newline > max_len * 0.7: chunk = chunk[:last_newline]
        send_telegram_message(chunk.strip())
        if i + max_len < len(text):
            asyncio.sleep(0.5)

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})

def load_matches():
    if not os.path.exists(MATCHES_FILE): return {}
    try:
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def save_matches(data):
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def parse_italian_formatted_date(date_str: str, time_str: str):
    try:
        parts = date_str.split()
        if len(parts) < 4: return None
        day = int(parts[1])
        month_name = parts[2]
        if month_name not in ITALIAN_MONTHS: return None
        month = ITALIAN_MONTHS.index(month_name) + 1
        year = int(parts[3])
        dt = datetime.strptime(time_str, "%H:%M")
        return datetime(year, month, day, dt.hour, dt.minute)
    except: return None

def create_ics_event(home, away, date_str, time_str, url, is_waterpolo):
    prefix = "[N][RTS]" if is_waterpolo else "[N][SD]"
    home_u = home.upper()
    away_u = away.upper()
    summary = f"{prefix} {home_u} {away_u}"
    dt = parse_italian_formatted_date(date_str, time_str)
    if not dt: return None
    dt_end = dt + timedelta(hours=2)
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = dt_end.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{home_u}-{away_u}-{dtstart}@diretta"
    ics_content = f"""BEGIN:VCALENDAR
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
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ics_content)
    return filename

def get_weather_data():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=44.407&longitude=8.934&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Europe/Rome"
        r = requests.get(url, timeout=10).json()
        return r["daily"]["time"], r["daily"]["weathercode"], r["daily"]["temperature_2m_max"], r["daily"]["temperature_2m_min"]
    except:
        return [], [], [], []

def weather_icon(code):
    if code == 0: return "☀️"
    if code in (1,2): return "⛅"
    if code == 3: return "☁️"
    if code in (45,48): return "🌫️"
    if code in (51,53,55,61,63,65): return "🌧️"
    if code in (71,73,75): return "❄️"
    if code in (95,96,99): return "⛈️"
    return "⛅"

async def extract_matches(url: str):
    print(f"🔎 Carico pagina: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}, locale="it-IT", timezone_id="Europe/Rome")
        page = await context.new_page()
        await page.goto(url, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        try:
            cookie_btn = await page.query_selector("button#onetrust-accept-btn-handler")
            if cookie_btn:
                await cookie_btn.click()
                await page.wait_for_timeout(1500)
        except: pass

        team_official_name = (await page.inner_text("div.heading__name")).strip()
        team_official_norm = normalize(team_official_name)
        print(f"🏷️ Nome ufficiale squadra: {team_official_name}")

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']") or await page.query_selector_all("div.event__match")
        print(f"➡️ Trovati {len(blocks)} blocchi partita")
        matches = []

        for block in blocks:
            date_time_el = await block.query_selector("span[class*='wcl-dateContent']")
            if date_time_el:
                raw = (await date_time_el.inner_text()).strip()
                formatted_date, formatted_time = format_match_date(raw)
                home_el = await block.query_selector("div.event__homeParticipant span.wcl-name_jjfMf")
                away_el = await block.query_selector("div.event__awayParticipant span.wcl-name_jjfMf")
                if not home_el or not away_el:
                    names = await block.query_selector_all("span.wcl-name_jjfMf")
                    if len(names) >= 1 and not home_el: home_el = names[0]
                    if len(names) >= 2 and not away_el: away_el = names[1]
                home = (await home_el.inner_text()).strip() if home_el else ""
                away = (await away_el.inner_text()).strip() if away_el else ""
                link_el = await block.query_selector("a[href*='/partita/']")
                href = await link_el.get_attribute("href") if link_el else None
                match_url = "https://www.diretta.it" + href if href and href.startswith("/") else href

                home_norm = normalize(home)
                if team_official_norm not in home_norm:
                    continue

                match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {match_url}"
                matches.append((team_official_norm, home, away, match_str))
                continue

            date_el = await block.query_selector("div.event__time--date") or await block.query_selector("span.event__time--date")
            time_el = await block.query_selector("div.event__time--time") or await block.query_selector("span.event__time--time")
            home_el = await block.query_selector("div[class*='participant'][class*='home']")
            away_el = await block.query_selector("div[class*='participant'][class*='away']")

            if date_el and time_el and home_el and away_el:
                raw_date = (await date_el.inner_text()).strip()
                raw_time = (await time_el.inner_text()).strip()
                formatted_date, formatted_time = format_match_date(f"{raw_date} {raw_time}")
                home = (await home_el.inner_text()).strip()
                away = (await away_el.inner_text()).strip()
                link_el = await block.query_selector("a[href*='/partita/']")
                href = await link_el.get_attribute("href") if link_el else None
                match_url = "https://www.diretta.it" + href if href and href.startswith("/") else href

                home_norm = normalize(home)
                if team_official_norm not in home_norm:
                    continue

                match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {match_url}"
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
        new_list = [match_str for _, _, _, match_str in extracted]

        for match_str in new_list:
            lines = match_str.split("\n")
            if len(lines) < 4: continue
            new_date = lines[0].replace("📅", "").strip()
            new_time = lines[1].replace("🕒", "").strip()
            new_vs = lines[2].replace("➡️", "").strip()
            new_url = lines[3].replace("🔗", "").strip()

            old_match_found = old_date = old_time = None
            for old in old_list:
                o = old.split("\n")
                if len(o) < 4: continue
                if o[2].replace("➡️", "").strip() == new_vs and o[3].replace("🔗", "").strip() == new_url:
                    old_match_found = old
                    old_date = o[0].replace("📅", "").strip()
                    old_time = o[1].replace("🕒", "").strip()
                    break

            emoji = get_sport_emoji(team_name)
            clean_name = team_name.upper().strip()

            if old_match_found is None:
                total_new_matches += 1
                send_telegram_message(f"⚠️ ! NUOVA PARTITA TROVATA ! ⚠️\n\n{emoji} Nuova partita: {clean_name}\n{match_str}")
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)
                continue

            if old_date != new_date or old_time != new_time:
                total_new_matches += 1
                date_msg = f"La vecchia data era {old_date} mentre la NUOVA DATA è {new_date}!" if old_date != new_date else f"La vecchia data era {old_date} mentre la NUOVA DATA è {new_date}! – NON VARIATA! –"
                time_msg = f"Il vecchio orario era {old_time} mentre il NUOVO ORARIO è {new_time}!" if old_time != new_time else f"Il vecchio orario era {old_time} mentre il NUOVO ORARIO è {new_time}! – NON VARIATA! –"
                send_telegram_message(f"⏰ ! VARIAZIONE ORARIO/DATA - Nuovo orario/data! ⏰\n\n{emoji} Squadra: {clean_name}\n{match_str}\n\n{time_msg}\n{date_msg}")
                home, away = new_vs.split(" vs ")
                is_waterpolo = (emoji == "🤽‍♂️")
                ics_file = create_ics_event(home, away, new_date, new_time, new_url, is_waterpolo)
                if ics_file:
                    send_ics_file(ics_file)
                    os.remove(ics_file)

        updated[team_name] = new_list

    save_matches(updated)
    print("✅ Fine esecuzione bot")

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
            if len(lines) < 4: continue
            dt = parse_italian_formatted_date(
                lines[0].replace("📅", "").strip(),
                lines[1].replace("🕒", "").strip())
            if dt and start_day <= dt < end_day:
                matches_by_day[dt.date()].append((dt, team_name, emoji, match))

    def format_italian_date(d):
        return f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month-1]} {d.year}"

    start_str = format_italian_date(start_day)
    end_str = format_italian_date(end_day - timedelta(days=1))

    riepilogo = f"📅 *Calendario partite prossimi 28 giorni:*\n\n🌏 Dal *{start_str}* al *{end_str}*\n\n"

    wx_dates, wx_codes, wx_max, wx_min = get_weather_data()
    wx_map = {wx_dates[i]: (wx_codes[i], wx_max[i], wx_min[i]) for i in range(len(wx_dates))}

    empty_start = None

    for d in days_list:
        day_key = d.date()
        day_label = format_italian_date(d)
        day_matches = sorted(matches_by_day[day_key], key=lambda x: x[0])

        d_str = d.strftime("%Y-%m-%d")
        if d_str in wx_map:
            code, tmax, tmin = wx_map[d_str]
            icon = weather_icon(code)
            temp = f"{int(tmin)}°C / {int(tmax)}°C"
        else:
            icon = "⛅"
            temp = "--°C / --°C"

        if not day_matches:
            if empty_start is None:
                empty_start = d
            continue

        if empty_start:
            end_empty = d - timedelta(days=1)
            if empty_start == end_empty:
                riepilogo += f"───────────────────────────────\n📌 *{format_italian_date(empty_start)}* ⛅ (Nessuna partita)\n\n"
            else:
                riepilogo += f"───────────────────────────────\n📌 *Dal {empty_start.day} al {end_empty.day} {ITALIAN_MONTHS[empty_start.month-1]} {empty_start.year}* ⛅ (Nessuna partita)\n\n"
            empty_start = None

        riepilogo += f"───────────────────────────────\n📌 *{day_label}* {icon} ({temp})\n\n"
        for _, team_name, emoji, match in day_matches:
            lines = match.split("\n")
            riepilogo += f"{emoji} *{team_name}*\n• {lines[1].replace('🕒','').strip()} — {lines[2].replace('➡️','').strip()}\n  🔗 {lines[3].replace('🔗','').strip()}\n\n"

    if empty_start:
        end_empty = end_day - timedelta(days=1)
        if empty_start == end_empty:
            riepilogo += f"───────────────────────────────\n📌 *{format_italian_date(empty_start)}* ⛅ (Nessuna partita)\n\n"
        else:
            riepilogo += f"───────────────────────────────\n📌 *Dal {empty_start.day} al {end_empty.day} {ITALIAN_MONTHS[empty_start.month-1]} {empty_start.year}* ⛅ (Nessuna partita)\n\n"

    timestamp = datetime.now() + timedelta(hours=2)
    riepilogo += "───────────────────────────────\n🔄 Scansione completata\n"
    riepilogo += f"Nuove partite trovate: {total_new_matches}\n"
    riepilogo += f"⏰ {timestamp.strftime('%H:%M')} | {timestamp.strftime('%A %d %B')}"

    send_long_message(riepilogo)

if __name__ == "__main__":
    asyncio.run(main())

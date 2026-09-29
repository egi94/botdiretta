import os, json, asyncio, requests, threading
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

STATUS_EMOJI = {"yellow": "🟡", "green": "🟢", "red": "🔴", "purple": "🟣"}
DEFAULT_STATUS = "🟡"
AUTO_DELETE_SECONDS = 600

def normalize(name: str): return name.lower().replace("_", " ").strip()
def normalize_link(link: str): return link.strip().replace("\n","").replace("\r","").replace(" ","").replace("\u200b","")
def normalize_vs(s: str):
    s = s.lower().replace("-", " vs ").replace(" "," ").strip()
    s = s.replace(" vs vs "," vs ")
    return " ".join(s.split())

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

def send_telegram_message(text: str, auto_delete_sec=None):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code!=200: return None
        msg_id = r.json().get("result", {}).get("message_id")
        if auto_delete_sec and msg_id:
            def _delete():
                try:
                    del_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
                    requests.post(del_url, json={"chat_id": CHAT_ID, "message_id": msg_id}, timeout=10)
                except: pass
            threading.Timer(auto_delete_sec, _delete).start()
        return msg_id
    except: return None

def send_long_message(text: str, max_len=3500):
    if len(text) <= max_len: send_telegram_message(text); return
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        if i + max_len < len(text) and "\n" in chunk:
            last_newline = chunk.rfind("\n")
            if last_newline > max_len*0.7: chunk = chunk[:last_newline]
        send_telegram_message(chunk.strip())

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f: requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})

def load_matches():
    if not os.path.exists(MATCHES_FILE): return {"matches": {}, "manual": [], "blacklist": [], "status": {}}
    try:
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "matches" not in data: return {"matches": {}, "manual": [], "blacklist": [], "status": {}}
            if "manual" not in data or not isinstance(data.get("manual"), list): data["manual"] = []
            if "blacklist" not in data or not isinstance(data.get("blacklist"), list): data["blacklist"] = []
            if "status" not in data or not isinstance(data.get("status"), dict): data["status"] = {}
            return data
    except: return {"matches": {}, "manual": [], "blacklist": [], "status": {}}

def save_matches(data):
    with open(MATCHES_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

def parse_italian_formatted_date(date_str: str, time_str: str):
    try:
        parts = date_str.split()
        if len(parts) < 4: return None
        day = int(parts[1]); month_name = parts[2]
        if month_name not in ITALIAN_MONTHS: return None
        month = ITALIAN_MONTHS.index(month_name) + 1; year = int(parts[3])
        dt = datetime.strptime(time_str, "%H:%M")
        return datetime(year, month, day, dt.hour, dt.minute)
    except: return None

def create_ics_event(home, away, date_str, time_str, url, is_waterpolo):
    prefix = "[N][RTS]" if is_waterpolo else "[N][SD]"
    summary = f"{prefix} {home.upper()} {away.upper()}"
    dt = parse_italian_formatted_date(date_str, time_str)
    if not dt: return None
    dt_end = dt + timedelta(hours=2)
    dtstart = dt.strftime("%Y%m%dT%H%M%S"); dtend = dt_end.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uid = f"{home.upper()}-{away.upper()}-{dtstart}@diretta"
    ics_content = f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{dtstamp}\nSUMMARY:{summary}\nDTSTART:{dtstart}\nDTEND:{dtend}\nDESCRIPTION:Link diretta: {url}\nEND:VEVENT\nEND:VCALENDAR\n"
    filename = f"{home.upper()}_{away.upper()}_{dt.strftime('%Y%m%dT%H%M')}.ics"
    with open(filename, "w", encoding="utf-8") as f: f.write(ics_content)
    return filename

def get_match_key(match_str: str):
    try:
        lines = match_str.split("\n")
        if len(lines) >= 4: return normalize_link(lines[3].replace("🔗", "").strip())
    except: pass
    return ""

def get_match_vs(match_str: str):
    try:
        lines = match_str.split("\n")
        if len(lines) >= 3: return lines[2].replace("➡️", "").strip()
    except: pass
    return ""

def get_weather_data():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=44.407&longitude=8.934&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Europe/Rome"
        r = requests.get(url, timeout=10).json()
        d = r["daily"]
        return d["time"], d["weathercode"], d["temperature_2m_max"], d["temperature_2m_min"]
    except:
        return [], [], [], []

def weather_description(code):
    try: code = int(code)
    except: return "☁️"
    if code == 0: return "☀️"
    if code in (1, 2, 3): return "☁️"
    if code in (45, 48): return "🌫️"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82): return "🌧️"
    if code in (71, 73, 75, 77, 85, 86): return "❄️"
    if code in (95, 96, 99): return "⛈️"
    return "☁️"

def get_status_emoji(link: str, status_map: dict):
    link = normalize_link(link)
    if link in status_map: return status_map[link]
    try:
        if "pid=" in link:
            pid = link.split("pid=")[1].split("&")[0]
            for k, v in status_map.items():
                if f"pid={pid}" in k: return v
        for k, v in status_map.items():
            if link in k or k in link: return v
    except: pass
    return DEFAULT_STATUS

def set_match_status(inp: str, color: str):
    inp_raw = inp.strip()
    is_link = inp_raw.startswith("http")
    data = load_matches()
    if "status" not in data: data["status"] = {}
    emoji = STATUS_EMOJI.get(color, DEFAULT_STATUS)
    all_matches = []
    for v in data.get("matches", {}).values(): all_matches.extend(v)
    all_matches.extend(data.get("manual", []))
    target_link = None
    target_vs = ""
    if is_link:
        nlink = normalize_link(inp_raw)
        for m in all_matches:
            stored = get_match_key(m)
            if not stored: continue
            if stored == nlink or nlink in stored or stored in nlink:
                target_link = stored; target_vs = get_match_vs(m); break
            if "pid=" in nlink and "pid=" in stored and nlink.split("pid=")[1].split("&")[0] == stored.split("pid=")[1].split("&")[0]:
                target_link = stored; target_vs = get_match_vs(m); break
        if not target_link: target_link = nlink
    else:
        vs_input = normalize_vs(inp_raw)
        for m in all_matches:
            vs = get_match_vs(m)
            if not vs: continue
            if normalize_vs(vs) == vs_input:
                target_link = get_match_key(m); target_vs = vs; break
        if not target_link:
            for m in all_matches:
                vs = get_match_vs(m)
                if vs_input in normalize_vs(vs):
                    target_link = get_match_key(m); target_vs = vs; break
        if not target_link:
            for m in all_matches:
                vs = get_match_vs(m)
                if inp_raw.lower() in vs.lower():
                    target_link = get_match_key(m); target_vs = vs; break
    if not target_link:
        send_telegram_message(f"❌ Non trovata: {inp_raw}", auto_delete_sec=AUTO_DELETE_SECONDS)
        return
    data["status"][target_link] = emoji
    data["status"][normalize_link(target_link)] = emoji
    if is_link: data["status"][normalize_link(inp_raw)] = emoji
    save_matches(data)
    if target_vs and target_vs.lower() not in target_link.lower():
        msg = f"{emoji} Stato {color.upper()} impostato\n{target_vs}\n{emoji} {target_link}"
    else:
        msg = f"{emoji} Stato {color.upper()} impostato\n{emoji} {target_link}"
    send_telegram_message(msg, auto_delete_sec=AUTO_DELETE_SECONDS)

async def extract_matches(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1366, "height": 768}, locale="it-IT", timezone_id="Europe/Rome")
        page = await context.new_page()
        await page.goto(url, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        try:
            btn = await page.query_selector("button#onetrust-accept-btn-handler")
            if btn: await btn.click(); await page.wait_for_timeout(1500)
        except: pass
        team_official_name = (await page.inner_text("div.heading__name")).strip()
        team_official_norm = normalize(team_official_name)
        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']") or await page.query_selector_all("div.event__match")
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
                    if len(names) >=1 and not home_el: home_el = names[0]
                    if len(names) >=2 and not away_el: away_el = names[1]
                home = (await home_el.inner_text()).strip() if home_el else ""
                away = (await away_el.inner_text()).strip() if away_el else ""
                link_el = await block.query_selector("a[href*='/partita/']")
                href = await link_el.get_attribute("href") if link_el else None
                match_url = "https://www.diretta.it" + href if href and href.startswith("/") else href
                if team_official_norm not in normalize(home): continue
                match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {normalize_link(match_url)}"
                matches.append((team_official_norm, home, away, match_str))
        await browser.close()
        return matches

async def add_match_manually(link: str):
    link = normalize_link(link)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1366, "height": 768}, locale="it-IT", timezone_id="Europe/Rome")
        page = await context.new_page()
        await page.goto(link, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(3000)
        time_el = await page.query_selector("div.duelParticipant__startTime div")
        home_el = await page.query_selector("div.duelParticipant__home a.participant__participantName")
        away_el = await page.query_selector("div.duelParticipant__away a.participant__participantName")
        raw_time = (await time_el.inner_text()).strip() if time_el else ""
        home = (await home_el.inner_text()).strip() if home_el else ""
        away = (await away_el.inner_text()).strip() if away_el else ""
        formatted_date, formatted_time = format_match_date(raw_time)
        match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {link}"
        data = load_matches()
        if match_str not in data["manual"]:
            data["manual"].append(match_str); save_matches(data)
            ics_file = create_ics_event(home, away, formatted_date, formatted_time, link, get_sport_emoji(home) == "🤽‍♂️")
            if ics_file: send_ics_file(ics_file); os.remove(ics_file)
        send_telegram_message(f"⚠️! NUOVA PARTITA MANUALMENTE! ⚠️\n\n{match_str}", auto_delete_sec=AUTO_DELETE_SECONDS)
        await browser.close()

async def add_match_manual_custom(raw_command: str):
    try:
        payload = raw_command.replace("/addmanual", "", 1).strip()
        if payload.startswith("http"):
            await add_match_manually(normalize_link(payload)); return
        if " - " in payload: parts = [p.strip() for p in payload.split(" - ")]
        elif "|" in payload: parts = [p.strip() for p in payload.split("|")]
        else:
            tmp = [p.strip() for p in payload.split("-")]
            if len(tmp) > 4: parts = [tmp[0], tmp[1], tmp[2], "-".join(tmp[3:]).strip()]
            else: parts = tmp
        if len(parts) < 4:
            send_telegram_message("❌ Formato errato\nUsa: /addmanual Casa - Trasferta - 15.10.2026 20:30 - https://link", auto_delete_sec=AUTO_DELETE_SECONDS); return
        home, away, datetime_raw, link = parts[0], parts[1], parts[2], normalize_link(parts[3])
        formatted_date, formatted_time = format_match_date(datetime_raw)
        if all(day not in formatted_date for day in ITALIAN_DAYS):
            dt = None
            for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%d/%m/%Y %H", "%d/%m/%Y"):
                try: dt = datetime.strptime(datetime_raw, fmt); break
                except: continue
            if dt:
                formatted_date = f"{ITALIAN_DAYS[dt.weekday()]} {dt.day} {ITALIAN_MONTHS[dt.month-1]} {dt.year}"
                formatted_time = dt.strftime("%H:%M")
            else: send_telegram_message(f"❌ Data non valida: {datetime_raw}", auto_delete_sec=AUTO_DELETE_SECONDS); return
        match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {link}"
        data = load_matches()
        if link in data.get("blacklist", []): data["blacklist"].remove(link)
        all_existing = []
        for v in data.get("matches", {}).values(): all_existing.extend(v)
        all_existing.extend(data.get("manual", []))
        if any(get_match_key(m) == link for m in all_existing):
            send_telegram_message(f"⚠️ Già presente:\n{match_str}", auto_delete_sec=AUTO_DELETE_SECONDS); return
        data["manual"].append(match_str); save_matches(data)
        ics_file = create_ics_event(home, away, formatted_date, formatted_time, link, get_sport_emoji(home) == "🤽‍♂️")
        if ics_file:
            try: send_ics_file(ics_file); os.remove(ics_file)
            except: pass
        send_telegram_message(f"⚠️! NUOVA PARTITA MANUALE! ⚠️\n\n{get_sport_emoji(home)} {match_str}", auto_delete_sec=AUTO_DELETE_SECONDS)
    except Exception as e: send_telegram_message(f"❌ Errore /addmanual: {e}", auto_delete_sec=AUTO_DELETE_SECONDS)

async def remove_match_manually(link: str):
    link = normalize_link(link)
    data = load_matches(); found=False; removed_str=None
    for team, matches in list(data.get("matches", {}).items()):
        for m in matches[:]:
            if get_match_key(m)==link: removed_str=m; matches.remove(m); found=True; break
        if found: break
    if not found:
        for m in data.get("manual", [])[:]:
            if get_match_key(m)==link: removed_str=m; data["manual"].remove(m); found=True; break
    if not found:
        send_telegram_message("❌ Partita non trovata.", auto_delete_sec=AUTO_DELETE_SECONDS); return
    if "blacklist" not in data: data["blacklist"]=[]
    if link not in data["blacklist"]: data["blacklist"].append(link)
    save_matches(data); send_telegram_message(f"❌ Partita rimossa:\n\n{removed_str or link}", auto_delete_sec=AUTO_DELETE_SECONDS)

async def read_pending_commands():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=15"
        resp = requests.get(url, timeout=20).json()
        for update in resp.get("result", []):
            if "message" not in update or "text" not in update["message"]: continue
            full_text = update["message"]["text"]
            raw_lines = full_text.splitlines()
            stitched=[]
            i=0
            while i < len(raw_lines):
                line=raw_lines[i].strip()
                if not line: i+=1; continue
                if line.lower().startswith(("/green ","/red ","/purple ","/yellow ","/removematch ","/addmatch ")) and "http" in line.lower():
                    cmd, url_part = line.split(maxsplit=1)
                    full_url=url_part.strip()
                    j=i+1
                    while j < len(raw_lines):
                        nxt=raw_lines[j].strip()
                        if not nxt or nxt.startswith("/"): break
                        if "&" in nxt or "=" in nxt or "season" in nxt or "pid" in nxt or "matchid" in nxt or (len(nxt)<60 and "?" in full_url):
                            full_url+=nxt; j+=1
                        else: break
                    stitched.append(f"{cmd} {normalize_link(full_url)}")
                    i=j
                else:
                    stitched.append(line); i+=1
            for text in stitched:
                low=text.lower()
                if low.startswith("/green "): set_match_status(text.split(maxsplit=1)[1], "green")
                elif low.startswith("/red "): set_match_status(text.split(maxsplit=1)[1], "red")
                elif low.startswith("/purple "): set_match_status(text.split(maxsplit=1)[1], "purple")
                elif low.startswith("/yellow "): set_match_status(text.split(maxsplit=1)[1], "yellow")
                elif text.startswith("/addmanual "): await add_match_manual_custom(text)
                elif text.startswith("/addmatch "): await add_match_manually(text.split(maxsplit=1)[1])
                elif text.startswith("/removematch "): await remove_match_manually(text.split(maxsplit=1)[1])
    except Exception as e: print(f"⚠️ Errore comandi: {e}")

async def main():
    data=load_matches(); stored=data.get("matches", {}); manual_list=data.get("manual", []); blacklist=data.get("blacklist", []); status_map=data.get("status", {})
    updated={}; total_new_matches=0
    for team_name, url in TEAMS.items():
        extracted=await extract_matches(url)
        old_list=stored.get(team_name, [])+manual_list
        new_list=[ms for _,_,_,ms in extracted if get_match_key(ms) not in blacklist]
        for match_str in new_list:
            lines=match_str.split("\n")
            if len(lines)<4: continue
            new_date=lines[0].replace("📅","").strip(); new_time=lines[1].replace("🕒","").strip()
            new_vs=lines[2].replace("➡️","").strip(); new_url=normalize_link(lines[3].replace("🔗","").strip())
            old_match_found=old_date=old_time=None
            for old in old_list:
                o=old.split("\n")
                if len(o)<4: continue
                if o[2].replace("➡️","").strip()==new_vs and normalize_link(o[3].replace("🔗","").strip())==new_url:
                    old_match_found=old; old_date=o[0].replace("📅","").strip(); old_time=o[1].replace("🕒","").strip(); break
            emoji=get_sport_emoji(team_name)
            if old_match_found is None:
                total_new_matches+=1
                send_telegram_message(f"⚠️! NUOVA PARTITA TROVATA! ⚠️\n\n{emoji} Nuova partita: {team_name.upper()}\n{match_str}")
                home, away=new_vs.split(" vs ")
                ics_file=create_ics_event(home, away, new_date, new_time, new_url, emoji=="🤽‍♂️")
                if ics_file: send_ics_file(ics_file); os.remove(ics_file); continue
            if old_date!=new_date or old_time!=new_time:
                total_new_matches+=1
                send_telegram_message(f"⏰! VARIAZIONE! ⏰\n\n{emoji} Squadra: {team_name.upper()}\n{match_str}")
                home, away=new_vs.split(" vs ")
                ics_file=create_ics_event(home, away, new_date, new_time, new_url, emoji=="🤽‍♂️")
                if ics_file: send_ics_file(ics_file); os.remove(ics_file)
        updated[team_name]=new_list
    save_matches({"matches": updated, "manual": manual_list, "blacklist": blacklist, "status": status_map})
    data=load_matches(); all_matches=list(data.get("matches", {}).values())+[data.get("manual", [])]
    all_matches_flat=[m for sublist in all_matches for m in sublist]
    today=datetime.now(); start_day=today.replace(hour=0, minute=0, second=0, microsecond=0); end_day=start_day+timedelta(days=28)
    days_list=[start_day+timedelta(days=i) for i in range(28)]
    matches_by_day={d.date(): [] for d in days_list}
    status_map=data.get("status", {}); blacklist=data.get("blacklist", [])
    for match in all_matches_flat:
        if get_match_key(match) in blacklist: continue
        lines=match.split("\n")
        if len(lines)<4: continue
        dt=parse_italian_formatted_date(lines[0].replace("📅","").strip(), lines[1].replace("🕒","").strip())
        if dt and start_day <= dt < end_day:
            team_name=lines[2].replace("➡️","").strip().split(" vs ")[0].strip()
            matches_by_day[dt.date()].append((dt, team_name, get_sport_emoji(team_name), match))
    def format_italian_date(d): return f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month-1]} {d.year}"
    start_str=format_italian_date(start_day); end_str=format_italian_date(end_day-timedelta(days=1))
    riepilogo=f"📅 *Calendario partite prossimi 28 giorni:*\n\n🌏 Dal *{start_str}* al *{end_str}*\n\n"
    wx_dates, wx_codes, wx_max, wx_min=get_weather_data()
    wx_map={wx_dates[i]: (wx_codes[i], wx_max[i], wx_min[i]) for i in range(len(wx_dates))}
    empty_start=None
    for d in days_list:
        day_key=d.date(); day_label=format_italian_date(d)
        day_matches=sorted(matches_by_day[day_key], key=lambda x: x[0])
        d_str=d.strftime("%Y-%m-%d")
        if d_str in wx_map:
            code, tmax, tmin=wx_map[d_str]
            desc=weather_description(code)
            tavg=round((tmin+tmax)/2)
            meteo_str=f"{desc} / {tavg}°"
        else: meteo_str="☁️ / --°"
        if not day_matches:
            if empty_start is None: empty_start=d; continue
        if empty_start:
            end_empty=d-timedelta(days=1)
            if empty_start==end_empty: riepilogo+=f"───────────────────────────────\n📌 *{format_italian_date(empty_start)}* (Nessuna partita)\n\n"
            else: riepilogo+=f"───────────────────────────────\n📌 *Dal {empty_start.day} al {end_empty.day} {ITALIAN_MONTHS[empty_start.month-1]} {empty_start.year}* (Nessuna partita)\n\n"
            empty_start=None
        riepilogo+=f"───────────────────────────────\n📌 *{day_label}* ({meteo_str})\n\n"
        for _, team_name, emoji, match in day_matches:
            lines=match.split("\n")
            link=normalize_link(lines[3].replace("🔗","").strip())
            status_emoji=get_status_emoji(link, status_map)
            vs_line=lines[2].replace("➡️","").strip()
            riepilogo+=f"{emoji} *{team_name}*\n• {lines[1].replace('🕒','').strip()} — {vs_line} - {status_emoji}\n 🔗 {link}\n\n"
    if empty_start:
        end_empty=end_day-timedelta(days=1)
        if empty_start==end_empty: riepilogo+=f"───────────────────────────────\n📌 *{format_italian_date(empty_start)}* (Nessuna partita)\n\n"
        else: riepilogo+=f"───────────────────────────────\n📌 *Dal {empty_start.day} al {end_empty.day} {ITALIAN_MONTHS[empty_start.month-1]} {empty_start.year}* (Nessuna partita)\n\n"
    timestamp=datetime.now()+timedelta(hours=2)
    riepilogo+="───────────────────────────────\n🔄 Scansione completata\n"
    riepilogo+=f"Nuove partite trovate: {total_new_matches}\n"
    riepilogo+=f"⏰ {timestamp.strftime('%H:%M')} | {timestamp.strftime('%A %d %B')}"
    send_long_message(riepilogo)

if __name__ == "__main__":
    asyncio.run(read_pending_commands())
    asyncio.run(main())

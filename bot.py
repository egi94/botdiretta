import os, json, asyncio, requests, threading, re, time
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
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
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}, timeout=10)
        if r.status_code != 200:
            print(f"❌ Telegram error {r.status_code}: {r.text[:500]} | inizio={text[:120]!r}")
            return None
        msg_id = r.json().get("result", {}).get("message_id")
        if auto_delete_sec and msg_id:
            def _delete():
                try:
                    del_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
                    requests.post(del_url, json={"chat_id": CHAT_ID, "message_id": msg_id}, timeout=10)
                except: pass
            timer = threading.Timer(auto_delete_sec, _delete)
            timer.daemon = True
            timer.start()
        return msg_id
    except Exception as e:
        print(f"❌ Errore send_telegram: {e}")
        return None

def send_long_message(text: str, max_len=3500):
    if len(text) <= max_len:
        send_telegram_message(text)
        return
    blocks = text.split("\n\n")
    chunks = []
    current = ""
    for block in blocks:
        if not block.strip():
            continue
        piece = block + "\n\n"
        if len(piece) > max_len:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            lines = piece.splitlines(True)
            buf = ""
            for ln in lines:
                if len(buf) + len(ln) > max_len:
                    if buf.strip():
                        chunks.append(buf.strip())
                    buf = ln
                else:
                    buf += ln
            if buf.strip():
                chunks.append(buf.strip())
            continue
        if len(current) + len(piece) > max_len:
            chunks.append(current.strip())
            current = piece
        else:
            current += piece
    if current.strip():
        chunks.append(current.strip())
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        labeled = f"({idx}/{total})\n{chunk}" if total > 1 else chunk
        send_telegram_message(labeled)
        time.sleep(0.5)

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f: requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})

# --- SOLO AGGIUNTA FOTO, NON TOCCA LA LOGICA ESISTENTE ---
def send_telegram_photo(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(file_path, "rb") as f:
            r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"photo": f}, timeout=20)
            if r.status_code != 200:
                print(f"❌ Foto error {r.status_code}: {r.text[:500]}")
                return None
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"❌ Errore foto: {e}")
        return None

def create_calendar_image(mode="all", title="TUTTE LE PARTITE"):
    data = load_matches()
    status_map = data.get("status", {})
    blacklist = data.get("blacklist", [])
    all_matches = []
    for v in data.get("matches", {}).values():
        all_matches.extend(v)
    all_matches.extend(data.get("manual", []))
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    matches_by_day = {}
    total = 0
    seen_links = set()
    for m in all_matches:
        link = get_match_key(m)
        if not link or link in blacklist or link in seen_links:
            continue
        seen_links.add(link)
        lines = m.split("\n")
        if len(lines) < 4:
            continue
        dt = parse_italian_formatted_date(lines[0].replace("📅", "").strip(), lines[1].replace("🕒", "").strip())
        if not dt or dt < today or dt >= today + timedelta(days=28):
            continue
        emoji = get_status_emoji(link, status_map)
        if mode == "green" and emoji != "🟢":
            continue
        vs = lines[2].replace("➡️", "").strip()
        time_str = lines[1].replace("🕒", "").strip()
        matches_by_day.setdefault(dt.date(), []).append((time_str, vs, emoji))
        total += 1
    W, H = 1400, 950
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 18)
        font_day = ImageFont.truetype("DejaVuSans-Bold.ttf", 19)
        font_match = ImageFont.truetype("DejaVuSans.ttf", 15)
    except:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_day = font_title
        font_match = font_title
    draw.text((30, 15), title, fill="black", font=font_title)
    draw.text((30, 55), f"Prossimi 28 giorni - {total} partite", fill="#666666", font=font_sub)
    if mode == "all":
        draw.rounded_rectangle([30, 85, 55, 105], radius=5, fill="#22c55e")
        draw.text((65, 83), "Confermata", fill="black", font=font_match)
        draw.rounded_rectangle([210, 85, 235, 105], radius=5, fill="#eab308")
        draw.text((245, 83), "Da confermare", fill="black", font=font_match)
        draw.rounded_rectangle([410, 85, 435, 105], radius=5, fill="#ef4444")
        draw.text((445, 83), "Annullata / No", fill="black", font=font_match)
        draw.rounded_rectangle([610, 85, 635, 105], radius=5, fill="#a855f7")
        draw.text((645, 83), "Da vedere", fill="black", font=font_match)
    else:
        draw.rounded_rectangle([30, 85, 55, 105], radius=5, fill="#22c55e")
        draw.text((65, 83), "Confermata", fill="black", font=font_match)
    start = today
    cell_w = (W - 60) // 7
    cell_h = 175
    top = 125
    headers = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    for col, h in enumerate(headers):
        draw.text((30 + col * cell_w + 10, top), h, fill="#666666", font=font_day)
    top += 32
    colors = {"🟢": "#22c55e", "🟡": "#eab308", "🔴": "#ef4444", "🟣": "#a855f7"}
    for week in range(4):
        for col in range(7):
            day = start + timedelta(days=week * 7 + col)
            x = 30 + col * cell_w
            y = top + week * cell_h
            is_today = day.date() == datetime.now().date()
            draw.rectangle([x, y, x + cell_w - 5, y + cell_h - 5], outline="#4285F4" if is_today else "#DDDDDD", width=2 if is_today else 1, fill="#F8F9FA" if is_today else "white")
            draw.text((x + 8, y + 6), f"{day.day} {ITALIAN_MONTHS[day.month-1][:3]}", fill="black", font=font_day)
            day_matches = sorted(matches_by_day.get(day.date(), []))
            my = y + 34
            for time_str, vs, emoji in day_matches[:4]:
                color = colors.get(emoji, "#eab308")
                text_color = "white" if emoji in ("🟢", "🔴", "🟣") else "black"
                draw.rounded_rectangle([x + 8, my, x + cell_w - 13, my + 26], radius=6, fill=color)
                label = f"{time_str} {vs}"
                if len(label) > 23:
                    label = label[:21] + ".."
                draw.text((x + 14, my + 4), label, fill=text_color, font=font_match)
                my += 32
            if len(day_matches) > 4:
                draw.text((x + 8, my), f"+{len(day_matches)-4} altre...", fill="#666666", font=font_match)
    filename = f"calendario_{mode}.png"
    img.save(filename)
    return filename, total
# --- FINE AGGIUNTA FOTO ---

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

def clear_match_status(inp: str):
    inp_raw = inp.strip()
    is_link = inp_raw.startswith("http")
    data = load_matches()
    if "status" not in data:
        data["status"] = {}
    all_matches = []
    for v in data.get("matches", {}).values():
        all_matches.extend(v)
    all_matches.extend(data.get("manual", []))
    target_link = None
    target_vs = ""
    if is_link:
        nlink = normalize_link(inp_raw)
        for m in all_matches:
            stored = get_match_key(m)
            if not stored:
                continue
            if stored == nlink or nlink in stored or stored in nlink:
                target_link = stored
                target_vs = get_match_vs(m)
                break
            if "pid=" in nlink and "pid=" in stored and nlink.split("pid=")[1].split("&")[0] == stored.split("pid=")[1].split("&")[0]:
                target_link = stored
                target_vs = get_match_vs(m)
                break
        if not target_link:
            target_link = nlink
    else:
        vs_input = normalize_vs(inp_raw)
        for m in all_matches:
            vs = get_match_vs(m)
            if vs and normalize_vs(vs) == vs_input:
                target_link = get_match_key(m)
                target_vs = vs
                break
        if not target_link:
            for m in all_matches:
                vs = get_match_vs(m)
                if vs and vs_input in normalize_vs(vs):
                    target_link = get_match_key(m)
                    target_vs = vs
                    break
    if not target_link:
        send_telegram_message(f"❌ Non trovata: {inp_raw}", auto_delete_sec=AUTO_DELETE_SECONDS)
        return
    for k in list(data["status"].keys()):
        if k == target_link or k == normalize_link(target_link) or k == normalize_link(inp_raw):
            del data["status"][k]
        elif "pid=" in target_link and f"pid={target_link.split('pid=')[1].split('&')[0]}" in k:
            del data["status"][k]
    save_matches(data)
    send_telegram_message(f"✅ Stato rimosso, torna a {DEFAULT_STATUS}\n{target_vs or target_link}", auto_delete_sec=AUTO_DELETE_SECONDS)

def list_matches_by_status(color: str):
    data = load_matches()
    status_map = data.get("status", {})
    wanted_emoji = STATUS_EMOJI.get(color, DEFAULT_STATUS)
    all_matches = []
    for v in data.get("matches", {}).values():
        all_matches.extend(v)
    all_matches.extend(data.get("manual", []))
    def _mid(link: str):
        if "mid=" in link:
            try: return link.split("mid=")[1].split("&")[0]
            except: return ""
        if "pid=" in link:
            try: return "pid:" + link.split("pid=")[1].split("&")[0]
            except: return ""
        return ""
    match_by_mid = {}
    match_by_link = {}
    for m in all_matches:
        link = get_match_key(m)
        if not link:
            continue
        match_by_link[normalize_link(link)] = m
        mid = _mid(link)
        if mid:
            match_by_mid[mid] = m
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    seen_mid = set()
    seen_link = set()
    filtered = []
    for raw_key, emoji in list(status_map.items()):
        if emoji != wanted_emoji:
            continue
        nkey = normalize_link(raw_key)
        mid = _mid(nkey)
        if mid and mid in seen_mid:
            continue
        if nkey in seen_link:
            continue
        if mid:
            seen_mid.add(mid)
        seen_link.add(nkey)
        m = match_by_mid.get(mid) if mid else None
        if not m:
            m = match_by_link.get(nkey)
        if not m:
            continue
        lines = m.split("\n")
        if len(lines) < 4:
            continue
        date_str = lines[0].replace("📅", "").strip()
        time_str = lines[1].replace("🕒", "").strip()
        vs = lines[2].replace("➡️", "").strip()
        link = get_match_key(m)
        dt = parse_italian_formatted_date(date_str, time_str)
        if not dt or dt < today:
            continue
        filtered.append((dt, date_str, time_str, vs, link))
    if color == "yellow":
        for m in all_matches:
            link = get_match_key(m)
            if not link:
                continue
            if get_status_emoji(link, status_map) != wanted_emoji:
                continue
            if normalize_link(link) in seen_link or _mid(link) in seen_mid:
                continue
            lines = m.split("\n")
            if len(lines) < 4:
                continue
            date_str = lines[0].replace("📅", "").strip()
            time_str = lines[1].replace("🕒", "").strip()
            vs = lines[2].replace("➡️", "").strip()
            dt = parse_italian_formatted_date(date_str, time_str)
            if not dt or dt < today:
                continue
            filtered.append((dt, date_str, time_str, vs, link))
    if not filtered:
        send_telegram_message(f"Nessuna partita futura con stato {wanted_emoji} {color.upper()}", auto_delete_sec=AUTO_DELETE_SECONDS)
        return
    filtered.sort(key=lambda x: x[0])
    # --- LOGICA TESTO INVARIATA ---
    if color == "green":
        title = f"✅ PARTITE CONFERMATE: ({len(filtered)})"
    else:
        title = f"{wanted_emoji} Partite {color.upper()} ({len(filtered)}):"
    send_telegram_message(title)
    time.sleep(0.3)
    batch = ""
    count = 0
    total_batches = (len(filtered) + 4) // 5
    batch_idx = 1
    for _, date_str, time_str, vs, link in filtered:
        emoji = get_sport_emoji(vs.split(" vs ")[0] if " vs " in vs else vs)
        batch += f"{emoji} {date_str} - {time_str}\n{vs} - {wanted_emoji}\n🔗 {link}\n\n"
        count += 1
        if count >= 5:
            send_telegram_message(f"({batch_idx}/{total_batches})\n{batch.strip()}")
            batch = ""
            count = 0
            batch_idx += 1
            time.sleep(0.5)
    if batch.strip():
        send_telegram_message(f"({batch_idx}/{total_batches})\n{batch.strip()}")
    # --- AGGIUNTA SOLO FOTO A PARTE, SOLO PER GREEN, NON ALTERA LA LISTA ---
    if color == "green":
        try:
            time.sleep(0.5)
            img_path, total = create_calendar_image(mode="green", title="PARTITE CONFERMATE")
            send_telegram_photo(img_path, caption=f"PARTITE CONFERMATE ({total})")
            if os.path.exists(img_path):
                os.remove(img_path)
        except Exception as e:
            print(f"❌ Errore foto green: {e}")

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

async def mod_match_manual_custom(raw_command: str):
    try:
        payload = raw_command.replace("/modmanual", "", 1).strip()
        payload = payload.replace("\n", " ").replace("\r", " ")
        payload = " ".join(payload.split())
        parts = [p.strip() for p in re.split(r'\s+-\s+', payload) if p.strip()]
        home = away = datetime_raw = None
        new_link = None
        if len(parts) >= 2 and " vs " in parts[0].lower():
            m = re.split(r'\s+vs\s+', parts[0], flags=re.IGNORECASE)
            if len(m) == 2:
                home, away = m[0].strip(), m[1].strip()
                datetime_raw = parts[1] if len(parts) >= 2 else None
                if len(parts) >= 3:
                    new_link = parts[2]
        elif len(parts) >= 3:
            home = parts[0]
            away = parts[1]
            datetime_raw = parts[2]
            if len(parts) >= 4:
                new_link = parts[3]
        else:
            send_telegram_message("❌ Formato errato\nUsa: /modmanual Casa - Trasferta - 07/04/2027 21:00 - https://...\nOppure: /modmanual Casa vs Trasferta - 07/04/2027 21:00 - https://...", auto_delete_sec=AUTO_DELETE_SECONDS); return
        if datetime_raw and "http" in datetime_raw:
            split_http = datetime_raw.split("http")
            datetime_raw = split_http[0].strip().rstrip("-").strip()
            if not new_link:
                new_link = "http" + "http".join(split_http[1:])
        if datetime_raw:
            datetime_raw = datetime_raw.rstrip("-").strip()
        if not home or not away or not datetime_raw:
            send_telegram_message("❌ Formato errato\nUsa: /modmanual Casa - Trasferta - 07/04/2027 21:00 - https://...", auto_delete_sec=AUTO_DELETE_SECONDS); return
        new_link = normalize_link(new_link) if new_link else None
        vs_search = normalize_vs(f"{home} vs {away}")
        data = load_matches()
        manual_list = data.get("manual", [])
        found_idx = -1
        old_match_str = None
        for idx, m in enumerate(manual_list):
            vs = get_match_vs(m)
            if not vs: continue
            if normalize_vs(vs) == vs_search:
                found_idx = idx; old_match_str = m; break
        if found_idx == -1:
            for idx, m in enumerate(manual_list):
                vs = get_match_vs(m)
                if vs_search in normalize_vs(vs):
                    found_idx = idx; old_match_str = m; break
        if found_idx == -1:
            send_telegram_message(f"❌ Partita manuale non trovata: {home} vs {away}", auto_delete_sec=AUTO_DELETE_SECONDS); return
        lines = old_match_str.split("\n")
        old_date_str = lines[0].replace("📅","").strip() if len(lines)>0 else ""
        old_time_str = lines[1].replace("🕒","").strip() if len(lines)>1 else ""
        old_link = get_match_key(old_match_str)
        formatted_date, formatted_time = format_match_date(datetime_raw)
        if all(day not in formatted_date for day in ITALIAN_DAYS):
            dt = None
            for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%d/%m/%Y %H", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
                try: dt = datetime.strptime(datetime_raw, fmt); break
                except: continue
            if dt:
                formatted_date = f"{ITALIAN_DAYS[dt.weekday()]} {dt.day} {ITALIAN_MONTHS[dt.month-1]} {dt.year}"
                formatted_time = dt.strftime("%H:%M")
            else:
                send_telegram_message(f"❌ Data non valida: {datetime_raw}", auto_delete_sec=AUTO_DELETE_SECONDS); return
        final_link = new_link if new_link else old_link
        new_match_str = f"📅 {formatted_date}\n🕒 {formatted_time}\n➡️ {home} vs {away}\n🔗 {final_link}"
        manual_list[found_idx] = new_match_str
        data["manual"] = manual_list
        if final_link!= old_link:
            if old_link in data.get("status", {}):
                data["status"][final_link] = data["status"][old_link]
            data["status"][normalize_link(final_link)] = data.get("status", {}).get(old_link, data.get("status", {}).get(normalize_link(old_link), DEFAULT_STATUS))
            if old_link in data.get("blacklist", []):
                data["blacklist"].remove(old_link)
        save_matches(data)
        ics_file = create_ics_event(home, away, formatted_date, formatted_time, final_link, get_sport_emoji(home) == "🤽‍♂️")
        if ics_file:
            try: send_ics_file(ics_file); os.remove(ics_file)
            except: pass
        emoji = get_sport_emoji(home)
        msg = f"⏰! VARIAZIONE! ⏰\n\n{emoji} Squadra: {home.upper()}\nVecchio: {old_date_str} {old_time_str}\nNuovo: {formatted_date} {formatted_time}\n➡️ {home} vs {away}\n🔗 {final_link}"
        send_telegram_message(msg)
    except Exception as e:
        send_telegram_message(f"❌ Errore /modmanual: {e}", auto_delete_sec=AUTO_DELETE_SECONDS)

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
                low_line = line.lower()
                if low_line.startswith(("/green ","/red ","/purple ","/yellow ","/clearstatus ","/nogreen ","/removematch ","/addmatch ","/addmanual ","/modmanual ")):
                    full_cmd = line
                    if "http" not in low_line and i+1 < len(raw_lines) and "http" in raw_lines[i+1].lower():
                        full_cmd = line + " " + raw_lines[i+1].strip()
                        i+=1
                    j=i+1
                    while j < len(raw_lines):
                        nxt=raw_lines[j].strip()
                        if not nxt or nxt.startswith("/"): break
                        if "&" in nxt or "pid=" in nxt or "season=" in nxt or "match_id=" in nxt or "=" in nxt:
                            if "http" not in nxt.lower():
                                full_cmd += nxt
                                j+=1
                            else:
                                break
                        else:
                            break
                    stitched.append(full_cmd.strip())
                    i=j
                else:
                    if "http" in low_line and stitched and stitched[-1].lower().startswith(("/modmanual","/addmanual")) and "http" not in stitched[-1].lower():
                        stitched[-1] = stitched[-1] + " " + line.strip()
                    else:
                        stitched.append(line)
                    i+=1
            for text in stitched:
                low=text.lower()
                if low == "/allgreen" or low.startswith("/allgreen "): list_matches_by_status("green")
                elif low == "/allyellow" or low.startswith("/allyellow "): list_matches_by_status("yellow")
                elif low == "/allred" or low.startswith("/allred "): list_matches_by_status("red")
                elif low == "/allpurple" or low.startswith("/allpurple "): list_matches_by_status("purple")
                elif low == "/calendario" or low == "/cal":
                    try:
                        img_all, tot_all = create_calendar_image(mode="all", title="TUTTE LE PARTITE")
                        send_telegram_photo(img_all, caption=f"TUTTE LE PARTITE ({tot_all})")
                        if os.path.exists(img_all): os.remove(img_all)
                        time.sleep(0.5)
                        img_green, tot_green = create_calendar_image(mode="green", title="PARTITE CONFERMATE")
                        send_telegram_photo(img_green, caption=f"PARTITE CONFERMATE ({tot_green})")
                        if os.path.exists(img_green): os.remove(img_green)
                    except Exception as e:
                        send_telegram_message(f"❌ Errore calendario: {e}")
                elif low.startswith("/green "): set_match_status(text.split(maxsplit=1)[1], "green")
                elif low.startswith("/red "): set_match_status(text.split(maxsplit=1)[1], "red")
                elif low.startswith("/purple "): set_match_status(text.split(maxsplit=1)[1], "purple")
                elif low.startswith("/yellow "): set_match_status(text.split(maxsplit=1)[1], "yellow")
                elif low.startswith("/clearstatus "): clear_match_status(text.split(maxsplit=1)[1])
                elif low.startswith("/nogreen "): clear_match_status(text.split(maxsplit=1)[1])
                elif text.startswith("/addmanual "): await add_match_manual_custom(text)
                elif text.startswith("/modmanual "): await mod_match_manual_custom(text)
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
    riepilogo = riepilogo.replace("*", "")
    # LOGICA TESTO INVARIATA
    send_long_message(riepilogo)
    # --- AGGIUNTA SOLO FOTO A PARTE, DOPO IL TESTO ---
    try:
        time.sleep(0.5)
        img_all, tot_all = create_calendar_image(mode="all", title="TUTTE LE PARTITE")
        send_telegram_photo(img_all, caption=f"TUTTE LE PARTITE ({tot_all})")
        if os.path.exists(img_all): os.remove(img_all)
        time.sleep(0.5)
        img_green, tot_green = create_calendar_image(mode="green", title="PARTITE CONFERMATE")
        send_telegram_photo(img_green, caption=f"PARTITE CONFERMATE ({tot_green})")
        if os.path.exists(img_green): os.remove(img_green)
    except Exception as e:
        print(f"❌ Errore foto calendario: {e}")

if __name__ == "__main__":
    asyncio.run(read_pending_commands())
    asyncio.run(main())

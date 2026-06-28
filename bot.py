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

def extract_time_from_match(match: str):
    lines = match.split("\n")
    for line in lines:
        if line.startswith("🕒"):
            time_str = line.replace("🕒", "").strip()
            try:
                return datetime.strptime(time_str, "%H:%M").time()
            except:
                return datetime.strptime("00:00", "%H:%M").time()
    return datetime.strptime("00:00", "%H:%M").time()

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

# 🔘 Bottone Telegram "LIVESCORE"
def send_telegram_message_with_button(text: str, url: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN o CHAT_ID mancanti, salto Telegram")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "LIVESCORE",
                        "url": url
                    }
                ]
            ]
        }
    }

    try:
        requests.post(api_url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Errore Telegram: {e}")

# 🔧 Messaggi SENZA bottone (per riepilogo 28 giorni)
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

def send_ics_file(file_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(
            url,
            data={"chat_id": CHAT_ID},
            files={"document": f}
        )

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

def parse_italian_formatted_date(date_str: str, time_str: str) -> datetime | None:
    try:
        parts = date_str.split()
        if len(parts) < 4:
            return None
        day = int(parts[1])
        month_name = parts[2]
        year = int(parts[3])
        if month_name not in ITALIAN_MONTHS:
            return None
        month = ITALIAN_MONTHS.index(month_name) + 1
        dt = datetime.strptime(time_str, "%H:%M")
        return datetime(year, month, day, dt.hour, dt.minute)
    except Exception:
        return None

# 🔥 ICS EVENTO + durata 2 ore + alert 30 min
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
        await page.wait_for_timeout(2000)

        team_official_name = await page.inner_text("div.heading__name")
        team_official_name = team_official_name.strip()
        team_official_norm = normalize(team_official_name)
        print(f"🏷️ Nome ufficiale squadra: {team_official_name}")

        blocks = await page.query_selector_all("div[data-testid='wcl-MatchRow']")
        if len(blocks) == 0:
            blocks = await page.query_selector_all("div.event__match")

        print(f"➡️ Trovati {len(blocks)} blocchi partita")

        matches = []

        for block in blocks:

            time_el = await block.query_selector("div.event__time")
            time_text = (await time_el.inner_text()).strip() if time_el else "N/D"

            home_el = await block.query_selector(
                "div.event__homeParticipant span, div.event__homeParticipant"
            )
            home = (await home_el.inner_text()).strip() if home_el else ""

            away_el = await block.query_selector(
                "div.event__awayParticipant span, div.event__awayParticipant"
            )
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
                    f"⚠️ ! NUOVA PARTITA TROVATA ! ⚠️\n\n"
                    f"{emoji} Nuova partita: {clean_name}\n"
                    f"{match_str}",
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

                date_msg = (
                    f"La vecchia data era {old_date} mentre la NUOVA DATA è {new_date}!"
                    if date_changed else
                    f"La vecchia data era {old_date} mentre la NUOVA DATA è {new_date}! – NON VARIATA! –"
                )

                time_msg = (
                    f"Il vecchio orario era {old_time} mentre il NUOVO ORARIO è {new_time}!"
                    if time_changed else
                    f"Il vecchio orario era {old_time} mentre il NUOVO ORARIO è {new_time}! – NON VARIATA! –"
                )

                send_telegram_message_with_button(
                    f"⏰ ! VARIAZIONE ORARIO/DATA - Nuovo orario/data! ⏰\n\n"
                    f"{emoji} Squadra: {clean_name}\n"
                    f"{match_str}\n\n"
                    f"{time_msg}\n"
                    f"{date_msg}",
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
    print("✅ Fine esecuzione bot")

    # === CALENDARIO 28 GIORNI ===
    stored = load_matches()
    today = datetime.now()
    start_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = start_day + timedelta(days=28)

    days_list = []
    for i in range(28):
        days_list.append(start_day + timedelta(days=i))

    matches_by_day = {d.date(): [] for d in days_list}

    for team_name, matches in stored.items():
        emoji = get_sport_emoji(team_name)
        for match in matches:
            lines = match.split("\n")
            if len(lines) < 3:
                continue
            raw_date = lines[0].replace("📅", "").strip()
            raw_time = lines[1].replace("🕒", "").strip()

            dt = parse_italian_formatted_date(raw_date, raw_time)
            if dt is None:
                continue

            if start_day <= dt < end_day:
                matches_by_day[dt.date()].append((dt, team_name, emoji, match))

    def format_italian_date(d: datetime) -> str:
        day_name = ITALIAN_DAYS[d.weekday()]
        month_name = ITALIAN_MONTHS[d.month - 1]
        return f"{day_name} {d.day} {month_name} {d.year}"

    start_str = format_italian_date(start_day)
    end_str = format_italian_date(end_day - timedelta(days=1))

    riepilogo = "📅 *Calendario partite prossimi 28 giorni:*\n\n"
    riepilogo += f"🌏 Dal *{start_str}* al *{end_str}*\n\n"

    for d in days_list:
        day_key = d.date()
        day_label = format_italian_date(d)

        riepilogo += "───────────────────────────────\n"
        riepilogo += f"📌 *{day_label}*\n"

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
    ora = timestamp_ita.strftime("%H:%M")
    giorno = timestamp_ita.strftime("%A %d %B")

    riepilogo += "───────────────────────────────\n"
    riepilogo += f"🔄 Scansione completata\n"
    riepilogo += f"Nuove partite trovate: {total_new_matches}\n"
    riepilogo += f"⏰ {ora} | {giorno}"

    send_telegram_message(riepilogo)

# ============================================================
# === ANALISI AI PARTITE RAGGIUNGIBILI (NUOVO MODULO) ========
# ============================================================

# --- Coordinate utente ---
USER_LAT = 44.39303075403038
USER_LON = 8.962905825758472

# --- Coordinate squadre ---
TEAM_LOCATIONS = {
    "VADO CALCIO": (44.27750019543724, 8.434573095857038),
    "SPEZIA CALCIO": (44.102188533549985, 9.809017097128153),
    "SPEZIA PRIMAVERA U19": (44.11635788106785, 9.86740059261646),
    "GENOA FEMMINILE": (44.44445702012944, 8.968750164657989),
    "GENOA (PRIMA SQUADRA)": (44.41643821659689, 8.952003985325629),
    "GENOA (PRIMAVERA)": (44.44445702012944, 8.968750164657989),
    "SAMPDORIA (PRIMA SQUADRA)": (44.41643821659689, 8.952003985325629),
    "SAMPDORIA (PRIMAVERA)": (44.38440095379068, 9.072554472976261),
    "CELLE VARAZZE": (44.34970752025405, 8.5587065547737),
    "IMPERIA": (43.897959244921864, 8.037843706064809),
    "SESTRI LEVANTE": (44.27261680914362, 9.415918232239386),
    "LIGORNA": (44.4478309622853, 8.996516676929202),
    "DERTHONA BASKET": (44.88929896165569, 8.836979631696888),
    "SC QUINTO": (44.39551820865677, 8.9685691473088),
    "BOGLIASCO FEMMINILE": (44.38122317522422, 9.068039004191519),
    "CDM FUTSAL GENOVA": (44.54049475547218, 8.696089688404),
    "RAPALLO PALLANUOTO FEMMINILE": (44.35794525142657, 9.212322172246232),
    "RN SAVONA PALLANUOTO": (44.3017474009747, 8.478087237655537),
    "ALESSANDRIA CALCIO": (44.920216077761985, 8.616514303298658),
    "JUVENTUS U23": (44.920216077761985, 8.616514303298658)
}

# --- Pro Recco: impianti multipli ---
PRO_RECCO_LOCATIONS = {
    "SCIORBA": (44.44445702012944, 8.968750164657989),
    "SANT_ANNA": (44.3740671881692, 9.105355615969316),
    "SORI": (44.360555880119996, 9.139530848483208)
}

PRO_RECCO_WEIGHTS = {
    "SCIORBA": 1.0,
    "SANT_ANNA": 1.2,
    "SORI": 1.3
}

# --- Formula Haversine ---
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

# --- Percorsi ---
def percorso_senza_pedaggi(dist_km):
    tempo_min = dist_km / 55 * 60
    return dist_km, tempo_min, 0.0

def percorso_autostrada(dist_km):
    tempo_min = dist_km / 95 * 60
    costo = dist_km * 0.09
    return dist_km, tempo_min, costo

# --- Scelta impianto Pro Recco ---
def choose_pro_recco_location():
    best_loc = None
    best_score = float("inf")

    for name, (lat, lon) in PRO_RECCO_LOCATIONS.items():
        dist = haversine(USER_LAT, USER_LON, lat, lon)
        score = dist * PRO_RECCO_WEIGHTS[name]
        if score < best_score:
            best_score = score
            best_loc = (name, lat, lon, dist)

    return best_loc  # (nome, lat, lon, distanza)

# --- Analisi AI ---
def run_ai_analysis(matches_by_day):
    today = datetime.now().date()
    today_matches = matches_by_day.get(today, [])

    if not today_matches:
        send_telegram_message("📊 *Analisi AI partite raggiungibili*\n\nOggi non ci sono partite.")
        return

    msg = "📊 *Analisi AI partite raggiungibili (oggi)*\n\n"

    # Impianto Pro Recco scelto
    pro_recco_choice = choose_pro_recco_location()
    if pro_recco_choice:
        name, lat, lon, dist = pro_recco_choice
        msg += f"🏊 *Pro Recco impianto stimato:* {name} ({dist:.1f} km)\n\n"

    # Analisi singole partite
    for dt, team_name, emoji, match in today_matches:
        lines = match.split("\n")
        time = lines[1].replace("🕒", "").strip()
        vs = lines[2].replace("➡️", "").strip()

        # Coordinate squadra
        if team_name == "PRO RECCO":
            lat, lon = pro_recco_choice[1], pro_recco_choice[2]
        else:
            lat, lon = TEAM_LOCATIONS.get(team_name, (None, None))

        if lat is None:
            continue

        dist = haversine(USER_LAT, USER_LON, lat, lon)

        # Percorsi
        dist_norm, t_norm, cost_norm = percorso_senza_pedaggi(dist)
        dist_auto, t_auto, cost_auto = percorso_autostrada(dist)

        msg += f"{emoji} *{team_name}* — {time}\n"
        msg += f"Distanza: {dist:.1f} km\n"
        msg += f"• Strada normale: {dist_norm:.1f} km — {t_norm:.0f} min — €{cost_norm:.2f}\n"
        msg += f"• Autostrada: {dist_auto:.1f} km — {t_auto:.0f} min — €{cost_auto:.2f}\n\n"

    send_telegram_message(msg)

# === CHIAMATA ANALISI AI ===
run_ai_analysis(matches_by_day)

if __name__ == "__main__":
    asyncio.run(main())

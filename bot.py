import os
import json
import asyncio
from playwright.async_api import async_playwright

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEAMS = json.loads(os.getenv("TEAMS", "{}"))

MATCHES_FILE = "matches.json"


# ==========================
# TELEGRAM
# ==========================

def send_telegram_message(text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    r = requests.post(url, json=payload)
    print(f"📨 Telegram: {r.text}")


# ==========================
# MATCHES STORAGE
# ==========================

def load_matches():
    if not os.path.exists(MATCHES_FILE):
        print("⚠️ matches.json non trovato, creato nuovo file.")
        return {}
    try:
        with open(MATCHES_FILE, "r") as f:
            return json.load(f)
    except:
        print("❌ Errore lettura matches.json, ricreo file.")
        return {}


def save_matches(data):
    with open(MATCHES_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("💾 matches.json aggiornato")


# ==========================
# PLAYWRIGHT SCRAPER ANTI‑BOT
# ==========================

async def extract_matches(url):
    print(f"🔎 Carico pagina: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-infobars",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="it-IT"
        )

        page = await context.new_page()

        await page.goto(url, timeout=60000, wait_until="networkidle")

        # Aspetta che Diretta.it renderizzi le partite
        try:
            await page.wait_for_selector("div.event_match", timeout=30000)
        except:
            print("⚠️ Nessun event_match trovato (possibile blocco anti‑bot)")
            await browser.close()
            return []

        blocks = await page.query_selector_all("div.event_match")
        print(f"➡️ Trovati {len(blocks)} blocchi event_match")

        matches = []

        for block in blocks:
            time_el = await block.query_selector("div.event_match--time")
            teams_el = await block.query_selector_all("div.event_match--participant")

            if not teams_el or len(teams_el) < 2:
                continue

            time_text = await time_el.inner_text() if time_el else "N/D"
            home = await teams_el[0].inner_text()
            away = await teams_el[1].inner_text()

            matches.append(f"{time_text} - {home} vs {away}")

        await browser.close()
        print(f"✅ Partite estratte: {len(matches)}")
        return matches


# ==========================
# MAIN
# ==========================

async def main():
    print("🚀 Avvio bot Diretta.it (Playwright Anti‑Bot)\n")

    stored = load_matches()
    updated = {}

    for team_name, url in TEAMS.items():
        print("\n==============================")
        print(f"👀 Squadra: {team_name}")

        new_list = await extract_matches(url)
        old_list = stored.get(team_name, [])

        print(f"📊 Vecchie partite: {len(old_list)}")

        new_matches = [m for m in new_list if m not in old_list]
        print(f"📊 Nuove partite trovate: {len(new_matches)}")

        for match in new_matches:
            send_telegram_message(f"📅 Nuova partita per {team_name}:\n{match}")

        updated[team_name] = new_list

    save_matches(updated)
    print("✅ Fine esecuzione bot")


if __name__ == "__main__":
    asyncio.run(main())

import os
import json
import time
import base64
import threading
import streamlit as st
from curl_cffi import requests
from PIL import Image

CONFIG_FILE = "config.json"
SEEN_CACHE_FILE = "seen_offers.json"
LOGO_PATH = "logo3.svg"
README_PDF_PATH = "readme.pdf"

SORT_OPTIONS = {
    "Najnowsze": "created_at:desc",
    "Najtańsze": "filter_float_price:asc",
    "Najdroższe": "filter_float_price:desc"
}
SORT_REVERSE = {v: k for k, v in SORT_OPTIONS.items()}

# --- ZARZĄDZANIE KONFIGURACJĄ ---

def load_config():
    default_config = {"webhook_url": "", "interval": 180, "searches": []}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_config
    return default_config

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)

# --- WYSYŁANIE DISCORD ---

def send_discord(session, webhook_url, title, price, url, location, has_delivery=False, photo_url=None):
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return

    deliv_tag = "📦 **Przesyłka OLX (Kup teraz): Dostępna**\n" if has_delivery else ""
    embed = {
        "title": f"🎯 {title}",
        "url": url,
        "color": 3066993 if has_delivery else 2067276,
        "description": deliv_tag,
        "fields": [
            {"name": "💰 Cena", "value": f"**{price} zł**", "inline": True},
            {"name": "📍 Lokalizacja", "value": location, "inline": True}
        ],
        "footer": {"text": "Snajper OLX Streamlit"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    if photo_url:
        embed["thumbnail"] = {"url": photo_url}

    payload = {
        "username": "Snajper Okazji",
        "avatar_url": "https://static.olx.pl/static/olxpl/naspersclassifieds-regional/olxpl-web/static/img/meta/favicon.ico",
        "embeds": [embed]
    }
    try:
        session.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Błąd wysyłania do Discorda: {e}")

# --- PĘTLA BOTA W TLE ---

def run_bot_loop(stop_event):
    session = requests.Session(impersonate="chrome124")
    seen_ids = set()

    if os.path.exists(SEEN_CACHE_FILE):
        try:
            with open(SEEN_CACHE_FILE, "r", encoding="utf-8") as f:
                seen_ids = set(json.load(f))
        except Exception:
            pass

    while not stop_event.is_set():
        config = load_config()
        webhook_url = config.get("webhook_url", "").strip()
        searches = list(config.get("searches", []))
        interval = config.get("interval", 180)

        for s in searches:
            if stop_event.is_set():
                break

            deliv_filter = s.get("only_delivery", False)
            params = {
                "query": s["query"],
                "sort_by": s.get("sort_by", "created_at:desc"),
                "limit": s.get("limit", 15)
            }
            if s.get("price_min"):
                params["filter_float_price:from"] = s["price_min"]
            if s.get("price_max"):
                params["filter_float_price:to"] = s["price_max"]

            try:
                res = session.get(
                    "https://www.olx.pl/api/v1/offers/",
                    params=params,
                    headers={"Accept": "*/*", "Referer": "https://www.olx.pl/"},
                    timeout=15
                )
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    for item in data:
                        item_id = str(item.get("id"))
                        if item_id in seen_ids:
                            continue

                        delivery_info = item.get("delivery", {})
                        has_delivery = (
                            delivery_info.get("rock", {}).get("active", False) 
                            or delivery_info.get("active", False)
                        )

                        if deliv_filter and not has_delivery:
                            continue

                        seen_ids.add(item_id)
                        title = item.get("title")
                        url = item.get("url")
                        price = "Brak ceny"
                        for param in item.get("params", []):
                            if param.get("key") == "price":
                                price = param.get("value", {}).get("value", "Nie podano")

                        city = item.get("location", {}).get("city", {}).get("name", "Polska")
                        photos = item.get("photos", [])
                        photo_url = photos[0].get("link", "").replace("{width}", "400").replace("{height}", "300") if photos else None

                        send_discord(session, webhook_url, title, price, url, city, has_delivery, photo_url)
                        time.sleep(1)
            except Exception as e:
                print(f"Błąd pobierania ofert z OLX: {e}")

            time.sleep(3)

        try:
            with open(SEEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(list(seen_ids)[-1000:], f)
        except Exception:
            pass

        for _ in range(int(interval)):
            if stop_event.is_set():
                break
            time.sleep(1)

# --- INTERFEJS STREAMLIT ---

st.set_page_config(page_title="Snajper Okazji OLX", page_icon="🎯", layout="wide")

# Usunięcie zbędnego górnego odstępu w panelu bocznym
st.markdown(
    """
    <style>
    div[data-testid="stSidebarContent"] {
        padding-top: 1rem;
    }
    div[data-testid="stSidebarContent"] > div:first-child {
        padding-top: 0rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

if "bot_thread" not in st.session_state:
    st.session_state["bot_thread"] = None
if "stop_event" not in st.session_state:
    st.session_state["stop_event"] = None

config = load_config()

# --- PANEL BOCZNY (data-testid="stSidebarContent") ---
with st.sidebar:
    # 1. Logo na samej górze panelu bocznego (klikalne, prowadzi do http://fabryka.tech/)
    if os.path.exists(LOGO_PATH):
        try:
            with open(LOGO_PATH, "rb") as f:
                svg_base64 = base64.b64encode(f.read()).decode("utf-8")
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 1rem;">
                    <a href="http://fabryka.tech/" target="_blank" rel="noopener noreferrer">
                        <img src="data:image/svg+xml;base64,{svg_base64}" style="max-width: 100%; height: auto;" alt="Logo" />
                    </a>
                </div>
                """,
                unsafe_allow_html=True
            )
        except Exception as e:
            st.warning(f"Nie udało się wczytać logo: {e}")

    # 2. Ustawienia bota
    st.header("⚙️ Ustawienia bota")
    webhook_url = st.text_input("Webhook Discord URL", value=config.get("webhook_url", ""), type="password")
    interval = st.number_input(
        "Interwał sprawdzania (sekundy)", 
        min_value=10, 
        max_value=3600, 
        value=int(config.get("interval", 180)), 
        step=10
    )

    if st.button("💾 Zapisz konfigurację"):
        config["webhook_url"] = webhook_url.strip()
        config["interval"] = int(interval)
        save_config(config)
        st.success("Zapisano ustawienia!")

    st.markdown("---")
    st.header("🎮 Sterowanie")
    is_running = st.session_state["bot_thread"] is not None and st.session_state["bot_thread"].is_alive()

    if not is_running:
        if st.button("▶ START BOT", type="primary", use_container_width=True):
            if not webhook_url.startswith("https://discord.com/api/webhooks/"):
                st.error("Podaj poprawny URL Webhooka Discord!")
            elif not config.get("searches"):
                st.warning("Dodaj najpierw przynajmniej jedną frazę.")
            else:
                config["webhook_url"] = webhook_url.strip()
                config["interval"] = int(interval)
                save_config(config)

                stop_event = threading.Event()
                thread = threading.Thread(target=run_bot_loop, args=(stop_event,), daemon=True)
                thread.start()

                st.session_state["bot_thread"] = thread
                st.session_state["stop_event"] = stop_event
                st.rerun()
    else:
        st.success("🟢 Bot jest aktywny i skanuje...")
        if st.button("⏹ STOP BOT", use_container_width=True):
            if st.session_state["stop_event"]:
                st.session_state["stop_event"].set()
            st.session_state["bot_thread"] = None
            st.session_state["stop_event"] = None
            st.rerun()

    # Dokumentacja pod przyciskami bota
    st.markdown("---")
    st.subheader("📄 Dokumentacja")
    if os.path.exists(README_PDF_PATH):
        with open(README_PDF_PATH, "rb") as pdf_file:
            st.download_button(
                label="📥 Pobierz instrukcję (readme.pdf)",
                data=pdf_file.read(),
                file_name="readme.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    else:
        st.caption("ℹ️ Umieść plik `readme.pdf` w katalogu programu, aby udostępnić go do pobrania.")

    st.markdown("Masz opinie, uwagi, komentarze?")
    st.link_button("Formularz Kontaktowy", "https://fabryka.tech/kontakt", use_container_width=True)

# --- GŁÓWNY WIDOK: 2 KOLUMNY ---
col1, col2 = st.columns([1, 1], gap="large")

# === LEWA KOLUMNA ===
with col1:
    st.title("🎯 Snajper Okazji OLX")

    # Krótka instrukcja obsługi
    with st.expander("💡 Szybka instrukcja obsługi", expanded=False):
        st.markdown("""
        - **1. Webhook**: Wklej link webhooka z Discorda w panelu po lewej i zapisz.
        - **2. Dodaj frazę**: Wpisz szukany przedmiot, widełki cenowe oraz zaznacz, czy interesuje Cię tylko wysyłka OLX.
        - **3. Uruchomienie**: Kliknij **▶ START BOT** w panelu po lewej.
        - **4. Powiadomienia**: Nowe ogłoszenia będą natychmiast wysyłane na Twój kanał Discord.
        """)

    # Formularz dodawania frazy
    st.subheader("➕ Dodaj wyszukiwanie")
    with st.form("add_search_form", clear_on_submit=True):
        query = st.text_input("Szukana fraza *", placeholder="np. RTX 4070, iPhone 13")
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            price_min = st.number_input("Cena min (zł)", min_value=0, value=0, step=10)
        with f_col2:
            price_max = st.number_input("Cena max (zł)", min_value=0, value=0, step=10, help="0 = brak limitu")

        s_col1, s_col2 = st.columns(2)
        with s_col1:
            sort_label = st.selectbox("Sortowanie", list(SORT_OPTIONS.keys()))
        with s_col2:
            limit = st.number_input("Limit ofert", min_value=5, max_value=50, value=15, step=5)

        only_delivery = st.checkbox("Tylko Przesyłka OLX (Kup teraz)", value=True)
        submitted = st.form_submit_button("Dodaj do listy", use_container_width=True)

        if submitted:
            if not query.strip():
                st.error("Fraza wyszukiwania nie może być pusta!")
            else:
                new_item = {
                    "query": query.strip(),
                    "price_min": int(price_min) if price_min > 0 else 0,
                    "price_max": int(price_max) if price_max > 0 else None,
                    "sort_by": SORT_OPTIONS[sort_label],
                    "limit": int(limit),
                    "only_delivery": only_delivery
                }
                config.setdefault("searches", []).append(new_item)
                save_config(config)
                st.success(f"Dodano wyszukiwanie: {query}")
                st.rerun()

# === PRAWA KOLUMNA ===
with col2:
    st.subheader("📋 Monitorowane frazy")
    searches = config.get("searches", [])
    if not searches:
        st.info("Brak aktywnych zapytań. Dodaj pierwsze z formularza po lewej stronie.")
    else:
        for idx, item in enumerate(searches):
            with st.container(border=True):
                c_title, c_del = st.columns([4, 1])
                with c_title:
                    p_min = f"{item.get('price_min', 0)} zł"
                    p_max = f"{item.get('price_max')} zł" if item.get('price_max') else "brak limitu"
                    sort_name = SORT_REVERSE.get(item.get("sort_by"), "Najnowsze")
                    deliv_str = "📦 Przesyłka OLX" if item.get("only_delivery") else "Wszystkie oferty"

                    st.markdown(f"**{item['query']}**")
                    st.caption(f"Cena: {p_min} – {p_max} | Sort: {sort_name} | Limit: {item.get('limit', 15)} | {deliv_str}")
                with c_del:
                    if st.button("Usuń", key=f"del_{idx}"):
                        config["searches"].pop(idx)
                        save_config(config)
                        st.rerun()

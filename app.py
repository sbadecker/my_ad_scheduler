import json
import os
import requests
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# -------------------------------------------------------
# Optional: Lade Umgebungsvariablen aus .env (wenn du python-dotenv benutzt)
# -------------------------------------------------------
# from dotenv import load_dotenv
# load_dotenv()

app = Flask(__name__)
app.secret_key = "SUPER_GEHEIM"  # Nur für Demo!

# Lies Username/Passwort aus den Env Vars, fallback auf Hardcoded
VALID_USERNAME = os.environ.get("AD_SCHEDULER_USERNAME", "admin")
VALID_PASSWORD = os.environ.get("AD_SCHEDULER_PASSWORD", "secret")

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('REFRESH_TOKEN')
PROFILE_ID = "1116786572588577"
BASE_URL = "https://advertising-api-eu.amazon.com"

BASE_DIR = os.path.dirname(__file__)
SCHEDULE_FILE = os.path.join(BASE_DIR, "schedule.json")


def get_access_token():
    url = "https://api.amazon.co.uk/auth/o2/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
    }
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': REFRESH_TOKEN,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    response = requests.post(url, headers=headers, data=payload)
    if response.status_code == 200:
        return response.json()['access_token']
    else:
        raise Exception("Failed to get access token")

def load_campaigns(access_token):
    url = f"{BASE_URL}/sp/campaigns/list"
    headers = {
        "Amazon-Advertising-API-ClientId": CLIENT_ID,
        "Authorization": f"Bearer {access_token}",
        'Amazon-Advertising-API-Scope': PROFILE_ID,
        "Accept": "application/vnd.spCampaign.v3+json",
        "Content-Type": "application/vnd.spCampaign.v3+json",
    }
    payload = {
        "stateFilter": {
            "include": ["ENABLED", "PAUSED"]
        }
    }
    # response = requests.get(url, headers=headers)
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["campaigns"]
    else:
        print(f"Failed to fetch campaigns: {response.json()}")
        return []

def set_campaign_status_batch(access_token, new_state, campaign_ids):
    url = f"{BASE_URL}/sp/campaigns"
    headers = {
        "Amazon-Advertising-API-ClientId": CLIENT_ID,
        "Authorization": f"Bearer {access_token}",
        'Amazon-Advertising-API-Scope': PROFILE_ID,
        "Accept": "application/vnd.spCampaign.v3+json",
        "Content-Type": "application/vnd.spCampaign.v3+json",
    }
    new_state = new_state.upper()
    payload = {
        "campaigns": [{
            "state": new_state,
            "campaignId": campaign_id
        } for campaign_id in campaign_ids]
    }
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code == 207:
        print(f"Successfully updated campaign state to '{new_state}' for {len(campaign_ids)} campaigns.")
    else:
        print(f"Failed to update campaign state to '{new_state}': {response.json()}")

# -------------------------------------------------------
# Hilfsfunktionen für Schedule
# -------------------------------------------------------
def load_schedule():
    """Lädt den EINEN Zeitplan aus JSON."""
    if not os.path.exists(SCHEDULE_FILE):
        return {
            "mon": [], "tue": [], "wed": [],
            "thu": [], "fri": [], "sat": [], "sun": []
        }
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schedule(schedule_dict):
    """Speichert den EINEN Zeitplan in eine JSON-Datei."""
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule_dict, f, indent=2)

# -------------------------------------------------------
# Flask-Routen
# -------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == VALID_USERNAME and password == VALID_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return "Falsche Login-Daten!"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    # Check Login
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    schedule = load_schedule()
    return render_template("index.html", schedule=schedule)

@app.route("/edit", methods=["GET", "POST"])
def edit_schedule():
    """Route zum Hinzufügen neuer Zeitfenster + Löschen vorhandener Zeitfenster."""
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    schedule = load_schedule()

    # Falls Query-Parameter: ?action=delete&weekday=mon&index=0
    action = request.args.get("action")
    if action == "delete":
        weekday = request.args.get("weekday")
        index_str = request.args.get("index")
        if weekday in schedule and index_str is not None:
            index = int(index_str)
            if 0 <= index < len(schedule[weekday]):
                schedule[weekday].pop(index)
                save_schedule(schedule)
        return redirect(url_for("edit_schedule"))

    if request.method == "POST":
        # Neues Zeitfenster hinzufügen
        weekday = request.form.get("weekday")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")

        if weekday not in schedule:
            # Falls versehentlich ein falscher Wochentag eingegeben wird,
            # könnte man hier ggf. einen Fehler abfangen.
            schedule[weekday] = []

        schedule[weekday].append({"start": start_time, "end": end_time})
        save_schedule(schedule)
        return redirect(url_for("index"))

    return render_template("edit.html", schedule=schedule)

@app.route("/edit_timeslot", methods=["GET", "POST"])
def edit_timeslot():
    """Route zum Bearbeiten eines einzelnen Zeitfensters."""
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    schedule = load_schedule()

    weekday = request.args.get("weekday")
    index_str = request.args.get("index")

    if weekday not in schedule or index_str is None:
        return redirect(url_for("edit_schedule"))

    index = int(index_str)
    if index < 0 or index >= len(schedule[weekday]):
        return redirect(url_for("edit_schedule"))

    current_slot = schedule[weekday][index]

    if request.method == "POST":
        # Aktualisiere das Zeitfenster
        new_start = request.form.get("start_time")
        new_end = request.form.get("end_time")
        schedule[weekday][index] = {"start": new_start, "end": new_end}
        save_schedule(schedule)
        return redirect(url_for("edit_schedule"))

    return render_template("edit_timeslot.html",
                           weekday=weekday,
                           index=index,
                           slot=current_slot)

# -------------------------------------------------------
# Scheduler-Funktion
# -------------------------------------------------------

CURRENT_STATE = {"state": ""}

def check_campaigns():
    """
    Läuft jede Minute (o.ä.) und setzt den Status
    aller Kampagnen anhand des EINEN Zeitplans.
    """
    now = datetime.now()
    weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    current_weekday = weekday_map[now.weekday()]  # z.B. "mon"
    current_time_str = now.strftime("%H:%M")

    schedule = load_schedule()
    day_windows = schedule.get(current_weekday, [])

    # Prüfen, ob wir uns in irgendeinem Zeitfenster befinden
    in_active_window = False
    for w in day_windows:
        if w["start"] <= current_time_str < w["end"]:
            in_active_window = True
            break
    desired_state = "ENABLED" if in_active_window else "PAUSED"
    current_state = CURRENT_STATE.get("state")

    if current_state != desired_state:

        access_token = get_access_token()
        campaigns = load_campaigns(access_token)

        campaign_ids = [camp["campaignId"] for camp in campaigns if camp["state"] != desired_state]
        if campaign_ids:
            set_campaign_status_batch(access_token, desired_state, campaign_ids)
            CURRENT_STATE["state"] = desired_state


# -------------------------------------------------------
# Scheduler einrichten
# -------------------------------------------------------
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=check_campaigns,
    trigger=IntervalTrigger(seconds=60),
    id="check_campaigns",
    name="Check campaigns every minute",
    replace_existing=True
)
scheduler.start()

port = int(os.environ.get("PORT", 5000))

if __name__ == "__main__":
    # Debug nur lokal
    app.run(debug=True, host="0.0.0.0", port=port)

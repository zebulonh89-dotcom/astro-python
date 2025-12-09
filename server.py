# -------------------- server.py --------------------
from flask import Flask, request, jsonify
from flask_cors import CORS
import swisseph as swe
import math
import os

from datetime import datetime
from timezonefinder import TimezoneFinder
import pytz

app = Flask(__name__)
CORS(app)  # Allow frontend / mobile app to call this API

# -------------------- EPHEMERIS PATH --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(BASE_DIR, "ephe")
swe.set_ephe_path(EPHE_PATH)

# -------------------- Utility --------------------

SIGN_NAMES = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

def wrap360(x: float) -> float:
    return x % 360.0

def sign_of(lon: float) -> str:
    return SIGN_NAMES[int(lon // 30)]

def whole_sign_house(lon: float, asc: float) -> int:
    asc_sign = int(asc // 30)
    body_sign = int(lon // 30)
    return ((body_sign - asc_sign + 12) % 12) + 1

# -------------------- Planet Calculation --------------------

PLANETS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN
}

def compute_planet_longitudes(jd_ut: float):
    planets = {}
    for name, p_id in PLANETS.items():
        result, flag = swe.calc_ut(jd_ut, p_id)
        lon = wrap360(result[0])
        planets[name] = {
            "longitude": lon,
            "sign": sign_of(lon),
            "degreeInSign": lon % 30
        }
    return planets

# -------------------- Ascendant & Houses --------------------

def compute_ascendant_and_houses(jd_ut: float, lat: float, lon: float):
    # 'W' = Placidus in Swiss Ephemeris
    cusps, ascmc = swe.houses(jd_ut, lat, lon, b'W')

    asc_lon = wrap360(ascmc[0])

    houses = []
    for h in range(12):
        cusp_value = wrap360(cusps[h])
        houses.append({
            "house": h + 1,
            "cuspLongitude": cusp_value,
            "sign": sign_of(cusp_value)
        })

    return asc_lon, houses

# -------------------- Timezone & JD helpers --------------------

tf = TimezoneFinder()

def compute_jd_ut_with_timezone(date_str: str, time_str: str,
                                lat: float, lon: float,
                                fallback_tz_minutes=None):
    """
    Convert a local civil date/time at (lat, lon) into a Julian Day in UT,
    using real timezone rules (DST etc.). If timezone lookup fails, fall
    back to fallback_tz_minutes (or 0).
    """
    # Parse date & time
    year, month, day = map(int, date_str.split("-"))
    hour, minute = map(int, time_str.split(":"))

    # 1) Find timezone name from coordinates
    tz_name = tf.timezone_at(lat=lat, lng=lon)
    print(f"[TZ] timezone_at({lat}, {lon}) -> {tz_name}")

    if tz_name is None:
        # Fallback: use provided minutes or UTC
        print("[TZ] WARNING: No timezone found from coordinates, using fallback offset")
        if fallback_tz_minutes is None:
            fallback_tz_minutes = 0
        hour_ut = hour - (fallback_tz_minutes / 60.0)
        jd_ut = swe.julday(year, month, day, hour_ut)
        return jd_ut, fallback_tz_minutes, "Etc/UTC (fallback)"

    tz = pytz.timezone(tz_name)

    # 2) Build naive local datetime for the birth moment
    naive_local = datetime(year, month, day, hour, minute)

    # 3) Localize with DST rules
    try:
        local_dt = tz.localize(naive_local, is_dst=None)
    except pytz.AmbiguousTimeError:
        # If time is ambiguous (DST changeover), pick standard time
        local_dt = tz.localize(naive_local, is_dst=False)
    except pytz.NonExistentTimeError:
        # If time "doesn't exist" (spring forward gap), shift by 1h
        fixed = naive_local + timedelta(hours=1)
        local_dt = tz.localize(fixed, is_dst=True)

    # 4) Convert to UTC
    utc_dt = local_dt.astimezone(pytz.utc)

    # 5) Extract offset in minutes (for debugging / optional return)
    offset = local_dt.utcoffset()
    tz_minutes = int(offset.total_seconds() / 60) if offset is not None else 0

    # 6) Build UT fraction hour for Swiss Ephemeris
    ut_hour = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0

    jd_ut = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, ut_hour)

    print(f"[TZ] Local {local_dt} in {tz_name}, offset {tz_minutes} min -> UTC {utc_dt}, JD_UT={jd_ut}")

    return jd_ut, tz_minutes, tz_name

# -------------------- ROOT ROUTE --------------------

@app.get("/")
def home():
    return jsonify({"status": "Astrology API is running!"})

# -------------------- API ROUTE --------------------

@app.post("/chart/natal")
def chart_natal():
    """
    Expected JSON:
    {
      "date": "YYYY-MM-DD",        # local civil date at birthplace
      "time": "HH:MM",             # local civil time at birthplace (24h)
      "lat":  float,
      "lon":  float,
      "timezoneOffsetMinutes": ... # optional, will be used only as fallback
    }
    """
    data = request.json or {}

    try:
        date = data["date"]
        time = data["time"]
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": True, "message": f"Missing or invalid fields: {e}"}), 400

    # Optional fallback offset from client (we now compute our own)
    client_tz_offset = data.get("timezoneOffsetMinutes", None)
    if isinstance(client_tz_offset, (int, float)):
        client_tz_offset = float(client_tz_offset)
    else:
        client_tz_offset = None

    # Compute JD in UT using timezonefinder + pytz
    jd_ut, effective_tz_minutes, tz_name = compute_jd_ut_with_timezone(
        date, time, lat, lon, fallback_tz_minutes=client_tz_offset
    )

    planets = compute_planet_longitudes(jd_ut)
    asc_lon, houses = compute_ascendant_and_houses(jd_ut, lat, lon)

    ascendant = {
        "longitude": asc_lon,
        "sign": sign_of(asc_lon),
        "degreeInSign": asc_lon % 30
    }

    # Attach houses to planets
    for name, p in planets.items():
        p["house"] = whole_sign_house(p["longitude"], asc_lon)

    return jsonify({
        "ascendant": ascendant,
        "houses": houses,
        "planets": planets,
        "timezone": {
            "name": tz_name,
            "offsetMinutes": effective_tz_minutes
        }
    })

# -------------------- PRODUCTION ENTRYPOINT --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    app.run(host="0.0.0.0", port=port)

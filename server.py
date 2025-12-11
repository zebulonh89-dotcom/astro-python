from flask import Flask, request, jsonify
from timezonefinder import TimezoneFinder
import requests
import pyswisseph as swe   # <-- FIXED HERE
import datetime
import pytz

app = Flask(__name__)

# If you still need Geoapify for geocoding, keep your key
GEOAPIFY_KEY = "7f244c53fa5d4123b5107a3cc1b3a99e"

# Load Swiss Ephemeris data folder
swe.set_ephe_path("ephe")

# Planets to calculate
PLANETS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN
}

# Zodiac names
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn",
    "Aquarius", "Pisces"
]

# TimezoneFinder instance (thread-safe)
tf = TimezoneFinder()

# -- OLD METHOD (kept for reference) ---------------------------------
def get_timezone(lat, lon, date_iso):
    """
    Ask Geoapify for timezone and offset.
    """
    url = (
        f"https://api.geoapify.com/v1/timezone?"
        f"lat={lat}&lon={lon}&apiKey={GEOAPIFY_KEY}"
    )

    try:
        r = requests.get(url)
        data = r.json()

        tzname = data.get("timezoneId", None)
        offset = data.get("offsetSTD", 0)
        dst = data.get("offsetDST", 0)

        total_offset_min = int((offset + dst) * 60)
        return tzname, total_offset_min

    except Exception as e:
        print("[TZ ERROR]", e)
        return None, 0


def to_jd(date, time, offset_minutes):
    """
    Convert local time to Julian Day using Swiss Ephemeris
    (This was the original approach)
    """
    year, month, day = map(int, date.split("-"))
    hour, minute = map(int, time.split(":"))

    ut = hour + (minute / 60.0) - (offset_minutes / 60.0)
    jd_ut = swe.julday(year, month, day, ut)
    return jd_ut


# -- NEW CORRECT METHOD ----------------------------------------------
def compute_jd_utc(date_str, time_str, lat, lon):
    """
    Convert birth local date/time + coordinates into:
    - jd_ut: Julian Day (UT)
    - tz_name: IANA timezone name
    - dt_local_iso: localized datetime string
    - dt_utc_iso: UTC datetime string
    Using historical DST rules via tz database.
    """

    # FIX: normalize separators (23.49 -> 23:49)
    time_str = time_str.replace(".", ":")

    # Parse date
    year, month, day = map(int, date_str.split("-"))

    # Parse time
    parts = time_str.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid time: {time_str}")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0

    dt_naive = datetime.datetime(year, month, day, hour, minute, second)

    # Determine timezone from lat/lon
    tz_name = tf.timezone_at(lat=lat, lng=lon) or tf.certain_timezone_at(lat=lat, lng=lon)
    if tz_name is None:
        raise ValueError("Could not determine timezone from coordinates")

    tz = pytz.timezone(tz_name)

    # Local time (with historical DST)
    dt_local = tz.localize(dt_naive)

    # Convert to UTC
    dt_utc = dt_local.astimezone(pytz.utc)

    # Julian Day UT
    ut_hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
    )
    jd_ut = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, ut_hour)

    return jd_ut, tz_name, dt_local.isoformat(), dt_utc.isoformat()


# -- Astrology calculations ------------------------------------------
def calc_ascendant(jd_ut, lat, lon):
    """
    Calculate Ascendant using Swiss Ephemeris houses
    NOTE: returns (cusps, ascmc)
    """
    cusps, ascmc = swe.houses(jd_ut, lat, lon, b"P")  # P = Placidus
    asc = ascmc[0]

    sign_index = int(asc // 30)
    deg = asc % 30

    return {
        "longitude": asc,
        "degreeInSign": round(deg, 6),
        "sign": SIGNS[sign_index]
    }


def calc_planets(jd_ut):
    """
    Calculate planetary positions at given Julian Day UT
    """
    result = {}
    for name, swe_id in PLANETS.items():
        flag = swe.FLG_SWIEPH | swe.FLG_SPEED
        lonlat, ret = swe.calc_ut(jd_ut, swe_id, flag)
        lon_deg = lonlat[0]

        sign_index = int(lon_deg // 30)
        deg = lon_deg % 30

        result[name] = {
            "longitude": lon_deg,
            "degreeInSign": round(deg, 6),
            "sign": SIGNS[sign_index]
        }
    return result


# -- API --------------------------------------------------------------
@app.route("/chart/natal", methods=["POST"])
def chart_natal():
    data = request.get_json(force=True) or {}

    date = data.get("date")
    time = data.get("time")
    lat = float(data.get("lat"))
    lon = float(data.get("lon"))

    # NEW: correct UT calculation
    jd_ut, tz_name, local_iso, utc_iso = compute_jd_utc(date, time, lat, lon)

    asc = calc_ascendant(jd_ut, lat, lon)
    planets = calc_planets(jd_ut)

    print("[TIME]", tz_name, local_iso, utc_iso)

    return jsonify({
        "ascendant": asc,
        "planets": planets,
        "timezone": {
            "name": tz_name,
            "localDateTime": local_iso,
            "utcDateTime": utc_iso
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4000)

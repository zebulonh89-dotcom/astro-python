from flask import Flask, request, jsonify
from timezonefinder import TimezoneFinder
import requests
import swisseph as swe
import datetime

app = Flask(__name__)

# YOUR GEOAPIFY KEY
GEOAPIFY_KEY = "7f244c53fa5d4123b5107a3cc1b3a99e"

# Load Swiss Ephemeris data
swe.set_ephe_path("ephe")

PLANETS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN
}

def get_timezone(lat, lon, date_iso):
    """
    Ask Geoapify for timezone and offset for THIS date.
    """
    url = (
        f"https://api.geoapify.com/v1/timezone?"
        f"lat={lat}&lon={lon}&apiKey={GEOAPIFY_KEY}"
    )

    try:
        r = requests.get(url)
        data = r.json()

        # Full timezone name: "America/Detroit"
        tzname = data.get("timezoneId", None)

        # Offset in minutes for this date
        offset = data.get("offsetSTD", 0)
        dst = data.get("offsetDST", 0)

        # Total offset (STD + DST)
        total_offset_min = int((offset + dst) * 60)

        return tzname, total_offset_min

    except Exception as e:
        print("[TZ ERROR]", e)
        return None, 0


def to_jd(date, time, offset_minutes):
    """
    Convert local time to Julian Day using Swiss Ephemeris
    """
    # Break date and time
    year, month, day = map(int, date.split("-"))
    hour, minute = map(int, time.split(":"))

    # Local civil time -> UTC
    ut = hour + (minute / 60.0) - (offset_minutes / 60.0)

    jd_ut = swe.julday(year, month, day, ut)
    return jd_ut


def calc_ascendant(jd_ut, lat, lon):
    """
    Calculate ASC using Swiss Ephemeris houses
    """
    ascmc, cusps = swe.houses(jd_ut, lat, lon, b"Placidus")
    asc = ascmc[0]  # ascendant longitude
    sign = int(asc // 30)
    deg = asc % 30
    signs = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn",
        "Aquarius", "Pisces"
    ]
    return {
        "longitude": asc,
        "degreeInSign": round(deg, 6),
        "sign": signs[sign]
    }


def calc_planets(jd_ut, lat, lon):
    result = {}
    signs = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn",
        "Aquarius", "Pisces"
    ]
    ascmc, cusps = swe.houses(jd_ut, lat, lon, b"Placidus")

    for name, swe_id in PLANETS.items():
        flag = swe.FLG_SWIEPH | swe.FLG_SPEED
        lonlat, ret = swe.calc_ut(jd_ut, swe_id, flag)
        lon_deg = lonlat[0]
        sign = int(lon_deg // 30)
        deg = lon_deg % 30
        result[name] = {
            "longitude": lon_deg,
            "degreeInSign": round(deg, 6),
            "sign": signs[sign]
        }

    return result


@app.route("/chart/natal", methods=["POST"])
def chart_natal():
    data = request.json

    date = data.get("date")
    time = data.get("time")
    lat = float(data.get("lat"))
    lon = float(data.get("lon"))

    # Get timezone + offset from Geoapify
    tzname, offset_minutes = get_timezone(lat, lon, date)

    # Convert to JD
    jd_ut = to_jd(date, time, offset_minutes)

    asc = calc_ascendant(jd_ut, lat, lon)
    planets = calc_planets(jd_ut, lat, lon)

    print("[TZ]", tzname, offset_minutes, date, time)

    return jsonify({
        "ascendant": asc,
        "planets": planets,
        "timezone": {
            "name": tzname,
            "offsetMinutes": offset_minutes
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4000)

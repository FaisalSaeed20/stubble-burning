# backend/fires/geocode_utils.py

from opencage.geocoder import OpenCageGeocode
import os

# You can set this as an environment variable too for security
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY", "<YOUR_API_KEY>")
geocoder = OpenCageGeocode(OPENCAGE_API_KEY)

def get_province_city(lat: float, lon: float):
    """
    Uses OpenCage Geocoding API to return province, city, and formatted address.
    """
    try:
        results = geocoder.reverse_geocode(lat, lon, language='en')
        if not results:
            return "Unknown", "Unknown", "Unknown"

        comp = results[0].get('components', {})
        province = comp.get('state') or comp.get('region') or "Unknown"
        city = comp.get('city') or comp.get('town') or comp.get('village') or "Unknown"
        formatted = results[0].get('formatted', 'Unknown')
        return province, city, formatted

    except Exception as e:
        print("OpenCage reverse geocode failed:", e)
        return "Unknown", "Unknown", "Unknown"

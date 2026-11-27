import requests


def get_live_air_quality(lat=23.67, lon=87.68):
    # Open-Meteo Air Quality API URL
    url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide"

    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        current = data.get("current", {})

        return {
            "pm2_5": current.get("pm2_5", 0),
            "pm10": current.get("pm10", 0),
            "co": current.get("carbon_monoxide", 0),
            "no2": current.get("nitrogen_dioxide", 0),
        }
    except Exception as e:
        print("Error fetching data:", e)
        return None


if __name__ == "__main__":
    print(get_live_air_quality())
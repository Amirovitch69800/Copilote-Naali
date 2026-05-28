HUBSPOT_API_KEY   = "pat-eu1-37f11d89-d0ae-45c7-b584-18773f12f018"
HUB_ID            = "143439337"
TEST_MODE         = False
SECRET_KEY        = "naali-local-secret-2026"

PROFILES = {
    "727665403": {
        "owner_id":  "727665403",
        "user_id":   "74415642",   # HubSpot user ID (Goals)
        "name":      "Amir Ounissi",
        "email":     "a.ounissi@naali.fr",
        "csv_path":  "data/naali_base_planning_geo.csv",
        "home_lat":  43.5138,
        "home_lon":  4.9803,
        "home_city": "Istres",
    },
    "78146570": {
        "owner_id":  "78146570",
        "user_id":   "78146570",
        "name":      "Icham Benaissa",
        "email":     "i.benaissa@naali.fr",
        "csv_path":  "data/naali_base_icham.csv",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
    "32059428": {
        "owner_id":  "32059428",
        "user_id":   "32059428",
        "name":      "Fatima Brahim",
        "email":     "f.brahim@naali.fr",
        "csv_path":  "data/naali_base_fatima.csv",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
    "30058900": {
        "owner_id":  "30058900",
        "user_id":   "30058900",
        "name":      "Emelyne Lahaies",
        "email":     "e.lahaies@naali.fr",
        "csv_path":  "data/naali_base_emelyne.csv",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
}

# Rétrocompatibilité (valeurs du premier profil par défaut)
_default = PROFILES["727665403"]
HUBSPOT_OWNER_ID = _default["owner_id"]
OWNER_NAME       = _default["name"]
CSV_PATH         = _default["csv_path"]
HOME_LAT         = _default["home_lat"]
HOME_LON         = _default["home_lon"]
HOME_CITY        = _default["home_city"]

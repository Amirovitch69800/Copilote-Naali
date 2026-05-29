import os as _os, pathlib as _pl
_env_file = _pl.Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            _os.environ.setdefault(_k.strip(), _v.strip())
HUBSPOT_API_KEY   = _os.getenv("HUBSPOT_API_KEY", "")
HUB_ID            = "143439337"
TEST_MODE         = False
SECRET_KEY        = "naali-local-secret-2026"

PROFILES = {
    "727665403": {
        "owner_id":  "727665403",
        "user_id":   "74415642",   # HubSpot user ID (Goals)
        "name":      "Amir Ounissi",
        "email":     "a.ounissi@naali.fr",
        "home_lat":  43.5138,
        "home_lon":  4.9803,
        "home_city": "Istres",
    },
    "78146570": {
        "owner_id":  "78146570",
        "user_id":   "78146570",
        "name":      "Icham Benaissa",
        "email":     "i.benaissa@naali.fr",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
    "32059428": {
        "owner_id":  "32059428",
        "user_id":   "32059428",
        "name":      "Fatima Brahim",
        "email":     "f.brahim@naali.fr",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
    "30058900": {
        "owner_id":  "30058900",
        "user_id":   "30058900",
        "name":      "Emelyne Lahaies",
        "email":     "e.lahaies@naali.fr",
        "home_lat":  None,
        "home_lon":  None,
        "home_city": "",
    },
}

# Rétrocompatibilité (valeurs du premier profil par défaut)
_default = PROFILES["727665403"]
HUBSPOT_OWNER_ID = _default["owner_id"]
OWNER_NAME       = _default["name"]
HOME_LAT         = _default["home_lat"]
HOME_LON         = _default["home_lon"]
HOME_CITY        = _default["home_city"]

"""
tools/geocoder.py
Enrichit le CSV avec les coordonnées GPS via Nominatim (OpenStreetMap).
Zéro coût, zéro clé API.

Pour les pharmacies sans adresse dans le CSV, récupère l'adresse depuis HubSpot.
Lancer UNE SEULE FOIS : python3 tools/geocoder.py

Résultat : data/naali_base_planning_geo.csv  (CSV original + colonnes lat, lon, address)
"""

import csv
import time
import sys
import os
import requests
from pathlib import Path

# Ajouter le répertoire racine au path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from config import HUBSPOT_API_KEY
except ImportError:
    HUBSPOT_API_KEY = ""

CSV_INPUT  = os.path.join(ROOT, "data/naali_base_planning.csv")
CSV_OUTPUT = os.path.join(ROOT, "data/naali_base_planning_geo.csv")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "NaaliPlanner/1.0 (a.ounissi@naali.fr)"}

HUBSPOT_BASE = "https://api.hubapi.com"


# ────────────────────────────────────────────────────────
# HubSpot : récupérer l'adresse d'une company
# ────────────────────────────────────────────────────────

def fetch_hubspot_address(company_id: str) -> str:
    """
    Récupère le champ 'address' d'une company HubSpot.
    Retourne une chaîne vide si indisponible.
    """
    if not HUBSPOT_API_KEY or not company_id:
        return ""
    try:
        url = f"{HUBSPOT_BASE}/crm/v3/objects/companies/{company_id}"
        params = {"properties": "address,address2"}
        headers = {
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            props = r.json().get("properties", {})
            addr = props.get("address", "") or ""
            addr2 = props.get("address2", "") or ""
            return f"{addr} {addr2}".strip()
    except Exception as e:
        print(f"    [HubSpot] Erreur adresse {company_id}: {e}")
    return ""


# ────────────────────────────────────────────────────────
# Géocodage Nominatim
# ────────────────────────────────────────────────────────

def geocode(address: str, city: str, cp: str) -> tuple:
    """
    Convertit une adresse en coordonnées GPS via Nominatim.
    Essaie d'abord l'adresse complète, puis se rabat sur ville+CP.
    Respecte le rate limit Nominatim : 1 requête/seconde max.
    Retourne (lat, lon) ou (None, None).
    """
    # Tentative 1 : adresse complète
    if address:
        params = {
            "q": f"{address}, {cp} {city}, France",
            "format": "json",
            "limit": 1,
            "countrycodes": "fr",
        }
        try:
            r = requests.get(NOMINATIM_URL, params=params,
                             headers=NOMINATIM_HEADERS, timeout=10)
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            pass
        time.sleep(1)

    # Tentative 2 : ville + CP seulement
    params = {
        "q": f"{cp} {city}, France",
        "format": "json",
        "limit": 1,
        "countrycodes": "fr",
    }
    try:
        r = requests.get(NOMINATIM_URL, params=params,
                         headers=NOMINATIM_HEADERS, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass

    return None, None


# ────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────

def main():
    # Lire le CSV existant
    with open(CSV_INPUT, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        original_fields = list(reader.fieldnames or [])

    # Ajouter les colonnes GPS + address si absentes
    new_fields = list(original_fields)
    for col in ("address", "lat", "lon"):
        if col not in new_fields:
            new_fields.append(col)

    # Initialiser les nouvelles colonnes sur les lignes existantes
    for row in rows:
        row.setdefault("address", "")
        row.setdefault("lat", "")
        row.setdefault("lon", "")

    print(f"🌍 Géocodage de {len(rows)} pharmacies...")
    print(f"   Entrée  : {CSV_INPUT}")
    print(f"   Sortie  : {CSV_OUTPUT}")
    print(f"   HubSpot : {'activé' if HUBSPOT_API_KEY else 'désactivé (HUBSPOT_API_KEY manquante)'}")
    print()

    ok = 0
    hs_fetch = 0

    for i, row in enumerate(rows):
        # Déjà géocodé → passer
        if row.get("lat") and row.get("lon"):
            ok += 1
            print(f"  {i+1:3d}/{len(rows)} — {row['nom'][:40]:<40} ⏭  déjà géocodé")
            continue

        # Récupérer l'adresse depuis HubSpot si manquante
        if not row.get("address"):
            company_id = row.get("id_hubspot", "").strip()
            if company_id and HUBSPOT_API_KEY:
                addr = fetch_hubspot_address(company_id)
                if addr:
                    row["address"] = addr
                    hs_fetch += 1
                    time.sleep(0.2)  # rate limit HubSpot

        city = row.get("ville", "").strip()
        cp   = row.get("cp", "").strip() or row.get("zip", "").strip()
        addr = row.get("address", "").strip()

        lat, lon = geocode(addr, city, cp)
        row["lat"] = lat if lat is not None else ""
        row["lon"] = lon if lon is not None else ""

        if lat:
            ok += 1
            status = f"✅ {lat:.4f}, {lon:.4f}"
        else:
            status = "❌ Non trouvée"

        print(f"  {i+1:3d}/{len(rows)} — {row['nom'][:40]:<40} {status}")
        time.sleep(1)  # Respect Nominatim rate limit (1 req/s max)

    # Écrire le CSV enrichi
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"✅ {ok}/{len(rows)} pharmacies géocodées")
    if hs_fetch:
        print(f"   {hs_fetch} adresses récupérées depuis HubSpot")
    print(f"   Fichier : {CSV_OUTPUT}")


if __name__ == "__main__":
    main()

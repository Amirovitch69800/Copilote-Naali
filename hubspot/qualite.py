"""
hubspot/qualite.py
Analyse qualité remplissage HubSpot par commercial.
- Nombre de notes prises
- Nombre de notes avec pièces jointes (proxy photos terrain)
- Date de la dernière note
Période : mars + avril 2026
"""

import requests
import sys
import os
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import HUBSPOT_API_KEY, PROFILES

BASE_URL = "https://api.hubapi.com"
HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json",
}

# Période : 1er mars 2026 → 30 avril 2026 (UTC)
DEBUT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
FIN   = datetime(2026, 4, 30, 23, 59, 59, tzinfo=timezone.utc)
TS_DEBUT = str(int(DEBUT.timestamp() * 1000))
TS_FIN   = str(int(FIN.timestamp() * 1000))


def _get_notes_owner(owner_id: str) -> list:
    """Récupère toutes les notes d'un commercial sur la période (pagination complète)."""
    url = f"{BASE_URL}/crm/v3/objects/notes/search"
    notes = []
    after = None

    while True:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                {"propertyName": "hs_createdate", "operator": "BETWEEN",
                 "value": TS_DEBUT, "highValue": TS_FIN},
            ]}],
            "properties": ["hs_note_body", "hs_createdate", "hs_attachment_ids"],
            "sorts": [{"propertyName": "hs_createdate", "direction": "DESCENDING"}],
            "limit": 200,
        }
        if after:
            payload["after"] = after

        resp = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  [!] Erreur API notes owner={owner_id}: {resp.status_code} {resp.text[:150]}")
            break

        data = resp.json()
        results = data.get("results", [])
        notes.extend(results)

        after = data.get("paging", {}).get("next", {}).get("after")
        if not after or not results:
            break

    return notes


def analyser_qualite() -> list:
    """
    Retourne une liste triée (notes décroissantes) avec pour chaque commercial :
      - nom, email
      - nb_notes          : total de notes sur mars-avril 2026
      - nb_avec_pj        : notes ayant au moins une pièce jointe (proxy photos terrain)
      - pct_pj            : % notes avec pièce jointe
      - derniere_note     : date de la dernière note (YYYY-MM-DD HH:MM)
    """
    resultats = []

    for owner_id, profil in PROFILES.items():
        print(f"→ {profil['name']} ({owner_id})...")
        notes = _get_notes_owner(owner_id)

        nb_notes = len(notes)
        nb_avec_pj = 0
        derniere_note = None

        for note in notes:
            props = note.get("properties", {})

            # Pièce jointe : hs_attachment_ids est une chaîne "id1;id2" ou None
            pj = props.get("hs_attachment_ids") or ""
            if isinstance(pj, list):
                pj = ";".join(pj)
            if pj.strip():
                nb_avec_pj += 1

            # Date de création
            created = props.get("hs_createdate")
            if created:
                try:
                    ts_val = int(created)
                    dt = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
                except (ValueError, TypeError):
                    try:
                        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    except Exception:
                        dt = None
                if dt and (derniere_note is None or dt > derniere_note):
                    derniere_note = dt

        pct = round(nb_avec_pj / nb_notes * 100, 1) if nb_notes else 0.0

        resultats.append({
            "nom":           profil["name"],
            "email":         profil["email"],
            "nb_notes":      nb_notes,
            "nb_avec_pj":    nb_avec_pj,
            "pct_pj":        pct,
            "derniere_note": derniere_note.strftime("%Y-%m-%d %H:%M") if derniere_note else None,
        })

    resultats.sort(key=lambda x: x["nb_notes"], reverse=True)
    return resultats


if __name__ == "__main__":
    print(f"Analyse qualité HubSpot — mars + avril 2026\n{'='*50}")
    data = analyser_qualite()
    print()
    print(json.dumps(data, indent=2, ensure_ascii=False))

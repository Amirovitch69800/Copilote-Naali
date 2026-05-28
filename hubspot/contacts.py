"""
hubspot/contacts.py
Lecture et gestion des contacts HubSpot associés à une company.
"""
import requests
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY
except ImportError:
    HUBSPOT_API_KEY = ""

BASE = "https://api.hubapi.com"
CONTACT_PROPS = ["firstname", "lastname", "jobtitle", "email", "phone", "mobilephone"]


def _headers():
    return {"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"}


def get_contacts_for_company(company_id: str) -> list:
    """Retourne la liste des contacts associés à une company HubSpot."""
    # 1. Récupérer les IDs contacts associés
    url = f"{BASE}/crm/v3/objects/companies/{company_id}/associations/contacts"
    resp = requests.get(url, headers=_headers(), timeout=10)
    if not resp.ok:
        return []
    results = resp.json().get("results", [])
    if not results:
        return []

    contact_ids = [r["id"] for r in results]

    # 2. Batch read des contacts
    batch_url = f"{BASE}/crm/v3/objects/contacts/batch/read"
    payload = {
        "inputs": [{"id": cid} for cid in contact_ids],
        "properties": CONTACT_PROPS,
    }
    resp2 = requests.post(batch_url, json=payload, headers=_headers(), timeout=10)
    if not resp2.ok:
        return []

    contacts = []
    for c in resp2.json().get("results", []):
        p = c.get("properties", {})
        contacts.append({
            "id":          c["id"],
            "firstname":   p.get("firstname") or "",
            "lastname":    p.get("lastname")  or "",
            "jobtitle":    p.get("jobtitle")  or "",
            "email":       p.get("email")     or "",
            "phone":       p.get("phone")     or p.get("mobilephone") or "",
        })
    return contacts


def create_contact(company_id: str, data: dict) -> dict:
    """Crée un contact HubSpot et l'associe à la company."""
    props = {k: v for k, v in {
        "firstname":   data.get("firstname", ""),
        "lastname":    data.get("lastname",  ""),
        "jobtitle":    data.get("jobtitle",  ""),
        "email":       data.get("email",     ""),
        "phone":       data.get("phone",     ""),
    }.items() if v}

    # Créer le contact
    resp = requests.post(
        f"{BASE}/crm/v3/objects/contacts",
        json={"properties": props},
        headers=_headers(),
        timeout=10,
    )
    if not resp.ok:
        raise ValueError(f"HubSpot contacts create error {resp.status_code}: {resp.text}")

    contact = resp.json()
    contact_id = contact["id"]

    # Associer à la company (type 1 = contact → company)
    assoc_url = f"{BASE}/crm/v3/associations/contacts/companies/batch/create"
    requests.post(
        assoc_url,
        json={"inputs": [{"from": {"id": contact_id}, "to": {"id": company_id}, "type": "contact_to_company"}]},
        headers=_headers(),
        timeout=10,
    )

    p = contact.get("properties", {})
    return {
        "id":        contact_id,
        "firstname": p.get("firstname") or "",
        "lastname":  p.get("lastname")  or "",
        "jobtitle":  p.get("jobtitle")  or "",
        "email":     p.get("email")     or "",
        "phone":     p.get("phone")     or "",
    }


def update_contact(contact_id: str, data: dict) -> dict:
    """Met à jour les propriétés d'un contact HubSpot."""
    props = {k: v for k, v in {
        "firstname": data.get("firstname", ""),
        "lastname":  data.get("lastname",  ""),
        "jobtitle":  data.get("jobtitle",  ""),
        "email":     data.get("email",     ""),
        "phone":     data.get("phone",     ""),
    }.items() if v is not None}

    resp = requests.patch(
        f"{BASE}/crm/v3/objects/contacts/{contact_id}",
        json={"properties": props},
        headers=_headers(),
        timeout=10,
    )
    if not resp.ok:
        raise ValueError(f"HubSpot contacts update error {resp.status_code}: {resp.text}")

    p = resp.json().get("properties", {})
    return {
        "id":        contact_id,
        "firstname": p.get("firstname") or "",
        "lastname":  p.get("lastname")  or "",
        "jobtitle":  p.get("jobtitle")  or "",
        "email":     p.get("email")     or "",
        "phone":     p.get("phone")     or "",
    }

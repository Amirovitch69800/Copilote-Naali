"""
hubspot/deals.py
CA mois courant + CA YTD — deals fermés, owner = HUBSPOT_OWNER_ID.
Filtre uniquement sur closedate + owner (pas de dealstage car l'ID est spécifique au CRM).
"""
import requests
from datetime import date
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY, HUBSPOT_OWNER_ID
except ImportError:
    HUBSPOT_API_KEY = ""
    HUBSPOT_OWNER_ID = "727665403"

BASE_URL = "https://api.hubapi.com"


def _h():
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }


def _sum_deals(date_debut: str, date_fin: str) -> float:
    """Somme des montants de deals fermés entre deux dates (owner = HUBSPOT_OWNER_ID)."""
    if not HUBSPOT_API_KEY:
        return 0.0
    try:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "closedate", "operator": "GTE", "value": date_debut},
                {"propertyName": "closedate", "operator": "LTE", "value": date_fin},
                {"propertyName": "hubspot_owner_id", "operator": "EQ",
                 "value": str(HUBSPOT_OWNER_ID)},
            ]}],
            "properties": ["amount"],
            "limit": 100,
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/deals/search",
                          json=payload, headers=_h(), timeout=10)
        if r.status_code != 200:
            print(f"[HubSpot] deals search {r.status_code}: {r.text[:100]}")
            return 0.0
        total = 0.0
        for deal in r.json().get("results", []):
            amt = deal.get("properties", {}).get("amount")
            if amt:
                try:
                    total += float(amt)
                except (ValueError, TypeError):
                    pass
        return total
    except Exception as e:
        print(f"[HubSpot] _sum_deals: {e}")
        return 0.0


def get_ca_mois_courant() -> float:
    """CA du mois civil en cours (1er du mois → aujourd'hui)."""
    today = date.today()
    return _sum_deals(today.replace(day=1).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))


def get_ca_ytd() -> float:
    """CA depuis le 1er janvier de l'année en cours jusqu'à aujourd'hui."""
    today = date.today()
    return _sum_deals(f"{today.year}-01-01", today.strftime("%Y-%m-%d"))


# ─── Pipeline IDs ─────────────────────────────────────────────────────────────
PIPELINE_COMMERCIAUX = "1543644371"
STAGE_PRECOMMANDE    = "2110945486"
STAGE_EN_COURS       = "2870908123"
STAGE_CLOTUREE       = "2110945491"


# ─── Créer un deal + line items ───────────────────────────────────────────────

def create_order(company_id: str, company_nom: str, line_items: list,
                 owner_id: str = None, note: str = "",
                 type_de_commande: str = "Réassort",
                 dealstage: str = None,
                 closed_won_reason: str = "Classique") -> dict:
    """
    Crée un deal HubSpot (pipeline Commerciaux Naali, stage Précommande)
    associé à une company, avec ses line items.

    line_items : [{"nom": str, "qty": float, "prix": float, "remise": float}]
    Retourne {"ok": True, "deal_id": str} ou {"ok": False, "error": str}
    """
    if not HUBSPOT_API_KEY:
        return {"ok": False, "error": "API key manquante"}

    today_str = date.today().strftime("%Y-%m-%d")
    oid = str(owner_id or HUBSPOT_OWNER_ID)
    montant = sum(
        float(li.get("prix", 0)) * float(li.get("qty", 1))
        * (1 - float(li.get("remise", 0)) / 100)
        for li in line_items
    )

    try:
        # 1. Créer le deal
        deal_payload = {
            "properties": {
                "dealname":                  company_nom,
                "pipeline":                  PIPELINE_COMMERCIAUX,
                "dealstage":                 dealstage or STAGE_PRECOMMANDE,
                "hubspot_owner_id":          oid,
                "amount":                    str(round(montant, 2)),
                "type_de_commande":          type_de_commande,
                "origine_de_la_commande":    "Commercial Naali",
                "prise_de_commande":         oid,
                "closed_won_reason":         "Classique",
            },
            "associations": [{
                "to": {"id": str(company_id)},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 5}],
            }],
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/deals",
                          json=deal_payload, headers=_h(), timeout=15)
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"Deal creation failed: {r.status_code} {r.text[:200]}"}

        deal_id = r.json()["id"]

        # 2. Créer les line items et les associer au deal
        for li in line_items:
            if not li.get("id"):
                print(f"[deals] line_item ignoré — id manquant: {li}")
                continue
            qty    = float(li.get("qty", 1))
            prix   = float(li.get("prix", 0))
            remise = float(li.get("remise", 0))
            props  = {
                "hs_product_id":          str(li["id"]),
                "quantity":               str(qty),
                "price":                  str(prix),
                "hs_discount_percentage": str(remise),
            }
            if li.get("tva_id"):
                props["hs_tax_rate_group_id"] = str(li["tva_id"])
            if li.get("classification"):
                props["test_type_dug"] = str(li["classification"])
            li_payload = {
                "properties": props,
                "associations": [{
                    "to": {"id": deal_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 20}],
                }],
            }
            lr = requests.post(f"{BASE_URL}/crm/v3/objects/line_items",
                               json=li_payload, headers=_h(), timeout=10)
            if lr.status_code not in (200, 201):
                print(f"[deals] line_item error {lr.status_code}: {lr.text[:200]}")

        # 3. Ajouter une note si fournie
        if note and company_id:
            from hubspot.suivi import create_company_note
            create_company_note(company_id, note, owner_id=owner_id)

        return {"ok": True, "deal_id": deal_id, "montant": round(montant, 2)}

    except Exception as e:
        print(f"[deals] create_order: {e}")
        return {"ok": False, "error": str(e)}


def get_goals_mois(user_id: str) -> dict:
    """Objectifs CA et implantations du mois courant depuis HubSpot Goals."""
    result = {"objectif_ca": 0.0, "objectif_implant": 0}
    if not HUBSPOT_API_KEY or not user_id:
        return result
    try:
        today = date.today()
        mois_debut = today.replace(day=1).strftime("%Y-%m-%dT00:00:00Z")
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_assignee_user_id", "operator": "EQ",  "value": user_id},
                {"propertyName": "hs_start_datetime",   "operator": "GTE", "value": mois_debut},
            ]}],
            "properties": ["hs_goal_name", "hs_target_amount"],
            "limit": 50,
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/goal_targets/search",
                          json=payload, headers=_h(), timeout=10)
        if r.status_code != 200:
            return result
        for g in r.json().get("results", []):
            p   = g["properties"]
            nom = (p.get("hs_goal_name") or "").lower()
            cible = float(p.get("hs_target_amount") or 0)
            if cible <= 0:
                continue
            if "ca" in nom and "terrain" in nom:
                result["objectif_ca"] = cible
            elif "implantation" in nom and "terrain" in nom:
                result["objectif_implant"] = int(cible)
        return result
    except Exception as e:
        print(f"[deals] get_goals_mois: {e}")
        return result


def get_implantations_mois(owner_id: str = None) -> int:
    """Nombre de deals type_de_commande=Implantation créés ce mois-ci pour cet owner."""
    if not HUBSPOT_API_KEY:
        return 0
    try:
        today = date.today()
        date_debut = today.replace(day=1).strftime("%Y-%m-%d")
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline",          "operator": "EQ",  "value": PIPELINE_COMMERCIAUX},
                {"propertyName": "hubspot_owner_id",  "operator": "EQ",  "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "type_de_commande",  "operator": "EQ",  "value": "Implantation"},
                {"propertyName": "createdate",        "operator": "GTE", "value": date_debut},
            ]}],
            "properties": ["dealname"],
            "limit": 100,
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/deals/search",
                          json=payload, headers=_h(), timeout=10)
        if r.status_code != 200:
            return 0
        return r.json().get("total", len(r.json().get("results", [])))
    except Exception as e:
        print(f"[deals] get_implantations_mois: {e}")
        return 0


def get_recent_orders(owner_id: str = None, days: int = 30) -> list:
    """Deals récents du pipeline Commerciaux Naali pour cet owner."""
    if not HUBSPOT_API_KEY:
        return []
    try:
        from datetime import timedelta
        date_from = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline",          "operator": "EQ",  "value": PIPELINE_COMMERCIAUX},
                {"propertyName": "hubspot_owner_id",  "operator": "EQ",  "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "createdate",        "operator": "GTE", "value": date_from},
            ]}],
            "properties": ["dealname", "dealstage", "amount", "closedate",
                           "createdate", "type_de_commande", "hubspot_owner_id"],
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
            "limit": 20,
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/deals/search",
                          json=payload, headers=_h(), timeout=15)
        if r.status_code != 200:
            return []

        _STAGE_LABELS = {
            STAGE_PRECOMMANDE:    "Précommande",
            STAGE_EN_COURS:       "En cours de traitement",
            "2110945485":         "Complément à envoyer",
            "2110945489":         "À finaliser par ADV",
            STAGE_CLOTUREE:       "Commandes clôturées",
        }
        orders = []
        for deal in r.json().get("results", []):
            p = deal.get("properties", {})
            stage = p.get("dealstage", "")
            orders.append({
                "id":       deal["id"],
                "nom":      p.get("dealname", ""),
                "stage":    stage,
                "stage_label": _STAGE_LABELS.get(stage, stage),
                "montant":  float(p.get("amount") or 0),
                "date":     (p.get("closedate") or p.get("createdate") or "")[:10],
                "owner_id": p.get("hubspot_owner_id", ""),
            })
        return orders
    except Exception as e:
        print(f"[deals] get_recent_orders: {e}")
        return []

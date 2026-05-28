"""
hubspot/companies.py
Lecture enrichie d'une company HubSpot :
  - Propriétés company (groupement, remise, catalogue, etc.)
  - Deals associés (pipeline, stage, montant, date)
  - Line items des deals
  - CompanySnapshot : read model complet
"""
import requests
import concurrent.futures
from datetime import datetime, timezone
import pytz
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY, HUB_ID, HUBSPOT_OWNER_ID
except ImportError:
    HUBSPOT_API_KEY = ""
    HUB_ID = "143439337"
    HUBSPOT_OWNER_ID = "727665403"

PARIS = pytz.timezone("Europe/Paris")
BASE = "https://api.hubapi.com"

# Propriétés company fetchées
_COMPANY_PROPS = [
    "name", "city", "address", "phone",
    "client_naali", "potentiel",
    "catalogue_naali_reference",
    "groupement_principal",
    "remise_sur_facture_appliquee",
    "remise_2025",
    "remise_2026",
    "identifiant_client_pennylane",
    "hs_lead_status",
]

# Propriétés deal fetchées
_DEAL_PROPS = [
    "dealname", "pipeline", "dealstage", "closedate",
    "amount", "montant_total",
    "type_de_commande", "origine_de_la_commande",
    "prise_de_commande", "remise____",
    "hubspot_owner_id",
]

# Propriétés line item fetchées
_LINE_ITEM_PROPS = [
    "name", "quantity", "price", "amount",
    "discount", "hs_discount_percentage",
    "hs_tax_amount", "remise_sur_facture", "code_ean",
]


def _h():
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }


# ─── Company ──────────────────────────────────────────────────────────────────

def get_nb_clients_prospects(owner_id: str) -> dict:
    """Compte clients et prospects depuis HubSpot pour un owner donné."""
    if not HUBSPOT_API_KEY:
        return {"nb_clients": 0, "nb_prospects": 0}
    try:
        _CLIENT_VALS = ["true"]

        def _count(extra_filter):
            payload = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                    extra_filter,
                ]}],
                "properties": ["name"],
                "limit": 1,
            }
            r = requests.post(f"{BASE}/crm/v3/objects/companies/search",
                              json=payload, headers=_h(), timeout=10)
            return r.json().get("total", 0) if r.status_code == 200 else 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_clients   = ex.submit(_count, {"propertyName": "client_naali", "operator": "IN",     "values": _CLIENT_VALS})
            f_prospects = ex.submit(_count, {"propertyName": "client_naali", "operator": "NOT_IN", "values": _CLIENT_VALS})
            nb_clients   = f_clients.result()
            nb_prospects = f_prospects.result()

        return {"nb_clients": nb_clients, "nb_prospects": nb_prospects}
    except Exception as e:
        print(f"[companies] get_nb_clients_prospects: {e}")
        return {"nb_clients": 0, "nb_prospects": 0}


def get_company(company_id: str) -> dict:
    """Fetch propriétés enrichies d'une company."""
    if not HUBSPOT_API_KEY:
        return {}
    try:
        r = requests.get(
            f"{BASE}/crm/v3/objects/companies/{company_id}",
            params={"properties": ",".join(_COMPANY_PROPS)},
            headers=_h(), timeout=10,
        )
        if r.status_code != 200:
            return {}
        props = r.json().get("properties", {})
        return {
            "id": company_id,
            "nom": props.get("name", ""),
            "ville": props.get("city", ""),
            "address": props.get("address", ""),
            "phone": props.get("phone", ""),
            "client_naali": props.get("client_naali", ""),
            "potentiel": props.get("potentiel", ""),
            "catalogue": props.get("catalogue_naali_reference", ""),
            "groupement": props.get("groupement_principal", ""),
            "remise": props.get("remise_sur_facture_appliquee", ""),
            "remise_2025": props.get("remise_2025", ""),
            "remise_2026": props.get("remise_2026", ""),
            "pennylane_id": props.get("identifiant_client_pennylane", ""),
            "lead_status": props.get("hs_lead_status", ""),
        }
    except Exception as e:
        print(f"[companies] get_company {company_id}: {e}")
        return {}


# ─── Deals ────────────────────────────────────────────────────────────────────

def get_company_deals(company_id: str) -> list:
    """Fetch deals associés à une company, triés par date décroissante."""
    if not HUBSPOT_API_KEY:
        return []
    try:
        # Récupérer les IDs des deals associés
        ra = requests.get(
            f"{BASE}/crm/v3/objects/companies/{company_id}/associations/deals",
            headers=_h(), timeout=10,
        )
        if ra.status_code != 200:
            return []
        deal_ids = [r["id"] for r in ra.json().get("results", [])]
        if not deal_ids:
            return []

        # Batch read des deals
        rb = requests.post(
            f"{BASE}/crm/v3/objects/deals/batch/read",
            json={
                "inputs": [{"id": did} for did in deal_ids[:20]],
                "properties": _DEAL_PROPS,
            },
            headers=_h(), timeout=15,
        )
        if rb.status_code not in (200, 207):
            return []

        deals = []
        for deal in rb.json().get("results", []):
            p = deal.get("properties", {})
            closedate = p.get("closedate", "")
            try:
                dt = datetime.fromisoformat(closedate.replace("Z", "+00:00")).astimezone(PARIS) if closedate else None
                date_label = dt.strftime("%d/%m/%Y") if dt else ""
            except Exception:
                date_label = ""
            deals.append({
                "id": deal["id"],
                "nom": p.get("dealname", ""),
                "pipeline": p.get("pipeline", ""),
                "stage": p.get("dealstage", ""),
                "montant": _safe_float(p.get("montant_total") or p.get("amount")),
                "closedate": closedate,
                "date_label": date_label,
                "type_commande": p.get("type_de_commande", ""),
                "origine": p.get("origine_de_la_commande", ""),
                "prise_commande": p.get("prise_de_commande", ""),
                "remise": p.get("remise____", ""),
            })

        # Trier par date décroissante
        deals.sort(key=lambda d: d["closedate"] or "", reverse=True)
        return deals

    except Exception as e:
        print(f"[companies] get_company_deals {company_id}: {e}")
        return []


# ─── Line items ───────────────────────────────────────────────────────────────

def get_deal_line_items(deal_id: str) -> list:
    """Fetch line items d'un deal."""
    if not HUBSPOT_API_KEY:
        return []
    try:
        ra = requests.get(
            f"{BASE}/crm/v3/objects/deals/{deal_id}/associations/line_items",
            headers=_h(), timeout=10,
        )
        if ra.status_code != 200:
            return []
        li_ids = [r["id"] for r in ra.json().get("results", [])]
        if not li_ids:
            return []

        rb = requests.post(
            f"{BASE}/crm/v3/objects/line_items/batch/read",
            json={
                "inputs": [{"id": lid} for lid in li_ids[:50]],
                "properties": _LINE_ITEM_PROPS,
            },
            headers=_h(), timeout=10,
        )
        if rb.status_code not in (200, 207):
            return []

        items = []
        for li in rb.json().get("results", []):
            p = li.get("properties", {})
            items.append({
                "id": li["id"],
                "nom": p.get("name", ""),
                "qty": _safe_float(p.get("quantity")),
                "prix": _safe_float(p.get("price")),
                "montant": _safe_float(p.get("amount")),
                "remise": _safe_float(p.get("discount") or p.get("hs_discount_percentage")),
                "code_ean": p.get("code_ean", ""),
            })
        return items

    except Exception as e:
        print(f"[companies] get_deal_line_items {deal_id}: {e}")
        return []


# ─── CompanySnapshot ──────────────────────────────────────────────────────────

def get_company_snapshot(company_id: str, days_notes: int = 730) -> dict:
    """
    Read model complet :
      - company (HubSpot)       → données lues depuis HubSpot
      - deals (HubSpot)         → données lues depuis HubSpot
      - last_note (HubSpot)     → données lues depuis HubSpot
      - dn (calculé)            → calculé depuis catalogue_naali_reference vs CATALOGUE local
      - ca_total (calculé)      → calculé depuis les deals
    """
    # Charge company + deals + notes en parallèle
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_c = ex.submit(get_company, company_id)
        f_d = ex.submit(get_company_deals, company_id)
        f_n = ex.submit(_get_last_note, company_id, days_notes)
        company = f_c.result()
        deals   = f_d.result()
        note    = f_n.result()

    # DN calculé depuis catalogue vs CATALOGUE local
    dn = _calc_dn(company.get("catalogue", ""))

    # CA total depuis les deals (somme des montants)
    ca_total = sum(d["montant"] for d in deals if d["montant"])
    dernier_deal = deals[0] if deals else None

    return {
        # Source : HubSpot (données lues)
        "company":     company,
        "deals":       deals[:5],   # 5 derniers
        "last_note":   note,
        "notes_list":  note.get("notes_list", []),
        # Source : calculé
        "dn":          dn,
        "ca_total":    ca_total,
        "last_deal":   dernier_deal,
        "hub_id":      HUB_ID,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def _get_last_note(company_id: str, days: int) -> dict:
    try:
        from hubspot.suivi import get_company_note_status
        return get_company_note_status(company_id, days=days)
    except Exception:
        return {}


# ─── Cache TTL pour load_pharmacies_hubspot ───────────────────────────────────
_ph_cache: dict = {}
_PH_CACHE_TTL = 1800  # 30 min


def _ph_cache_get(key):
    entry = _ph_cache.get(key)
    if entry is None:
        return None
    ts, val = entry
    if (datetime.now(timezone.utc).timestamp() - ts) > _PH_CACHE_TTL:
        del _ph_cache[key]
        return None
    return val


def _ph_cache_set(key, val):
    _ph_cache[key] = (datetime.now(timezone.utc).timestamp(), val)


# Propriétés planification (noms internes HubSpot = noms colonnes CSV)
_PH_PROPERTIES = [
    "name", "city", "zip",
    "client_naali", "potentiel", "catalogue_naali_reference", "origine",
    "lat", "lon",
]


def _map_pharma(obj: dict) -> dict:
    """Mappe un objet HubSpot company vers le format interne (compatible filtres.py)."""
    props = obj.get("properties", {})

    cp = (props.get("zip") or "").strip()
    if cp.endswith(".0"):
        cp = cp[:-2]
    cp = cp.zfill(5) if cp else ""

    client_raw = (props.get("client_naali") or "").strip()

    lat = lon = None
    try:
        v = props.get("lat") or ""
        lat = float(v) if v else None
    except (ValueError, TypeError):
        pass
    try:
        v = props.get("lon") or ""
        lon = float(v) if v else None
    except (ValueError, TypeError):
        pass

    return {
        "id_hubspot":        str(obj["id"]),
        "hs_object_id":      str(obj["id"]),
        "nom":               (props.get("name") or "").strip(),
        "ville":             (props.get("city") or "").strip().upper(),
        "cp":                cp,
        "client_naali":      client_raw,
        "_client_naali_raw": client_raw,
        "potentiel":         (props.get("potentiel") or "").strip(),
        "catalogue":         (props.get("catalogue_naali_reference") or "").strip(),
        "origine":           (props.get("origine") or "").strip(),
        "lat":               lat,
        "lon":               lon,
    }


def load_pharmacies_hubspot(owner_id: str = None, force_refresh: bool = False) -> list:
    """
    Charge toutes les companies HubSpot de l'owner via l'API search paginée.
    Retourne une liste de dicts compatibles avec filtres.py (même format que load_pharmacies).
    Cache TTL 30 min en mémoire.
    """
    _oid = str(owner_id or HUBSPOT_OWNER_ID)
    cache_key = f"ph:{_oid}"

    if not force_refresh:
        cached = _ph_cache_get(cache_key)
        if cached is not None:
            return cached

    if not HUBSPOT_API_KEY:
        return []

    companies = []
    after = None

    while True:
        body = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": _oid},
            ]}],
            "properties": _PH_PROPERTIES,
            "sorts": [{"propertyName": "name", "direction": "ASCENDING"}],
            "limit": 100,
        }
        if after:
            body["after"] = after

        try:
            r = requests.post(
                f"{BASE}/crm/v3/objects/companies/search",
                json=body, headers=_h(), timeout=30,
            )
            if r.status_code not in (200, 207):
                print(f"[HubSpot] companies search {r.status_code}: {r.text[:300]}")
                break

            data = r.json()
            results = data.get("results", [])
            companies.extend(_map_pharma(obj) for obj in results)

            after = data.get("paging", {}).get("next", {}).get("after")
            if not after or not results:
                break

        except Exception as e:
            print(f"[HubSpot] load_pharmacies_hubspot: {e}")
            break

    _ph_cache_set(cache_key, companies)
    print(f"[HubSpot] {len(companies)} companies chargées (owner={_oid})")
    return companies


def invalidate_pharmacies_cache(owner_id: str = None):
    """Vide le cache companies pour forcer un rechargement au prochain appel."""
    key = f"ph:{owner_id or HUBSPOT_OWNER_ID}"
    _ph_cache.pop(key, None)


def _calc_dn(catalogue_str: str) -> dict:
    """
    Calculé depuis catalogue_naali_reference (source : HubSpot company)
    vs CATALOGUE cible (source : dn_engine.py local).
    """
    try:
        from core.dn_engine import CATALOGUE
        if not CATALOGUE:
            return {"refs": 0, "total": 0, "pct": 0, "presents": [], "manquants": []}
        refs_presentes = [r.strip() for r in (catalogue_str or "").split(";") if r.strip()]
        refs_set = set(r.lower() for r in refs_presentes)
        manquants = [c for c in CATALOGUE if c.lower() not in refs_set]
        return {
            "refs":      len(refs_presentes),
            "total":     len(CATALOGUE),
            "pct":       round(len(refs_presentes) / len(CATALOGUE) * 100) if CATALOGUE else 0,
            "presents":  refs_presentes,
            "manquants": manquants[:10],  # top 10
        }
    except Exception:
        return {"refs": 0, "total": 0, "pct": 0, "presents": [], "manquants": []}

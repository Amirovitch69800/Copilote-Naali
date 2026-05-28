"""
hubspot/catalogue.py
Catalogue produits + taxes HubSpot.
"""
import requests
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY
except ImportError:
    HUBSPOT_API_KEY = ""

BASE = "https://api.hubapi.com"
PCB  = 6  # Par Carton de Base — fixe pour Naali

# Produits à masquer dans l'interface de commande (archivés côté Naali)
_EXCLUDED_KEYWORDS = [
    "crème jour",
    "safran",
    "x42 sucr",
    "as 42 sucr",
    "masque de nuit",
    "osmose",
    "zen orange",
    "zen gout orange",
    "zen goût orange",
    "zenkids",
    "zen kids",
]


def _is_excluded(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _EXCLUDED_KEYWORDS)

_cache_products = None
_cache_taxes    = None


def _h():
    return {"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"}


def get_products() -> list:
    global _cache_products
    if _cache_products is not None:
        return _cache_products

    if not HUBSPOT_API_KEY:
        return []

    try:
        r = requests.get(
            f"{BASE}/crm/v3/objects/products",
            params={
                "limit": 100,
                "properties": "name,price,code_ean,hs_sku,pvc,type_de_produit_naali",
                "archived": "false",
            },
            headers=_h(), timeout=15,
        )
        if r.status_code != 200:
            return []

        products = []
        for p in r.json().get("results", []):
            props = p.get("properties", {})
            if _is_excluded(props.get("name", "")):
                continue
            prix = _safe_float(props.get("price"))
            pvc  = _safe_float((props.get("pvc") or "").replace(",", "."))
            products.append({
                "id":      p["id"],
                "nom":     props.get("name", ""),
                "prix":    prix,
                "pvc":     pvc,
                "ean":     props.get("code_ean") or props.get("hs_sku") or "",
                "type":    props.get("type_de_produit_naali") or "Normal",
                "pcb":     PCB,
            })

        # Trier : Normal d'abord, puis UG, PLV, autres
        _ORDER = {"Normal": 0, "UG": 1, "PLV": 2, "UG échantillon": 3}
        products.sort(key=lambda p: (_ORDER.get(p["type"], 9), p["nom"]))

        _cache_products = products
        return products

    except Exception as e:
        print(f"[catalogue] get_products: {e}")
        return []


def get_taxes() -> list:
    """Taux d'imposition HubSpot (hs_tax_rate_group_id sur les line items)."""
    return [
        {"id": "115968336", "label": "TVA Antilles 2%",                        "value": 2.0},
        {"id": "115991071", "label": "TVA complément alimentaire Corse 2.1%",  "value": 2.1},
        {"id": "116915187", "label": "TVA Luxembourg 3%",                      "value": 3.0},
        {"id": "115989351", "label": "TVA complément alimentaire 5.5%",        "value": 5.5},
        {"id": "116087659", "label": "TVA suisse 8.1%",                        "value": 8.1},
        {"id": "117518330", "label": "TVA Belgique 21%",                       "value": 21.0},
    ]


def invalidate_cache():
    global _cache_products, _cache_taxes
    _cache_products = None
    _cache_taxes    = None


def _safe_float(v) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0

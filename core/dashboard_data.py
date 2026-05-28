"""
core/dashboard_data.py
Données HubSpot pour le dashboard performance — intégré dans naali_planner.
"""
import requests
import time
import concurrent.futures
from datetime import date, datetime, timezone, timedelta
from calendar import monthrange
import holidays
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HUBSPOT_API_KEY, HUB_ID, PROFILES

_ro_equipe_cache: dict = {}
_RO_CACHE_TTL = 300
_dn_benchmark_cache: dict = {}
_DN_CACHE_TTL = 600
_data_periode_cache: dict = {}
_DATA_CACHE_TTL = 300
_comparatif_cache: dict = {}
_COMPARATIF_CACHE_TTL = 600

# ── Config ────────────────────────────────────────────────────────────────────
OWNER_ID = "727665403"
USER_ID  = PROFILES["727665403"]["user_id"]
HUB_ID   = HUB_ID
BASE            = "https://api.hubapi.com"
PIPELINE_COM    = "1543644371"
PIPELINE_AGENTS = "1543733493"

AGENTS = {
    "78016487":  {"name": "F. Boachon"},
    "76786553":  {"name": "S. Dolibeau"},
    "77373625":  {"name": "E. Lecomte"},
    "76832397":  {"name": "C. Crampe"},
    "76786567":  {"name": "A. Ciprut"},
    "76786571":  {"name": "G. Kohn"},
    "77373626":  {"name": "S. Lecomte"},
    "78734677":  {"name": "H. Etienne"},
    "76786566":  {"name": "A. Herreros"},
    "76786552":  {"name": "M. Moreac"},
    "76786551":  {"name": "F. Gallon"},
    "76786563":  {"name": "C. Jeanpierre"},
    "76786565":  {"name": "C. Bac"},
    "76786569":  {"name": "R. Cadeville"},
    "77373623":  {"name": "D. Bitton"},
    "76786568":  {"name": "O. Lacoste"},
    "76786562":  {"name": "C. Moreac"},
    "77373622":  {"name": "C. Waldner"},
    "76786560":  {"name": "S. Levecq"},
    "78016488":  {"name": "C. Devemy"},
    "78016486":  {"name": "C. Michel"},
    "76786555":  {"name": "L. Casse"},
    "76786550":  {"name": "D. Isvy"},
    "78016482":  {"name": "B. Bariseau"},
    "78734675":  {"name": "V. Brios"},
    "77373624":  {"name": "A. Touitou"},
    "78016492":  {"name": "A. Lefort"},
    "78734676":  {"name": "G. Morin"},
    "78016490":  {"name": "V. Chupin"},
    "78016483":  {"name": "C. Lelegard"},
    "76786549":  {"name": "V. Itturalde"},
    "31838468":  {"name": "E. Flegeo"},
    "31113493":  {"name": "I. Tayach"},
    "78016491":  {"name": "E. Nueil"},
    "76786548":  {"name": "J. Levecq"},
    "77373621":  {"name": "A. Napoleoni"},
    "32492118":  {"name": "L. Gonzales"},
    "29604960":  {"name": "M. Delalande"},
    "32877351":  {"name": "C. Danten"},
}

COMMERCIAUX = {
    "727665403": {"name": "Amir Ounissi",    "user_id": "74415642",  "initials": "AO"},
    "78146570":  {"name": "Icham Benaissa",  "user_id": "78146570",  "initials": "IB"},
    "32059428":  {"name": "Fatima Brahim",   "user_id": "32059428",  "initials": "FB"},
    "30058900":  {"name": "Emelyne Lahaies", "user_id": "30058900",  "initials": "EL"},
    "32320882":  {"name": "Jérémy Le Feur",  "user_id": "32320882",  "initials": "JL"},
    "33361505":  {"name": "Lamia Chabane",   "user_id": "33361505",  "initials": "LC"},
}

MOIS_FR = ["Jan.", "Fév.", "Mar.", "Avr.", "Mai", "Juin",
           "Juil.", "Août", "Sep.", "Oct.", "Nov.", "Déc."]

# ── Catalogue actif DN (12 références commerciales) ───────────────────────────
CATALOGUE_ACTIF = [
    "Gommes Anti Stress x42",
    "Gommes Anti Stress x60",
    "Zen Fraise",
    "Magnésium +",
    "Cheveux - Pousse et Force",
    "Dream",
    "Sachet Anti Stress",
    "Collagène Citron-Vert Menthe",
    "Éclat - Teint et hydratation",
    "Cycle",
    "Ménopause",
    "Digestion",
]

# Variantes de noms acceptées dans HubSpot
CATALOGUE_ALIASES = {
    "Gommes Anti Stress x42":       {"Gommes Anti Stress x42", "Anti Stress x42"},
    "Gommes Anti Stress x60":       {"Gommes Anti Stress x60"},
    "Zen Fraise":                   {"Zen Fraise", "Zen", "Zen - goût fraise", "Zen - gout fraise"},
    "Magnésium +":                  {"Magnésium +", "Magnésium+"},
    "Collagène Citron-Vert Menthe": {"Collagène Citron-Vert Menthe", "Collagène", "Collagene"},
    "Sachet Anti Stress":           {"Sachet Anti Stress", "Sachet découverte Gommes Anti-Stress x20"},
}

# Les "5 fantastiques" — références phares prioritaires
CINQ_FANTASTIQUES = {
    "Gommes Anti Stress x42",
    "Gommes Anti Stress x60",
    "Sachet Anti Stress",
    "Zen Fraise",
    "Magnésium +",
    "Dream",
    "Collagène Citron-Vert Menthe",
    "Cheveux - Pousse et Force",
}

STAGE_LABELS = {
    "2110945486": "Précommande",
    "2870908123": "En cours",
    "2110945485": "Complément à envoyer",
    "2110945489": "À finaliser ADV",
    "2110945491": "Clôturée",
}

POTENTIEL_ORDER = {"Prioritaires": 0, "Secondaires": 1, "Non Prioritaires": 2}

# Congés connus par owner_id → set de dates (date objects)
CONGES = {
    OWNER_ID: {  # Amir Ounissi
        date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 31),
    },
}

# Poids par weekday (0=lundi … 6=dimanche)
_JOUR_POIDS = {0: 0.8, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.0}  # vendredi=0, sam/dim absents


def jours_travailles(debut: str, fin: str, owner_id: str = OWNER_ID) -> float:
    """
    Nombre de jours terrain équivalents entre debut et fin (inclus).
    - Lundi : 0.8 (pas le matin)
    - Mardi–Jeudi : 1.0
    - Vendredi, Samedi, Dimanche : 0
    - Jours fériés français : 0
    - Congés connus du commercial : 0
    """
    fr_holidays = holidays.France()
    conges = CONGES.get(owner_id, set())
    d = datetime.strptime(debut, "%Y-%m-%d").date()
    d_fin = datetime.strptime(fin, "%Y-%m-%d").date()
    total = 0.0
    while d <= d_fin:
        poids = _JOUR_POIDS.get(d.weekday(), 0.0)
        if poids > 0 and d not in fr_holidays and d not in conges:
            total += poids
        d += timedelta(days=1)
    return round(total, 2)


def _h():
    return {"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"}


def _safe_float(v) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def _fmt_date(raw: str) -> str:
    s = (raw or "")[:10]
    if len(s) == 10:
        y, m, d = s.split("-")
        return f"{d}/{m}/{y[2:]}"
    return ""


def _to_ms(date_str: str, end_of_day: bool = False) -> int:
    """'YYYY-MM-DD' → millisecondes UTC. end_of_day=True ajoute 23h59m59s."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp() * 1000)


# ── Requête HubSpot avec retry sur 429 ───────────────────────────────────────

def _post(url: str, payload: dict, timeout: int = 15) -> dict:
    """POST avec retry automatique sur 429 (rate limit)."""
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=_h(), timeout=timeout)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 0.5 * (attempt + 1)))
                time.sleep(min(wait, 3))
                continue
            return r
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise
            time.sleep(0.5)
    return None


# ── CA par période (deals closedate) ─────────────────────────────────────────

def _sum_deals_period(debut: str, fin: str, owner_id: str = OWNER_ID, pipeline: str = None) -> float:
    """Somme des deals (closedate dans [debut, fin]). owner_id=None → tous owners."""
    try:
        filters = [
            {"propertyName": "closedate", "operator": "GTE", "value": _to_ms(debut)},
            {"propertyName": "closedate", "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
            {"propertyName": "pipeline",  "operator": "EQ",  "value": pipeline or PIPELINE_COM},
        ]
        if owner_id:
            filters.append({"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id})
        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": ["amount"],
            "limit": 200,
        }
        total, after = 0.0, None
        while True:
            if after:
                payload["after"] = after
            r = _post(f"{BASE}/crm/v3/objects/deals/search", payload)
            if r is None or r.status_code != 200:
                print(f"[data] _sum_deals_period {debut}→{fin} status={getattr(r,'status_code','timeout')}")
                break
            data = r.json()
            for deal in data.get("results", []):
                total += _safe_float(deal.get("properties", {}).get("amount"))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return total
    except Exception as e:
        print(f"[data] _sum_deals_period {debut}→{fin}: {e}")
        return 0.0


def _count_implantations(debut: str, fin: str, owner_id: str = OWNER_ID) -> int:
    """Nb deals Implantation créés dans la période."""
    try:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline",         "operator": "EQ",  "value": PIPELINE_COM},
                {"propertyName": "hubspot_owner_id", "operator": "EQ",  "value": owner_id},
                {"propertyName": "type_de_commande", "operator": "EQ",  "value": "Implantation"},
                {"propertyName": "createdate",       "operator": "GTE", "value": _to_ms(debut)},
                {"propertyName": "createdate",       "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
            ]}],
            "properties": ["dealname"],
            "limit": 1,
        }
        r = _post(f"{BASE}/crm/v3/objects/deals/search", payload)
        return r.json().get("total", 0) if (r and r.status_code == 200) else 0
    except Exception as e:
        print(f"[data] _count_implantations: {e}")
        return 0


MEETING_TYPE_LABELS = {
    "Visite client":     "Visite client",
    "Rendez-vous client":"RDV client",
    "Visite prospection":"Visite prospect",
    "Formation":         "Formation",
}

def _get_meetings_par_type(debut: str, fin: str, owner_id: str = OWNER_ID) -> dict:
    """Nb meetings par hs_activity_type dans la période (paginé)."""
    try:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_timestamp",     "operator": "GTE", "value": _to_ms(debut)},
                {"propertyName": "hs_timestamp",     "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
                {"propertyName": "hubspot_owner_id", "operator": "EQ",  "value": owner_id},
            ]}],
            "properties": ["hs_activity_type"],
            "limit": 200,
        }
        counts, after = {}, None
        while True:
            if after:
                payload["after"] = after
            r = _post(f"{BASE}/crm/v3/objects/meetings/search", payload)
            if not r or r.status_code != 200:
                break
            data = r.json()
            for m in data.get("results", []):
                t = (m.get("properties", {}).get("hs_activity_type") or "Non défini").strip()
                counts[t] = counts.get(t, 0) + 1
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        total = sum(counts.values())
        # Ordre d'affichage
        ordre = ["Visite client", "Visite prospection", "Rendez-vous client", "Formation"]
        par_type_ordonne = {k: counts[k] for k in ordre if k in counts}
        for k, v in counts.items():
            if k not in par_type_ordonne:
                par_type_ordonne[k] = v
        return {"total": total, "par_type": par_type_ordonne}
    except Exception as e:
        print(f"[data] _get_meetings_par_type: {e}")
        return {"total": 0, "par_type": {}}


def _get_commandes(debut: str, fin: str, limit: int = 25, owner_id: str = OWNER_ID, pipeline: str = None) -> list:
    """Deals d'un pipeline créés dans la période."""
    try:
        filters = [
            {"propertyName": "pipeline",   "operator": "EQ",  "value": pipeline or PIPELINE_COM},
            {"propertyName": "createdate", "operator": "GTE", "value": _to_ms(debut)},
            {"propertyName": "createdate", "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
        ]
        if owner_id:
            filters.append({"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id})
        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": ["dealname", "dealstage", "amount", "closedate",
                           "type_de_commande", "createdate"],
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
            "limit": limit,
        }
        r = _post(f"{BASE}/crm/v3/objects/deals/search", payload)
        if not r or r.status_code != 200:
            return []
        orders = []
        for deal in r.json().get("results", []):
            p        = deal.get("properties", {})
            stage    = p.get("dealstage", "")
            type_cmd = p.get("type_de_commande") or "Réassort"
            orders.append({
                "id":         deal["id"],
                "nom":        p.get("dealname", ""),
                "stage":      STAGE_LABELS.get(stage, stage or "—"),
                "montant":    _safe_float(p.get("amount")),
                "date":       _fmt_date(p.get("closedate") or p.get("createdate") or ""),
                "type":       type_cmd,
                "is_implant": type_cmd.lower() == "implantation",
            })
        return orders
    except Exception as e:
        print(f"[data] _get_commandes: {e}")
        return []


def _get_goals_periode(debut: str, fin: str, user_id: str = USER_ID) -> dict:
    """Somme des objectifs mensuels pour tous les mois dans [debut, fin]."""
    dt = datetime.strptime(debut, "%Y-%m-%d").replace(day=1)
    dt_fin = datetime.strptime(fin, "%Y-%m-%d")
    total = {"objectif_ca": 0.0, "objectif_implant": 0}
    while dt <= dt_fin:
        g = _get_goals_mois(dt.strftime("%Y-%m-%d"), user_id)
        total["objectif_ca"]     += g["objectif_ca"]
        total["objectif_implant"] += g["objectif_implant"]
        if dt.month == 12:
            dt = dt.replace(year=dt.year + 1, month=1)
        else:
            dt = dt.replace(month=dt.month + 1)
    return total


def _get_goals_mois(debut: str, user_id: str = USER_ID) -> dict:
    """Objectifs HubSpot Goals pour le mois contenant 'debut'."""
    result = {"objectif_ca": 0.0, "objectif_implant": 0}
    try:
        dt = datetime.strptime(debut, "%Y-%m-%d")
        premier = dt.replace(day=1).strftime("%Y-%m-%d")
        dernier_j = monthrange(dt.year, dt.month)[1]
        dernier = dt.replace(day=dernier_j).strftime("%Y-%m-%d")
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_assignee_user_id", "operator": "EQ",  "value": user_id},
                {"propertyName": "hs_start_datetime",   "operator": "GTE", "value": f"{premier}T00:00:00Z"},
                {"propertyName": "hs_start_datetime",   "operator": "LTE", "value": f"{dernier}T23:59:59Z"},
            ]}],
            "properties": ["hs_goal_name", "hs_target_amount"],
            "limit": 50,
        }
        r = _post(f"{BASE}/crm/v3/objects/goal_targets/search", payload)
        if not r or r.status_code != 200:
            return result
        for g in r.json().get("results", []):
            p     = g["properties"]
            nom   = (p.get("hs_goal_name") or "").lower()
            cible = _safe_float(p.get("hs_target_amount"))
            if cible <= 0:
                continue
            if "ca" in nom and "terrain" in nom:
                result["objectif_ca"] = cible
            elif "implantation" in nom and "terrain" in nom:
                result["objectif_implant"] = int(cible)
        return result
    except Exception as e:
        print(f"[data] _get_goals_mois: {e}")
        return result


# ── Données période ───────────────────────────────────────────────────────────

def get_ro_equipe(debut: str, fin: str) -> dict:
    """R/O moyen de l'équipe Naali pour la période. Résultat mis en cache 5 min."""
    key = (debut, fin)
    now = time.time()
    if key in _ro_equipe_cache:
        ts, val = _ro_equipe_cache[key]
        if now - ts < _RO_CACHE_TTL:
            return val

    # Séquentiel par commercial pour éviter le rate-limiting HubSpot
    ros = {}
    for oid, info in COMMERCIAUX.items():
        try:
            ca  = _sum_deals_period(debut, fin, oid)
            obj = _get_goals_periode(debut, fin, info["user_id"])["objectif_ca"]
            if obj > 0:
                ros[oid] = round(ca / obj * 100)
        except Exception as e:
            print(f"[ro_equipe] {oid}: {e}")

    ro_equipe = round(sum(ros.values()) / len(ros)) if ros else None
    result = {"ro_equipe": ro_equipe, "detail": ros}
    # Ne pas cacher un résultat vide ou tous à zéro (signe d'erreur API)
    if ros and any(v > 0 for v in ros.values()):
        _ro_equipe_cache[key] = (now, result)
    return result


def _get_precommandes_stats(debut: str, fin: str, owner_id: str = OWNER_ID) -> dict:
    """Nb et montant total des deals en Précommande actifs (toutes dates)."""
    STAGE_PRECOMMANDE = "2110945486"
    try:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "pipeline",         "operator": "EQ", "value": PIPELINE_COM},
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                {"propertyName": "dealstage",        "operator": "EQ", "value": STAGE_PRECOMMANDE},
            ]}],
            "properties": ["amount"],
            "limit": 200,
        }
        nb, montant, after = 0, 0.0, None
        while True:
            if after:
                payload["after"] = after
            r = _post(f"{BASE}/crm/v3/objects/deals/search", payload)
            if not r or r.status_code != 200:
                break
            data = r.json()
            for deal in data.get("results", []):
                nb += 1
                montant += _safe_float(deal.get("properties", {}).get("amount"))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return {"nb": nb, "montant": round(montant, 2)}
    except Exception as e:
        print(f"[data] _get_precommandes_stats: {e}")
        return {"nb": 0, "montant": 0.0}


def _count_deals_period(debut: str, fin: str, owner_id: str = None, pipeline: str = None) -> int:
    """Nombre total de deals (closedate dans [debut, fin])."""
    try:
        filters = [
            {"propertyName": "closedate", "operator": "GTE", "value": _to_ms(debut)},
            {"propertyName": "closedate", "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
            {"propertyName": "pipeline",  "operator": "EQ",  "value": pipeline or PIPELINE_COM},
        ]
        if owner_id:
            filters.append({"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id})
        r = _post(f"{BASE}/crm/v3/objects/deals/search",
                  {"filterGroups": [{"filters": filters}], "properties": ["amount"], "limit": 1})
        return r.json().get("total", 0) if r and r.status_code == 200 else 0
    except Exception as e:
        print(f"[data] _count_deals_period: {e}")
        return 0


def get_data_periode(debut: str, fin: str, owner_id: str = OWNER_ID, user_id: str = USER_ID, pipeline: str = None) -> dict:
    """Tous les KPIs + commandes pour une période [debut, fin] (format YYYY-MM-DD)."""
    cache_key = f"{debut}|{fin}|{owner_id}|{pipeline}"
    now = time.time()
    if cache_key in _data_periode_cache:
        ts, val = _data_periode_cache[cache_key]
        if now - ts < _DATA_CACHE_TTL:
            return val

    is_agent = (pipeline == PIPELINE_AGENTS)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        f_ca    = ex.submit(_sum_deals_period, debut, fin, owner_id, pipeline)
        f_cmd   = ex.submit(_get_commandes, debut, fin, 30, owner_id, pipeline)
        f_count = ex.submit(_count_deals_period, debut, fin, owner_id, pipeline)

        if not is_agent:
            f_implant  = ex.submit(_count_implantations, debut, fin, owner_id)
            f_meetings = ex.submit(_get_meetings_par_type, debut, fin, owner_id)
            f_goals    = ex.submit(_get_goals_periode, debut, fin, user_id)
            f_precom   = ex.submit(_get_precommandes_stats, debut, fin, owner_id)

        ca           = f_ca.result()
        commandes    = f_cmd.result()
        nb_commandes = f_count.result()

        if is_agent:
            implant, meetings_data, goals = 0, {"total": 0, "par_type": {}}, {"objectif_ca": 0.0, "objectif_implant": 0}
            precommandes = {"nb": 0, "montant": 0.0}
        else:
            implant       = f_implant.result()
            meetings_data = f_meetings.result()
            goals         = f_goals.result()
            precommandes  = f_precom.result()

    meetings = meetings_data["total"]

    obj_ca        = goals["objectif_ca"]
    obj_implant   = goals["objectif_implant"]
    ro_commercial = round(ca / obj_ca * 100) if obj_ca > 0 else None
    pct_ca        = min(100, ro_commercial) if ro_commercial is not None else None
    pct_implant   = min(100, round(implant / obj_implant * 100)) if obj_implant > 0 else None
    ca_commande   = round(ca / nb_commandes, 2) if nb_commandes > 0 else 0.0

    # Points de visite par jour travaillé
    _PTS = {"Visite client": 2, "Rendez-vous client": 2, "Visite prospection": 1, "Formation": 2}
    total_pts = sum(_PTS.get(t, 2) * n for t, n in meetings_data["par_type"].items())
    nb_jours  = jours_travailles(debut, fin, owner_id or OWNER_ID) if not is_agent else 0
    pts_jour  = round(total_pts / nb_jours, 1) if nb_jours > 0 else 0.0

    result = {
        "ca":                round(ca, 2),
        "implantations":     implant,
        "meetings":          meetings,
        "meetings_par_type": meetings_data["par_type"],
        "pts_jour":          pts_jour,
        "nb_jours":          nb_jours,
        "total_pts":         total_pts,
        "ca_commande":       ca_commande,
        "nb_commandes":      nb_commandes,
        "objectif_ca":       obj_ca,
        "objectif_implant":  obj_implant,
        "pct_ca":            pct_ca,
        "pct_implant":       pct_implant,
        "ro_commercial":     ro_commercial,
        "commandes":         commandes,
        "precommandes":      precommandes,
        "debut":             debut,
        "fin":               fin,
        "updated_at":        datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }
    _data_periode_cache[cache_key] = (now, result)
    return result


# ── Comparatif annuel ─────────────────────────────────────────────────────────

def get_comparatif_annuel(owner_id: str = OWNER_ID) -> dict:
    """
    CA mois par mois pour 2025 et 2026.
    Un seul pool limité à 4 workers pour ne pas saturer l'API HubSpot.
    """
    now = time.time()
    cache_key = f"comparatif|{owner_id}"
    if cache_key in _comparatif_cache:
        ts, val = _comparatif_cache[cache_key]
        if now - ts < _COMPARATIF_CACHE_TTL:
            return val

    today = date.today()

    # Construire la liste de toutes les tâches (année, mois)
    tasks = []
    for year in [2025, 2026]:
        n_mois = 12 if year < today.year else today.month
        for m in range(1, n_mois + 1):
            tasks.append((year, m))

    def fetch_one(year: int, month: int):
        days = monthrange(year, month)[1]
        ca   = _sum_deals_period(f"{year}-{month:02d}-01", f"{year}-{month:02d}-{days:02d}", owner_id)
        return (year, month), round(ca, 2)

    # Pool unique, concurrence limitée à 4
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_one, y, m) for y, m in tasks]
        for fut in concurrent.futures.as_completed(futs):
            try:
                key, ca = fut.result()
                results[key] = ca
            except Exception as e:
                print(f"[comparatif] erreur future: {e}")

    ca_2025 = [results.get((2025, m), 0.0) for m in range(1, 13)]
    ca_2026 = [results.get((2026, m), 0.0) for m in range(1, 13)]

    # Mois futurs de 2026 → None (pas de barre dans Chart.js)
    for m in range(today.month + 1, 13):
        ca_2026[m - 1] = None

    result = {
        "mois":    MOIS_FR[:],
        "ca_2025": ca_2025,
        "ca_2026": ca_2026,
    }
    _comparatif_cache[cache_key] = (time.time(), result)
    return result


# ── Portefeuille ──────────────────────────────────────────────────────────────

def get_portefeuille(owner_id: str = OWNER_ID) -> dict:
    try:
        _CLIENT_VALS = ["true"]

        def _count(extra_filter):
            payload = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                    extra_filter,
                ]}],
                "properties": ["name"],
                "limit": 1,
            }
            r = _post(f"{BASE}/crm/v3/objects/companies/search", payload)
            return r.json().get("total", 0) if (r and r.status_code == 200) else 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_c = ex.submit(_count, {"propertyName": "client_naali", "operator": "IN",     "values": _CLIENT_VALS})
            f_p = ex.submit(_count, {"propertyName": "client_naali", "operator": "NOT_IN", "values": _CLIENT_VALS})
            return {"nb_clients": f_c.result(), "nb_prospects": f_p.result()}
    except Exception as e:
        print(f"[data] get_portefeuille: {e}")
        return {"nb_clients": 0, "nb_prospects": 0}


# ── DN Produit ────────────────────────────────────────────────────────────────

def _get_all_clients(owner_id: str = None, owner_ids: list = None) -> list:
    """Fetch toutes les pharmacies clientes avec leur catalogue (paginé).
    owner_id : un seul owner. owner_ids : liste (filtre IN)."""
    clients = []
    if owner_ids:
        owner_filter = {"propertyName": "hubspot_owner_id", "operator": "IN", "values": owner_ids}
    else:
        owner_filter = {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id or OWNER_ID}
    payload = {
        "filterGroups": [{"filters": [
            owner_filter,
            {"propertyName": "client_naali",     "operator": "IN",  "values": ["true"]},
        ]}],
        "properties": ["name", "catalogue_naali_reference", "potentiel", "city", "hubspot_owner_id"],
        "limit": 100,
    }
    after = None
    while True:
        if after:
            payload["after"] = after
        r = _post(f"{BASE}/crm/v3/objects/companies/search", payload, timeout=20)
        if not r or r.status_code != 200:
            print(f"[data] _get_all_clients status={getattr(r,'status_code','timeout')}")
            break
        data = r.json()
        for co in data.get("results", []):
            p         = co.get("properties", {})
            cat_raw   = (p.get("catalogue_naali_reference") or "")
            cat_set   = {x.strip() for x in cat_raw.split(";") if x.strip()}
            potentiel = (p.get("potentiel") or "Non Prioritaires").strip()
            clients.append({
                "id":       co["id"],
                "nom":      p.get("name", ""),
                "ville":    p.get("city", ""),
                "potentiel": potentiel,
                "cat_set":  cat_set,
                "owner_id": p.get("hubspot_owner_id", ""),
            })
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    return clients


def _has_product(cat_set: set, product: str) -> bool:
    aliases = CATALOGUE_ALIASES.get(product, {product})
    return bool(aliases & cat_set)


def _best_per_product(clients_by_owner: dict, name_map: dict) -> dict:
    """Retourne {produit: {name, pct}} pour le meilleur owner par produit."""
    best = {}
    for prod in CATALOGUE_ACTIF:
        top_oid, top_pct = None, -1.0
        for oid, clients in clients_by_owner.items():
            if not clients:
                continue
            nb  = sum(1 for c in clients if _has_product(c["cat_set"], prod))
            pct = nb / len(clients) * 100
            if pct > top_pct:
                top_pct, top_oid = pct, oid
        if top_oid:
            best[prod] = {"name": name_map.get(top_oid, top_oid), "pct": round(top_pct, 1)}
    return best


def get_dn_benchmarks(exclude_owner_id: str = None) -> dict:
    """
    DN par produit pour l'équipe Naali et pour les agents + meilleur par produit.
    exclude_owner_id : exclut ce commercial du calcul de la moyenne (pas du meilleur).
    Cache 10 min par clé (exclude_owner_id).
    """
    now = time.time()
    cache_key = f"benchmarks_{exclude_owner_id or 'all'}"
    if cache_key in _dn_benchmark_cache:
        ts, val = _dn_benchmark_cache[cache_key]
        if now - ts < _DN_CACHE_TTL:
            return val

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_naali  = ex.submit(_get_all_clients, owner_ids=list(COMMERCIAUX.keys()))
        f_agents = ex.submit(_get_all_clients, owner_ids=list(AGENTS.keys()))
        naali_clients  = f_naali.result()
        agents_clients = f_agents.result()

    # DN globale poolée — moyenne sur tous les clients
    def _pool_dn(clients):
        n = len(clients)
        return {prod: round(sum(1 for c in clients if _has_product(c["cat_set"], prod)) / n * 100, 1)
                for prod in CATALOGUE_ACTIF} if n else {}

    naali_excl = [c for c in naali_clients if c["owner_id"] != exclude_owner_id] if exclude_owner_id else naali_clients
    if not naali_excl:  # fallback si l'exclusion vide la liste (owner unique avec données)
        naali_excl = naali_clients
    naali_dn  = _pool_dn(naali_excl)
    agents_dn = _pool_dn(agents_clients)

    # Grouper par owner — best inclut tout le monde (exclude ne s'applique pas)
    from collections import defaultdict
    naali_by_owner = defaultdict(list)
    for c in naali_clients:
        naali_by_owner[c["owner_id"]].append(c)

    agent_by_owner = defaultdict(list)
    for c in agents_clients:
        agent_by_owner[c["owner_id"]].append(c)

    naali_names = {oid: info["name"].split()[0] for oid, info in COMMERCIAUX.items()}
    agent_names = {oid: info["name"] for oid, info in AGENTS.items()}

    best_naali  = _best_per_product(naali_by_owner, naali_names)
    best_agents = _best_per_product(agent_by_owner, agent_names)

    # Per-segment benchmarks
    SEGS = {
        "Prioritaires":     lambda c: c["potentiel"] == "Prioritaires",
        "Secondaires":      lambda c: c["potentiel"] == "Secondaires",
        "Non Prioritaires": lambda c: c["potentiel"] not in ("Prioritaires", "Secondaires"),
    }
    naali_segs, agents_segs, best_naali_segs, best_agents_segs = {}, {}, {}, {}
    for seg_key, seg_fn in SEGS.items():
        nc_all  = [c for c in naali_clients if seg_fn(c)]
        nc_excl = [c for c in naali_excl    if seg_fn(c)] or [c for c in naali_clients if seg_fn(c)]
        ac = [c for c in agents_clients if seg_fn(c)]
        naali_segs[seg_key]  = _pool_dn(nc_excl)
        agents_segs[seg_key] = _pool_dn(ac)
        nb_seg = defaultdict(list)
        for c in nc_all: nb_seg[c["owner_id"]].append(c)   # best = tout le monde
        ab_seg = defaultdict(list)
        for c in ac: ab_seg[c["owner_id"]].append(c)
        best_naali_segs[seg_key]  = _best_per_product(nb_seg, naali_names)
        best_agents_segs[seg_key] = _best_per_product(ab_seg, agent_names)

    result = {
        "naali":            naali_dn,
        "agents":           agents_dn,
        "best_naali":       best_naali,
        "best_agents":      best_agents,
        "naali_segs":       naali_segs,
        "agents_segs":      agents_segs,
        "best_naali_segs":  best_naali_segs,
        "best_agents_segs": best_agents_segs,
    }
    if naali_clients:  # ne pas cacher un résultat vide (erreur HubSpot transitoire)
        _dn_benchmark_cache[cache_key] = (now, result)
    return result


def get_dn_analyse(owner_id: str = OWNER_ID, owner_ids: list = None) -> dict:
    """
    Calcule la DN produit complète :
    - DN globale par produit
    - DN par potentiel (Prioritaires / Secondaires / Non Prioritaires)
    - DN catalogue par pharmacie (profondeur de gamme)
    owner_ids : liste d'owner_ids (mode agents globaux).
    """
    clients = _get_all_clients(owner_id=None if owner_ids else owner_id, owner_ids=owner_ids)
    if not clients:
        return {"error": "Aucun client trouvé", "dn_produits": [], "nb_clients": 0}

    nb_total = len(clients)
    segments = {
        "Prioritaires":     [c for c in clients if c["potentiel"] == "Prioritaires"],
        "Secondaires":      [c for c in clients if c["potentiel"] == "Secondaires"],
        "Non Prioritaires": [c for c in clients if c["potentiel"] not in ("Prioritaires", "Secondaires")],
    }

    # Clients "5 fantastiques" = ont au moins un des produits phares
    clients_5f = [c for c in clients if any(_has_product(c["cat_set"], p) for p in CINQ_FANTASTIQUES)]
    nb_5f = len(clients_5f)

    # DN par produit
    dn_produits = []
    for prod in CATALOGUE_ACTIF:
        nb_g   = sum(1 for c in clients if _has_product(c["cat_set"], prod))
        nb_g5f = sum(1 for c in clients_5f if _has_product(c["cat_set"], prod))
        seg_data = {}
        for seg_name, seg_list in segments.items():
            nb_s = sum(1 for c in seg_list if _has_product(c["cat_set"], prod))
            seg_data[seg_name] = {
                "nb":    nb_s,
                "total": len(seg_list),
                "pct":   round(nb_s / len(seg_list) * 100, 1) if seg_list else 0.0,
            }
        dn_produits.append({
            "produit":    prod,
            "nb":         nb_g,
            "total":      nb_total,
            "pct":        round(nb_g / nb_total * 100, 1) if nb_total > 0 else 0.0,
            "is_5f":      prod in CINQ_FANTASTIQUES,
            "dn_5f":      round(nb_g5f / nb_5f * 100, 1) if nb_5f > 0 else 0.0,
            "nb_5f":      nb_g5f,
            "total_5f":   nb_5f,
            "segments":   seg_data,
        })

    # Tri par DN globale croissante (opportunités en tête)
    dn_produits.sort(key=lambda x: x["pct"])

    # DN catalogue par pharmacie (profondeur de gamme)
    n_cat        = len(CATALOGUE_ACTIF)
    nb_refs_list = [
        sum(1 for prod in CATALOGUE_ACTIF if _has_product(c["cat_set"], prod))
        for c in clients
    ]
    dn_cat_list  = [n / n_cat * 100 for n in nb_refs_list]
    dn_cat_moy   = round(sum(dn_cat_list) / nb_total, 1) if nb_total else 0.0
    refs_moy     = round(sum(nb_refs_list) / nb_total, 1) if nb_total else 0.0
    ph_faibles   = sum(1 for d in dn_cat_list if d < 50)
    ph_moyen     = sum(1 for d in dn_cat_list if 50 <= d < 75)
    ph_forts     = sum(1 for d in dn_cat_list if d >= 75)

    # DN catalogue par segment
    dn_par_seg = {}
    for seg_name, seg_list in segments.items():
        if not seg_list:
            dn_par_seg[seg_name] = {"refs_moy": 0, "dn_moy": 0, "nb": 0}
            continue
        refs = [
            sum(1 for prod in CATALOGUE_ACTIF if _has_product(c["cat_set"], prod))
            for c in seg_list
        ]
        seg_dn_list = [r / n_cat * 100 for r in refs]
        dn_par_seg[seg_name] = {
            "nb":        len(seg_list),
            "refs_moy":  round(sum(refs) / len(seg_list), 1),
            "dn_moy":    round(sum(refs) / len(seg_list) / n_cat * 100, 1),
            "ph_faibles": sum(1 for d in seg_dn_list if d < 50),
            "ph_forts":   sum(1 for d in seg_dn_list if d >= 75),
        }

    return {
        "nb_clients":       nb_total,
        "nb_references":    n_cat,
        "dn_produits":      dn_produits,
        "dn_catalogue_moy": dn_cat_moy,
        "refs_moyennes":    refs_moy,
        "ph_faibles":       ph_faibles,
        "ph_moyen":         ph_moyen,
        "ph_forts":         ph_forts,
        "dn_par_segment":   dn_par_seg,
        "updated_at":       datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }


# ── Comparatif portefeuilles commerciaux ─────────────────────────────────────

def get_comparatif_portefeuilles() -> list:
    """
    Pour chaque commercial Naali : stats portefeuille client + DN + opportunités.
    Retourne une liste triée par score de potentiel décroissant.
    """
    all_clients = _get_all_clients(owner_ids=list(COMMERCIAUX.keys()))

    from collections import defaultdict
    by_owner = defaultdict(list)
    for c in all_clients:
        by_owner[c["owner_id"]].append(c)

    n_cat = len(CATALOGUE_ACTIF)
    n_5f  = len(CINQ_FANTASTIQUES)

    result = []
    for oid, info in COMMERCIAUX.items():
        clients = by_owner.get(oid, [])
        nb = len(clients)
        if nb == 0:
            result.append({
                "owner_id":      oid,
                "name":          info["name"],
                "initials":      info["initials"],
                "nb_clients":    0,
                "nb_prio":       0,
                "nb_sec":        0,
                "nb_non_prio":   0,
                "dn_global_moy": 0.0,
                "dn_5f_moy":     0.0,
                "nb_low_dn":     0,
                "nb_sans_5f":    0,
                "score_potentiel": 0,
            })
            continue

        nb_prio     = sum(1 for c in clients if c["potentiel"] == "Prioritaires")
        nb_sec      = sum(1 for c in clients if c["potentiel"] == "Secondaires")
        nb_non_prio = nb - nb_prio - nb_sec

        refs_list   = [sum(1 for p in CATALOGUE_ACTIF if _has_product(c["cat_set"], p)) for c in clients]
        refs_5f     = [sum(1 for p in CINQ_FANTASTIQUES if _has_product(c["cat_set"], p)) for c in clients]

        dn_global_moy = round(sum(refs_list) / nb / n_cat * 100, 1)
        dn_5f_moy     = round(sum(refs_5f) / nb / n_5f * 100, 1)
        nb_low_dn     = sum(1 for r in refs_list if r / n_cat * 100 < 50)
        nb_sans_5f    = sum(1 for r in refs_5f  if r == 0)

        # Score potentiel : clients prioritaires + opportunités DN (plus c'est bas, plus c'est à activer)
        score = nb_prio * 3 + nb_sec + nb_low_dn * 2 + nb_sans_5f * 2

        result.append({
            "owner_id":        oid,
            "name":            info["name"],
            "initials":        info["initials"],
            "nb_clients":      nb,
            "nb_prio":         nb_prio,
            "nb_sec":          nb_sec,
            "nb_non_prio":     nb_non_prio,
            "dn_global_moy":   dn_global_moy,
            "dn_5f_moy":       dn_5f_moy,
            "nb_low_dn":       nb_low_dn,
            "nb_sans_5f":      nb_sans_5f,
            "score_potentiel": score,
        })

    result.sort(key=lambda x: x["score_potentiel"], reverse=True)
    return result


# ── Classement clients par CA 2026 ───────────────────────────────────────────

def get_clients_ca_annee(owner_id: str = OWNER_ID, annee: int = 2026) -> list:
    """
    Tous les clients avec leur CA sur l'année donnée.
    Utilise les associations deals → companies pour un groupement fiable.
    """
    debut = f"{annee}-01-01"
    fin   = date.today().strftime("%Y-%m-%d") if annee == date.today().year else f"{annee}-12-31"

    # 1. Fetch tous les deals de la période
    filters = [
        {"propertyName": "closedate",         "operator": "GTE", "value": _to_ms(debut)},
        {"propertyName": "closedate",         "operator": "LTE", "value": _to_ms(fin, end_of_day=True)},
        {"propertyName": "pipeline",          "operator": "EQ",  "value": PIPELINE_COM},
        {"propertyName": "hubspot_owner_id",  "operator": "EQ",  "value": owner_id},
    ]
    payload = {
        "filterGroups": [{"filters": filters}],
        "properties": ["amount"],
        "limit": 200,
    }
    deal_amount: dict = {}
    after = None
    while True:
        if after:
            payload["after"] = after
        r = _post(f"{BASE}/crm/v3/objects/deals/search", payload)
        if not r or r.status_code != 200:
            break
        data = r.json()
        for deal in data.get("results", []):
            deal_amount[deal["id"]] = _safe_float(deal.get("properties", {}).get("amount"))
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break

    # 2. Associations deals → companies (batch par 100)
    ca_by_company: dict = {}
    deal_ids = list(deal_amount.keys())
    for i in range(0, len(deal_ids), 100):
        batch = deal_ids[i:i + 100]
        try:
            r = requests.post(
                f"{BASE}/crm/v4/associations/deals/companies/batch/read",
                json={"inputs": [{"id": did} for did in batch]},
                headers=_h(), timeout=15,
            )
            if r.status_code == 200:
                for res in r.json().get("results", []):
                    amount = deal_amount.get(res["from"]["id"], 0.0)
                    for assoc in res.get("to", []):
                        cid = str(assoc["toObjectId"])
                        ca_by_company[cid] = ca_by_company.get(cid, 0.0) + amount
        except Exception as e:
            print(f"[data] get_clients_ca_annee batch {i}: {e}")

    # 3. Liste clients + merge CA + DN
    clients = _get_all_clients(owner_id=owner_id)
    n_cat   = len(CATALOGUE_ACTIF)
    n_5f    = len(CINQ_FANTASTIQUES)
    result  = []
    for c in clients:
        nb_global = sum(1 for p in CATALOGUE_ACTIF if _has_product(c["cat_set"], p))
        nb_5f     = sum(1 for p in CINQ_FANTASTIQUES if _has_product(c["cat_set"], p))
        result.append({
            "id":        c["id"],
            "nom":       c["nom"],
            "ville":     c["ville"],
            "potentiel": c["potentiel"],
            "ca":        round(ca_by_company.get(c["id"], 0.0), 2),
            "dn_global": round(nb_global / n_cat * 100, 1) if n_cat else 0.0,
            "dn_5f":     round(nb_5f / n_5f * 100, 1) if n_5f else 0.0,
            "nb_refs":   nb_global,
            "nb_5f":     nb_5f,
        })
    result.sort(key=lambda x: x["ca"], reverse=True)
    return result


# ── Initial data (chargement page) ───────────────────────────────────────────

def get_initial_data() -> dict:
    """Données initiales : KPIs mois courant + portefeuille."""
    today = date.today()
    debut = today.replace(day=1).strftime("%Y-%m-%d")
    fin   = today.strftime("%Y-%m-%d")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_period = ex.submit(get_data_periode, debut, fin, OWNER_ID, USER_ID)
        f_portef = ex.submit(get_portefeuille, OWNER_ID)
        period   = f_period.result()
        portef   = f_portef.result()

    now = datetime.now()
    return {
        **period,
        "nb_clients":      portef["nb_clients"],
        "nb_prospects":    portef["nb_prospects"],
        "mois_label":      f"{MOIS_FR[now.month - 1]} {now.year}",
        "hub_id":          HUB_ID,
        "catalogue_actif": CATALOGUE_ACTIF,
        "commerciaux":     COMMERCIAUX,
        "owner_id":        OWNER_ID,
        "agents":          AGENTS,
    }

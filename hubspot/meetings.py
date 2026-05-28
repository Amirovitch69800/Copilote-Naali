import requests
from datetime import datetime, timedelta, timezone
import pytz
import sys
import os

# Ajouter le répertoire parent au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY, HUBSPOT_OWNER_ID, TEST_MODE
except ImportError:
    HUBSPOT_API_KEY = ""
    HUBSPOT_OWNER_ID = "727665403"
    TEST_MODE = True

PARIS = pytz.timezone("Europe/Paris")
BASE_URL = "https://api.hubapi.com"
HEADERS = lambda: {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json",
}

# Cache en mémoire : company_id → last_visit datetime
_cache_last_visit: dict = {}


def get_last_meeting_date(company_id: str) -> object:
    """
    Retourne la date du dernier MEETING_EVENT associé à la company.
    Source UNIQUEMENT : hs_timestamp des MEETING_EVENT.
    Méthode : associations endpoint v3 → batch read des meetings.
    Cache en mémoire.
    """
    if company_id in _cache_last_visit:
        return _cache_last_visit[company_id]

    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        _cache_last_visit[company_id] = None
        return None

    try:
        # Étape 1 : récupérer les IDs des meetings associés à la company
        url = f"{BASE_URL}/crm/v3/objects/companies/{company_id}/associations/meetings"
        resp = requests.get(url, headers=HEADERS(), timeout=10)

        if resp.status_code != 200:
            print(f"[HubSpot] Associations {company_id}: {resp.status_code}")
            _cache_last_visit[company_id] = None
            return None

        meeting_ids = [r["id"] for r in resp.json().get("results", [])]
        if not meeting_ids:
            _cache_last_visit[company_id] = None
            return None

        # Étape 2 : batch read pour récupérer hs_timestamp de chaque meeting
        batch_url = f"{BASE_URL}/crm/v3/objects/meetings/batch/read"
        payload = {
            "inputs": [{"id": mid} for mid in meeting_ids[:50]],
            "properties": ["hs_timestamp", "hs_meeting_title", "hubspot_owner_id"],
        }
        resp2 = requests.post(batch_url, json=payload, headers=HEADERS(), timeout=10)

        if resp2.status_code not in (200, 207):
            _cache_last_visit[company_id] = None
            return None

        results = resp2.json().get("results", [])
        datetimes = []
        for r in results:
            ts = r.get("properties", {}).get("hs_timestamp")
            if not ts:
                continue
            try:
                # Format ISO : "2025-01-15T09:30:00Z"
                dt_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PARIS)
                datetimes.append(dt_parsed)
            except Exception:
                try:
                    # Format ms entier : 1735826400000
                    dt_parsed = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS)
                    datetimes.append(dt_parsed)
                except Exception:
                    pass

        if not datetimes:
            _cache_last_visit[company_id] = None
            return None

        dt = max(datetimes)
        _cache_last_visit[company_id] = dt
        return dt

    except Exception as e:
        print(f"[HubSpot] Erreur get_last_meeting_date {company_id}: {e}")
        _cache_last_visit[company_id] = None
        return None


def get_existing_meetings(dt_debut: datetime, dt_fin: datetime, owner_id: str = None) -> list:
    """Créneaux déjà occupés sur une plage de dates."""
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return []

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        ts_debut = int(dt_debut.astimezone(timezone.utc).timestamp() * 1000)
        ts_fin = int(dt_fin.astimezone(timezone.utc).timestamp() * 1000)

        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hubspot_owner_id",
                            "operator": "EQ",
                            "value": str(owner_id or HUBSPOT_OWNER_ID),
                        },
                        {
                            "propertyName": "hs_timestamp",
                            "operator": "BETWEEN",
                            "value": str(ts_debut),
                            "highValue": str(ts_fin),
                        },
                    ]
                }
            ],
            "properties": ["hs_timestamp", "hs_meeting_title", "hs_meeting_end_time"],
            "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
            "limit": 100,
        }

        resp = requests.post(url, json=payload, headers=HEADERS(), timeout=10)
        if resp.status_code == 200:
            meetings = []
            for r in resp.json().get("results", []):
                props = r.get("properties", {})
                ts = props.get("hs_timestamp")
                ts_end = props.get("hs_meeting_end_time")
                if ts:
                    try:
                        dt = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS)
                        dt_e = datetime.fromtimestamp(int(ts_end) / 1000, tz=PARIS) if ts_end else dt + timedelta(hours=1)
                        duree = int((dt_e - dt).total_seconds() / 60)
                        meetings.append({
                            "hs_timestamp": int(ts),
                            "hs_meeting_title": props.get("hs_meeting_title", ""),
                            "duree_min": duree,
                        })
                    except Exception:
                        pass
            return meetings
    except Exception as e:
        print(f"[HubSpot] Erreur get_existing_meetings: {e}")

    return []


def get_meetings_this_week(owner_id: str = None) -> list:
    """Meetings créés cette semaine (bilan)."""
    from datetime import date
    today = date.today()
    lundi = today - timedelta(days=today.weekday())
    dt_debut = datetime(lundi.year, lundi.month, lundi.day, 0, 0, tzinfo=PARIS)
    dt_fin = dt_debut + timedelta(days=7)
    return get_existing_meetings(dt_debut, dt_fin, owner_id=owner_id)


def create_meeting(pharmacie: dict, visit_type: str, dt_start: datetime, refs_dn: list = None, owner_id: str = None) -> object:
    """
    Crée un MEETING_EVENT dans HubSpot.
    """
    if TEST_MODE:
        print(f"[TEST_MODE] Simulation création meeting : {pharmacie.get('nom', '')} {visit_type} {dt_start}")
        return {"id": "test_" + str(id(pharmacie)), "simulated": True}

    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        print("[HubSpot] Clé API non configurée")
        return None

    from core.planning import DUREES
    duree_min = DUREES.get(visit_type, 60)
    dt_end = dt_start + timedelta(minutes=duree_min)

    nom = pharmacie.get("nom", pharmacie.get("name", "Pharmacie"))
    titre = f"{visit_type} — {nom}"
    if refs_dn:
        titre += f" | DN: {', '.join(refs_dn[:3])}"
        if len(refs_dn) > 3:
            titre += f" +{len(refs_dn)-3}"

    _ACTIVITY_TYPE = {
        "VC": "Visite client",
        "VP": "Visite prospection",
        "RC": "Rendez-vous client",
        "RP": "Rendez-vous prospect",
        "F":  "Formation",
    }

    company_id = pharmacie.get("id_hubspot", pharmacie.get("hs_object_id", ""))

    payload = {
        "properties": {
            "hs_meeting_title": titre,
            "hs_timestamp": str(int(dt_start.astimezone(timezone.utc).timestamp() * 1000)),
            "hs_meeting_end_time": str(int(dt_end.astimezone(timezone.utc).timestamp() * 1000)),
            "hubspot_owner_id": str(owner_id or HUBSPOT_OWNER_ID),
            "hs_activity_type": _ACTIVITY_TYPE.get(visit_type, visit_type),
        },
        "associations": [],
    }

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings"
        resp = requests.post(url, json=payload, headers=HEADERS(), timeout=10)
        if resp.status_code not in (200, 201):
            print(f"[HubSpot] Erreur création meeting: {resp.status_code} {resp.text[:200]}")
            return None

        data = resp.json()
        meeting_id = data.get("id")

        # Associer au company via l'API v4 (MEETING_EVENT 0-47 → Company 0-2)
        if company_id and meeting_id:
            assoc_url = f"{BASE_URL}/crm/v4/objects/meetings/{meeting_id}/associations/default/companies/{company_id}"
            requests.put(assoc_url, headers=HEADERS(), timeout=10)

        if company_id:
            _cache_last_visit[str(company_id)] = dt_start
        return data

    except Exception as e:
        print(f"[HubSpot] Exception create_meeting: {e}")
        return None


def get_anchors_par_jour(
    jours: list,
    pharmacies_by_hubspot_id: dict,
    owner_id: str = None,
) -> dict:
    """
    Pour chaque jour de la liste, cherche les meetings HubSpot déjà planifiés.
    Récupère la company associée à chaque meeting, la matche dans pharmacies_by_hubspot_id
    pour obtenir les coordonnées GPS.
    Retourne {date_str: {"lat": float, "lon": float, "label": str}}.
    """
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return {}
    if not pharmacies_by_hubspot_id or not jours:
        return {}

    # Plage de dates couvrant tous les jours
    try:
        date_strs = []
        for j in jours:
            ds = j.get("date_str")
            if not ds:
                d = j.get("date")
                ds = d.isoformat() if hasattr(d, "isoformat") else str(d)
            date_strs.append(ds)
        if not date_strs:
            return {}
        from datetime import date as date_type
        d_debut = date_type.fromisoformat(min(date_strs))
        d_fin   = date_type.fromisoformat(max(date_strs))
        dt_debut = datetime(d_debut.year, d_debut.month, d_debut.day, 0, 0, tzinfo=PARIS)
        dt_fin   = datetime(d_fin.year,   d_fin.month,   d_fin.day,   23, 59, 59, tzinfo=PARIS)
    except Exception as e:
        print(f"[HubSpot] get_anchors_par_jour date range: {e}")
        return {}

    # Recherche meetings sur la période (on a besoin des IDs → requête directe)
    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        ts_deb = str(int(dt_debut.astimezone(timezone.utc).timestamp() * 1000))
        ts_fin = str(int(dt_fin.astimezone(timezone.utc).timestamp() * 1000))
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "BETWEEN",
                 "value": ts_deb, "highValue": ts_fin},
            ]}],
            "properties": ["hs_timestamp", "hs_meeting_title"],
            "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
            "limit": 100,
        }
        resp = requests.post(url, json=payload, headers=HEADERS(), timeout=15)
        if resp.status_code != 200:
            return {}
        raw_meetings = resp.json().get("results", [])
    except Exception as e:
        print(f"[HubSpot] get_anchors_par_jour search: {e}")
        return {}

    if not raw_meetings:
        return {}

    # Associer chaque meeting à sa date (date_str)
    meetings_by_day: dict = {}
    for m in raw_meetings:
        props = m.get("properties", {})
        ts = props.get("hs_timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS)
            ds = dt.strftime("%Y-%m-%d")
            meetings_by_day.setdefault(ds, []).append({
                "id": m["id"],
                "titre": props.get("hs_meeting_title", ""),
                "dt": dt,
            })
        except Exception:
            continue

    if not meetings_by_day:
        return {}

    # Récupérer les company associations pour tous les meetings en parallèle
    all_meeting_ids = [m["id"] for day_ms in meetings_by_day.values() for m in day_ms]
    meeting_company: dict = {}  # meeting_id → company_id

    def _fetch_company(mid):
        try:
            r = requests.get(
                f"{BASE_URL}/crm/v3/objects/meetings/{mid}/associations/companies",
                headers=HEADERS(), timeout=10,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    meeting_company[mid] = str(results[0]["id"])
        except Exception:
            pass

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_fetch_company, all_meeting_ids))

    # Construire les anchors par jour
    anchors: dict = {}
    for ds, day_meetings in meetings_by_day.items():
        for m in day_meetings:
            cid = meeting_company.get(m["id"])
            if not cid:
                continue
            pharma = pharmacies_by_hubspot_id.get(cid)
            if not pharma:
                continue
            try:
                lat = float(pharma.get("lat") or "")
                lon = float(pharma.get("lon") or "")
            except (ValueError, TypeError):
                continue
            # Premier meeting avec coords trouvé = anchor du jour
            anchors[ds] = {
                "lat": lat,
                "lon": lon,
                "label": pharma.get("nom", m["titre"]),
                "ville": pharma.get("ville", ""),
            }
            break  # un seul anchor par jour suffit

    return anchors


def create_meetings_batch(visites: list, owner_id: str = None) -> list:
    """
    Crée plusieurs meetings. Vérifie les doublons avant création :
    si un meeting existe déjà pour la même company le même jour, on le saute.
    """
    import concurrent.futures
    if not visites:
        return []

    # Déterminer la plage de dates du planning
    dt_starts = []
    for v in visites:
        try:
            dt_starts.append(datetime.fromisoformat(v["dt_start"]).astimezone(PARIS))
        except Exception:
            pass
    if not dt_starts:
        return []

    dt_debut = min(dt_starts).replace(hour=0, minute=0, second=0)
    dt_fin   = max(dt_starts).replace(hour=23, minute=59, second=59)

    # Récupérer les meetings existants sur cette période
    existants_raw = get_existing_meetings(dt_debut, dt_fin, owner_id=owner_id)

    # Construire un set (company_id, jour) déjà occupés
    # On a besoin des company_id des meetings existants → requête associations
    existants_par_jour: set = set()  # (company_id, "YYYY-MM-DD")

    _CANCELED_OUTCOMES = {"CANCELED", "CANCELLED", "canceled", "cancelled"}

    if existants_raw and not TEST_MODE:
        try:
            import concurrent.futures
            url = f"{BASE_URL}/crm/v3/objects/meetings/search"
            ts_deb = str(int(dt_debut.astimezone(timezone.utc).timestamp() * 1000))
            ts_fin_str = str(int(dt_fin.astimezone(timezone.utc).timestamp() * 1000))
            payload = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ",
                     "value": str(owner_id or HUBSPOT_OWNER_ID)},
                    {"propertyName": "hs_timestamp", "operator": "BETWEEN",
                     "value": ts_deb, "highValue": ts_fin_str},
                ]}],
                "properties": ["hs_timestamp", "hs_meeting_outcome"],
                "limit": 200,
            }
            resp = requests.post(url, json=payload, headers=HEADERS(), timeout=10)
            if resp.status_code == 200:
                # Filtrer les CANCELED côté Python — plus fiable que l'opérateur NOT_IN HubSpot
                existing_meetings = [
                    m for m in resp.json().get("results", [])
                    if (m.get("properties", {}).get("hs_meeting_outcome") or "") not in _CANCELED_OUTCOMES
                ]
                print(f"[HubSpot] Dedup: {len(existing_meetings)} meeting(s) actifs trouvés sur la période")

                def _get_assoc_day(m):
                    mid = m["id"]
                    ts = m.get("properties", {}).get("hs_timestamp")
                    if not ts:
                        return
                    try:
                        dt = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS)
                        day = dt.strftime("%Y-%m-%d")
                        r = requests.get(
                            f"{BASE_URL}/crm/v3/objects/meetings/{mid}/associations/companies",
                            headers=HEADERS(), timeout=8,
                        )
                        if r.status_code == 200:
                            for res in r.json().get("results", []):
                                existants_par_jour.add((str(res["id"]), day))
                    except Exception:
                        pass

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                    list(ex.map(_get_assoc_day, existing_meetings))
        except Exception as e:
            print(f"[HubSpot] create_meetings_batch dedup: {e}")

    # Préparer les candidats valides (parsing + dedup avant envoi parallèle)
    candidats = []  # [(idx, v, pharma, visit_type, dt_start, refs_dn)]
    skipped = []
    for idx, v in enumerate(visites):
        pharma = v.get("pharmacie", {})
        visit_type = v.get("type_visite", "VP")
        refs_dn = v.get("refs_manquantes", [])
        nom_pharma = pharma.get("nom", pharma.get("name", "?"))

        dt_start_str = v.get("dt_start", "")
        heure_debut  = v.get("heure_debut", "")
        date_jour    = v.get("date_jour", "")
        if not dt_start_str and heure_debut and date_jour:
            dt_start_str = f"{date_jour}T{heure_debut}:00"

        if not dt_start_str:
            print(f"[HubSpot] Skip {nom_pharma}: dt_start manquant")
            skipped.append({"visite": v, "raison": "dt_start manquant", "idx": idx})
            continue

        try:
            dt_parsed = datetime.fromisoformat(dt_start_str)
            if dt_parsed.tzinfo is None:
                dt_parsed = PARIS.localize(dt_parsed)
            dt_start = dt_parsed.astimezone(PARIS)
        except Exception as e:
            print(f"[HubSpot] Skip {nom_pharma}: dt_start invalide ({dt_start_str}) — {e}")
            skipped.append({"visite": v, "raison": "dt_start invalide", "idx": idx})
            continue

        company_id = str(pharma.get("id_hubspot", pharma.get("hs_object_id", "")))
        day = dt_start.strftime("%Y-%m-%d")

        if company_id and (company_id, day) in existants_par_jour:
            skipped.append({"visite": v, "raison": "déjà planifié ce jour", "idx": idx})
            print(f"[HubSpot] Skip doublon: {nom_pharma} le {day}")
            continue

        candidats.append((idx, v, pharma, visit_type, dt_start, refs_dn))

    # Créer tous les meetings en parallèle
    results = []
    if candidats:
        def _creer(args):
            idx, v, pharma, visit_type, dt_start, refs_dn = args
            result = create_meeting(pharma, visit_type, dt_start, refs_dn, owner_id=owner_id)
            return idx, v, pharma, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures_res = list(ex.map(_creer, candidats))

        for idx, v, pharma, result in futures_res:
            if result:
                results.append({"visite": v, "hubspot": result, "idx": idx})
            else:
                nom_pharma = pharma.get("nom", pharma.get("name", "?"))
                print(f"[HubSpot] Échec création: {nom_pharma}")
                skipped.append({"visite": v, "raison": "erreur API", "idx": idx})

    print(f"[HubSpot] Batch terminé: {len(results)} créés, {len(skipped)} ignorés")
    return results


def detecter_conflits_mois(visites: list, owner_id: str = None) -> list:
    """
    Pour chaque visite planifiée, vérifie si un meeting du même type existe déjà
    pour la même company dans le même mois (côté HubSpot).
    Retourne la liste des conflits détectés.
    """
    if not visites or not HUBSPOT_API_KEY:
        return []

    from calendar import monthrange
    import re, concurrent.futures

    # Déterminer les mois couverts par le planning
    months = set()
    for v in visites:
        try:
            dt = datetime.fromisoformat(v["dt_start"]).astimezone(PARIS)
            months.add((dt.year, dt.month))
        except Exception:
            pass
    if not months:
        return []

    def _normalise(hs_type: str, titre: str) -> str:
        m = re.match(r'^(VC|VP|RC|RP|F)\s*[–—\-]', titre.strip(), re.IGNORECASE)
        if m:
            return m.group(1).upper()
        _map = {
            "visite client": "VC", "rendez-vous client": "VC",
            "visite prospection": "VP", "visite prospect": "VP", "rendez-vous prospect": "VP",
            "relance client": "RC", "relance prospect": "RP", "formation": "F",
        }
        return _map.get((hs_type or "").lower().strip(), hs_type or "")

    existing = []  # [{company_id, type, dt}]

    for year, month in months:
        _, last_day = monthrange(year, month)
        deb = datetime(year, month, 1, 0, 0, tzinfo=PARIS)
        fin = datetime(year, month, last_day, 23, 59, 59, tzinfo=PARIS)
        iso_deb = deb.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        iso_fin = fin.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            url = f"{BASE_URL}/crm/v3/objects/meetings/search"
            payload = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ",
                     "value": str(owner_id or HUBSPOT_OWNER_ID)},
                    {"propertyName": "hs_timestamp", "operator": "GTE", "value": iso_deb},
                    {"propertyName": "hs_timestamp", "operator": "LTE", "value": iso_fin},
                ]}],
                "properties": ["hs_timestamp", "hs_activity_type", "hs_meeting_title"],
                "limit": 200,
            }
            resp = requests.post(url, json=payload, headers=HEADERS(), timeout=15)
            if resp.status_code != 200:
                continue

            meetings_raw = resp.json().get("results", [])

            def _get_company(m):
                mid = m["id"]
                props = m.get("properties", {})
                ts = props.get("hs_timestamp")
                if not ts:
                    return None
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PARIS)
                except Exception:
                    return None
                norm_type = _normalise(
                    props.get("hs_activity_type", ""),
                    props.get("hs_meeting_title", "")
                )
                try:
                    r = requests.get(
                        f"{BASE_URL}/crm/v3/objects/meetings/{mid}/associations/companies",
                        headers=HEADERS(), timeout=8
                    )
                    if r.status_code == 200:
                        ids = [res["id"] for res in r.json().get("results", [])]
                        if ids:
                            return {"company_id": str(ids[0]), "type": norm_type, "dt": dt}
                except Exception:
                    pass
                return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                batch = list(ex.map(_get_company, meetings_raw))
            existing.extend([r for r in batch if r])

        except Exception as e:
            print(f"[HubSpot] detecter_conflits_mois {year}/{month}: {e}")

    # Construire le dictionnaire des meetings existants
    existing_map = {}  # (company_id, type, year, month) → dt
    for e in existing:
        key = (e["company_id"], e["type"], e["dt"].year, e["dt"].month)
        if key not in existing_map:
            existing_map[key] = e["dt"]

    # Identifier les conflits (un seul par pharmacie+type+mois)
    conflits = []
    seen = set()
    for v in visites:
        try:
            pharma = v.get("pharmacie", {})
            company_id = str(pharma.get("id_hubspot", pharma.get("hs_object_id", "")))
            visit_type = v.get("type_visite", "")
            dt = datetime.fromisoformat(v["dt_start"]).astimezone(PARIS)
            key = (company_id, visit_type, dt.year, dt.month)
            if company_id and key in existing_map and key not in seen:
                seen.add(key)
                conflits.append({
                    "pharmacie_nom": pharma.get("nom", ""),
                    "type_visite": visit_type,
                    "date_planifiee": dt.strftime("%d/%m/%Y"),
                    "date_existant": existing_map[key].strftime("%d/%m/%Y"),
                })
        except Exception:
            pass

    return conflits


def is_retard(pharmacie: dict, last_visit: object) -> bool:
    """Prioritaires > 30j, Secondaires > 60j."""
    if last_visit is None:
        # Jamais visité → considéré en retard si Prioritaires
        potentiel = pharmacie.get("potentiel", "")
        return potentiel in ("Prioritaires", "Secondaires")

    now = datetime.now(PARIS)
    delta = (now - last_visit.astimezone(PARIS)).days
    potentiel = pharmacie.get("potentiel", "")

    if potentiel == "Prioritaires":
        return delta > 30
    elif potentiel == "Secondaires":
        return delta > 60
    return False


def is_proche(pharmacie: dict, last_visit: object) -> bool:
    """Échéance dans les 10 prochains jours."""
    if last_visit is None:
        return False

    now = datetime.now(PARIS)
    delta = (now - last_visit.astimezone(PARIS)).days
    potentiel = pharmacie.get("potentiel", "")

    if potentiel == "Prioritaires":
        # Échéance à 30j, proche si entre 20j et 30j passés
        return 20 <= delta <= 30
    elif potentiel == "Secondaires":
        # Échéance à 60j, proche si entre 50j et 60j passés
        return 50 <= delta <= 60
    return False


def enrichir_avec_statuts(pharmacies: list, max_workers: int = 20) -> list:
    """Ajoute is_retard, is_proche, last_visit à chaque pharmacie. Parallélisé."""
    import concurrent.futures

    def _enrich_one(p):
        pc = dict(p)
        company_id = pc.get("id_hubspot", pc.get("hs_object_id", ""))
        last_visit = get_last_meeting_date(str(company_id)) if company_id else None
        pc["last_visit"] = last_visit.isoformat() if last_visit else None
        pc["is_retard"] = is_retard(pc, last_visit)
        pc["is_proche"] = is_proche(pc, last_visit)
        return pc

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_enrich_one, pharmacies))


def get_company_ids_planifies(nb_jours: int = 14, owner_id: str = None) -> set:
    """
    Retourne l'ensemble des IDs HubSpot (str) des companies qui ont déjà
    un meeting planifié dans les nb_jours prochains jours pour cet owner.
    Requête légère : 1 search + N associations en parallèle.
    """
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return set()

    now    = datetime.now(timezone.utc)
    dt_fin = now + timedelta(days=nb_jours)

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ",
                 "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "BETWEEN",
                 "value": str(int(now.timestamp() * 1000)),
                 "highValue": str(int(dt_fin.timestamp() * 1000))},
            ]}],
            "properties": ["hs_timestamp"],
            "limit": 200,
        }
        resp = requests.post(url, json=payload, headers=HEADERS(), timeout=10)
        if resp.status_code != 200:
            return set()

        meetings = resp.json().get("results", [])
        if not meetings:
            return set()

        company_ids: set = set()

        def _fetch_assoc(mid):
            try:
                r = requests.get(
                    f"{BASE_URL}/crm/v3/objects/meetings/{mid}/associations/companies",
                    headers=HEADERS(), timeout=10,
                )
                if r.status_code == 200:
                    for res in r.json().get("results", []):
                        company_ids.add(str(res["id"]))
            except Exception:
                pass

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(_fetch_assoc, [m["id"] for m in meetings]))

        return company_ids

    except Exception as e:
        print(f"[HubSpot] Erreur get_company_ids_planifies: {e}")
        return set()


def check_doublons(owner_id: str = None, nb_jours: int = 90) -> list:
    """
    Détecte les meetings en doublon : même company + même jour.
    Cherche sur les nb_jours derniers jours + les 30 prochains jours.
    Retourne une liste de groupes de doublons avec le meeting à garder et ceux à supprimer.
    """
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return []

    now = datetime.now(timezone.utc)
    dt_debut = now - timedelta(days=nb_jours)
    dt_fin   = now + timedelta(days=30)

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ",
                 "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "BETWEEN",
                 "value": str(int(dt_debut.timestamp() * 1000)),
                 "highValue": str(int(dt_fin.timestamp() * 1000))},
            ]}],
            "properties": ["hs_timestamp", "hs_meeting_title", "hs_meeting_outcome", "hs_createdate"],
            "limit": 200,
        }
        resp = requests.post(url, json=payload, headers=HEADERS(), timeout=15)
        if resp.status_code != 200:
            return []
        meetings = resp.json().get("results", [])
    except Exception as e:
        print(f"[HubSpot] check_doublons search: {e}")
        return []

    if not meetings:
        return []

    # Récupérer les company_id pour chaque meeting
    meeting_info: dict = {}  # mid → {dt, title, outcome, created, company_id}
    for m in meetings:
        props = m.get("properties", {})
        ts = props.get("hs_timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS)
        except Exception:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(PARIS)
            except Exception:
                continue
        created_ts = props.get("hs_createdate")
        try:
            created = datetime.fromtimestamp(int(created_ts) / 1000, tz=PARIS) if created_ts else None
        except Exception:
            created = None
        meeting_info[m["id"]] = {
            "dt": dt,
            "title": props.get("hs_meeting_title", "") or "",
            "outcome": props.get("hs_meeting_outcome", "") or "",
            "created": created,
            "company_id": None,
        }

    import concurrent.futures
    def _fetch_company(mid):
        try:
            r = requests.get(
                f"{BASE_URL}/crm/v3/objects/meetings/{mid}/associations/companies",
                headers=HEADERS(), timeout=10,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results and mid in meeting_info:
                    meeting_info[mid]["company_id"] = str(results[0]["id"])
        except Exception:
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_fetch_company, list(meeting_info.keys())))

    # Grouper par (company_id, jour)
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for mid, info in meeting_info.items():
        cid = info.get("company_id")
        if not cid:
            continue
        day = info["dt"].strftime("%Y-%m-%d")
        groups[(cid, day)].append({"id": mid, **info})

    # Ne garder que les groupes avec doublons
    doublons = []
    for (cid, day), items in groups.items():
        if len(items) < 2:
            continue
        # Trier : garder COMPLETED en premier, sinon le plus ancien
        items.sort(key=lambda x: (
            0 if x["outcome"] == "COMPLETED" else 1,
            x["created"] or datetime.min.replace(tzinfo=PARIS)
        ))
        garder = items[0]
        supprimer = items[1:]
        doublons.append({
            "company_id": cid,
            "jour": day,
            "garder": {"id": garder["id"], "title": garder["title"], "heure": garder["dt"].strftime("%H:%M"), "outcome": garder["outcome"]},
            "supprimer": [{"id": d["id"], "title": d["title"], "heure": d["dt"].strftime("%H:%M"), "outcome": d["outcome"]} for d in supprimer],
        })

    doublons.sort(key=lambda x: x["jour"])
    return doublons


def cancel_meetings_for_day(date_iso: str, owner_id: str = None) -> dict:
    """
    Marque TOUS les meetings d'une journée comme CANCELLED sur HubSpot.
    Ne supprime pas — conserve la trace dans le CRM.
    Returns: {"cancelled": n, "errors": n, "total": n, "ids": [...]}
    """
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return {"cancelled": 0, "errors": 0, "total": 0, "ids": []}

    try:
        from datetime import date as _date
        d = _date.fromisoformat(date_iso)
        dt_debut = datetime(d.year, d.month, d.day, 0, 0, tzinfo=PARIS)
        dt_fin   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=PARIS)
        ts_deb = str(int(dt_debut.astimezone(timezone.utc).timestamp() * 1000))
        ts_fin = str(int(dt_fin.astimezone(timezone.utc).timestamp() * 1000))

        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "BETWEEN", "value": ts_deb, "highValue": ts_fin},
            ]}],
            "properties": ["hs_timestamp", "hs_meeting_title", "hs_meeting_outcome"],
            "limit": 100,
        }
        resp = requests.post(f"{BASE_URL}/crm/v3/objects/meetings/search",
                             json=payload, headers=HEADERS(), timeout=15)
        if resp.status_code != 200:
            print(f"[HubSpot] cancel_meetings_for_day search {date_iso}: {resp.status_code}")
            return {"cancelled": 0, "errors": 0, "total": 0, "ids": []}

        meetings = resp.json().get("results", [])
        total = len(meetings)
        cancelled, errors, ids = 0, 0, []

        for m in meetings:
            mid = m["id"]
            r = requests.patch(
                f"{BASE_URL}/crm/v3/objects/meetings/{mid}",
                json={"properties": {"hs_meeting_outcome": "CANCELED"}},
                headers=HEADERS(), timeout=10,
            )
            if r.status_code in (200, 204):
                cancelled += 1
                ids.append(mid)
            else:
                errors += 1
                print(f"[HubSpot] cancel_meetings_for_day PATCH {mid}: {r.status_code}")

        return {"cancelled": cancelled, "errors": errors, "total": total, "ids": ids}

    except Exception as e:
        print(f"[HubSpot] cancel_meetings_for_day {date_iso}: {e}")
        return {"cancelled": 0, "errors": 0, "total": 0, "ids": [], "error": str(e)}


def delete_meetings_batch(ids: list) -> dict:
    """Supprime une liste de meetings par leurs IDs HubSpot."""
    if not ids or not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return {"deleted": 0, "errors": []}

    deleted = 0
    errors = []
    BATCH = 100
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        payload = {"inputs": [{"id": str(mid)} for mid in batch]}
        try:
            r = requests.post(
                f"{BASE_URL}/crm/v3/objects/meetings/batch/archive",
                headers=HEADERS(), json=payload, timeout=15,
            )
            if r.status_code in (200, 204):
                deleted += len(batch)
            else:
                errors.append(f"batch {i//BATCH+1}: {r.status_code}")
        except Exception as e:
            errors.append(str(e))

    return {"deleted": deleted, "errors": errors}


def cancel_meeting(meeting_id: str) -> bool:
    """Marque un meeting unique comme CANCELED sur HubSpot."""
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return False
    try:
        r = requests.patch(
            f"{BASE_URL}/crm/v3/objects/meetings/{meeting_id}",
            json={"properties": {"hs_meeting_outcome": "CANCELED"}},
            headers=HEADERS(), timeout=10,
        )
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[HubSpot] cancel_meeting {meeting_id}: {e}")
        return False


def update_meeting_time(meeting_id: str, dt_start: datetime, dt_end: datetime) -> bool:
    """Met à jour les horaires d'un meeting HubSpot existant."""
    if not HUBSPOT_API_KEY or HUBSPOT_API_KEY.startswith("pat-eu1-VOTRE"):
        return False
    try:
        ts_start = str(int(dt_start.astimezone(timezone.utc).timestamp() * 1000))
        ts_end   = str(int(dt_end.astimezone(timezone.utc).timestamp() * 1000))
        r = requests.patch(
            f"{BASE_URL}/crm/v3/objects/meetings/{meeting_id}",
            json={"properties": {
                "hs_timestamp": ts_start,
                "hs_meeting_end_time": ts_end,
            }},
            headers=HEADERS(), timeout=10,
        )
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[HubSpot] update_meeting_time {meeting_id}: {e}")
        return False


def clear_cache():
    """Vide le cache last_visit."""
    _cache_last_visit.clear()

"""
hubspot/suivi.py
Suivi des rendez-vous, prises de note, nom du commercial.
"""
import requests
from datetime import datetime, timedelta, timezone, date
import pytz
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import HUBSPOT_API_KEY, HUBSPOT_OWNER_ID, HUB_ID
except ImportError:
    HUBSPOT_API_KEY = ""
    HUBSPOT_OWNER_ID = "727665403"
    HUB_ID = "143439337"

PARIS = pytz.timezone("Europe/Paris")
BASE_URL = "https://api.hubapi.com"

_owner_cache: dict = {}

# Cache TTL simple — évite les appels répétés à HubSpot sur navigations rapides
_ttl_cache: dict = {}   # key → (timestamp, value)
_TTL = 300              # 5 minutes

def _cache_get(key):
    entry = _ttl_cache.get(key)
    if entry and (datetime.now(timezone.utc).timestamp() - entry[0]) < _TTL:
        return entry[1]
    return None

def _cache_set(key, value):
    _ttl_cache[key] = (datetime.now(timezone.utc).timestamp(), value)
    return value

def invalidate_cache():
    _ttl_cache.clear()


def _h():
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }


# ─── Nom du commercial ────────────────────────────────────────────────────────

def get_owner_name(owner_id: str) -> str:
    """Appel HubSpot owners API, mis en cache au démarrage."""
    if owner_id in _owner_cache:
        return _owner_cache[owner_id]
    if not HUBSPOT_API_KEY:
        return "Commercial"
    try:
        r = requests.get(f"{BASE_URL}/crm/v3/owners/{owner_id}", headers=_h(), timeout=10)
        if r.status_code == 200:
            d = r.json()
            name = f"{d.get('firstName','').strip()} {d.get('lastName','').strip()}".strip()
            _owner_cache[owner_id] = name or d.get("email", "Commercial")
            return _owner_cache[owner_id]
    except Exception as e:
        print(f"[HubSpot] get_owner_name: {e}")
    _owner_cache[owner_id] = "Commercial"
    return "Commercial"


# ─── Meetings par semaine (offset=0 courante, -1 précédente) ──────────────────

def get_meetings_week(offset: int = -1, owner_id: str = None, use_cache: bool = True) -> list:
    """
    Meetings lundi–dimanche de la semaine courante (offset=0) ou N-1 (offset=-1).
    Enrichis avec company associée + statut note.
    """
    if not HUBSPOT_API_KEY:
        return []

    _ck = f"meetings_week:{owner_id or HUBSPOT_OWNER_ID}:{offset}"
    if use_cache:
        cached = _cache_get(_ck)
        if cached is not None:
            return cached

    today = date.today()
    lundi = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    dimanche = lundi + timedelta(days=6)

    iso_deb = datetime(lundi.year, lundi.month, lundi.day, 0, 0,
                       tzinfo=PARIS).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_fin = datetime(dimanche.year, dimanche.month, dimanche.day, 23, 59, 59,
                       tzinfo=PARIS).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "GTE", "value": iso_deb},
                {"propertyName": "hs_timestamp", "operator": "LTE", "value": iso_fin},
            ]}],
            "properties": [
                "hs_timestamp", "hs_meeting_title", "hs_activity_type",
                "hs_meeting_outcome", "hs_meeting_end_time",
            ],
            "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
            "limit": 100,
        }
        r = requests.post(url, json=payload, headers=_h(), timeout=15)
        if r.status_code != 200:
            return []

        meetings = []
        for m in r.json().get("results", []):
            props = m.get("properties", {})
            ts = props.get("hs_timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PARIS)
            except Exception:
                continue
            titre = props.get("hs_meeting_title", "")
            meetings.append({
                "id": m["id"],
                "titre": titre,
                "type": _normalise_type(props.get("hs_activity_type", ""), titre),
                "outcome": props.get("hs_meeting_outcome", "") or "SCHEDULED",
                "dt": dt.isoformat(),
                "date_label": _fr_date(dt),
                "heure": dt.strftime("%H:%M"),
                "company_id": "",
                "company_nom": "",
            })

        _enrichir_companies(meetings)
        # Enrichir les notes sur une fenêtre large pour couvrir les CR faits j+1
        _enrichir_notes(meetings, days=21, owner_id=owner_id)
        if use_cache:
            _cache_set(_ck, meetings)
        return meetings

    except Exception as e:
        print(f"[HubSpot] get_meetings_week(offset={offset}): {e}")
        return []


def get_meetings_last_week() -> list:
    return get_meetings_week(offset=-1)


# ─── Meetings 7 derniers jours (prises de note) ───────────────────────────────

def get_meetings_for_notes(days: int = 7, date_from: str = None, date_to: str = None, owner_id: str = None, use_cache: bool = True) -> list:
    """
    Meetings enrichis avec statut note.
    Si date_from/date_to (format YYYY-MM-DD) sont fournis, ils priment sur `days`.
    """
    if not HUBSPOT_API_KEY:
        return []

    _ck = f"meetings_notes:{owner_id or HUBSPOT_OWNER_ID}:{days}:{date_from}:{date_to}"
    if use_cache:
        cached = _cache_get(_ck)
        if cached is not None:
            return cached

    if date_from and date_to:
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d")
            d_to   = datetime.strptime(date_to,   "%Y-%m-%d")
            dt_deb = PARIS.localize(d_from.replace(hour=0,  minute=0,  second=0))
            dt_fin = PARIS.localize(d_to.replace(  hour=23, minute=59, second=59))
            # Pour _enrichir_notes : calculer le nombre de jours de la plage
            days = max(1, (d_to - d_from).days + 1)
        except ValueError:
            date_from = date_to = None

    if not (date_from and date_to):
        today  = date.today()
        dt_deb = datetime(today.year, today.month, today.day, 0, 0, tzinfo=PARIS) - timedelta(days=days)
        dt_fin = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=PARIS)

    # Filtrer en ISO — HubSpot accepte les deux formats mais ISO est plus fiable
    iso_deb = dt_deb.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_fin = dt_fin.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/search"
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id or HUBSPOT_OWNER_ID)},
                {"propertyName": "hs_timestamp", "operator": "GTE", "value": iso_deb},
                {"propertyName": "hs_timestamp", "operator": "LTE", "value": iso_fin},
            ]}],
            "properties": ["hs_timestamp", "hs_meeting_title", "hs_activity_type", "hs_meeting_outcome"],
            "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}],
            "limit": 100,
        }
        r = requests.post(url, json=payload, headers=_h(), timeout=15)
        if r.status_code != 200:
            return []

        meetings = []
        for m in r.json().get("results", []):
            props = m.get("properties", {})
            ts = props.get("hs_timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PARIS)
            except Exception:
                continue
            titre = props.get("hs_meeting_title", "")
            meetings.append({
                "id": m["id"],
                "titre": titre,
                "type": _normalise_type(props.get("hs_activity_type", ""), titre),
                "outcome": props.get("hs_meeting_outcome", "") or "SCHEDULED",
                "dt": dt.isoformat(),
                "date_label": _fr_date(dt),
                "heure": dt.strftime("%H:%M"),
                "company_id": "",
                "company_nom": "",
                "has_note": False,
                "has_photo": False,
            })

        _enrichir_companies(meetings)
        _enrichir_notes(meetings, days=days, owner_id=owner_id)
        if use_cache:
            _cache_set(_ck, meetings)
        return meetings

    except Exception as e:
        print(f"[HubSpot] get_meetings_for_notes: {e}")
        return []


# ─── Update outcome ───────────────────────────────────────────────────────────

def update_meeting_outcome(meeting_id: str, outcome: str) -> bool:
    """PATCH hs_meeting_outcome sur un meeting."""
    try:
        url = f"{BASE_URL}/crm/v3/objects/meetings/{meeting_id}"
        r = requests.patch(url, json={"properties": {"hs_meeting_outcome": outcome}},
                           headers=_h(), timeout=10)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[HubSpot] update_meeting_outcome {meeting_id}: {e}")
        return False


# ─── Helpers internes ─────────────────────────────────────────────────────────

def _enrichir_companies(meetings: list):
    """Ajoute company_id + company_nom à chaque meeting — 2 appels batch au lieu de N*2."""
    if not meetings:
        return
    try:
        # 1. Batch associations meetings → companies (1 seul appel)
        ra = requests.post(
            f"{BASE_URL}/crm/v4/associations/meetings/companies/batch/read",
            json={"inputs": [{"id": m["id"]} for m in meetings]},
            headers=_h(), timeout=15,
        )
        if ra.status_code not in (200, 207):
            return
        # meeting_id → company_id
        meeting_to_cid = {}
        for item in ra.json().get("results", []):
            mid = str(item.get("from", {}).get("id", ""))
            tos = item.get("to", [])
            if mid and tos:
                meeting_to_cid[mid] = str(tos[0]["toObjectId"])

        company_ids = list(set(meeting_to_cid.values()))
        if not company_ids:
            return

        # 2. Batch read companies (1 seul appel)
        rb = requests.post(
            f"{BASE_URL}/crm/v3/objects/companies/batch/read",
            json={"inputs": [{"id": cid} for cid in company_ids], "properties": ["name"]},
            headers=_h(), timeout=15,
        )
        cid_to_nom = {}
        if rb.status_code in (200, 207):
            for c in rb.json().get("results", []):
                cid_to_nom[str(c["id"])] = c.get("properties", {}).get("name", "")

        # Affecter aux meetings
        for m in meetings:
            cid = meeting_to_cid.get(str(m["id"]), "")
            m["company_id"]  = cid
            m["company_nom"] = cid_to_nom.get(cid, "")
    except Exception as e:
        print(f"[HubSpot] _enrichir_companies batch: {e}")


def _enrichir_notes(meetings: list, days: int = 7, owner_id: str = None):
    """Ajoute has_note, has_photo, last_note_text, last_note_date.

    Recherche les notes par owner + date (triées desc) puis associations notes→companies.
    Évite le nids[:20] qui ratait les notes récentes pour les companies avec beaucoup d'historique.
    """
    company_ids = {m["company_id"] for m in meetings if m.get("company_id")}
    if not company_ids:
        return

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    _oid = str(owner_id or HUBSPOT_OWNER_ID)

    try:
        # 1. Rechercher les notes récentes par owner, triées desc, paginer jusqu'à 200
        all_notes = []
        after = None
        while len(all_notes) < 200:
            body = {
                "filterGroups": [{"filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": _oid},
                    {"propertyName": "hs_timestamp", "operator": "GTE", "value": str(cutoff_ms)},
                ]}],
                "properties": ["hs_timestamp", "hs_attachment_ids", "hs_note_body"],
                "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}],
                "limit": 100,
            }
            if after:
                body["after"] = after
            rs = requests.post(
                f"{BASE_URL}/crm/v3/objects/notes/search",
                json=body, headers=_h(), timeout=15,
            )
            if rs.status_code not in (200, 207):
                break
            data = rs.json()
            results = data.get("results", [])
            all_notes.extend(results)
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after or not results:
                break

        if not all_notes:
            return

        note_ids = [n["id"] for n in all_notes]
        note_props = {n["id"]: n.get("properties", {}) for n in all_notes}

        # 2. Batch associations notes → companies (sens inverse)
        rb = requests.post(
            f"{BASE_URL}/crm/v4/associations/notes/companies/batch/read",
            json={"inputs": [{"id": nid} for nid in note_ids]},
            headers=_h(), timeout=15,
        )
        if rb.status_code not in (200, 207):
            return

        note_to_cid: dict = {}
        for item in rb.json().get("results", []):
            nid = str(item.get("from", {}).get("id", ""))
            to_list = item.get("to", [])
            if nid and to_list:
                note_to_cid[nid] = str(to_list[0]["toObjectId"])

        # 3. Construire statut par company
        cid_status: dict = {}
        for note in all_notes:
            nid = str(note["id"])
            cid = note_to_cid.get(nid)
            if not cid or cid not in company_ids:
                continue
            props = note_props[nid]
            ts_raw = props.get("hs_timestamp", "")
            try:
                ts_int = int(ts_raw) if str(ts_raw).isdigit() else int(
                    datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp() * 1000
                )
            except Exception:
                continue

            if cid not in cid_status:
                cid_status[cid] = {"has_note": False, "has_photo": False,
                                   "last_note_text": None, "last_note_date": None, "_ts": 0}
            st = cid_status[cid]
            st["has_note"] = True
            if (props.get("hs_attachment_ids") or "").strip():
                st["has_photo"] = True
            if ts_int > st["_ts"]:
                st["_ts"] = ts_int
                st["last_note_text"] = (props.get("hs_note_body") or "").strip() or None
                try:
                    dt = datetime.fromtimestamp(ts_int / 1000, tz=PARIS)
                    st["last_note_date"] = dt.strftime("%d/%m %H:%M")
                except Exception:
                    st["last_note_date"] = None

        # 4. Affecter aux meetings
        for m in meetings:
            s = cid_status.get(m.get("company_id", ""), {})
            m["has_note"]       = s.get("has_note", False)
            m["has_photo"]      = s.get("has_photo", False)
            m["last_note_text"] = s.get("last_note_text")
            m["last_note_date"] = s.get("last_note_date")

    except Exception as e:
        print(f"[HubSpot] _enrichir_notes search: {e}")


def get_company_note_status(company_id: str, days: int = 7) -> dict:
    """
    Cherche les notes associées à la company créées dans les N derniers jours.
    Retourne {"has_note": bool, "has_photo": bool, "last_note_text": str|None, "last_note_date": str|None}.
    """
    empty = {"has_note": False, "has_photo": False, "last_note_text": None, "last_note_date": None}
    try:
        url = f"{BASE_URL}/crm/v3/objects/companies/{company_id}/associations/notes"
        r = requests.get(url, headers=_h(), timeout=10)
        if r.status_code != 200:
            return empty

        note_ids = [n["id"] for n in r.json().get("results", [])]
        if not note_ids:
            return empty

        cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

        batch_url = f"{BASE_URL}/crm/v3/objects/notes/batch/read"
        payload = {
            "inputs": [{"id": nid} for nid in note_ids[:20]],
            "properties": ["hs_timestamp", "hs_attachment_ids", "hs_note_body"],
        }
        rb = requests.post(batch_url, json=payload, headers=_h(), timeout=10)
        if rb.status_code not in (200, 207):
            return empty

        notes_with_ts = []
        has_photo = False

        for note in rb.json().get("results", []):
            props = note.get("properties", {})
            ts = props.get("hs_timestamp", "")
            try:
                ts_int = int(ts) if str(ts).isdigit() else int(
                    datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000
                )
            except Exception:
                continue
            if (props.get("hs_attachment_ids") or "").strip():
                has_photo = True
            text = (props.get("hs_note_body") or "").strip() or None
            try:
                dt = datetime.fromtimestamp(ts_int / 1000, tz=PARIS)
                date_label = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                date_label = None
            notes_with_ts.append({"ts": ts_int, "text": text, "date": date_label})

        notes_with_ts.sort(key=lambda n: n["ts"], reverse=True)
        notes_list = [{"text": n["text"], "date": n["date"]} for n in notes_with_ts[:3]]
        has_note = bool(notes_list)
        last = notes_list[0] if notes_list else {}

        return {
            "has_note": has_note,
            "has_photo": has_photo,
            "last_note_text": last.get("text"),
            "last_note_date": last.get("date"),
            "notes_list": notes_list,
        }

    except Exception as e:
        print(f"[HubSpot] get_company_note_status {company_id}: {e}")
        return empty


def _upload_file_hs(file_bytes: bytes, filename: str):
    """
    Upload un fichier vers HubSpot Files API v3.
    Retourne l'ID du fichier (str) ou None en cas d'erreur.
    """
    import mimetypes
    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
    try:
        r = requests.post(
            f"{BASE_URL}/files/v3/files",
            headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}"},
            files={"file": (filename, file_bytes, mime)},
            data={
                "options": '{"access":"PRIVATE","overwrite":false,"duplicateValidationStrategy":"NONE"}',
                "folderPath": "/naali/compte-rendus",
            },
            timeout=30,
        )
        if r.status_code in (200, 201):
            fid = str(r.json().get("id", ""))
            print(f"[HubSpot] fichier uploadé id={fid} ({filename})")
            return fid
        print(f"[HubSpot] upload fichier {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"[HubSpot] _upload_file_hs: {e}")
        return None


def create_company_note(company_id: str, body: str, owner_id: str = None,
                        file_bytes: bytes = None, file_name: str = None,
                        files: list = None) -> bool:
    """
    Crée une note HubSpot associée à une company.
    - file_bytes + file_name : rétro-compatibilité (1 fichier)
    - files : liste de (bytes, filename) pour multi-photos
    Les IDs de fichiers sont joints par ';' dans hs_attachment_ids.
    """
    import concurrent.futures
    try:
        props = {
            "hs_note_body": body,
            "hs_timestamp": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "hubspot_owner_id": str(owner_id or HUBSPOT_OWNER_ID),
        }
        # Normaliser en liste unique
        all_files = list(files or [])
        if file_bytes and file_name:
            all_files.insert(0, (file_bytes, file_name))

        if all_files:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futs = [ex.submit(_upload_file_hs, fb, fn) for fb, fn in all_files]
                ids = [f.result() for f in futs]
            ids = [i for i in ids if i]
            if ids:
                props["hs_attachment_ids"] = ";".join(ids)

        payload = {
            "properties": props,
            "associations": [{
                "to": {"id": str(company_id)},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}],
            }],
        }
        r = requests.post(f"{BASE_URL}/crm/v3/objects/notes", json=payload, headers=_h(), timeout=15)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[HubSpot] create_company_note {company_id}: {e}")
        return False


def _normalise_type(hs_type: str, titre: str) -> str:
    """
    Retourne le code court du type de visite (VC, VP, RC, RP, F).
    Priorité : préfixe du titre (créé par le planner) > hs_activity_type.
    """
    import re
    # 1. Extraire depuis le titre : "VC – ...", "VP – ...", "VC — ...", "VC - ..."
    m = re.match(r'^(VC|VP|RC|RP|F)\s*[–—\-]', titre.strip(), re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 2. Mapper les labels HubSpot en français
    _map = {
        "visite client":       "VC",
        "rendez-vous client":  "VC",
        "visite prospect":     "VP",
        "rendez-vous prospect":"VP",
        "relance client":      "RC",
        "relance prospect":    "RP",
        "formation":           "F",
    }
    return _map.get((hs_type or "").lower().strip(), hs_type or "")


def _fr_date(dt: datetime) -> str:
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    return f"{jours[dt.weekday()]} {dt.strftime('%d/%m')}"

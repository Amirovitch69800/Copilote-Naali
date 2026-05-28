import sys
import os

# Ajouter le répertoire racine au path Python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── DEMO MODE — doit être détecté AVANT tout import de db (init_db() lancé à l'import) ──
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

if DEMO_MODE:
    from demo.mock_data import (
        mock_today, mock_kpis, mock_agenda, mock_brief_meeting,
        mock_brief_company, mock_post_rdv, mock_search,
        mock_planificateur, mock_portefeuille,
    )

    class _DemoDb:
        def get_users(self): return {}
        def get_offres(self, **kw): return []
        def get_next_actions(self, *a, **kw): return []
        def upsert_signal(self, *a, **kw): pass
        def create_next_action(self, *a, **kw): return None
        def upsert_user(self, *a, **kw): pass
        def create_offre(self, *a, **kw): return {}
        def update_offre(self, *a, **kw): return {}
        def toggle_offre_statut(self, *a, **kw): return {}
        def delete_offre(self, *a, **kw): return True
        def update_next_action_status(self, *a, **kw): return True

    _db = _DemoDb()
else:
    import db as _db  # init_db() appelé ici — nécessite un filesystem inscriptible

from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
from datetime import datetime, date, timedelta
import pytz
import io

from config import PROFILES, HUB_ID, TEST_MODE, SECRET_KEY, HUBSPOT_OWNER_ID, OWNER_NAME, CSV_PATH, HOME_LAT, HOME_LON

from core.calendrier import get_prochain_lundi, get_jours_ouvrables, get_semaines, formater_date
from core.ics_export import generer_ics
from core.filtres import (
    filter_by_departements, filter_clients, filter_prospects,
    filter_by_origines, filter_by_villes, sort_by_potentiel,
    get_departements_disponibles, get_villes_par_dept, get_origines_disponibles, is_client,
    filter_by_deciles, filter_by_produits_cibles,
    get_deciles_disponibles, get_produits_disponibles,
)
from core.dn_engine import calculer_groupes_dn, CATALOGUE
from core.itineraire import optimiser_itineraire, repartir_sur_jours, resume_itineraire
from core.planning import construire_planning_jour, construire_planning_semaines
from hubspot.meetings import (
    get_last_meeting_date, get_existing_meetings, get_meetings_this_week,
    create_meetings_batch, enrichir_avec_statuts, is_retard, is_proche,
    get_anchors_par_jour, get_company_ids_planifies,
    check_doublons, delete_meetings_batch,
    cancel_meeting, update_meeting_time,
)
from core.itineraire import optimiser_journees
from hubspot.companies import load_pharmacies_hubspot, invalidate_pharmacies_cache

PARIS = pytz.timezone("Europe/Paris")

app = Flask(__name__, template_folder="templates")
app.config["JSON_ENSURE_ASCII"] = False
app.secret_key = SECRET_KEY

@app.template_filter("euros")
def euros_filter(value):
    try:
        return f"{float(value):,.0f} €".replace(",", "\u202f")
    except (TypeError, ValueError):
        return "0 €"

# Fusionner les profils config.py + SQLite (la DB prend la priorité pour les nouveaux)
if not DEMO_MODE:
    PROFILES.update(_db.get_users())

if DEMO_MODE:
    _DEMO_OWNER = "demo"
    PROFILES[_DEMO_OWNER] = {
        "owner_id":  _DEMO_OWNER,
        "name":      "Amir Ounissi",
        "email":     "demo@naali.fr",
        "csv_path":  "",
        "home_lat":  43.2965,
        "home_lon":  5.3698,
        "home_city": "Marseille",
        "user_id":   _DEMO_OWNER,
    }

def _profile() -> dict:
    oid = session.get("owner_id", HUBSPOT_OWNER_ID)
    return PROFILES.get(oid, PROFILES[HUBSPOT_OWNER_ID])

def _owner_id() -> str:
    return _profile()["owner_id"]

def _csv_path() -> str:
    path = _profile()["csv_path"]
    if os.path.exists(os.path.join(ROOT, path)):
        return path
    raise FileNotFoundError(path)

def _home_coords() -> tuple:
    p = _profile()
    return p.get("home_lat"), p.get("home_lon")

def _load_pharmacies(force_refresh: bool = False) -> list:
    """Source unique de données pharmacies : HubSpot API (cache TTL 30 min)."""
    return load_pharmacies_hubspot(owner_id=_owner_id(), force_refresh=force_refresh)

@app.errorhandler(FileNotFoundError)
def handle_csv_missing(e):
    return jsonify({"error": "csv_manquant", "message": str(e)}), 404

if DEMO_MODE:
    @app.before_request
    def _demo_autologin():
        from flask import request as _req
        if _req.endpoint in ("static", "login", "logout"):
            return
        if "owner_id" not in session:
            session["owner_id"] = _DEMO_OWNER

@app.route("/api/cache/refresh", methods=["POST"])
def api_cache_refresh():
    """Vide le cache companies + meetings pour forcer un rechargement depuis HubSpot."""
    from hubspot.meetings import clear_cache as clear_meetings_cache
    invalidate_pharmacies_cache(_owner_id())
    try:
        clear_meetings_cache()
    except Exception:
        pass
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET"])
def login():
    if DEMO_MODE:
        session["owner_id"] = _DEMO_OWNER
        return redirect(url_for("copilote"))
    return render_template("login.html", profiles=list(PROFILES.values()))

@app.route("/api/login/check", methods=["POST"])
def api_login_check():
    owner_id = (request.json or {}).get("owner_id", "")
    if owner_id not in PROFILES:
        return jsonify({"error": "Profil introuvable"}), 404
    return jsonify({"has_password": _db.has_password(owner_id)})

@app.route("/api/login/authenticate", methods=["POST"])
def api_login_authenticate():
    data = request.json or {}
    owner_id = data.get("owner_id", "")
    password = data.get("password", "")
    if owner_id not in PROFILES:
        return jsonify({"error": "Profil introuvable"}), 400
    if not _db.check_password(owner_id, password):
        return jsonify({"error": "Mot de passe incorrect"}), 401
    session["owner_id"] = owner_id
    return jsonify({"ok": True, "redirect": url_for("index")})

@app.route("/api/login/set-password", methods=["POST"])
def api_login_set_password():
    data = request.json or {}
    owner_id = data.get("owner_id", "")
    password = data.get("password", "")
    if owner_id not in PROFILES:
        return jsonify({"error": "Profil introuvable"}), 400
    # Si une session existe, seul l'utilisateur connecté peut définir son propre mot de passe
    current_session = session.get("owner_id")
    if current_session and current_session != owner_id:
        return jsonify({"error": "Non autorisé"}), 403
    if len(password) < 6:
        return jsonify({"error": "Min. 6 caractères requis"}), 400
    _db.set_password(owner_id, password)
    session["owner_id"] = owner_id
    return jsonify({"ok": True, "redirect": url_for("index")})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------------------------------------------------------
# Auth middleware — protège toutes les routes sauf login/logout/api-login
# ---------------------------------------------------------------------------

_PUBLIC_ENDPOINTS = frozenset({
    "login", "logout", "static",
    "api_login_check", "api_login_authenticate", "api_login_set_password",
})

@app.before_request
def require_login():
    """Redirige vers /login si aucune session active (sauf routes publiques)."""
    if DEMO_MODE:
        return
    endpoint = request.endpoint
    if endpoint is None or endpoint in _PUBLIC_ENDPOINTS:
        return
    if "owner_id" not in session:
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Non authentifié", "redirect": "/login"}), 401
        return redirect(url_for("login"))

# Cache nom du commercial — isolé par owner_id
_owner_name_cache: dict = {}

def _get_owner_name() -> str:
    oid = _owner_id()
    if oid not in _owner_name_cache:
        from hubspot.suivi import get_owner_name
        _owner_name_cache[oid] = get_owner_name(oid)
    return _owner_name_cache[oid]

# ---------------------------------------------------------------------------
# Route principale
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "owner_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("copilote"))

@app.route("/copilote")
def copilote():
    if "owner_id" not in session:
        return redirect(url_for("login"))
    return render_template("copilote.html")
# ---------------------------------------------------------------------------
# Copilote V2 — API today
# ---------------------------------------------------------------------------

@app.route("/api/today")
def api_today():
    """Meetings du jour + points restants + CR manquants."""
    if DEMO_MODE:
        return jsonify(mock_today())
    from hubspot.suivi import get_meetings_for_notes, get_meetings_week
    import concurrent.futures

    today_str = date.today().isoformat()
    now = datetime.now(PARIS)

    # Meetings de la semaine courante, filtrer sur aujourd'hui
    week = get_meetings_week(offset=0, owner_id=_owner_id())
    _CANCELED = {"CANCELED", "CANCELLED", "canceled", "cancelled"}
    today_meetings = [
        m for m in week
        if m.get("dt", "").startswith(today_str)
        and (m.get("outcome") or "") not in _CANCELED
    ]

    # CR manquants sur 7 jours (meetings passés sans note)
    past7 = get_meetings_for_notes(days=7, owner_id=_owner_id())
    _SKIP = _CANCELED | {"SCHEDULED", "scheduled", ""}
    cr_manquants = [
        m for m in past7
        if not m.get("has_note")
        and (m.get("outcome") or "") not in _SKIP
        and m.get("dt", "") < now.isoformat()
    ]

    # Points du jour (capacité selon le jour de semaine)
    _CREDITS_PAR_JOUR = {0: 8, 1: 10, 2: 10, 3: 10, 4: 8}
    _CREDITS_VISITE = {"VC": 2, "VP": 1, "RC": 2, "RP": 2, "F": 2}
    wd = date.today().weekday()
    points_max = _CREDITS_PAR_JOUR.get(wd, 8)
    points_used = sum(_CREDITS_VISITE.get(m.get("type", ""), 1) for m in today_meetings)
    points_left = max(0, points_max - points_used)

    # CA mois + YTD + objectif
    ca_mois = ca_ytd = ca_objectif = 0.0
    try:
        import concurrent.futures as _cf
        from hubspot.deals import get_ca_mois_courant, get_ca_ytd
        with _cf.ThreadPoolExecutor(max_workers=2) as ex:
            f_m = ex.submit(get_ca_mois_courant)
            f_y = ex.submit(get_ca_ytd)
            ca_mois, ca_ytd = f_m.result(), f_y.result()
        pharmacies = _load_pharmacies()
        ca_objectif = sum(float(p.get("ca_2025") or p.get("ca") or 0) for p in filter_clients(pharmacies))
    except Exception:
        pass

    # Offres actives pertinentes pour les visites du jour
    offres_jour = []
    try:
        today_types = {m.get("type", "").upper() for m in today_meetings}
        has_clients  = bool(today_types & {"VC", "RC", "F"})
        has_prospects = bool(today_types & {"VP", "RP"})
        for o in _db.get_offres(statut="active"):
            if not o.get("sans_date_limite"):
                if o.get("date_fin")   and o["date_fin"]   < today_str: continue
                if o.get("date_debut") and o["date_debut"] > today_str: continue
            cible = o.get("cible_offre", "")
            if "prospect" in cible and has_prospects:
                offres_jour.append(o)
            elif "prospect" not in cible and has_clients:
                offres_jour.append(o)
    except Exception:
        pass

    # Prochaines actions échues ou du jour
    actions_echeances = []
    try:
        for a in _db.get_next_actions(_owner_id(), status="a_faire"):
            if a.get("due_date", "") <= today_str:
                actions_echeances.append(a)
    except Exception:
        pass

    return jsonify({
        "today_meetings":    today_meetings,
        "points_max":        points_max,
        "points_used":       points_used,
        "points_left":       points_left,
        "cr_manquants":      cr_manquants,
        "ca_mois":           ca_mois,
        "ca_ytd":            ca_ytd,
        "ca_objectif":       ca_objectif,
        "offres_jour":       offres_jour,
        "actions_echeances": actions_echeances,
        "hub_id": HUB_ID,
    })

# ---------------------------------------------------------------------------
# Copilote V2 — API brief visite
# ---------------------------------------------------------------------------

@app.route("/api/brief/<meeting_id>")
def api_brief(meeting_id):
    """Company snapshot complet pour la vue Brief visite."""
    if DEMO_MODE:
        return jsonify(mock_brief_meeting(meeting_id))
    import requests as _req
    from hubspot.suivi import _normalise_type
    from hubspot.companies import get_company_snapshot

    try:
        from config import HUBSPOT_API_KEY as _key
    except ImportError:
        return jsonify({"error": "API key manquante"}), 500

    _hdr = {"Authorization": f"Bearer {_key}", "Content-Type": "application/json"}
    BASE = "https://api.hubapi.com"

    # 1. Meeting details
    try:
        r = _req.get(
            f"{BASE}/crm/v3/objects/meetings/{meeting_id}",
            params={"properties": "hs_meeting_title,hs_timestamp,hs_activity_type,hs_meeting_outcome"},
            headers=_hdr, timeout=10,
        )
        if r.status_code != 200:
            return jsonify({"error": "Meeting introuvable"}), 404
        m_props = r.json().get("properties", {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 2. Company associée
    company_id = None
    try:
        ra = _req.get(
            f"{BASE}/crm/v3/objects/meetings/{meeting_id}/associations/companies",
            headers=_hdr, timeout=10,
        )
        results = ra.json().get("results", []) if ra.status_code == 200 else []
        if results:
            company_id = results[0]["id"]
    except Exception:
        pass

    # 3. CompanySnapshot (company + deals + notes + DN calculé)
    snapshot = get_company_snapshot(company_id) if company_id else {}

    titre = m_props.get("hs_meeting_title", "")
    type_visite = _normalise_type(m_props.get("hs_activity_type", ""), titre)

    company   = snapshot.get("company", {})
    lead_status = company.get("lead_status", "") or company.get("hs_lead_status", "")
    is_client_flag = company.get("client_naali", "").lower().strip() in (
        "true", "rétrocession", "retrocession", "1", "oui", "yes")
    today_str = date.today().isoformat()

    # Offres actives pertinentes pour ce compte
    offres_compte = []
    try:
        for o in _db.get_offres(statut="active"):
            if not o.get("sans_date_limite"):
                if o.get("date_fin")   and o["date_fin"]   < today_str: continue
                if o.get("date_debut") and o["date_debut"] > today_str: continue
            cible = o.get("cible_offre", "")
            if "prospect" in cible and not is_client_flag: offres_compte.append(o)
            elif "prospect" not in cible and is_client_flag: offres_compte.append(o)
    except Exception:
        pass

    # Prochaines actions ouvertes pour ce compte
    actions_compte = []
    if company_id:
        try:
            actions_compte = _db.get_next_actions(_owner_id(), company_id=company_id, status="a_faire")
        except Exception:
            pass

    return jsonify({
        "meeting_id":    meeting_id,
        "titre":         titre,
        "type":          type_visite,
        "outcome":       m_props.get("hs_meeting_outcome", "") or "SCHEDULED",
        "company":       company,
        "deals":         snapshot.get("deals", []),
        "last_note":     snapshot.get("last_note", {}),
        "notes_list":    snapshot.get("notes_list", []),
        "dn":            snapshot.get("dn", {}),
        "ca_total":      snapshot.get("ca_total", 0),
        "last_deal":     snapshot.get("last_deal"),
        "lead_status":   lead_status,
        "offres_compte": offres_compte,
        "actions_compte": actions_compte,
        "hub_id":        HUB_ID,
    })

# ---------------------------------------------------------------------------
# Brief visite par company (sans meeting)
# ---------------------------------------------------------------------------

@app.route("/api/brief/company/<company_id>")
def api_brief_company(company_id):
    """Snapshot brief chargé directement depuis une company HubSpot (sans meeting)."""
    if DEMO_MODE:
        return jsonify(mock_brief_company(company_id))
    from hubspot.companies import get_company_snapshot

    try:
        from config import HUBSPOT_API_KEY  # noqa
    except ImportError:
        return jsonify({"error": "API key manquante"}), 500

    snapshot = get_company_snapshot(company_id)
    company  = snapshot.get("company", {})
    lead_status = company.get("lead_status", "") or company.get("hs_lead_status", "")
    is_client_flag = company.get("client_naali", "").lower().strip() in (
        "true", "rétrocession", "retrocession", "1", "oui", "yes")
    today_str = date.today().isoformat()

    offres_compte = []
    try:
        for o in _db.get_offres(statut="active"):
            if not o.get("sans_date_limite"):
                if o.get("date_fin")   and o["date_fin"]   < today_str: continue
                if o.get("date_debut") and o["date_debut"] > today_str: continue
            cible = o.get("cible_offre", "")
            if "prospect" in cible and not is_client_flag: offres_compte.append(o)
            elif "prospect" not in cible and is_client_flag: offres_compte.append(o)
    except Exception:
        pass

    actions_compte = []
    try:
        actions_compte = _db.get_next_actions(_owner_id(), company_id=company_id, status="a_faire")
    except Exception:
        pass

    return jsonify({
        "meeting_id":    None,
        "titre":         company.get("nom", ""),
        "type":          None,
        "outcome":       None,
        "company":       company,
        "deals":         snapshot.get("deals", []),
        "last_note":     snapshot.get("last_note", {}),
        "notes_list":    snapshot.get("notes_list", []),
        "dn":            snapshot.get("dn", {}),
        "ca_total":      snapshot.get("ca_total", 0),
        "last_deal":     snapshot.get("last_deal"),
        "lead_status":   lead_status,
        "offres_compte": offres_compte,
        "actions_compte": actions_compte,
        "hub_id":        HUB_ID,
    })

# ---------------------------------------------------------------------------
# Contacts HubSpot
# ---------------------------------------------------------------------------

@app.route("/api/contacts/<company_id>", methods=["GET"])
def api_get_contacts(company_id):
    if DEMO_MODE:
        return jsonify({"contacts": []})
    try:
        from hubspot.contacts import get_contacts_for_company
        contacts = get_contacts_for_company(company_id)
        return jsonify({"contacts": contacts})
    except Exception as e:
        return jsonify({"error": str(e), "contacts": []}), 500


@app.route("/api/contacts/<company_id>", methods=["POST"])
def api_create_contact(company_id):
    if DEMO_MODE:
        return jsonify({"error": "Demo mode"}), 403
    data = request.get_json(force=True) or {}
    try:
        from hubspot.contacts import create_contact
        contact = create_contact(company_id, data)
        return jsonify(contact), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/contacts/update/<contact_id>", methods=["POST"])
def api_update_contact(contact_id):
    if DEMO_MODE:
        return jsonify({"error": "Demo mode"}), 403
    data = request.get_json(force=True) or {}
    try:
        from hubspot.contacts import update_contact
        contact = update_contact(contact_id, data)
        return jsonify(contact)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Test mode toggle
# ---------------------------------------------------------------------------

@app.route("/api/test-mode", methods=["GET", "POST"])
def api_test_mode():
    import config as cfg
    import hubspot.meetings as _mtg
    if request.method == "POST":
        enabled = bool(request.get_json(force=True).get("enabled", False))
        cfg.TEST_MODE = enabled
        _mtg.TEST_MODE = enabled
        return jsonify({"test_mode": enabled})
    return jsonify({"test_mode": cfg.TEST_MODE})

# ---------------------------------------------------------------------------
# KPIs sidebar
# ---------------------------------------------------------------------------

@app.route("/api/kpis")
def api_kpis():
    if DEMO_MODE:
        return jsonify(mock_kpis())
    from hubspot.deals import get_ca_mois_courant, get_ca_ytd, get_implantations_mois, get_goals_mois
    from hubspot.companies import get_nb_clients_prospects

    owner   = _owner_id()
    profile = _profile()
    user_id = profile.get("user_id", owner)

    # Tous les appels HubSpot en parallèle
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        f_mois    = ex.submit(get_ca_mois_courant)
        f_ytd     = ex.submit(get_ca_ytd)
        f_implant = ex.submit(get_implantations_mois, owner)
        f_goals   = ex.submit(get_goals_mois, user_id)
        f_portefeuille = ex.submit(get_nb_clients_prospects, owner)
        ca_mois      = f_mois.result()
        ca_ytd       = f_ytd.result()
        nb_implant   = f_implant.result()
        goals        = f_goals.result()
        portefeuille = f_portefeuille.result()

    objectif_ca      = goals.get("objectif_ca", 0)
    objectif_implant = goals.get("objectif_implant", 0)
    nb_clients       = portefeuille.get("nb_clients", 0)
    nb_prospects     = portefeuille.get("nb_prospects", 0)
    _mois_fr = ["Janvier","Février","Mars","Avril","Mai","Juin",
                "Juillet","Août","Septembre","Octobre","Novembre","Décembre"]
    now = datetime.now(PARIS)
    mois_label = f"{_mois_fr[now.month - 1]} {now.year}"

    try:
        pharmacies = _load_pharmacies()
        _DEPT_NOMS = {
            "04":"Alpes-de-Hte-Prov.","05":"Hautes-Alpes","06":"Alpes-Maritimes",
            "11":"Aude","13":"Bouches-du-Rhône","30":"Gard","34":"Hérault",
            "48":"Lozère","66":"Pyrénées-Or.","83":"Var","84":"Vaucluse",
        }
        depts = get_departements_disponibles(pharmacies)
        territoire = " · ".join(_DEPT_NOMS.get(d, d) for d in depts[:5]) or "–"
    except Exception:
        territoire = "–"

    return jsonify({
        "owner_name":       profile.get("name", OWNER_NAME),
        "territoire":       territoire,
        "nb_clients":       nb_clients,
        "nb_prospects":     nb_prospects,
        "ca_ytd":           round(ca_ytd, 2),
        "ca_mois":          round(ca_mois, 2),
        "mois_label":       mois_label,
        "objectif_ca":      objectif_ca,
        "nb_implant":       nb_implant,
        "objectif_implant": objectif_implant,
        "hub_id":           HUB_ID,
    })

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    if DEMO_MODE:
        from demo.mock_data import _PH, _CLIENTS, _PROSPECTS
        return jsonify({
            "total": len(_PH), "clients": len(_CLIENTS), "prospects": len(_PROSPECTS),
            "departements": ["04","05","06","11","13","30","34","48","66","83","84"],
            "origines": [], "catalogue": [], "villes_par_dept": {}, "deciles": [], "produits": [],
        })
    pharmacies = _load_pharmacies()
    clients = filter_clients(pharmacies)
    prospects = filter_prospects(pharmacies)
    depts = get_departements_disponibles(pharmacies)
    origines = get_origines_disponibles(filter_prospects(pharmacies))
    villes_par_dept = get_villes_par_dept(pharmacies)
    deciles = get_deciles_disponibles(clients)  # déciles = clients uniquement
    produits = get_produits_disponibles(pharmacies)
    return jsonify({
        "total": len(pharmacies),
        "clients": len(clients),
        "prospects": len(prospects),
        "departements": depts,
        "origines": origines,
        "catalogue": CATALOGUE,
        "villes_par_dept": villes_par_dept,
        "deciles": deciles,
        "produits": produits,
    })
@app.route("/api/creer", methods=["POST"])
def api_creer():
    if DEMO_MODE:
        data = request.get_json() or {}
        n = len(data.get("visites", []))
        return jsonify({"created": n, "total": n, "created_indices": list(range(n)),
                        "hubspot_ids": {}, "test_mode": True, "ics_disponible": False})
    data = request.get_json() or {}
    visites = data.get("visites", [])

    if not visites:
        return jsonify({"error": "Aucune visite à créer"}), 400

    # Créer les meetings dans HubSpot
    results = create_meetings_batch(visites, owner_id=_owner_id())

    # Construire la map index → hubspot_meeting_id pour les UIDs stables
    hubspot_ids = {}
    created_indices = []
    for r in results:
        try:
            idx = r.get("idx")
            hs_id = r.get("hubspot", {}).get("id")
            if idx is not None and hs_id:
                hubspot_ids[idx] = hs_id
                created_indices.append(idx)
            elif hs_id:
                # fallback si idx absent
                v_orig = r.get("visite", {})
                if v_orig in visites:
                    i = visites.index(v_orig)
                    hubspot_ids[i] = hs_id
                    created_indices.append(i)
        except Exception:
            pass

    # Invalider le cache Python pour que le prochain fetch soit frais
    try:
        from hubspot.suivi import _ttl_cache
        keys_to_del = [k for k in _ttl_cache if k.startswith("meetings_week:")]
        for k in keys_to_del:
            del _ttl_cache[k]
    except Exception:
        pass

    return jsonify({
        "created":         len(created_indices),
        "total":           len(visites),
        "created_indices": created_indices,
        "hubspot_ids":     hubspot_ids,          # index → hs_meeting_id
        "test_mode":       TEST_MODE,
        "ics_disponible":  True,
    })
# ---------------------------------------------------------------------------
# Carte territoire
# ---------------------------------------------------------------------------

@app.route("/api/pharmacies/search")
def api_pharmacies_search():
    """Recherche rapide de pharmacies par nom/ville — pour autocomplete."""
    q = (request.args.get("q", "") or "").strip().lower()
    limit = min(int(request.args.get("limit", 20)), 50)
    if DEMO_MODE:
        return jsonify(mock_search(q))
    pharmacies = _load_pharmacies()
    if not pharmacies:  # cache vide/poisonné — forcer rechargement
        pharmacies = _load_pharmacies(force_refresh=True)
    if q:
        pharmacies = [p for p in pharmacies if
                      q in (p.get("nom","") or "").lower() or
                      q in (p.get("ville","") or "").lower() or
                      q in (p.get("cp","") or "").lower()]
    results = []
    for p in pharmacies[:limit]:
        results.append({
            "nom":        p.get("nom",""),
            "ville":      p.get("ville",""),
            "cp":         p.get("cp",""),
            "id_hubspot": str(p.get("id_hubspot","") or p.get("hs_object_id","") or ""),
            "is_client":  is_client(p),
        })
    return jsonify({"results": results})

@app.route("/api/post-rdv")
def api_post_rdv_list():
    """Meetings passés sur une période — pour l'onglet Comptes-rendus."""
    if DEMO_MODE:
        return jsonify(mock_post_rdv())
    from hubspot.suivi import get_meetings_for_notes

    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    owner_id  = _owner_id()

    meetings = get_meetings_for_notes(
        date_from=date_from, date_to=date_to,
        owner_id=owner_id, use_cache=False
    )

    _SKIP = {"CANCELED", "CANCELLED", "canceled", "cancelled", "SCHEDULED", "scheduled", ""}
    past = [m for m in meetings if (m.get("outcome") or "") not in _SKIP]

    sans_note  = [m for m in past if not m.get("has_note") and m.get("outcome") != "CANCELED"]
    sans_photo = [m for m in past if m.get("has_note") and not m.get("has_photo")]
    completes  = [m for m in past if m.get("has_note")]

    return jsonify({
        "sans_note":  sans_note,
        "sans_photo": sans_photo,
        "completes":  completes,
    })

@app.route("/api/post-rdv/<meeting_id>/submit", methods=["POST"])
def api_post_rdv_submit(meeting_id):
    if DEMO_MODE:
        return jsonify({"ok": True, "next_meeting_id": None})
    from hubspot.suivi import update_meeting_outcome, create_company_note, invalidate_cache
    from hubspot.meetings import create_meeting, clear_cache
    import concurrent.futures
    import pytz
    from datetime import datetime
    PARIS = pytz.timezone("Europe/Paris")

    # Accepte JSON ou multipart/form-data (avec photo)
    ct = request.content_type or ""
    if "multipart" in ct:
        data = request.form
    else:
        data = request.get_json() or {}

    outcome     = data.get("outcome", "COMPLETED")
    company_id  = data.get("company_id", "")
    company_nom = data.get("company_nom", "Pharmacie")
    note_body   = data.get("note_body", "")
    next_date   = data.get("next_date", "")
    next_time   = data.get("next_time", "")
    next_type   = data.get("next_type", "VC")
    owner_id    = _owner_id()

    # Photos jointes à la note (multi-upload)
    files = []
    if "multipart" in ct:
        for pf in request.files.getlist("photos"):
            if pf and pf.filename:
                files.append((pf.read(), pf.filename))
        # rétro-compatibilité champ "photo" (singulier)
        legacy = request.files.get("photo")
        if legacy and legacy.filename:
            files.append((legacy.read(), legacy.filename))
    # Prépare le meeting si besoin (avant les threads, datetime parsing ici)
    dt_start = None
    if next_date and next_time and company_id:
        try:
            dt_start = PARIS.localize(datetime.strptime(f"{next_date} {next_time}", "%Y-%m-%d %H:%M"))
        except Exception:
            pass

    # Lancer outcome + note (+ upload photo dans le thread note) en parallèle
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = []
        if outcome:
            futures.append(ex.submit(update_meeting_outcome, meeting_id, outcome))
        if note_body and company_id:
            futures.append(ex.submit(
                create_company_note, company_id, note_body, owner_id,
                None, None, files,
            ))
        if dt_start:
            pharmacie = {"nom": company_nom, "id_hubspot": company_id}
            futures.append(ex.submit(create_meeting, pharmacie, next_type or "VC", dt_start, owner_id))
        results = [f.result() for f in futures]

    # Récupérer l'ID du nouveau meeting (dernier future si dt_start)
    next_meeting_id = None
    if dt_start:
        try:
            new_meeting = results[-1]
            if new_meeting:
                next_meeting_id = new_meeting.get("id")
                clear_cache()
        except Exception as e:
            print(f"[post-rdv] create_meeting: {e}")

    # Signal relance (local, rapide)
    if next_date and company_id:
        _db.upsert_signal(owner_id, str(company_id), next_date, next_type or "", str(meeting_id))

    # Prochaine action terrain (si fournie)
    action_type = data.get("action_type", "")
    action_due  = data.get("action_due", "")
    action_note = data.get("action_note", "")
    action_plan = data.get("action_impacts_planning")  # bool, str "true"/"false", ou None
    if action_type and action_due and company_id:
        # FormData envoie des chaînes → normaliser explicitement
        ip = str(action_plan).lower() in ("true", "1") if action_plan is not None else None
        _db.create_next_action(
            owner_id, str(company_id), action_type, action_due,
            note=action_note, impacts_planning=ip,
            source_meeting_id=str(meeting_id),
        )

    invalidate_cache()
    return jsonify({"ok": True, "next_meeting_id": next_meeting_id})
# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------

@app.route("/api/company/<company_id>")
def api_company(company_id):
    """Retourne les propriétés légères d'une company (remise, statut client)."""
    from hubspot.companies import get_company
    c = get_company(company_id)
    return jsonify(c)

@app.route("/api/catalogue")
def api_catalogue():
    if DEMO_MODE:
        return jsonify({"products": [
            {"nom": "Fiole Magnésium", "ref": "MAG01", "prix_ht": 12.50, "tva": 5.5},
            {"nom": "Fiole Fer",       "ref": "FER01", "prix_ht": 11.00, "tva": 5.5},
            {"nom": "Fiole Zinc",      "ref": "ZNC01", "prix_ht": 10.50, "tva": 5.5},
            {"nom": "Fiole Vitamine C","ref": "VTC01", "prix_ht": 9.90,  "tva": 5.5},
            {"nom": "Gluco",           "ref": "GLU01", "prix_ht": 14.00, "tva": 5.5},
            {"nom": "Éclat",           "ref": "ECL01", "prix_ht": 15.50, "tva": 5.5},
            {"nom": "Fiole Safran",    "ref": "SAF01", "prix_ht": 13.00, "tva": 5.5},
        ], "taxes": [{"taux": 5.5}, {"taux": 20.0}]})
    from hubspot.catalogue import get_products, get_taxes
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_p = ex.submit(get_products)
        f_t = ex.submit(get_taxes)
        products, taxes = f_p.result(), f_t.result()
    return jsonify({"products": products, "taxes": taxes})

@app.route("/api/commandes")
def api_commandes():
    if DEMO_MODE:
        return jsonify({"orders": []})
    from hubspot.deals import get_recent_orders
    orders = get_recent_orders(owner_id=_owner_id(), days=30)
    return jsonify({"orders": orders})

@app.route("/api/commandes/create", methods=["POST"])
def api_commandes_create():
    if DEMO_MODE:
        return jsonify({"ok": True, "deal_id": "demo_deal"})
    from hubspot.deals import create_order
    data        = request.get_json() or {}
    company_id        = data.get("company_id", "")
    company_nom       = data.get("company_nom", "Pharmacie")
    line_items        = data.get("line_items", [])
    note              = data.get("note", "")
    type_de_commande  = data.get("type_de_commande", "Réassort")
    dealstage         = data.get("dealstage", "2110945486")
    closed_won_reason = data.get("closed_won_reason", "Classique")

    if not company_id:
        return jsonify({"ok": False, "error": "company_id requis"}), 400
    if not line_items:
        return jsonify({"ok": False, "error": "Au moins un produit requis"}), 400

    result = create_order(
        company_id=company_id,
        company_nom=company_nom,
        line_items=line_items,
        owner_id=_owner_id(),
        note=note,
        type_de_commande=type_de_commande,
        dealstage=dealstage,
        closed_won_reason=closed_won_reason,
    )
    # Invalider le cache post-commande
    try:
        from hubspot.suivi import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    return jsonify(result), 200

@app.route("/api/agenda")
def api_agenda():
    offset = int(request.args.get("offset", 0))
    if DEMO_MODE:
        return jsonify(mock_agenda(offset))
    from hubspot.suivi import get_meetings_week
    force  = request.args.get("force", "0") == "1"
    # use_cache=False si force ou si semaine courante (données critiques)
    use_cache = not force and offset != 0
    meetings = get_meetings_week(offset=offset, owner_id=_owner_id(), use_cache=use_cache)
    return jsonify({"meetings": meetings, "hub_id": HUB_ID})
# ---------------------------------------------------------------------------
# Data — upload / info CSV
# ---------------------------------------------------------------------------

# Colonnes attendues par l'application
_COLS_REQUIRED = {"nom", "cp", "client_naali", "potentiel"}
_COLS_OPTIONAL = {"ville", "code_postal", "catalogue", "catalogue_naali_reference",
                  "origine", "id_hubspot", "hs_object_id", "lat", "lon"}

# Mapping labels HubSpot FR → noms internes
_HUBSPOT_COL_MAP = {
    "id de fiche d'informations": "id_hubspot",
    "nom de l'entreprise":        "nom",
    "cp":                         "cp",
    "code postal":                "cp",
    "client naali":               "client_naali",
    "potentiel":                  "potentiel",
    "ville":                      "ville",
    "commune":                    "ville",
    "catalogue naali référencé":  "catalogue",
    "origine de prospection":     "origine",
    "ca 2025":                    "ca_2025",
    "ca 2024":                    "ca_2024",
    "adresse postale":            "address",
    "département":                "departement",
    "lat":                        "lat",
    "lon":                        "lon",
    "latitude":                   "lat",
    "longitude":                  "lon",
    "décile":                     "decile",
    "decile":                     "decile",
}
# ---------------------------------------------------------------------------
# Profils commerciaux
# ---------------------------------------------------------------------------

@app.route("/api/profiles")
def api_profiles():
    """Liste des profils disponibles + profil actif."""
    actif = _owner_id()
    return jsonify({
        "profiles": list(PROFILES.values()),
        "active_owner_id": actif,
    })

@app.route("/api/profiles", methods=["POST"])
def api_profiles_create():
    """Crée un nouveau profil commercial (SQLite + mémoire)."""
    data     = request.get_json() or {}
    owner_id = str(data.get("owner_id", "")).strip()
    name     = str(data.get("name", "")).strip()
    email    = str(data.get("email", "")).strip().lower()
    home_city = str(data.get("home_city", "")).strip()

    if not owner_id or not name or not email:
        return jsonify({"error": "owner_id, name et email sont requis"}), 400
    if not owner_id.isdigit():
        return jsonify({"error": "owner_id doit être numérique"}), 400

    # Nom de fichier CSV dérivé du prénom (slug simple)
    import re
    slug = re.sub(r"[^a-z0-9]", "_", name.split()[0].lower())
    csv_path = f"data/naali_base_{slug}.csv"

    profile = {
        "owner_id":  owner_id,
        "name":      name,
        "email":     email,
        "csv_path":  csv_path,
        "home_lat":  None,
        "home_lon":  None,
        "home_city": home_city,
    }

    _db.upsert_user(owner_id, name, email, csv_path, None, None, home_city)
    PROFILES[owner_id] = profile

    return jsonify({"ok": True, "profile": profile})
@app.route("/api/agenda/export-ics")
def api_agenda_export_ics():
    """Export ICS Outlook de la semaine affichée dans l'agenda."""
    from hubspot.suivi import get_meetings_week
    from core.ics_export import generer_ics
    from flask import Response
    offset = int(request.args.get("offset", 0))
    meetings = get_meetings_week(offset=offset, owner_id=_owner_id(), use_cache=True)
    visites = []
    for m in meetings:
        visites.append({
            "pharmacie": {"nom": m.get("company_nom") or m.get("titre", ""), "ville": "", "cp": ""},
            "type_visite": m.get("type", "VC"),
            "dt_start": m.get("dt", ""),
        })
    ics_bytes = generer_ics(visites)
    return Response(
        ics_bytes,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=naali-agenda.ics"},
    )

@app.route("/api/agenda/meeting/<meeting_id>/delete", methods=["POST"])
def api_agenda_delete_meeting(meeting_id):
    """Supprime un meeting de l'agenda par son ID."""
    result = delete_meetings_batch([str(meeting_id)])
    return jsonify(result)

@app.route("/api/agenda/meeting/<meeting_id>/update", methods=["POST"])
def api_agenda_update_meeting(meeting_id):
    """
    Met à jour un meeting existant : heure, durée, type.
    Body JSON : { heure: "HH:MM", duree_min: 30|60|90, type_visite: "VC"|"VP"|...,
                  date_str: "YYYY-MM-DD" (optionnel, pour déplacer) }
    """
    from config import HUBSPOT_API_KEY
    BASE_URL = "https://api.hubapi.com"
    data = request.get_json() or {}

    heure    = data.get("heure", "09:00")
    duree    = int(data.get("duree_min", 60))
    type_v   = data.get("type_visite", "VC").upper()
    date_str = data.get("date_str", "")

    _ACTIVITY_MAP = {
        "VC": "Visite client",
        "VP": "Visite prospection",
        "RC": "Rendez-vous client",
        "RP": "Rendez-vous prospect",
        "F":  "Formation",
    }

    if not date_str:
        return jsonify({"error": "date_str requis"}), 400
    try:
        from datetime import datetime as _dt_cls
        hh, mm = map(int, heure.split(":"))
        dt_start = PARIS.localize(_dt_cls.strptime(date_str, "%Y-%m-%d").replace(hour=hh, minute=mm))
        dt_end   = dt_start + timedelta(minutes=duree)
        ts_start = str(int(dt_start.astimezone(pytz.utc).timestamp() * 1000))
        ts_end   = str(int(dt_end.astimezone(pytz.utc).timestamp() * 1000))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # IDs temporaires (optimistes) → pas encore dans HubSpot
    if str(meeting_id).startswith("tmp_"):
        return jsonify({"ok": True, "skipped": True})

    headers = {"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"}
    payload = {"properties": {
        "hs_timestamp":       ts_start,
        "hs_meeting_end_time": ts_end,
        "hs_activity_type":   _ACTIVITY_MAP.get(type_v, type_v),
    }}
    try:
        import requests as _req
        r = _req.patch(
            f"{BASE_URL}/crm/v3/objects/meetings/{meeting_id}",
            json=payload, headers=headers, timeout=10
        )
        if r.status_code not in (200, 204):
            return jsonify({"ok": False, "error": r.text[:300]}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200
    try:
        from hubspot.suivi import _ttl_cache
        for k in [k for k in _ttl_cache if k.startswith("meetings_week:")]:
            del _ttl_cache[k]
    except Exception:
        pass
    return jsonify({"ok": True})

@app.route("/api/agenda/optimiser-jour", methods=["POST"])
def api_agenda_optimiser_jour():
    """Réordonne les meetings d'un jour via TSP nearest-neighbor (tri par CP)."""
    from hubspot.suivi import get_meetings_week
    data     = request.get_json() or {}
    date_str = data.get("date", "")
    if not date_str:
        return jsonify({"ok": False, "error": "date requis"}), 400

    # Calculer l'offset semaine pour charger les meetings
    from datetime import date as _date_cls
    try:
        target = _date_cls.fromisoformat(date_str)
    except Exception:
        return jsonify({"ok": False, "error": "date invalide"}), 400
    today      = _date_cls.today()
    day_of_wk  = today.weekday()
    lundi_curr = today - timedelta(days=day_of_wk)
    delta_days  = (target - lundi_curr).days
    offset      = delta_days // 7

    meetings_all = get_meetings_week(offset=offset, owner_id=_owner_id(), use_cache=False)
    _INACTIVE    = {"CANCELED", "NO_SHOW"}
    day_mtgs     = [m for m in meetings_all
                    if (m.get("dt") or "").startswith(date_str)
                    and (m.get("outcome") or "") not in _INACTIVE]

    if len(day_mtgs) < 2:
        return jsonify({"ok": False, "error": "Moins de 2 rendez-vous actifs ce jour."}), 400

    # Tri nearest-neighbor basé sur le CP (approximation simple sans coordonnées GPS)
    def _cp_key(m):
        cp = str(m.get("cp") or m.get("company_cp") or "99999").zfill(5)
        return cp

    sorted_mtgs = sorted(day_mtgs, key=_cp_key)

    # Calculer les horaires selon les crédits par type
    _DUR = {"VC":30, "VP":30, "RC":60, "RP":60, "F":60}
    _DAY_START = {"0":12, "1":9, "2":9, "3":9, "4":9}  # 0=lundi
    day_of_week = str(target.weekday())
    h_start = _DAY_START.get(day_of_week, 9)
    cur_min = h_start * 60

    ordre = []
    for m in sorted_mtgs:
        type_v  = (m.get("type") or "VC").upper()
        duree   = _DUR.get(type_v, 60)
        hh      = cur_min // 60
        mm      = cur_min % 60
        heure   = f"{hh:02d}:{mm:02d}"
        ordre.append({"id": m["id"], "heure": heure, "duree_min": duree, "type_visite": type_v})
        cur_min += duree + 15  # 15 min de trajet entre visites

    return jsonify({"ok": True, "ordre": ordre})


@app.route("/api/portefeuille")
def api_portefeuille():
    """Vue arbitrage portefeuille : CSV + statuts HubSpot + DN + PBA."""
    if DEMO_MODE:
        return jsonify(mock_portefeuille())
    from core.dn_engine import calculer_groupes_dn

    pharmacies = _load_pharmacies()
    clients    = filter_clients(pharmacies)

    enrichis = enrichir_avec_statuts(clients, max_workers=30)

    # DN map : id_hubspot → pct (clients seulement)
    dn_map: dict = {}
    try:
        groupes = calculer_groupes_dn(clients)
        for grp_items in groupes.values():
            for p in grp_items:
                cid = str(p.get("id_hubspot") or p.get("hs_object_id") or "")
                if cid:
                    dn_map[cid] = round(float(p.get("dn_pct", 0) or 0), 1)
    except Exception as e:
        print(f"[portefeuille] DN: {e}")

    def _sf(v):
        try: return float(str(v).replace(",", ".").strip()) if v else 0.0
        except: return 0.0

    def _si(v):
        try: return int(float(str(v).strip())) if v else 0
        except: return 0

    def _col(p, *keys):
        """Cherche la première clé non vide parmi plusieurs variantes."""
        for k in keys:
            v = p.get(k, "")
            if v and str(v).strip():
                return str(v).strip()
        return ""

    def _pba(is_client, is_retard, dn_pct, last_order_days, potentiel):
        if not is_client:
            if is_retard: return "Relancer sous 7 jours"
            return "Qualifier le besoin"
        if is_retard and dn_pct is not None and dn_pct < 40:
            return "Visite urgente + référencer"
        if is_retard:
            return "Visiter rapidement"
        if dn_pct is not None and dn_pct < 40:
            return "Référencer produits manquants"
        if dn_pct is not None and dn_pct < 80:
            return "Extension gamme"
        if last_order_days and last_order_days > 60:
            return "Réassort à pousser"
        return "Fidéliser"

    today = date.today()
    result = []
    for p in enrichis:
        cid = str(p.get("id_hubspot") or p.get("hs_object_id") or "")
        is_cl = p.get("_client_naali_raw", "").lower().strip() in (
            "true", "rétrocession", "retrocession", "1", "oui", "yes")

        ca_2025 = _sf(_col(p, "ca_2025", "CA 2025", "ca 2025"))
        ca_2026 = _sf(_col(p, "ca_2026", "CA 2026", "ca 2026"))
        remise  = _col(p, "remise", "Remise sur facture appliquée",
                       "remise sur facture appliquée")
        groupement = _col(p, "groupement", "Groupement Principal",
                          "groupement principal")
        nb_cmd = _si(_col(p, "nb_commande_2026", "NB commande 2026",
                          "nb commande 2026", "nb_commande_2025", "NB commande 2025"))

        last_order_raw = _col(p,
            "date_derniere_commande",
            "Date de conclusion de la transaction la plus récente",
            "date de conclusion de la transaction la plus récente")
        last_order = last_order_raw[:10] if last_order_raw else ""
        last_order_days = None
        if last_order:
            try:
                last_order_days = (today - date.fromisoformat(last_order)).days
            except Exception:
                pass

        dn_pct      = dn_map.get(cid) if is_cl else None
        is_retard   = bool(p.get("is_retard"))
        is_proche   = bool(p.get("is_proche"))
        potentiel   = p.get("potentiel", "")

        urgence = "high" if is_retard else ("medium" if (
            not is_cl or (dn_pct is not None and dn_pct < 40)
            or (last_order_days and last_order_days > 60)
        ) else "low")

        result.append({
            "id":              cid,
            "nom":             p.get("nom", ""),
            "ville":           p.get("ville", ""),
            "cp":              p.get("cp", ""),
            "dept":            (p.get("cp", "") or "")[:2],
            "groupement":      groupement,
            "is_client":       is_cl,
            "potentiel":       potentiel,
            "remise":          remise,
            "ca_2025":         ca_2025,
            "ca_2026":         ca_2026,
            "nb_cmd":          nb_cmd,
            "last_order":      last_order,
            "last_order_days": last_order_days,
            "dn_pct":          dn_pct,
            "last_visit":      p.get("last_visit"),
            "is_retard":       is_retard,
            "is_proche":       is_proche,
            "urgence":         urgence,
            "pba":             _pba(is_cl, is_retard, dn_pct, last_order_days, potentiel),
        })

    # Portefeuille = clients Naali uniquement (règle absolue)
    result = [x for x in result if x["is_client"]]
    result.sort(key=lambda x: (
        0 if x["urgence"] == "high"   else 1 if x["urgence"] == "medium" else 2,
        0 if x["potentiel"] == "Prioritaires" else 1,
        x["nom"],
    ))

    return jsonify({"pharmacies": result, "hub_id": HUB_ID, "total": len(result)})
# ---------------------------------------------------------------------------
# Planificateur intelligent (Copilote)
# ---------------------------------------------------------------------------

@app.route("/api/planificateur/suggestions", methods=["POST"])
def api_planificateur_suggestions():
    """Génère des suggestions de visites enrichies."""
    if DEMO_MODE:
        return jsonify(mock_planificateur(request.get_json() or {}))
    from core.filtres import is_client as _is_cl
    from core.planning import CREDITS as _CRED_PL

    data             = request.get_json() or {}
    mode             = data.get("mode", "completer")
    date_debut_str   = data.get("date_debut")
    date_jour_str    = data.get("date_jour")              # jour unique sélectionné (filtre strict)
    filtre_depts     = data.get("departements", [])
    filtre_villes    = data.get("villes", [])
    filtre_segment   = data.get("segment", "all")        # all|clients|prospects
    filtre_pot       = data.get("potentiel", [])          # ["Prioritaires","Secondaires","Non Prioritaires"]
    filtre_refs_dn   = data.get("refs_dn", [])            # DN à activer : pharmacies qui N'ont PAS ces refs
    filtre_refs_pres = data.get("refs_presentes", [])     # DN à pousser : pharmacies qui ONT ces refs
    filtre_origines  = data.get("origines", [])           # Origine de prospection (prospects)
    geo_optimise        = data.get("geo_optimise", mode == "optimiser")
    # Point de départ : lat/lon directs, ou ville résolue depuis le CSV, ou domicile
    pt_depart_lat       = data.get("point_depart_lat")
    pt_depart_lon       = data.get("point_depart_lon")
    pt_depart_ville     = (data.get("point_depart_ville") or "").strip()

    # ── 1. Semaine cible ────────────────────────────────────────────────────
    if date_debut_str:
        try:
            lundi = date.fromisoformat(date_debut_str)
        except Exception:
            return jsonify({"error": "date_debut invalide"}), 400
    else:
        lundi = get_prochain_lundi(date.today())

    jours_raw = get_jours_ouvrables(lundi, nb_semaines=1)
    jours = [dict(j) for j in jours_raw]  # j["date"] reste un objet date

    # Si un jour unique est sélectionné, restreindre à ce seul jour
    if date_jour_str:
        jours = [j for j in jours if j["date_str"] == date_jour_str]

    # ── 2. Crédits disponibles par jour ─────────────────────────────────────
    owner_id = _owner_id()
    credits_par_jour = {}
    for j in jours:
        if j.get("ferie") or j.get("credits", 0) == 0:
            credits_par_jour[j["date_str"]] = {"max": 0, "used": 0, "libre": 0}
            continue
        ds    = j["date_str"]
        d_obj = j["date"]
        dt_d  = datetime(d_obj.year, d_obj.month, d_obj.day, 0,  0,  tzinfo=PARIS)
        dt_f  = datetime(d_obj.year, d_obj.month, d_obj.day, 23, 59, tzinfo=PARIS)
        mtgs  = get_existing_meetings(dt_d, dt_f, owner_id=owner_id)
        used  = sum(2 if m.get("duree_min", 60) >= 50 else 1 for m in mtgs)
        libre = max(0, j.get("credits", 0) - used)
        credits_par_jour[ds] = {"max": j.get("credits", 0), "used": used, "libre": libre}

    # ── 3. IDs déjà planifiés ───────────────────────────────────────────────
    ids_planifies = get_company_ids_planifies(nb_jours=14, owner_id=owner_id)

    # ── 4. Charger et filtrer les pharmacies ────────────────────────────────
    pharmacies = _load_pharmacies()
    if filtre_depts:
        pharmacies = filter_by_departements(pharmacies, filtre_depts)
    if filtre_villes:
        pharmacies = filter_by_villes(pharmacies, filtre_villes)

    clients          = filter_clients(pharmacies)
    tous_non_clients = [p for p in pharmacies if not _is_cl(p)]

    # Prospects : si filtre_pot inclut "Non Prioritaires", charger tous les non-clients filtrés
    # Sinon : défaut = Prioritaires + Secondaires uniquement
    if filtre_pot:
        prospects = [p for p in tous_non_clients if p.get("potentiel", "") in filtre_pot]
        clients   = [p for p in clients          if p.get("potentiel", "") in filtre_pot]
    else:
        prospects = [p for p in tous_non_clients
                     if p.get("potentiel", "") in ("Prioritaires", "Secondaires", "Non Prioritaires")]

    if filtre_origines:
        prospects = filter_by_origines(prospects, filtre_origines)

    if filtre_segment == "clients":
        tous = clients
    elif filtre_segment == "prospects":
        tous = prospects
    else:
        tous = clients + prospects

    # ── 5. Enrichissement HubSpot (last_visit, is_retard, is_proche) ────────
    tous_enrichis = enrichir_avec_statuts(tous)

    # ── 6. Groupes DN (clients) avec refs ciblées ───────────────────────────
    refs_cibles  = filtre_refs_dn if filtre_refs_dn else CATALOGUE
    n_cibles     = len(refs_cibles)
    clients_enr  = [p for p in tous_enrichis if _is_cl(p)]
    dn_info      = {}
    if clients_enr:
        groupes_dn = calculer_groupes_dn(clients_enr, refs_cibles)
        for grp_idx, grp_name in enumerate(["groupe_0", "groupe_1", "groupe_2"]):
            for p in groupes_dn.get(grp_name, []):
                pid = str(p.get("id_hubspot", ""))
                rp  = p.get("refs_presentes", [])
                rm  = p.get("refs_manquantes", [])
                dn_info[pid] = {
                    "groupe_dn":       grp_idx,
                    "refs_manquantes": rm,
                    "refs_presentes":  rp,
                    "dn_pct":          round(len(rp) / n_cibles * 100) if n_cibles else 0,
                }

    for p in tous_enrichis:
        pid = str(p.get("id_hubspot", ""))
        if _is_cl(p):
            info = dn_info.get(pid, {"groupe_dn": 2, "refs_manquantes": [],
                                     "refs_presentes": [], "dn_pct": 100})
        else:
            info = {"groupe_dn": None, "refs_manquantes": [], "refs_presentes": [], "dn_pct": None}
        p.update(info)

    # ── 7. (offres retirées des critères de planification) ───────────────────
    offres_noms = []

    # ── 7b. Prochaines actions terrain (impacts_planning=True) ──────────────
    actions_terrain = _db.get_next_actions(owner_id, impacts_planning=True, status="a_faire")
    # Index : company_id → action la plus urgente (due_date la plus proche)
    actions_map = {}
    for a in actions_terrain:
        cid = str(a["company_id"])
        if cid not in actions_map or a["due_date"] < actions_map[cid]["due_date"]:
            actions_map[cid] = a

    _ACTION_LABELS = {
        "rappeler":           "Relance planifiée",
        "reprogrammer_visite":"Visite à reprogrammer",
        "formation":          "Formation à programmer",
        "controle_pack":      "Contrôle pack dû",
        "reassort":           "Réassort à pousser",
        "relance_offre":      "Relance offre en cours",
    }

    # ── 8. Scoring enrichi ──────────────────────────────────────────────────
    today_d = date.today()

    def _last_order_days(p):
        raw = (p.get("Date de conclusion de la transaction la plus récente", "") or "")[:10]
        if not raw:
            return None
        try:
            return (today_d - date.fromisoformat(raw)).days
        except Exception:
            return None

    def _compute_score(p):
        weighted = []

        # ── Retard / Proche ──────────────────────────────────────────────────
        if p.get("is_retard"):
            weighted.append((100, "En retard de visite"))
        elif p.get("is_proche"):
            weighted.append((50, "Visite à planifier bientôt"))

        # ── DN ───────────────────────────────────────────────────────────────
        gdn = p.get("groupe_dn")
        if gdn == 0:
            weighted.append((40, "DN incomplète 🔴"))
        elif gdn == 1:
            weighted.append((20, "DN partielle 🟡"))

        # ── Réassort ─────────────────────────────────────────────────────────
        lod = _last_order_days(p)
        if lod is not None and lod > 90:
            weighted.append((60, "Réassort urgent"))
        elif lod is not None and lod > 60:
            weighted.append((40, "Réassort à pousser"))

        # ── Prochaine action terrain ─────────────────────────────────────────
        pid = str(p.get("id_hubspot", ""))
        action = actions_map.get(pid)
        if action:
            try:
                due = date.fromisoformat(action["due_date"])
                delta = (due - today_d).days
            except Exception:
                delta = 0
            if delta < 0:
                w_act = 150
            elif delta == 0:
                w_act = 130
            elif delta <= 3:
                w_act = 100
            elif delta <= 7:
                w_act = 70
            else:
                w_act = 40
            if p.get("potentiel") == "Prioritaires":
                w_act += 15
            label = _ACTION_LABELS.get(action["action_type"], "Action de suivi")
            if delta < 0:
                label += f" ({abs(delta)}j de retard)"
            elif delta == 0:
                label += " (échue aujourd'hui)"
            elif delta <= 7:
                label += f" (J+{delta})"
            weighted.append((w_act, label))

        # ── Potentiel ────────────────────────────────────────────────────────
        pot = p.get("potentiel", "")
        if pot == "Prioritaires":
            weighted.append((10, "Prioritaire"))
        elif pot == "Secondaires":
            weighted.append((5, "Secondaire"))

        score       = sum(w[0] for w in weighted)
        raison_dom  = max(weighted, key=lambda x: x[0])[1] if weighted else (pot or "À visiter")
        all_raisons = [w[1] for w in weighted] if weighted else [pot or "À visiter"]

        return score, raison_dom, all_raisons, lod, ""

    # ── 9a. Filtres durs post-enrichissement ─────────────────────────────────
    # DN à activer : garder clients qui manquent au moins une des refs sélectionnées
    if filtre_refs_dn:
        def _manque_ref_dn(p):
            if not _is_cl(p):
                return True  # prospects non filtrés par refs_dn
            cat = {r.strip() for r in (p.get("catalogue") or "").split(";") if r.strip()}
            return any(r not in cat for r in filtre_refs_dn)
        tous_enrichis = [p for p in tous_enrichis if _manque_ref_dn(p)]

    # DN à pousser : garder pharmacies qui ont au moins une des refs sélectionnées
    if filtre_refs_pres:
        def _a_ref_pres(p):
            cat = {r.strip() for r in (p.get("catalogue") or "").split(";") if r.strip()}
            return any(r in cat for r in filtre_refs_pres)
        tous_enrichis = [p for p in tous_enrichis if _a_ref_pres(p)]

    # ── 9b. Construire les candidats enrichis ────────────────────────────────
    candidats = []
    for p in tous_enrichis:
        pid = str(p.get("id_hubspot", ""))
        if not pid or pid in ids_planifies:
            continue
        score, raison_dom, all_raisons, lod, ls = _compute_score(p)
        type_v = "VC" if _is_cl(p) else "VP"
        candidats.append({
            "nom":              p.get("nom", ""),
            "id_hubspot":       pid,
            "ville":            p.get("ville", ""),
            "cp":               p.get("cp", ""),
            "dept":             (p.get("cp", "") or "")[:2],
            "lat":              p.get("lat"),
            "lon":              p.get("lon"),
            "is_client":        _is_cl(p),
            "type_visite":      type_v,
            "credits":          _CRED_PL.get(type_v, 2),
            "potentiel":        p.get("potentiel", ""),
            "lead_status":      ls,
            "last_visit":       p.get("last_visit"),
            "is_retard":        bool(p.get("is_retard")),
            "is_proche":        bool(p.get("is_proche")),
            "last_order_days":  lod,
            "groupe_dn":        p.get("groupe_dn"),
            "dn_pct":           p.get("dn_pct"),
            "refs_manquantes":  (p.get("refs_manquantes") or [])[:5],
            "score":            score,
            "raison":           raison_dom,
            "raisons":          all_raisons,
            "offre":            "",
        })

    # ── 10. Jours avec crédits disponibles ──────────────────────────────────
    jours_dispo = []
    for j in jours:
        if j.get("ferie") or j.get("credits", 0) == 0:
            continue
        info = credits_par_jour.get(j["date_str"], {})
        if info.get("libre", 0) <= 0:
            continue
        jc = dict(j)
        jc["_libre"] = info["libre"]
        jours_dispo.append(jc)

    # ── 11. Assigner — toujours géographique, 2-opt intra-jour si "optimiser" ──
    suggestions_par_jour = []
    attribues = set()

    hlat, hlon = _home_coords()
    # Point de départ : lat/lon direct > ville résolue > domicile profil
    start_lat, start_lon = hlat, hlon
    if pt_depart_lat is not None and pt_depart_lon is not None:
        start_lat, start_lon = float(pt_depart_lat), float(pt_depart_lon)
    elif pt_depart_ville:
        # Chercher une pharmacie GPS dans cette ville (insensible à la casse)
        v_norm = pt_depart_ville.lower()
        all_ph = _load_pharmacies()
        match  = next(
            (p for p in all_ph
             if (p.get("ville") or "").lower() == v_norm
             and p.get("lat") and p.get("lon")),
            None,
        )
        if match:
            start_lat, start_lon = float(match["lat"]), float(match["lon"])

    candidats.sort(key=lambda x: x["score"], reverse=True)
    pharma_geo   = [c for c in candidats if c.get("lat") and c.get("lon")]
    pharma_nogeo = [c for c in candidats if not (c.get("lat") and c.get("lon"))]

    jours_obj = []
    for j in jours_dispo:
        jc = dict(j)
        jc["credits"] = j["_libre"]
        jours_obj.append(jc)

    # Regroupement géographique systématique (secteurs ~33km)
    affectation = repartir_sur_jours(
        pharma_geo + pharma_nogeo, jours_obj,
        start_lat=start_lat, start_lon=start_lon,
    )

    # Mode "optimiser" : ré-ordonner en intra-jour (nearest-neighbor + 2-opt)
    if mode == "optimiser" and geo_optimise:
        affectation = optimiser_journees(affectation, start_lat=start_lat, start_lon=start_lon)

    idx_map = {c["id_hubspot"]: c for c in candidats}
    for j in jours_dispo:
        ds   = j["date_str"]
        info = credits_par_jour[ds]
        sugg_jour = []
        for p in affectation.get(ds, []):
            pid = str(p.get("id_hubspot", ""))
            if pid in attribues:
                continue
            c = idx_map.get(pid)
            if c is None:
                continue
            sugg_jour.append(c)
            attribues.add(pid)
        if sugg_jour:
            suggestions_par_jour.append({
                "date_str":      ds,
                "nom":           j.get("nom", ""),
                "debut":         j.get("debut", "09:00"),
                "credits_max":   info["max"],
                "credits_used":  info["used"],
                "credits_libre": info["libre"],
                "suggestions":   sugg_jour,
            })

    from core.filtres import get_origines_disponibles as _get_origines
    from core.filtres import get_produits_disponibles as _get_produits
    pharmacies_all = _load_pharmacies()
    return jsonify({
        "mode":                  mode,
        "date_debut":            lundi.isoformat(),
        "jours":                 suggestions_par_jour,
        "catalogue":             _get_produits(pharmacies_all),
        "origines_disponibles":  _get_origines(pharmacies_all),
        "total_suggestions":     sum(len(j["suggestions"]) for j in suggestions_par_jour),
    })

# ---------------------------------------------------------------------------
# Offres commerciales
# ---------------------------------------------------------------------------

@app.route("/api/actions/<company_id>")
def api_actions_list(company_id):
    """Actions à faire (a_faire + partielle) pour une pharmacie."""
    actions = _db.get_next_actions(_owner_id(), company_id=company_id)
    active = [a for a in actions if a["status"] in ("a_faire", "partielle")]
    return jsonify({"actions": active})

@app.route("/api/actions/<int:action_id>/status", methods=["POST"])
def api_action_status(action_id):
    """Met à jour le statut d'une action (faite / partielle / a_faire)."""
    data   = request.get_json() or {}
    status = data.get("status", "")
    if status not in ("faite", "partielle", "a_faire"):
        return jsonify({"error": "statut invalide"}), 400
    ok = _db.update_next_action_status(action_id, status)
    return jsonify({"ok": ok})

@app.route("/api/offres", methods=["GET"])
def api_offres_list():
    if DEMO_MODE:
        return jsonify({"offres": []})
    statut = request.args.get("statut")
    return jsonify({"offres": _db.get_offres(statut=statut)})

@app.route("/api/offres", methods=["POST"])
def api_offres_create():
    data = request.get_json() or {}
    if not data.get("nom_offre", "").strip():
        return jsonify({"error": "nom_offre requis"}), 400
    offre = _db.create_offre(data)
    return jsonify({"ok": True, "offre": offre}), 201

@app.route("/api/offres/<int:offre_id>", methods=["PUT"])
def api_offres_update(offre_id):
    data = request.get_json() or {}
    offre = _db.update_offre(offre_id, data)
    if offre is None:
        return jsonify({"error": "Offre introuvable"}), 404
    return jsonify({"ok": True, "offre": offre})

@app.route("/api/offres/<int:offre_id>/toggle", methods=["POST"])
def api_offres_toggle(offre_id):
    offre = _db.toggle_offre_statut(offre_id)
    if offre is None:
        return jsonify({"error": "Offre introuvable"}), 404
    return jsonify({"ok": True, "offre": offre})

@app.route("/api/offres/<int:offre_id>", methods=["DELETE"])
def api_offres_delete(offre_id):
    ok = _db.delete_offre(offre_id)
    if not ok:
        return jsonify({"error": "Offre introuvable"}), 404
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Dashboard Performance (routes /dash/ + page /performance)
# ---------------------------------------------------------------------------
from core import dashboard_data as _dash

def _dash_nocache(obj):
    from flask import make_response
    resp = make_response(jsonify(obj))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp

def _dash_commercial():
    owner_id = request.args.get("commercial", _dash.OWNER_ID)
    if owner_id not in _dash.COMMERCIAUX:
        owner_id = _dash.OWNER_ID
    user_id = _dash.COMMERCIAUX[owner_id]["user_id"]
    return owner_id, user_id

@app.route("/performance")
def performance_page():
    data = _dash.get_initial_data()
    data["session_owner_id"] = _owner_id()
    return render_template("performance.html", **data)

@app.route("/dash/api/data")
def dash_api_data():
    from datetime import date as _date
    debut = request.args.get("debut")
    fin   = request.args.get("fin")
    if not debut or not fin:
        today = _date.today()
        debut = today.replace(day=1).strftime("%Y-%m-%d")
        fin   = today.strftime("%Y-%m-%d")
    agent = request.args.get("agent")
    if agent is not None:
        owner_id = None if agent == "all" else (agent if agent in _dash.AGENTS else None)
        return _dash_nocache(_dash.get_data_periode(debut, fin, owner_id=owner_id, user_id=None, pipeline=_dash.PIPELINE_AGENTS))
    owner_id, user_id = _dash_commercial()
    return _dash_nocache(_dash.get_data_periode(debut, fin, owner_id, user_id))

@app.route("/dash/api/comparatif")
def dash_api_comparatif():
    owner_id, _ = _dash_commercial()
    return _dash_nocache(_dash.get_comparatif_annuel(owner_id))

@app.route("/dash/api/dn")
def dash_api_dn():
    agent = request.args.get("agent")
    if agent is not None:
        if agent == "all":
            return _dash_nocache(_dash.get_dn_analyse(owner_ids=list(_dash.AGENTS.keys())))
        elif agent in _dash.AGENTS:
            return _dash_nocache(_dash.get_dn_analyse(owner_id=agent))
        return _dash_nocache({"error": "Agent inconnu", "dn_produits": [], "nb_clients": 0})
    owner_id, _ = _dash_commercial()
    return _dash_nocache(_dash.get_dn_analyse(owner_id))

@app.route("/dash/api/portefeuille")
def dash_api_portefeuille():
    owner_id, _ = _dash_commercial()
    return _dash_nocache(_dash.get_portefeuille(owner_id))

@app.route("/dash/api/ro-equipe")
def dash_api_ro_equipe():
    from datetime import date as _date
    debut = request.args.get("debut")
    fin   = request.args.get("fin")
    if not debut or not fin:
        today = _date.today()
        debut = today.replace(day=1).strftime("%Y-%m-%d")
        fin   = today.strftime("%Y-%m-%d")
    return _dash_nocache(_dash.get_ro_equipe(debut, fin))

@app.route("/dash/api/comparatif-portefeuilles")
def dash_api_comparatif_portefeuilles():
    return _dash_nocache(_dash.get_comparatif_portefeuilles())

@app.route("/dash/api/clients-ca")
def dash_api_clients_ca():
    owner_id, _ = _dash_commercial()
    annee = int(request.args.get("annee", 2026))
    return _dash_nocache(_dash.get_clients_ca_annee(owner_id, annee))

@app.route("/dash/api/dn-benchmarks")
def dash_api_dn_benchmarks():
    exclude = request.args.get("exclude")
    return _dash_nocache(_dash.get_dn_benchmarks(exclude_owner_id=exclude))

@app.route("/dash/api/debug-ca")
def dash_api_debug_ca():
    """Debug : deals d'Amir avec closedate en mai 2025, tous pipelines."""
    import requests as _req
    from config import HUBSPOT_API_KEY
    payload = {
        "filterGroups": [{"filters": [
            {"propertyName": "closedate",        "operator": "GTE", "value": _dash._to_ms("2025-05-01")},
            {"propertyName": "closedate",        "operator": "LTE", "value": _dash._to_ms("2025-05-31", end_of_day=True)},
            {"propertyName": "hubspot_owner_id", "operator": "EQ",  "value": "727665403"},
        ]}],
        "properties": ["dealname", "amount", "closedate", "pipeline", "dealstage"],
        "limit": 50,
    }
    r = _req.post("https://api.hubapi.com/crm/v3/objects/deals/search",
                  json=payload,
                  headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"},
                  timeout=15)
    if r.status_code != 200:
        return jsonify({"error": r.status_code, "detail": r.text[:300]})
    results = []
    for d in r.json().get("results", []):
        p = d.get("properties", {})
        results.append({
            "id":       d["id"],
            "nom":      p.get("dealname"),
            "montant":  p.get("amount"),
            "closedate":p.get("closedate", "")[:10],
            "pipeline": p.get("pipeline"),
            "stage":    p.get("dealstage"),
        })
    return jsonify({"total": r.json().get("total", 0), "deals": results})


@app.route("/dash/api/debug-dn")
def dash_api_debug_dn():
    """Debug : nb clients par commercial Naali et leur DN moyenne."""
    from collections import defaultdict
    clients = _dash._get_all_clients(owner_ids=list(_dash.COMMERCIAUX.keys()))
    by_owner = defaultdict(list)
    for c in clients:
        by_owner[c["owner_id"]].append(c)
    result = {}
    for oid, info in _dash.COMMERCIAUX.items():
        cl = by_owner.get(oid, [])
        nb_with_cat = sum(1 for c in cl if c["cat_set"])
        dn_by_prod = {}
        for prod in _dash.CATALOGUE_ACTIF:
            nb = sum(1 for c in cl if _dash._has_product(c["cat_set"], prod))
            dn_by_prod[prod] = round(nb / len(cl) * 100, 1) if cl else 0
        result[oid] = {
            "name":         info["name"],
            "nb_clients":   len(cl),
            "nb_with_cat":  nb_with_cat,
            "dn_produits":  dn_by_prod,
        }
    return _dash_nocache(result)

@app.route("/dash/api/commerciaux")
def dash_api_commerciaux():
    return _dash_nocache([{"id": oid, **info} for oid, info in _dash.COMMERCIAUX.items()])

@app.route("/dash/api/agents")
def dash_api_agents():
    return _dash_nocache([{"id": oid, **info} for oid, info in _dash.AGENTS.items()])

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, importlib
    parser = argparse.ArgumentParser()
    parser.add_argument("--test",    action="store_true", help="Mode test (sans écriture HubSpot)")
    parser.add_argument("--port",    type=int, default=5001)
    parser.add_argument("--profile", type=str, default=None, help="Ex: icham  → charge config_icham.py")
    args = parser.parse_args()

    import config as cfg

    # Charger les overrides du profil si spécifié
    if args.profile:
        profile_module = f"config_{args.profile}"
        try:
            overrides = importlib.import_module(profile_module)
            for key in ["HUBSPOT_OWNER_ID", "OWNER_NAME", "CSV_PATH", "HOME_LAT", "HOME_LON", "HOME_CITY"]:
                if hasattr(overrides, key):
                    setattr(cfg, key, getattr(overrides, key))
            # Recharger les variables dans le module courant
            from config import HUBSPOT_OWNER_ID, OWNER_NAME, CSV_PATH, HOME_LAT, HOME_LON
            print(f"[PROFIL] {cfg.OWNER_NAME} — CSV: {cfg.CSV_PATH}")
        except ModuleNotFoundError:
            print(f"[ERREUR] Profil '{args.profile}' introuvable (config_{args.profile}.py manquant)")
            sys.exit(1)

    if args.test:
        cfg.TEST_MODE = True
        print("[TEST MODE] Aucune écriture HubSpot ne sera effectuée.")

    print(f"Naali Planner — {cfg.OWNER_NAME} — http://localhost:{args.port}")
    app.run(debug=True, port=args.port, host="0.0.0.0")

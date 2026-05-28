"""
demo/mock_data.py
Données fictives pour la démo Naali Planner.
Pharmacies réelles (demo/pharmacies.json) + visites/CA/notes inventés.
"""
import json, os, random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
_BASE = os.path.dirname(os.path.abspath(__file__))

# ── Chargement pharmacies réelles ─────────────────────────────────────────────
def _load_pharmacies():
    with open(os.path.join(_BASE, "pharmacies.json"), encoding="utf-8") as f:
        return json.load(f)

_PH = _load_pharmacies()
_CLIENTS    = [p for p in _PH if p["client_naali"].lower() in ("true","rétrocession","retrocession","1","oui")]
_PROSPECTS  = [p for p in _PH if p not in _CLIENTS]
_PH_BY_ID   = {p["id"]: p for p in _PH}

# ── Seed reproductible (même données à chaque démo) ──────────────────────────
_RNG = random.Random(42)

# ── Constantes fictives ───────────────────────────────────────────────────────
_TYPES_COMMANDE = ["Réassort", "Implantation", "Compléments", "Précommande lancement"]
_MOTIFS         = ["Passage commercial", "Suivi client", "Formation équipe", "Présentation nouveauté"]
_OUTCOMES       = ["COMPLETED", "COMPLETED", "COMPLETED", "NO_SHOW", "RESCHEDULED"]
_TYPES_VISITE   = ["VC", "VC", "VC", "VP", "VP", "RC"]
_NOTES_CLIENTS  = [
    "Titulaire présent. Satisfait des résultats Naali. Réassort validé sur Collagène et Gommes.",
    "Rendez-vous avec responsable achats. Commande passée. Sellout en cours, bon retour équipe.",
    "Visite rapide. Titulaire absent, responsable achat a confirmé la commande. À suivre.",
    "Formation équipe officine réalisée. 3 conseillères formées sur la gamme complète.",
    "Bon accueil. CA en progression. Ont accepté d'élargir sur les références manquantes.",
    "Titulaire motivé, veut passer au pack supérieur. Devis envoyé pour Pack Partenaire.",
    "Litige paiement réglé. Relation normalisée. Commande relancée.",
    "Démo produit réalisée en zone conseil. Bonne réception des nouveautés saison.",
]
_NOTES_PROSPECTS = [
    "Premier contact. Pharmacien intéressé mais souhaite réfléchir. Rappel dans 3 semaines.",
    "Prospect tiède. A demandé des échantillons. Relance planifiée.",
    "Pas disponible. Secrétaire a pris les coordonnées. À recontacter.",
    "Intérêt pour la gamme Zen. Souhaite voir les tarifs. Devis à envoyer.",
    "Pas de rendez-vous. Laissé documentation. Suivi dans 1 mois.",
    "Titulaire curieux, connaît déjà Naali via un confrère. Bon potentiel.",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _isodate(d: date) -> str:
    return d.isoformat()

def _fake_meeting_id(n: int) -> str:
    return f"demo_{n:010d}"

def _fake_deal_id(n: int) -> str:
    return f"deal_{n:010d}"

def _monday(offset_weeks: int = 0) -> date:
    today = date.today()
    dow = today.weekday()
    return today - timedelta(days=dow) + timedelta(weeks=offset_weeks)

def _fmt_dt(d: date, h: int, m: int) -> str:
    return f"{d.isoformat()}T{h:02d}:{m:02d}:00+02:00"

# ── Génération meetings semaine ───────────────────────────────────────────────
def _gen_week_meetings(offset: int, seed_extra: int = 0) -> list:
    """Génère ~8-10 meetings fictifs pour la semaine `offset`."""
    lundi = _monday(offset)
    rng = random.Random(42 + offset * 100 + seed_extra)

    meetings = []
    mtg_id = abs(offset) * 1000 + seed_extra * 500

    # Jours lundi-vendredi
    jours = [(lundi + timedelta(days=i)) for i in range(5)]

    # Clients : 3-4 par semaine
    clients_sample = rng.sample(_CLIENTS, min(len(_CLIENTS), rng.randint(3, 5)))
    # Prospects : 4-6 par semaine
    prospects_sample = rng.sample(_PROSPECTS, min(len(_PROSPECTS), rng.randint(4, 7)))

    all_visites = (
        [(p, "VC") for p in clients_sample] +
        [(p, "VP") for p in prospects_sample]
    )
    rng.shuffle(all_visites)

    heures = [9, 10, 11, 14, 15, 16, 17]
    h_idx = 0

    for i, (pharma, vtype) in enumerate(all_visites[:10]):
        jour = jours[i % 5]
        heure = heures[h_idx % len(heures)]
        h_idx += 1
        dt_start = _fmt_dt(jour, heure, 0)
        dt_end   = _fmt_dt(jour, heure + (1 if vtype == "VC" else 0), 30 if vtype == "VP" else 0)

        past = jour < date.today()
        outcome = rng.choice(["COMPLETED","COMPLETED","COMPLETED","NO_SHOW"]) if past else "SCHEDULED"

        has_note = past and outcome == "COMPLETED" and rng.random() > 0.25
        note_pool = _NOTES_CLIENTS if vtype == "VC" else _NOTES_PROSPECTS
        note_text = rng.choice(note_pool) if has_note else None

        meetings.append({
            "id":           _fake_meeting_id(mtg_id + i),
            "titre":        f"{vtype} — {pharma['nom']}",
            "type":         vtype,
            "dt":           dt_start,
            "dt_end":       dt_end,
            "heure":        f"{heure:02d}:00",
            "company_id":   pharma["id"],
            "company_nom":  pharma["nom"],
            "city":         pharma["ville"],
            "outcome":      outcome,
            "has_note":     has_note,
            "has_photo":    has_note and rng.random() > 0.6,
            "last_note_text": note_text,
            "last_note_date": (date.today() - timedelta(days=rng.randint(0, 3))).strftime("%d/%m %H:%M") if has_note else None,
            "date_label":   jour.strftime("%A %d/%m"),
        })

    return meetings

# ── Génération deals fictifs ──────────────────────────────────────────────────
def _gen_deals(company_id: str, count: int = 4) -> list:
    rng = random.Random(int(company_id or "0") % 9999 + 1)
    deals = []
    base = date.today()
    for i in range(count):
        d = base - timedelta(days=rng.randint(10, 300))
        montant = round(rng.uniform(80, 800), 2)
        deals.append({
            "id":           _fake_deal_id(int(company_id or "0") + i),
            "nom":          _PH_BY_ID.get(company_id, {}).get("nom", "Pharmacie"),
            "closedate":    f"{d.isoformat()}T10:00:00.000Z",
            "date_label":   d.strftime("%d/%m/%Y"),
            "montant":      montant,
            "type_commande": rng.choice(_TYPES_COMMANDE),
            "origine":      "Commercial Naali",
            "pipeline":     "demo_pipeline",
            "stage":        "demo_stage",
            "prise_commande": "demo",
            "remise":       rng.choice(["30%","35%",None]),
        })
    deals.sort(key=lambda x: x["closedate"], reverse=True)
    return deals

# ── Génération notes fictives ─────────────────────────────────────────────────
def _gen_notes(company_id: str, is_client: bool) -> dict:
    rng = random.Random(int(company_id or "1") % 9999 + 7)
    pool = _NOTES_CLIENTS if is_client else _NOTES_PROSPECTS
    text = rng.choice(pool)
    days_ago = rng.randint(5, 45)
    d = date.today() - timedelta(days=days_ago)
    date_label = d.strftime("%d/%m/%Y %H:%M")
    notes_list = [
        {"text": text, "date": date_label},
        {"text": rng.choice(pool), "date": (d - timedelta(days=rng.randint(20,60))).strftime("%d/%m/%Y %H:%M")},
    ]
    if rng.random() > 0.5:
        notes_list.append({"text": rng.choice(pool), "date": (d - timedelta(days=rng.randint(80,120))).strftime("%d/%m/%Y %H:%M")})
    return {
        "has_note":       True,
        "has_photo":      rng.random() > 0.6,
        "last_note_text": text,
        "last_note_date": date_label,
        "notes_list":     notes_list,
    }

# ── Génération DN fictif ──────────────────────────────────────────────────────
_CATALOGUE_REF = [
    "Collagène Citron-Vert Menthe","Gommes Anti Stress x42","Gommes Anti Stress x60",
    "Zen","Sommeil","Minceur","Vitalité","Articulations","Immunité","Beauté Peau"
]

def _gen_dn(company_id: str, is_client: bool) -> dict:
    rng = random.Random(int(company_id or "1") % 9999 + 3)
    if not is_client:
        return {"refs": 0, "total": len(_CATALOGUE_REF), "pct": 0, "presents": [], "manquants": _CATALOGUE_REF[:]}
    n = rng.randint(2, len(_CATALOGUE_REF))
    presents  = rng.sample(_CATALOGUE_REF, n)
    manquants = [r for r in _CATALOGUE_REF if r not in presents]
    pct = round(n / len(_CATALOGUE_REF) * 100)
    return {"refs": n, "total": len(_CATALOGUE_REF), "pct": pct, "presents": presents, "manquants": manquants}

# ── API mocks ─────────────────────────────────────────────────────────────────

def mock_today() -> dict:
    today_str = date.today().isoformat()
    week_mtgs = _gen_week_meetings(0)
    today_mtgs = [m for m in week_mtgs if m["dt"].startswith(today_str)]

    _CREDITS = {"VC": 2, "VP": 1, "RC": 2, "RP": 2, "F": 2}
    _MAX = {0:8,1:10,2:10,3:10,4:8}
    wd = date.today().weekday()
    pts_max  = _MAX.get(wd, 8)
    pts_used = sum(_CREDITS.get(m["type"], 1) for m in today_mtgs)
    pts_left = max(0, pts_max - pts_used)

    cr_manquants = [
        m for m in _gen_week_meetings(-1)
        if m["outcome"] == "COMPLETED" and not m["has_note"]
    ]

    return {
        "today_meetings":    today_mtgs,
        "points_max":        pts_max,
        "points_used":       pts_used,
        "points_left":       pts_left,
        "cr_manquants":      cr_manquants,
        "ca_mois":           14280.0,
        "ca_ytd":            68450.0,
        "ca_objectif":       180000.0,
        "offres_jour":       [],
        "actions_echeances": [],
        "hub_id":            "143439337",
    }

def mock_kpis() -> dict:
    return {
        "owner_name":    "Amir Ounissi",
        "hub_id":        "143439337",
        "ca_mois":       14280.0,
        "ca_ytd":        68450.0,
        "ca_objectif":   180000.0,
        "nb_clients":    len(_CLIENTS),
        "nb_prospects":  len(_PROSPECTS),
        "nb_meetings_semaine": 9,
        "implantations_mois":  2,
    }

def mock_agenda(offset: int = 0) -> dict:
    meetings = _gen_week_meetings(offset)
    return {"meetings": meetings, "hub_id": "143439337"}

def mock_post_rdv(date_from: str = None, date_to: str = None) -> dict:
    past = _gen_week_meetings(-1) + _gen_week_meetings(-2)
    completed = [m for m in past if m["outcome"] in ("COMPLETED","NO_SHOW","RESCHEDULED")]
    sans_note  = [m for m in completed if not m["has_note"] and m["outcome"] != "NO_SHOW"]
    sans_photo = [m for m in completed if m["has_note"] and not m["has_photo"]]
    completes  = [m for m in completed if m["has_note"]]
    return {"sans_note": sans_note, "sans_photo": sans_photo, "completes": completes}

def mock_brief_meeting(meeting_id: str) -> dict:
    # Retrouver le meeting dans la semaine courante ou passée
    all_mtgs = _gen_week_meetings(0) + _gen_week_meetings(-1)
    mtg = next((m for m in all_mtgs if m["id"] == meeting_id), None)
    company_id = mtg["company_id"] if mtg else (_CLIENTS[0]["id"] if _CLIENTS else "")
    return mock_brief_company(company_id, meeting_type=mtg["type"] if mtg else "VC")

def mock_brief_company(company_id: str, meeting_type: str = None) -> dict:
    pharma = _PH_BY_ID.get(company_id, _CLIENTS[0] if _CLIENTS else {})
    is_cl  = pharma.get("client_naali","").lower() in ("true","rétrocession","retrocession","1","oui")
    rng    = random.Random(int(company_id or "1") % 9999)

    _PACK_LABELS = {
        "Prioritaires":    ("partenaire",  "35%"),
        "Secondaires":     ("démarrage",   "30%"),
        "Non Prioritaires":("découverte",  "30%"),
    }
    pot = pharma.get("potentiel","")
    pack_key, remise = _PACK_LABELS.get(pot, ("découverte","30%")) if is_cl else (None, None)

    deals = _gen_deals(company_id, count=rng.randint(2,6)) if is_cl else []
    ca_2025 = round(sum(d["montant"] for d in deals if "2025" in d["closedate"]), 2)
    ca_2026 = round(sum(d["montant"] for d in deals if "2026" in d["closedate"]), 2)
    note   = _gen_notes(company_id, is_cl) if is_cl or rng.random() > 0.5 else {"has_note":False,"has_photo":False,"last_note_text":None,"last_note_date":None,"notes_list":[]}
    dn     = _gen_dn(company_id, is_cl)
    last_deal = deals[0] if deals else None

    return {
        "meeting_id":    None,
        "titre":         pharma.get("nom",""),
        "type":          meeting_type,
        "outcome":       "SCHEDULED" if meeting_type else None,
        "company": {
            "id":          company_id,
            "nom":         pharma.get("nom",""),
            "ville":       pharma.get("ville",""),
            "cp":          pharma.get("cp",""),
            "phone":       "+33400000000",
            "client_naali": pharma.get("client_naali",""),
            "potentiel":   pot,
            "catalogue":   pharma.get("catalogue",""),
            "groupement":  pharma.get("groupement",""),
            "remise":      remise,
            "remise_2025": remise,
            "remise_2026": remise,
            "lead_status": pack_key.capitalize() if pack_key else "",
            "pennylane_id": None,
        },
        "deals":         deals[:5],
        "last_note":     note,
        "notes_list":    note.get("notes_list",[]),
        "dn":            dn,
        "ca_total":      ca_2025 + ca_2026,
        "last_deal":     last_deal,
        "lead_status":   pack_key.capitalize() if pack_key else "",
        "offres_compte": [],
        "actions_compte":[],
        "hub_id":        "143439337",
    }

def mock_search(q: str) -> dict:
    q = q.lower()
    results = [
        p for p in _PH
        if q in p["nom"].lower() or q in p["ville"].lower()
    ][:15]
    is_cl_set = {p["id"] for p in _CLIENTS}
    return {"results": [
        {
            "nom":        p["nom"],
            "ville":      p["ville"],
            "cp":         p["cp"],
            "id_hubspot": p["id"],
            "is_client":  p["id"] in is_cl_set,
        } for p in results
    ]}

def mock_planificateur(payload: dict) -> dict:
    """Suggestions fictives pour le planificateur."""
    rng = random.Random(99)
    jours_noms = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi"]
    lundi = _monday(0)
    jours = []
    for i in range(5):
        d = lundi + timedelta(days=i)
        suggs = []
        pool = _PROSPECTS if i % 2 == 0 else _CLIENTS
        for pharma in rng.sample(pool, min(len(pool), 3)):
            suggs.append({
                "id_hubspot":  pharma["id"],
                "nom":         pharma["nom"],
                "ville":       pharma["ville"],
                "cp":          pharma["cp"],
                "type_visite": "VC" if pharma in _CLIENTS else "VP",
                "score":       rng.randint(30, 120),
                "groupe_dn":   rng.choice([0,1,2]),
                "is_retard":   rng.random() > 0.7,
                "is_proche":   rng.random() > 0.6,
                "potentiel":   pharma.get("potentiel",""),
            })
        jours.append({
            "date_str":     d.isoformat(),
            "nom":          jours_noms[i],
            "debut":        "12:00" if i == 0 else "09:00",
            "credits_libre": rng.randint(2, 6),
            "suggestions":  suggs,
        })
    return {
        "jours":              jours,
        "total_suggestions":  sum(len(j["suggestions"]) for j in jours),
        "villes_par_dept":    {},
        "origines_disponibles": [],
    }

def mock_portefeuille() -> dict:
    rng = random.Random(55)
    rows = []
    for p in _CLIENTS:
        days_ago = rng.randint(5, 120)
        last = (date.today() - timedelta(days=days_ago)).isoformat()
        ca = round(rng.uniform(200, 3000), 2)
        rows.append({
            "company_id":   p["id"],
            "nom":          p["nom"],
            "ville":        p["ville"],
            "cp":           p["cp"],
            "potentiel":    p.get("potentiel",""),
            "last_visit":   last,
            "days_since":   days_ago,
            "ca_ytd":       ca,
            "has_note":     True,
            "pba":          "Réassort" if days_ago > 30 else "OK",
        })
    return {"pharmacies": rows, "hub_id": "143439337", "total": len(rows)}

from datetime import datetime, timedelta, date as date_type
import pytz
from core.itineraire import distance_km

PARIS = pytz.timezone("Europe/Paris")

# Crédits consommés par type de visite
CREDITS = {"VC": 2, "VP": 1, "RC": 2, "RP": 2, "F": 2}
# Durées en minutes
DUREES  = {"VC": 30, "VP": 30, "RC": 60, "RP": 60, "F": 60}


def _parse_heure(d: date_type, heure_str: str) -> datetime:
    """Convertit 'HH:MM' en datetime Paris-aware pour la date donnée."""
    h, m = map(int, heure_str.split(":"))
    dt = datetime(d.year, d.month, d.day, h, m, tzinfo=PARIS)
    return dt


def _type_visite(pharmacie: dict) -> str:
    """Détermine le type de visite selon le statut du client."""
    from core.filtres import is_client
    return "VC" if is_client(pharmacie) else "VP"


def construire_planning_jour(
    jour: dict,
    pharmacies_selectionnees: list,
    meetings_existants: list,
    home_lat: float = None,
    home_lon: float = None,
    ratio_vc_cible: float = 40.0,
    preserve_order: bool = False,
) -> dict:
    """
    Construit le planning horaire pour un jour.
    """
    d = jour["date"] if isinstance(jour["date"], date_type) else datetime.strptime(jour["date"], "%Y-%m-%d").date()
    credits_max = jour.get("credits", 0)
    debut_str = jour.get("debut", "09:00")
    fin_str = jour.get("fin", "18:30")

    dt_debut = _parse_heure(d, debut_str)
    dt_fin = _parse_heure(d, fin_str)

    # Pause déjeuner (Mardi–Jeudi : 12h30–14h00)
    pause_debut_str = jour.get("pause_debut")
    pause_fin_str   = jour.get("pause_fin")
    dt_pause_debut = _parse_heure(d, pause_debut_str) if pause_debut_str else None
    dt_pause_fin   = _parse_heure(d, pause_fin_str)   if pause_fin_str   else None

    # Construire les créneaux occupés (injecter la pause en premier)
    occupes = []
    if dt_pause_debut and dt_pause_fin:
        occupes.append({"dt_start": dt_pause_debut, "dt_end": dt_pause_fin, "titre": "Pause déjeuner", "_pause": True})
    for m in meetings_existants:
        ts = m.get("hs_timestamp")
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt_m = datetime.fromtimestamp(ts / 1000, tz=PARIS)
                else:
                    dt_m = datetime.fromisoformat(str(ts)).astimezone(PARIS)
                duree = m.get("duree_min", 60)
                occupes.append({
                    "dt_start": dt_m,
                    "dt_end": dt_m + timedelta(minutes=duree),
                    "titre": m.get("hs_meeting_title", "Réunion"),
                })
            except Exception:
                pass

    # Si déjà géo-ordonné (planification semaine), conserver l'ordre STRICTEMENT
    # Sinon trier par priorité (planification jour manuel)
    if preserve_order:
        pharmacies_triees = list(pharmacies_selectionnees)
    else:
        pharmacies_triees = _trier_par_priorite(pharmacies_selectionnees)

    visites = []
    credits_utilises = 0
    cursor = dt_debut
    vc_count = 0
    vp_count = 0

    if preserve_order:
        # Mode géographique : respecter l'ordre exact, pas d'interleaving VC/VP
        # Les distances sont calculées sur l'ordre final des visites retenues
        file = list(pharmacies_triees)
        while file:
            if credits_utilises >= credits_max:
                break
            pharma = file.pop(0)
            type_v    = _type_visite(pharma)
            credit_v  = CREDITS.get(type_v, 2)
            duree_min = DUREES.get(type_v, 60)
            if credits_utilises + credit_v > credits_max:
                continue
            cursor = _avancer_hors_occupes(cursor, duree_min, occupes, dt_fin)
            dt_end = cursor + timedelta(minutes=duree_min)
            if dt_end > dt_fin:
                break
            if dt_pause_debut and cursor < dt_pause_debut:
                periode = "matin"
            elif dt_pause_fin and cursor >= dt_pause_fin:
                periode = "apres_midi"
            else:
                periode = "matin"
            visites.append({
                "pharmacie":       pharma,
                "type_visite":     type_v,
                "dt_start":        cursor.isoformat(),
                "dt_end":          dt_end.isoformat(),
                "heure_debut":     cursor.strftime("%H:%M"),
                "heure_fin":       dt_end.strftime("%H:%M"),
                "credits":         credit_v,
                "refs_manquantes": pharma.get("refs_manquantes", []),
                "periode":         periode,
            })
            credits_utilises += credit_v
            if type_v == "VC":
                vc_count += 1
            else:
                vp_count += 1
            cursor = dt_end
        # Annoter les distances sur l'ordre réel des visites retenues
        _annoter_distances([v["pharmacie"] for v in visites], home_lat, home_lon)
    else:
        # Mode manuel : Bresenham VC/VP sur ordre priorité
        _annoter_distances(pharmacies_triees, home_lat, home_lon)
        from core.filtres import is_client as _is_client
        vc_queue = [p for p in pharmacies_triees if _is_client(p)]
        vp_queue = [p for p in pharmacies_triees if not _is_client(p)]
        acc_ratio = 0.0

        while vc_queue or vp_queue:
            if credits_utilises >= credits_max:
                break
            acc_ratio += ratio_vc_cible
            if acc_ratio >= 100.0 and vc_queue:
                pharma = vc_queue.pop(0)
                acc_ratio -= 100.0
            elif vp_queue:
                pharma = vp_queue.pop(0)
            elif vc_queue:
                pharma = vc_queue.pop(0)
            else:
                break

            type_v    = _type_visite(pharma)
            credit_v  = CREDITS.get(type_v, 2)
            duree_min = DUREES.get(type_v, 60)

            if credits_utilises + credit_v > credits_max:
                continue

            cursor = _avancer_hors_occupes(cursor, duree_min, occupes, dt_fin)
            dt_end = cursor + timedelta(minutes=duree_min)
            if dt_end > dt_fin:
                break

            if dt_pause_debut and cursor < dt_pause_debut:
                periode = "matin"
            elif dt_pause_fin and cursor >= dt_pause_fin:
                periode = "apres_midi"
            else:
                periode = "matin"

            visites.append({
                "pharmacie":       pharma,
                "type_visite":     type_v,
                "dt_start":        cursor.isoformat(),
                "dt_end":          dt_end.isoformat(),
                "heure_debut":     cursor.strftime("%H:%M"),
                "heure_fin":       dt_end.strftime("%H:%M"),
                "credits":         credit_v,
                "refs_manquantes": pharma.get("refs_manquantes", []),
                "periode":         periode,
            })
            credits_utilises += credit_v
            if type_v == "VC":
                vc_count += 1
            else:
                vp_count += 1
            cursor = dt_end

    total_visites = vc_count + vp_count
    ratio_vc = (vc_count / total_visites * 100) if total_visites > 0 else 0

    # Filtrer les occupes non-pause pour le retour (ne pas exposer la pause interne)
    occupes_externes = [o for o in occupes if not o.get("_pause")]

    return {
        "date": jour.get("date_str", str(d)),
        "nom": jour.get("nom", ""),
        "visites": visites,
        "matin":      [v for v in visites if v.get("periode") == "matin"],
        "apres_midi": [v for v in visites if v.get("periode") == "apres_midi"],
        "pause_debut": pause_debut_str,
        "pause_fin":   pause_fin_str,
        "credits_utilises": credits_utilises,
        "credits_max": credits_max,
        "credits_libres": max(0, credits_max - credits_utilises),
        "occupes": occupes_externes,
        "vc": vc_count,
        "vp": vp_count,
        "ratio_vc": round(ratio_vc, 1),
        "ratio_ok": abs(ratio_vc - ratio_vc_cible) <= 10,
        "ratio_cible": ratio_vc_cible,
    }


def _annoter_distances(pharmacies: list, home_lat: float = None, home_lon: float = None):
    """
    Recalcule distance_prec_km sur chaque pharmacie dans l'ordre donné.
    La première visite part du domicile si home_lat/home_lon sont fournis.
    """
    prev_lat = home_lat
    prev_lon = home_lon
    for p in pharmacies:
        try:
            lat = float(p.get("lat") or "")
            lon = float(p.get("lon") or "")
        except (ValueError, TypeError):
            p["distance_prec_km"] = None
            continue
        if prev_lat is not None and prev_lon is not None:
            p["distance_prec_km"] = round(distance_km(prev_lat, prev_lon, lat, lon), 1)
        else:
            p["distance_prec_km"] = None
        prev_lat, prev_lon = lat, lon


def _trier_par_priorite(pharmacies: list) -> list:
    """
    Ordre : 🔴 retard → 🟡 proche → Prioritaires → Secondaires
    """
    def sort_key(p):
        retard = 1 if p.get("is_retard") else 0
        proche = 1 if p.get("is_proche") else 0
        ordre_potentiel = {"Prioritaires": 0, "Secondaires": 1, "Non Prioritaires": 2}
        pot = ordre_potentiel.get(p.get("potentiel", ""), 99)
        groupe = p.get("groupe_dn", 1)
        return (-retard, -proche, groupe, pot)

    return sorted(pharmacies, key=sort_key)


def _avancer_hors_occupes(cursor: datetime, duree_min: int, occupes: list, dt_fin: datetime) -> datetime:
    """Avance le curseur pour éviter les créneaux occupés."""
    MAX_ITER = 20
    for _ in range(MAX_ITER):
        dt_end = cursor + timedelta(minutes=duree_min)
        conflit = False
        for occ in occupes:
            # Chevauchement ?
            if cursor < occ["dt_end"] and dt_end > occ["dt_start"]:
                cursor = occ["dt_end"]
                conflit = True
                break
        if not conflit:
            break
    return cursor


def construire_planning_semaines(
    jours: list,
    pharmacies_par_jour: dict,
    meetings_par_jour: dict,
    home_lat: float = None,
    home_lon: float = None,
    ratio_vc_cible: float = 40.0,
) -> list:
    """
    Construit le planning sur N jours.
    """
    planning = []
    total_vc = 0
    total_vp = 0

    for jour in jours:
        if jour.get("ferie") or jour.get("credits", 0) == 0:
            planning.append({
                "date": jour.get("date_str"),
                "nom": jour.get("nom"),
                "ferie": jour.get("ferie", False),
                "ferie_nom": jour.get("ferie_nom", ""),
                "visites": [],
                "credits_utilises": 0,
                "credits_max": 0,
                "vc": 0,
                "vp": 0,
                "ratio_vc": 0,
                "ratio_ok": True,
            })
            continue

        ds = jour["date_str"]
        pharmacies = pharmacies_par_jour.get(ds, [])
        meetings = meetings_par_jour.get(ds, [])

        result = construire_planning_jour(jour, pharmacies, meetings, home_lat=home_lat, home_lon=home_lon, ratio_vc_cible=ratio_vc_cible, preserve_order=True)
        result["ferie"] = False
        result["ferie_nom"] = ""
        planning.append(result)
        total_vc += result["vc"]
        total_vp += result["vp"]

    # Ratio global
    total = total_vc + total_vp
    ratio_global = (total_vc / total * 100) if total > 0 else 0

    # Synthèse crédits
    total_credits_max      = sum(j.get("credits_max", 0)      for j in planning)
    total_credits_utilises = sum(j.get("credits_utilises", 0) for j in planning)
    total_credits_libres   = max(0, total_credits_max - total_credits_utilises)

    # Jours avec crédits disponibles (pour le remplissage)
    jours_avec_place = [
        {"date": j["date"], "nom": j.get("nom",""), "libres": j.get("credits_libres", 0)}
        for j in planning
        if not j.get("ferie") and j.get("credits_libres", 0) > 0
    ]

    return {
        "jours": planning,
        "total_vc": total_vc,
        "total_vp": total_vp,
        "ratio_global": round(ratio_global, 1),
        "ratio_global_ok": abs(ratio_global - ratio_vc_cible) <= 10,
        "ratio_cible": ratio_vc_cible,
        "total_credits_max": total_credits_max,
        "total_credits_utilises": total_credits_utilises,
        "total_credits_libres": total_credits_libres,
        "jours_avec_place": jours_avec_place,
    }

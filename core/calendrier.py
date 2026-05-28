from datetime import date, timedelta

try:
    import holidays
except ImportError:
    holidays = None

# Jours fériés où Amir travaille quand même (traités comme jours normaux)
JOURS_TRAVAILLES_MALGRE_FERIE = {
    date(2026, 5, 25),  # Lundi de Pentecôte 2026
}

CAPACITE = {
    "Lundi":    {"credits": 8,  "debut": "12:00", "fin": "18:30", "pause_debut": None,    "pause_fin": None},
    "Mardi":    {"credits": 10, "debut": "09:00", "fin": "18:30", "pause_debut": "12:30", "pause_fin": "14:00"},
    "Mercredi": {"credits": 10, "debut": "09:00", "fin": "18:30", "pause_debut": "12:30", "pause_fin": "14:00"},
    "Jeudi":    {"credits": 10, "debut": "09:00", "fin": "18:30", "pause_debut": "12:30", "pause_fin": "14:00"},
    "Vendredi": {"credits": 8,  "debut": "09:00", "fin": "12:00", "pause_debut": None,    "pause_fin": None},
}

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def get_prochain_lundi(depuis: date = None) -> date:
    """Retourne le lundi de la semaine courante, ou le suivant si weekend."""
    if depuis is None:
        depuis = date.today()
    wd = depuis.weekday()  # 0=lundi … 6=dimanche
    if wd < 5:  # lundi à vendredi → lundi de la semaine courante
        return depuis - timedelta(days=wd)
    else:        # samedi/dimanche → lundi suivant
        return depuis + timedelta(days=7 - wd)


def get_jours_ouvrables(date_debut: date, nb_semaines: int = 2, offset_semaines: int = 0) -> list:
    """
    Retourne la liste des jours ouvrables sur N semaines.
    offset_semaines : décalage en semaines depuis date_debut
      0  → date_debut (défaut)
     -1  → une semaine en arrière
     +1  → une semaine en avance
    Retourne : [{"date": date, "nom": "Lundi", "credits": 8, "debut": "12:00", "fin": "18:30", "ferie": False, "passe": bool, "today": bool}]
    """
    date_start = date_debut + timedelta(weeks=offset_semaines)
    today = date.today()

    if holidays is not None:
        fr_holidays = holidays.France(years=[date_start.year, date_start.year + 1])
    else:
        fr_holidays = {}

    jours = []
    current = date_start
    nb_jours = nb_semaines * 7

    for _ in range(nb_jours):
        weekday = current.weekday()  # 0=lundi … 4=vendredi
        if weekday < 5:  # jours de semaine uniquement
            nom = JOURS_FR[weekday]
            is_ferie = current in fr_holidays and current not in JOURS_TRAVAILLES_MALGRE_FERIE
            cap = CAPACITE.get(nom, {})
            jours.append({
                "date": current,
                "date_str": current.strftime("%Y-%m-%d"),
                "nom": nom,
                "credits": cap.get("credits", 0) if not is_ferie else 0,
                "debut": cap.get("debut", "09:00"),
                "fin": cap.get("fin", "18:30"),
                "pause_debut": cap.get("pause_debut"),
                "pause_fin": cap.get("pause_fin"),
                "ferie": is_ferie,
                "ferie_nom": fr_holidays.get(current, "") if is_ferie else "",
                "passe": current < today,
                "today": current == today,
            })
        current += timedelta(days=1)

    return jours


def formater_date(d: date) -> str:
    """Ex: 'Lundi 31/03/2026'"""
    nom = JOURS_FR[d.weekday()]
    return f"{nom} {d.strftime('%d/%m/%Y')}"


def get_semaines(jours: list) -> list:
    """Regroupe les jours par semaine."""
    if not jours:
        return []

    semaines = []
    semaine_courante = []
    semaine_num = None

    for jour in jours:
        iso_week = jour["date"].isocalendar()[1]
        if semaine_num is None:
            semaine_num = iso_week
        if iso_week != semaine_num:
            semaines.append(semaine_courante)
            semaine_courante = []
            semaine_num = iso_week
        semaine_courante.append(jour)

    if semaine_courante:
        semaines.append(semaine_courante)

    return semaines

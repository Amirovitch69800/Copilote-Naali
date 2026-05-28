"""
Génération de fichiers .ics compatibles Outlook.
- DTSTART/DTEND avec TZID=Europe/Paris (pas UTC)
- Bloc VTIMEZONE présent
- Séparateurs CRLF obligatoires
- UID stable : id_hubspot ou uuid4
"""
import uuid
from datetime import datetime, timedelta
import pytz

PARIS = pytz.timezone("Europe/Paris")

# Durées en minutes par type de visite
DUREES = {"VC": 60, "VP": 30, "RC": 60, "RP": 30, "F": 60}

VTIMEZONE = (
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Paris\r\n"
    "BEGIN:STANDARD\r\n"
    "TZOFFSETFROM:+0200\r\n"
    "TZOFFSETTO:+0100\r\n"
    "TZNAME:CET\r\n"
    "DTSTART:19701025T030000\r\n"
    "END:STANDARD\r\n"
    "BEGIN:DAYLIGHT\r\n"
    "TZOFFSETFROM:+0100\r\n"
    "TZOFFSETTO:+0200\r\n"
    "TZNAME:CEST\r\n"
    "DTSTART:19700329T020000\r\n"
    "END:DAYLIGHT\r\n"
    "END:VTIMEZONE\r\n"
)


def _ics_escape(text: str) -> str:
    """Échappe les caractères spéciaux ICS."""
    return (
        text.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n")
            .replace("\r", "")
    )


def _fmt_dt(dt: datetime) -> str:
    """Formate un datetime Paris en YYYYMMDDTHHMMSS pour TZID."""
    dt_paris = dt.astimezone(PARIS)
    return dt_paris.strftime("%Y%m%dT%H%M%S")


def generer_ics(visites: list, hubspot_ids: dict = None) -> bytes:
    """
    Génère un fichier .ics Outlook-compatible.

    visites : liste de dicts avec keys :
        - pharmacie (dict avec nom, ville, cp, id_hubspot)
        - type_visite : "VC" | "VP" | ...
        - dt_start : ISO string datetime
        - dt_end   : ISO string datetime (optionnel)
        - refs_manquantes : list[str] (optionnel)

    hubspot_ids : {index_visite: hubspot_meeting_id} — pour UID stable post-création
    """
    if hubspot_ids is None:
        hubspot_ids = {}

    lines = [
        "BEGIN:VCALENDAR\r\n",
        "VERSION:2.0\r\n",
        "PRODID:-//Naali Planner//FR\r\n",
        "CALSCALE:GREGORIAN\r\n",
        "METHOD:PUBLISH\r\n",
        "X-WR-CALNAME:Naali Planning\r\n",
        "X-WR-TIMEZONE:Europe/Paris\r\n",
        VTIMEZONE,
    ]

    for idx, v in enumerate(visites):
        pharma = v.get("pharmacie", {})
        type_v = v.get("type_visite", "VP")
        dt_start_str = v.get("dt_start", "")
        dt_end_str = v.get("dt_end", "")

        if not dt_start_str:
            continue

        try:
            dt_parsed = datetime.fromisoformat(dt_start_str)
            if dt_parsed.tzinfo is None:
                dt_parsed = PARIS.localize(dt_parsed)
            dt_start = dt_parsed.astimezone(PARIS)
        except Exception:
            continue

        # Durée selon type de visite
        duree_min = DUREES.get(type_v, 60)
        if dt_end_str:
            try:
                dt_end = datetime.fromisoformat(dt_end_str).astimezone(PARIS)
            except Exception:
                dt_end = dt_start + timedelta(minutes=duree_min)
        else:
            dt_end = dt_start + timedelta(minutes=duree_min)

        # UID : id_hubspot du meeting ou uuid4
        hs_meeting_id = hubspot_ids.get(idx)
        hs_company_id = pharma.get("id_hubspot", "")
        if hs_meeting_id:
            uid = f"{hs_meeting_id}@naali.fr"
        elif hs_company_id:
            uid = f"{hs_company_id}-{_fmt_dt(dt_start)}@naali.fr"
        else:
            uid = f"{uuid.uuid4()}@naali.fr"

        # Titre : "VC – PHARMACIE MARTIN (1234567 – 13001)"
        nom = pharma.get("nom", "Pharmacie")
        ville = pharma.get("ville", "")
        cp = pharma.get("cp", "")
        cip = pharma.get("cip", "")

        titre_parts = [f"{type_v} \u2013 {nom}"]
        if ville:
            titre_parts.append(f"({ville})")
        summary = _ics_escape(" ".join(titre_parts))

        # Description
        desc_lines = [f"Visite {'client' if type_v == 'VC' else 'prospect'} \u2013 {nom}"]
        if ville and cp:
            desc_lines.append(f"{ville} {cp}")
        potentiel = pharma.get("potentiel", "")
        if potentiel:
            desc_lines.append(f"Potentiel : {potentiel}")
        refs = v.get("refs_manquantes", [])
        if refs:
            desc_lines.append(f"DN manquantes : {', '.join(refs[:6])}")
        description = _ics_escape("\\n".join(desc_lines))

        # Location
        location = _ics_escape(f"{cp} {ville}".strip())

        event_lines = [
            "BEGIN:VEVENT\r\n",
            f"UID:{uid}\r\n",
            f"DTSTART;TZID=Europe/Paris:{_fmt_dt(dt_start)}\r\n",
            f"DTEND;TZID=Europe/Paris:{_fmt_dt(dt_end)}\r\n",
            f"SUMMARY:{summary}\r\n",
            f"DESCRIPTION:{description}\r\n",
            f"LOCATION:{location}\r\n",
            "ORGANIZER;CN=Amir Ounissi:MAILTO:a.ounissi@naali.fr\r\n",
            "STATUS:CONFIRMED\r\n",
            "END:VEVENT\r\n",
        ]
        lines.extend(event_lines)

    lines.append("END:VCALENDAR\r\n")

    content = "".join(lines)
    return content.encode("utf-8")

"""
Import meetings from .ics file directly into HubSpot.
Usage: python3 import_ics_hubspot.py path/to/planning.ics
"""
import sys, re
from datetime import datetime
import pytz

sys.path.insert(0, '/Users/amirounissi/naali_planner')
from config import HUBSPOT_API_KEY, HUBSPOT_OWNER_ID
from hubspot.meetings import create_meeting, PARIS

def parse_ics(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    events = []
    for block in re.split(r'BEGIN:VEVENT', content)[1:]:
        block = block.split('END:VEVENT')[0]

        def get(key):
            m = re.search(rf'^{key}[^:]*:(.+)$', block, re.MULTILINE)
            return m.group(1).strip() if m else ''

        uid      = get('UID')
        summary  = get('SUMMARY')
        dtstart  = get('DTSTART')
        dtend    = get('DTEND')
        location = get('LOCATION')

        # Extract company_id from UID: "47493118191-20260414T105100@naali.fr"
        m_uid = re.match(r'^(\d+)-', uid)
        company_id = m_uid.group(1) if m_uid else ''

        # Extract visit type from SUMMARY: "VP – PHARMACIE ..."
        m_type = re.match(r'^(VC|VP|RC|RP|F)\s*[–—\-]', summary.strip(), re.IGNORECASE)
        visit_type = m_type.group(1).upper() if m_type else 'VP'

        # Extract pharmacie name
        nom = re.sub(r'^(VC|VP|RC|RP|F)\s*[–—\-]\s*', '', summary).strip()
        # Remove code and CP from name: "PHARMACIE DES ETANGS - 2005889 - 13800"
        nom_clean = re.sub(r'\s*-\s*\d{7}\s*-\s*\d{5}.*$', '', nom).strip()

        # Parse datetime
        def parse_dt(s):
            # Format: 20260414T105100
            s = s.replace('Z', '')
            try:
                dt_naive = datetime.strptime(s, '%Y%m%dT%H%M%S')
                return PARIS.localize(dt_naive)
            except Exception:
                return None

        dt_start = parse_dt(dtstart)
        dt_end   = parse_dt(dtend)

        if not dt_start or not company_id:
            continue

        events.append({
            'pharmacie': {
                'nom': nom_clean,
                'id_hubspot': company_id,
                'ville': location,
            },
            'visit_type': visit_type,
            'dt_start': dt_start,
            'dt_end': dt_end,
            'summary': summary,
        })

    return events

def run(ics_path):
    events = parse_ics(ics_path)
    print(f"📋 {len(events)} meetings à créer\n")

    created, skipped = 0, 0
    for i, ev in enumerate(events):
        pharma = ev['pharmacie']
        try:
            result = create_meeting(
                pharmacie=pharma,
                visit_type=ev['visit_type'],
                dt_start=ev['dt_start'],
                refs_dn=[],
                owner_id=HUBSPOT_OWNER_ID,
            )
            if result:
                created += 1
                print(f"  ✅ [{i+1}/{len(events)}] {ev['dt_start'].strftime('%d/%m %H:%M')} · {ev['visit_type']} · {pharma['nom']}")
            else:
                skipped += 1
                print(f"  ⚠️  [{i+1}/{len(events)}] Échec : {pharma['nom']}")
        except Exception as e:
            skipped += 1
            print(f"  ❌ [{i+1}/{len(events)}] Erreur : {pharma['nom']} — {e}")

    print(f"\n{'='*50}")
    print(f"✅ {created} meetings créés · ⚠️  {skipped} échecs")

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '/Users/amirounissi/Downloads/naali_planning-5.ics'
    run(path)

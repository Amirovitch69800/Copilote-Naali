"""
Supprime les doublons HubSpot sur la période du planning.
Garde 1 seul meeting par (company_id, jour), supprime les autres.
"""
import sys, requests
from datetime import datetime, timezone
from collections import defaultdict
import pytz

sys.path.insert(0, '/Users/amirounissi/naali_planner')
from config import HUBSPOT_API_KEY, HUBSPOT_OWNER_ID

PARIS = pytz.timezone('Europe/Paris')
BASE = 'https://api.hubapi.com'
H = lambda: {'Authorization': f'Bearer {HUBSPOT_API_KEY}', 'Content-Type': 'application/json'}

def fetch_meetings(date_from, date_to):
    """Récupère tous les meetings sur la période."""
    ts_deb = str(int(datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc).timestamp() * 1000))
    ts_fin = str(int(datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc).timestamp() * 1000))
    payload = {
        'filterGroups': [{'filters': [
            {'propertyName': 'hubspot_owner_id', 'operator': 'EQ', 'value': str(HUBSPOT_OWNER_ID)},
            {'propertyName': 'hs_timestamp', 'operator': 'BETWEEN', 'value': ts_deb, 'highValue': ts_fin},
        ]}],
        'properties': ['hs_timestamp', 'hs_meeting_title', 'hs_activity_type'],
        'limit': 200,
    }
    r = requests.post(f'{BASE}/crm/v3/objects/meetings/search', json=payload, headers=H(), timeout=15)
    return r.json().get('results', []) if r.status_code == 200 else []

def get_company_id(meeting_id):
    r = requests.get(f'{BASE}/crm/v3/objects/meetings/{meeting_id}/associations/companies', headers=H(), timeout=8)
    if r.status_code == 200:
        results = r.json().get('results', [])
        return str(results[0]['id']) if results else ''
    return ''

def delete_meeting(meeting_id):
    r = requests.delete(f'{BASE}/crm/v3/objects/meetings/{meeting_id}', headers=H(), timeout=8)
    return r.status_code == 204

def run():
    print('🔍 Recherche des meetings du 14 au 25 avril...')
    meetings = fetch_meetings('2026-04-13T22:00:00', '2026-04-25T22:00:00')
    print(f'   {len(meetings)} meetings trouvés\n')

    # Pour chaque meeting, récupérer la company associée
    print('🔗 Récupération des associations company...')
    import concurrent.futures
    def enrich(m):
        ts = m.get('properties', {}).get('hs_timestamp')
        try:
            dt = datetime.fromtimestamp(int(ts) / 1000, tz=PARIS) if ts else None
        except (ValueError, TypeError):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(PARIS) if ts else None
        company_id = get_company_id(m['id'])
        return {
            'id': m['id'],
            'company_id': company_id,
            'day': dt.strftime('%Y-%m-%d') if dt else '',
            'titre': m.get('properties', {}).get('hs_meeting_title', ''),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        enriched = list(ex.map(enrich, meetings))

    # Grouper par (company_id, day)
    groups = defaultdict(list)
    for m in enriched:
        if m['company_id'] and m['day']:
            groups[(m['company_id'], m['day'])].append(m)

    # Identifier les doublons
    to_delete = []
    for key, group in groups.items():
        if len(group) > 1:
            # Garder le premier, supprimer les autres
            to_delete.extend(group[1:])

    dupes = len(to_delete)
    if dupes == 0:
        print('✅ Aucun doublon détecté.')
        return

    print(f'\n⚠️  {dupes} meetings en doublon à supprimer')
    confirm = input('Confirmer la suppression ? (oui/non) : ').strip().lower()
    if confirm != 'oui':
        print('Annulé.')
        return

    deleted, errors = 0, 0
    for m in to_delete:
        if delete_meeting(m['id']):
            deleted += 1
            print(f'  🗑  Supprimé : {m["titre"][:60]}')
        else:
            errors += 1
            print(f'  ❌ Échec : {m["id"]}')

    print(f'\n{"="*50}')
    print(f'✅ {deleted} supprimés · ❌ {errors} erreurs')

if __name__ == '__main__':
    run()

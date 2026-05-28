# naali_planner — CLAUDE.md

## 1. CONTEXTE PROJET

**Utilisateur :** Amir Ounissi, commercial Naali (compléments alimentaires)
**Territoire :** Sud de la France — depts 04, 05, 06, 11, 13, 30, 34, 48, 66, 83, 84
**Objectif :** Planifier les visites de 314 pharmacies sur 2 semaines, optimiser les itinéraires, créer les meetings HubSpot et exporter en .ics

---

## 2. ARCHITECTURE

```
naali_planner/
├── core/
│   ├── calendrier.py   → jours ouvrables, jours fériés, crédits par jour
│   ├── filtres.py      → chargement CSV, filtrage dept/client/prospect/origine
│   ├── dn_engine.py    → groupes DN 0/N 🔴 / X/N 🟡 / N/N masqué (clients seuls)
│   ├── itineraire.py   → tri par CP/département + répartition sur jours
│   └── planning.py     → construction horaire (zéro LLM)
├── data/
│   └── naali_base_planning.csv   ← SOURCE UNIQUE pour les companies
├── hubspot/
│   └── meetings.py     → lecture/écriture MEETING_EVENT uniquement
├── web/
│   ├── app.py          → Flask, 12 routes API
│   └── templates/index.html  → UI thème sombre
├── config.py           → clés API (ne pas modifier)
└── requirements.txt
```

**Source de données :**
- Companies → **CSV uniquement** (`data/naali_base_planning.csv`)
- Meetings → **HubSpot MEETING_EVENT uniquement** (jamais notes_last_contacted)

---

## 3. RÈGLES ABSOLUES

- **Zéro LLM pour le planning** — Python pur uniquement. Claude ne construit, ne calcule, ne filtre, n'optimise rien dans le planning.
- **Zéro appel HubSpot pour lire les companies** — toutes les données pharmacies viennent du CSV.
- **DN produit = clients uniquement** — jamais appliquer le filtre DN aux prospects.
- **Prospects VP chargés sans filtre DN** — ils passent directement dans la liste sans calcul de référence.
- **Dates = prochain lundi** depuis `date.today()`, hors jours fériés français (`holidays.France`).
- **Cache last_visit en mémoire** (`_cache_last_visit` dict dans `hubspot/meetings.py`) — évite les doublons d'appels HubSpot.
- **TEST_MODE** (`config.py`) — quand `True`, `create_meeting()` simule sans écrire dans HubSpot.

---

## 4. HUBSPOT

| Paramètre | Valeur |
|-----------|--------|
| Owner ID | `727665403` |
| Hub ID | `143439337` |
| API base | `https://api.hubapi.com` |
| Clé | `HUBSPOT_API_KEY` dans `config.py` |

**Seuls appels autorisés :**
- `POST /crm/v3/objects/meetings/search` — lire les MEETING_EVENT (last_visit, créneaux existants)
- `POST /crm/v3/objects/meetings` — créer un MEETING_EVENT

**Propriétés créées sur chaque meeting :**
```
hs_meeting_title, hs_timestamp, hs_meeting_end_time, hubspot_owner_id, hs_activity_type
+ association company (associationTypeId: 186)
```

---

## 5. LOGIQUE MÉTIER

### Crédits par type de visite
| Type | Crédits | Durée |
|------|---------|-------|
| VC (Visite Client) | 2 | 60 min |
| VP (Visite Prospect) | 1 | 30 min |
| RC / RP / F | 2 | 60 min |

### Capacité journalière
| Jour | Crédits | Début | Fin |
|------|---------|-------|-----|
| Lundi | 8 | 12:00 | 18:30 |
| Mardi–Jeudi | 10 | 09:00 | 18:30 |
| Vendredi | 8 | 09:00 | 12:00 |

### Rythme recommandé
- **Prioritaires** : toutes les 30 jours → retard si > 30j
- **Secondaires** : toutes les 60 jours → retard si > 60j
- **Proche** : échéance dans les 10 prochains jours (Prioritaires 20–30j / Secondaires 50–60j)

### Logique DN
- S'applique **uniquement aux clients** (`client_naali = true/Rétrocession`)
- `groupe_0` 🔴 : 0 références parmi les cibles → priorité haute
- `groupe_1` 🟡 : partiel → priorité moyenne
- `groupe_2` : tout → **masqué dans l'interface**
- Tri dans chaque groupe : score décroissant puis potentiel

### Ratio VC/VP
- Cible : **40% VC / 60% VP** par jour et sur la semaine
- Alerte si `abs(ratio_vc - 40) > 10`

### Priorité de planification
`🔴 retard → 🟡 proche → Prioritaires → Secondaires`

---

## 6. DONNÉES CSV

**Colonnes principales :**
| Colonne | Signification |
|---------|--------------|
| `nom` | Nom de la pharmacie |
| `ville` | Ville |
| `cp` / `code_postal` | Code postal (normalisé 5 chiffres avec `.zfill(5)`) |
| `client_naali` | Voir enum ci-dessous |
| `potentiel` | Voir enum ci-dessous |
| `catalogue` / `catalogue_naali_reference` | Références produits séparées par `;` |
| `origine` | Origine de prospection (prospects) |
| `id_hubspot` / `hs_object_id` | ID company HubSpot pour l'association meeting |

**Enum `client_naali` :**
- Clients : `true`, `Rétrocession` (ou `retrocession`, `1`, `oui`)
- Prospects : tout le reste (vérifier `potentiel` pour filtrer)

**Enum `potentiel` :**
- `Prioritaires` → visite toutes les 30j
- `Secondaires` → visite toutes les 60j
- `Non Prioritaires` → à bas de liste

---

## 7. COMMANDES UTILES

```bash
# Installer les dépendances
pip3 install -r requirements.txt

# Lancer le serveur (port 5001)
python3 web/app.py

# Mode test (sans écriture HubSpot)
python3 web/app.py --test

# Vérifier la syntaxe d'un module
python3 -m py_compile core/calendrier.py

# Vérifier tous les modules
for f in config.py core/*.py hubspot/*.py web/app.py; do
  python3 -m py_compile $f && echo "$f OK"
done

# Accès
open http://localhost:5001
```

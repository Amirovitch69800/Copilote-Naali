import csv
import os
import re as _re

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_path(csv_path: str) -> str:
    """Résout un chemin relatif depuis la racine du projet."""
    if not os.path.isabs(csv_path):
        return os.path.join(_BASE_DIR, csv_path)
    return csv_path


def _extract_cp_from_nom(nom: str) -> str:
    """Tente d'extraire un code postal 5 chiffres depuis le nom de la pharmacie."""
    m = _re.search(r'\b(\d{5})\b', nom or "")
    return m.group(1) if m else ""


def _read_csv(csv_path: str) -> list:
    """Lit un CSV et normalise les colonnes de base."""
    pharmacies = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cp = row.get("code_postal", row.get("cp", "")).strip()
            if cp:
                if cp.endswith(".0"):
                    cp = cp[:-2]
                cp = cp.zfill(5)

            # Fallback 1 : extraire un code postal 5 chiffres depuis le nom
            if not cp:
                cp = _extract_cp_from_nom(row.get("nom", ""))

            # Fallback 2 : extraire depuis la colonne departement ("59 : Nord" → "59000")
            if not cp:
                dept_raw = row.get("departement", "").strip()
                if dept_raw:
                    dept_code = dept_raw.split(":")[0].strip()
                    if dept_code.isdigit():
                        cp = (dept_code.zfill(2) + "000")[:5]  # "59" → "59000"

            row["cp"] = cp
            row["_client_naali_raw"] = row.get("client_naali", "").strip()

            # Normaliser lat/lon en float si présents
            for col in ("lat", "lon"):
                val = row.get(col, "").strip()
                try:
                    row[col] = float(val) if val else None
                except ValueError:
                    row[col] = None

            pharmacies.append(row)

    # Enrichir les villes manquantes via HubSpot (batch/read companies) + cache SQLite
    sans_ville = [r for r in pharmacies if not r.get("ville", "").strip() and r.get("id_hubspot", "").strip()]
    if sans_ville:
        _enrich_villes_hubspot(sans_ville)

    return pharmacies


def _enrich_villes_hubspot(rows: list):
    """
    Récupère la ville (city) depuis HubSpot pour les lignes sans ville.
    Utilise un cache SQLite (table company_cities) pour éviter les appels répétés.
    """
    import sqlite3, requests as _req
    from config import HUBSPOT_API_KEY

    db_path = os.path.join(_BASE_DIR, "data", "naali.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS company_cities (
            company_id TEXT PRIMARY KEY,
            city       TEXT DEFAULT ''
        )
    """)
    con.commit()

    # Charger le cache existant
    cached = {r[0]: r[1] for r in con.execute("SELECT company_id, city FROM company_cities").fetchall()}

    # Séparer : déjà en cache vs à fetcher
    a_fetcher = [r for r in rows if r["id_hubspot"] not in cached]

    # Batch HubSpot par tranches de 100
    fetched: dict = {}
    ids_batch = list({r["id_hubspot"] for r in a_fetcher})
    for i in range(0, len(ids_batch), 100):
        batch = ids_batch[i:i+100]
        try:
            resp = _req.post(
                "https://api.hubapi.com/crm/v3/objects/companies/batch/read",
                headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"},
                json={"properties": ["city"], "inputs": [{"id": cid} for cid in batch]},
                timeout=10,
            )
            for obj in resp.json().get("results", []):
                city = (obj.get("properties") or {}).get("city") or ""
                fetched[obj["id"]] = city.upper().strip()
        except Exception as e:
            print(f"[filtres] HubSpot batch city error: {e}")

    # Sauvegarder en cache SQLite
    if fetched:
        con.executemany(
            "INSERT OR REPLACE INTO company_cities (company_id, city) VALUES (?, ?)",
            fetched.items(),
        )
        con.commit()
    con.close()

    # Appliquer aux lignes
    all_cities = {**cached, **fetched}
    for r in rows:
        city = all_cities.get(r["id_hubspot"], "")
        if city:
            r["ville"] = city


def load_pharmacies(csv_path: str) -> list:
    """
    Charge le CSV et normalise les codes postaux.
    Si csv_path est absent, tente le CSV_PATH_FALLBACK défini dans config.
    """
    path = _resolve_path(csv_path)

    if os.path.exists(path):
        return _read_csv(path)

    # Fallback sur le CSV sans GPS
    try:
        from config import CSV_PATH_FALLBACK
        fallback = _resolve_path(CSV_PATH_FALLBACK)
        if os.path.exists(fallback):
            print(f"[filtres] CSV géo absent — fallback sur {CSV_PATH_FALLBACK}")
            return _read_csv(fallback)
    except ImportError:
        pass

    return []


def filter_by_departements(pharmacies: list, depts: list) -> list:
    """
    Filtre par département(s).
    depts : liste de codes à 2 chiffres, ex. ["13", "04", "34"]
    """
    if not depts:
        return pharmacies
    # Normaliser depts
    depts_norm = [str(d).zfill(2) for d in depts]
    result = []
    for p in pharmacies:
        cp = p.get("cp", "")
        dept = cp[:2] if len(cp) >= 2 else ""
        if dept in depts_norm:
            result.append(p)
    return result


def filter_clients(pharmacies: list) -> list:
    """client_naali in ("true", "Rétrocession", "rétrocession")"""
    result = []
    for p in pharmacies:
        val = p.get("_client_naali_raw", "").lower().strip()
        if val in ("true", "rétrocession", "retrocession", "1", "oui", "yes"):
            result.append(p)
    return result


def filter_prospects(pharmacies: list) -> list:
    """client_naali = false ET potentiel défini (Prioritaires, Secondaires, Non Prioritaires)"""
    result = []
    for p in pharmacies:
        val = p.get("_client_naali_raw", "").lower().strip()
        if val not in ("true", "rétrocession", "retrocession", "1", "oui", "yes"):
            potentiel = p.get("potentiel", "").strip()
            if potentiel in ("Prioritaires", "Secondaires", "Non Prioritaires"):
                result.append(p)
    return result


def filter_by_origine(pharmacies: list, origine: str) -> list:
    """Filtre par origine de prospection (sur prospects uniquement)."""
    if not origine:
        return pharmacies
    return [p for p in pharmacies if p.get("origine", "").strip() == origine]


def filter_by_origines(pharmacies: list, origines: list) -> list:
    """Filtre par origines multiples."""
    if not origines:
        return pharmacies
    return [p for p in pharmacies if p.get("origine", "").strip() in origines]


def sort_by_potentiel(pharmacies: list) -> list:
    """Prioritaires → Secondaires → Non Prioritaires."""
    ordre = {"Prioritaires": 0, "Secondaires": 1, "Non Prioritaires": 2}
    return sorted(pharmacies, key=lambda p: ordre.get(p.get("potentiel", ""), 99))


def get_departements_disponibles(pharmacies: list) -> list:
    """Retourne la liste des départements présents dans le CSV."""
    depts = set()
    for p in pharmacies:
        cp = p.get("cp", "")
        if len(cp) >= 2:
            depts.add(cp[:2])
    return sorted(list(depts))


def get_villes_par_dept(pharmacies: list) -> dict:
    """
    Retourne {dept: [villes triées]} pour toutes les pharmacies.
    Ex. {"13": ["Aix En Provence", "Marseille", ...], "34": [...]}
    """
    from collections import defaultdict
    result = defaultdict(set)
    for p in pharmacies:
        cp = p.get("cp", "")
        ville = p.get("ville", "").strip()
        if len(cp) >= 2 and ville:
            result[cp[:2]].add(ville)
    return {dept: sorted(villes) for dept, villes in sorted(result.items())}


def filter_by_villes(pharmacies: list, villes: list) -> list:
    """Filtre par ville(s). Liste vide = pas de filtre. Insensible à la casse."""
    if not villes:
        return pharmacies
    villes_set = {v.strip().upper() for v in villes}
    return [p for p in pharmacies if p.get("ville", "").strip().upper() in villes_set]


def get_origines_disponibles(pharmacies: list) -> list:
    """Retourne la liste des origines de prospection présentes."""
    origines = set()
    for p in pharmacies:
        o = p.get("origine", "").strip()
        if o:
            origines.add(o)
    return sorted(list(origines))


def is_client(pharmacie: dict) -> bool:
    val = pharmacie.get("_client_naali_raw", "").lower().strip()
    return val in ("true", "rétrocession", "retrocession", "1", "oui", "yes")


def filter_by_deciles(pharmacies: list, deciles: list) -> list:
    """Filtre par décile(s). Liste vide = pas de filtre."""
    if not deciles:
        return pharmacies
    deciles_norm = {str(d).strip() for d in deciles}
    return [p for p in pharmacies if str(p.get("decile", "")).strip() in deciles_norm]


def filter_by_produits_cibles(pharmacies: list, produits: list) -> list:
    """
    Filtre les pharmacies qui N'ONT PAS encore les produits ciblés dans leur catalogue.
    Logique : au moins un des produits cibles est absent du catalogue → pharmacie éligible.
    Produits séparés par ';' dans la colonne catalogue.
    """
    if not produits:
        return pharmacies
    produits_norm = {p.strip().lower() for p in produits}
    result = []
    for pharma in pharmacies:
        cat_raw = pharma.get("catalogue", "") or ""
        cat_refs = {r.strip().lower() for r in cat_raw.split(";") if r.strip()}
        # Éligible si au moins un produit ciblé est absent
        if produits_norm - cat_refs:
            result.append(pharma)
    return result


def get_deciles_disponibles(pharmacies: list) -> list:
    """Retourne la liste des déciles présents, triés numériquement."""
    deciles = set()
    for p in pharmacies:
        v = str(p.get("decile", "")).strip()
        if v:
            deciles.add(v)
    try:
        return sorted(deciles, key=lambda x: int(x))
    except ValueError:
        return sorted(deciles)


def get_produits_disponibles(pharmacies: list) -> list:
    """Retourne la liste unique de tous les produits présents dans les catalogues."""
    produits = set()
    for p in pharmacies:
        cat_raw = p.get("catalogue", "") or ""
        for ref in cat_raw.split(";"):
            ref = ref.strip()
            if ref:
                produits.add(ref)
    return sorted(produits)

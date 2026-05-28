import math


# ────────────────────────────────────────────────────────
# Géographie
# ────────────────────────────────────────────────────────

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distance à vol d'oiseau entre deux points GPS (formule Haversine).
    Suffisamment précis pour optimiser une tournée — pas besoin d'API routing.
    """
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _has_gps(p: dict) -> bool:
    try:
        float(p["lat"])
        float(p["lon"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


# ────────────────────────────────────────────────────────
# Optimisation itinéraire
# ────────────────────────────────────────────────────────

def optimiser_itineraire(
    pharmacies: list,
    start_lat: float = None,
    start_lon: float = None,
) -> list:
    """
    Optimise l'ordre de visite pour minimiser la distance totale.

    ALGORITHME : Nearest Neighbor (glouton)
    - Si start_lat/start_lon fournis : partir de ce point (domicile commercial)
    - Sinon fallback : pharmacie la plus au nord (lat maximale)
    - À chaque étape, aller à la non-visitée la plus proche
    - Simple, rapide, 80-90% de l'optimal

    Si coordonnées GPS absentes → fallback tri par CP (ancien algo).

    Ajoute sur chaque pharmacie :
    - "distance_prec_km" : distance depuis le point précédent (None si sans GPS)
    """
    if not pharmacies:
        return []

    avec_gps = [p for p in pharmacies if _has_gps(p)]
    sans_gps = [p for p in pharmacies if not _has_gps(p)]

    if not avec_gps:
        # Fallback : tri par CP
        return sorted(pharmacies, key=lambda p: p.get("cp", ""))

    # Nearest Neighbor
    restantes = avec_gps.copy()

    # Point de départ : domicile si fourni, sinon pharmacie la plus au nord
    if start_lat is not None and start_lon is not None:
        cur_lat, cur_lon = float(start_lat), float(start_lon)
    else:
        depart = max(restantes, key=lambda p: float(p["lat"]))
        restantes.remove(depart)
        chemin = [depart]
        depart["distance_prec_km"] = 0.0
        cur_lat, cur_lon = float(depart["lat"]), float(depart["lon"])
        # Continue le nearest-neighbor depuis ce départ
        while restantes:
            plus_proche = min(
                restantes,
                key=lambda p: distance_km(cur_lat, cur_lon, float(p["lat"]), float(p["lon"])),
            )
            d = distance_km(cur_lat, cur_lon, float(plus_proche["lat"]), float(plus_proche["lon"]))
            plus_proche["distance_prec_km"] = round(d, 1)
            cur_lat, cur_lon = float(plus_proche["lat"]), float(plus_proche["lon"])
            chemin.append(plus_proche)
            restantes.remove(plus_proche)
        for p in sans_gps:
            p["distance_prec_km"] = None
        return chemin + sans_gps

    # Nearest Neighbor depuis le domicile
    chemin = []
    while restantes:
        plus_proche = min(
            restantes,
            key=lambda p: distance_km(cur_lat, cur_lon, float(p["lat"]), float(p["lon"])),
        )
        d = distance_km(cur_lat, cur_lon, float(plus_proche["lat"]), float(plus_proche["lon"]))
        plus_proche["distance_prec_km"] = round(d, 1)
        cur_lat, cur_lon = float(plus_proche["lat"]), float(plus_proche["lon"])
        chemin.append(plus_proche)
        restantes.remove(plus_proche)

    # Pharmacies sans GPS ajoutées à la fin
    for p in sans_gps:
        p["distance_prec_km"] = None

    return chemin + sans_gps


# ────────────────────────────────────────────────────────
# Optimisation intra-journée
# ────────────────────────────────────────────────────────

def _priority_weight(p: dict) -> float:
    """
    Facteur multiplicateur de distance selon la priorité.
    < 1.0 = pharmacie attirante (visitée plus tôt)
    > 1.0 = pharmacie moins urgente (visitée plus tard si d'autres sont proches)
    """
    if p.get("is_retard"):  return 0.4
    if p.get("is_proche"):  return 0.6
    pot = p.get("potentiel", "")
    if pot == "Prioritaires": return 1.0
    if pot == "Secondaires":  return 1.2
    return 1.5


def _deux_opt(chemin: list, start_lat: float = None, start_lon: float = None) -> list:
    """
    Amélioration 2-opt : élimine les croisements et aller-retours résiduels.
    Inclut le point de départ (domicile) dans le calcul du premier segment.
    """
    n = len(chemin)
    if n < 4:
        return chemin

    def _d(a, b):
        if not (_has_gps(a) and _has_gps(b)):
            return 0.0
        return distance_km(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))

    # Noeud virtuel pour le point de départ
    depart = {"lat": start_lat, "lon": start_lon} if start_lat is not None else None

    improved = True
    best = chemin[:]
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                # Arêtes actuelles : (i→i+1) et (j→j+1)
                # Pour i==0, l'arête de départ est (depart→best[0])
                a = depart if (i == 0 and depart) else best[i - 1] if i > 0 else best[i]
                # Arête 1 : a → best[i]  (si i==0 : depart → best[0])
                if i == 0 and depart:
                    e1_start = depart
                    e1_end   = best[0]
                else:
                    e1_start = best[i]
                    e1_end   = best[i + 1]

                e2_start = best[j]
                e2_end   = best[j + 1] if j + 1 < n else None

                d_old = _d(e1_start, e1_end) + (_d(e2_start, e2_end) if e2_end else 0)
                d_new = _d(e1_start, e2_start) + (_d(e1_end, e2_end) if e2_end else 0)

                if d_new < d_old - 0.1:
                    if i == 0 and depart:
                        best[0:j + 1] = best[0:j + 1][::-1]
                    else:
                        best[i + 1:j + 1] = best[i + 1:j + 1][::-1]
                    improved = True
    return best


def optimiser_journees(
    affectation: dict,
    start_lat: float = None,
    start_lon: float = None,
    anchors_par_jour: dict = None,
) -> dict:
    """
    Re-ordonne les pharmacies de chaque journée :
    1. Nearest-neighbor global avec pondération de priorité (pas de tiers stricts)
       → évite les aller-retours liés au changement de tier
    2. Post-traitement 2-opt pour éliminer les croisements résiduels
    """
    for date_str, pharmas in affectation.items():
        if len(pharmas) <= 1:
            continue

        avec_gps = [p for p in pharmas if _has_gps(p)]
        sans_gps  = [p for p in pharmas if not _has_gps(p)]

        if not avec_gps:
            affectation[date_str] = sorted(pharmas, key=_priority_weight)
            continue

        # Point de départ : anchor > domicile > centroïde
        if anchors_par_jour and date_str in anchors_par_jour:
            anchor = anchors_par_jour[date_str]
            cur_lat, cur_lon = float(anchor["lat"]), float(anchor["lon"])
        elif start_lat is not None:
            cur_lat, cur_lon = float(start_lat), float(start_lon)
        else:
            cur_lat = sum(float(p["lat"]) for p in avec_gps) / len(avec_gps)
            cur_lon = sum(float(p["lon"]) for p in avec_gps) / len(avec_gps)

        sl, slon = cur_lat, cur_lon  # conserver pour le 2-opt

        # Nearest-neighbor global pondéré par priorité
        restantes = avec_gps.copy()
        chemin = []
        while restantes:
            plus_proche = min(
                restantes,
                key=lambda p: distance_km(cur_lat, cur_lon, float(p["lat"]), float(p["lon"]))
                              * _priority_weight(p),
            )
            cur_lat, cur_lon = float(plus_proche["lat"]), float(plus_proche["lon"])
            chemin.append(plus_proche)
            restantes.remove(plus_proche)

        # 2-opt : élimine les croisements
        chemin = _deux_opt(chemin, sl, slon)

        # Recalculer les distances sur le chemin final
        prev_lat, prev_lon = sl, slon
        for p in chemin:
            d = distance_km(prev_lat, prev_lon, float(p["lat"]), float(p["lon"]))
            p["distance_prec_km"] = round(d, 1)
            prev_lat, prev_lon = float(p["lat"]), float(p["lon"])

        for p in sans_gps:
            p["distance_prec_km"] = None

        affectation[date_str] = chemin + sans_gps

    return affectation


# ────────────────────────────────────────────────────────
# Résumé tournée
# ────────────────────────────────────────────────────────

def distance_totale_km(pharmacies: list) -> float:
    return sum(p.get("distance_prec_km") or 0 for p in pharmacies)


def detecter_grands_ecarts(pharmacies: list, seuil_km: float = 25.0) -> list:
    """Détecte les sauts > seuil_km entre deux visites consécutives."""
    ecarts = []
    for i in range(1, len(pharmacies)):
        d = pharmacies[i].get("distance_prec_km")
        if d and d > seuil_km:
            ecarts.append({
                "index": i,
                "de":    pharmacies[i - 1].get("nom", "?"),
                "vers":  pharmacies[i].get("nom", "?"),
                "km":    d,
            })
    return ecarts


def resume_itineraire(pharmacies: list) -> dict:
    """Génère un résumé de la tournée."""
    total_km = distance_totale_km(pharmacies)
    nb = len(pharmacies)
    ecarts = detecter_grands_ecarts(pharmacies)
    optimise = any(_has_gps(p) for p in pharmacies)
    return {
        "total_km":     round(total_km, 1),
        "nb_visites":   nb,
        "km_moyen":     round(total_km / max(nb - 1, 1), 1),
        "ecarts":       ecarts,
        "optimise_gps": optimise,
    }


# ────────────────────────────────────────────────────────
# Regroupement par secteur géographique
# ────────────────────────────────────────────────────────

def _centre_cellule(pharmacies: list) -> tuple:
    """Centroïde d'un groupe de pharmacies avec GPS."""
    lats = [float(p["lat"]) for p in pharmacies if _has_gps(p)]
    lons = [float(p["lon"]) for p in pharmacies if _has_gps(p)]
    if not lats:
        return (0.0, 0.0)
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _secteurs_ordonnes(
    pharmacies: list,
    resolution: float = 0.3,
    start_lat: float = None,
    start_lon: float = None,
) -> list:
    """
    Regroupe les pharmacies par secteur géographique (grille lat/lon, ~33km par cellule).
    Trie les secteurs par nearest-neighbor depuis le domicile (start_lat/start_lon).
    Retourne une liste de listes : [[pharmas secteur1], [pharmas secteur2], ...]
    """
    from collections import defaultdict

    avec_gps = [p for p in pharmacies if _has_gps(p)]
    sans_gps  = [p for p in pharmacies if not _has_gps(p)]

    if not avec_gps:
        return [pharmacies] if pharmacies else []

    grille: dict = defaultdict(list)
    for p in avec_gps:
        cell = (
            round(float(p["lat"]) / resolution) * resolution,
            round(float(p["lon"]) / resolution) * resolution,
        )
        grille[cell].append(p)

    centroides = {cell: _centre_cellule(pharmas) for cell, pharmas in grille.items()}
    restants = list(grille.keys())

    if start_lat is not None and start_lon is not None:
        cur_lat, cur_lon = float(start_lat), float(start_lon)
    else:
        premiere = max(restants, key=lambda c: c[0])
        cur_lat, cur_lon = centroides[premiere]

    ordre = []
    while restants:
        plus_proche = min(
            restants,
            key=lambda c: distance_km(cur_lat, cur_lon, centroides[c][0], centroides[c][1]),
        )
        ordre.append(plus_proche)
        cur_lat, cur_lon = centroides[plus_proche]
        restants.remove(plus_proche)

    secteurs = [grille[cell] for cell in ordre]
    if sans_gps:
        secteurs.append(sans_gps)
    return secteurs


# ────────────────────────────────────────────────────────
# Répartition sur les jours
# ────────────────────────────────────────────────────────

def _reorder_for_anchors(secteurs: list, jours_ouverts: list, anchors_par_jour: dict) -> list:
    """
    Réorganise les secteurs pour que les jours avec un anchor HubSpot
    reçoivent les pharmacies géographiquement les plus proches de cet anchor.
    """
    if not secteurs or not anchors_par_jour:
        return secteurs

    # Centroïde de chaque secteur
    centroids = []
    for s in secteurs:
        avec_gps = [p for p in s if _has_gps(p)]
        if avec_gps:
            lat = sum(float(p["lat"]) for p in avec_gps) / len(avec_gps)
            lon = sum(float(p["lon"]) for p in avec_gps) / len(avec_gps)
            centroids.append((lat, lon))
        else:
            centroids.append(None)

    # Pour chaque jour ancré (dans l'ordre chrono), réserver le secteur le plus proche
    used = [False] * len(secteurs)
    anchored_indices = []  # (position dans jours_ouverts, secteur_index)

    for day_pos, ds in enumerate(jours_ouverts):
        if ds not in anchors_par_jour:
            continue
        anchor = anchors_par_jour[ds]
        alat, alon = float(anchor["lat"]), float(anchor["lon"])

        best_i, best_d = None, float("inf")
        for i, c in enumerate(centroids):
            if used[i] or c is None:
                continue
            d = distance_km(alat, alon, c[0], c[1])
            if d < best_d:
                best_d, best_i = d, i

        if best_i is not None:
            used[best_i] = True
            anchored_indices.append((day_pos, best_i))

    if not anchored_indices:
        return secteurs

    # Construire le nouvel ordre :
    # secteurs ancrés en tête (triés par position du jour), puis les autres dans l'ordre d'origine
    anchored_set = {si for _, si in anchored_indices}
    new_order = [si for _, si in sorted(anchored_indices)] + [i for i in range(len(secteurs)) if i not in anchored_set]
    return [secteurs[i] for i in new_order]


def repartir_sur_jours(
    pharmacies: list,
    jours: list,
    start_lat: float = None,
    start_lon: float = None,
    anchors_par_jour: dict = None,
) -> dict:
    """
    Répartit les pharmacies sur les jours ouvrables en respectant les crédits.
    Cohérence géographique : chaque journée reste dans un même secteur (~33km).
    Un nouveau secteur commence toujours sur une nouvelle journée.
    Retourne {date_str: [pharmacies]}.
    """
    from core.filtres import is_client

    affectation    = {j["date_str"]: [] for j in jours if not j.get("ferie")}
    credits_restants = {j["date_str"]: j["credits"] for j in jours if not j.get("ferie")}
    jours_ouverts  = [j["date_str"] for j in jours if not j.get("ferie") and j["credits"] > 0]

    if not jours_ouverts:
        return affectation

    secteurs = _secteurs_ordonnes(pharmacies, resolution=0.3,
                                   start_lat=start_lat, start_lon=start_lon)
    if anchors_par_jour:
        secteurs = _reorder_for_anchors(secteurs, jours_ouverts, anchors_par_jour)
    idx_jour = 0

    for secteur in secteurs:
        # Début de secteur : si le jour courant a déjà des pharmacies → nouveau jour
        if idx_jour < len(jours_ouverts) and affectation[jours_ouverts[idx_jour]]:
            idx_jour += 1

        for p in secteur:
            credit_visite = 2 if is_client(p) else 1
            placed = False

            while idx_jour < len(jours_ouverts):
                ds = jours_ouverts[idx_jour]
                if credits_restants[ds] >= credit_visite:
                    affectation[ds].append(p)
                    credits_restants[ds] -= credit_visite
                    placed = True
                    if credits_restants[ds] == 0:
                        idx_jour += 1
                    break
                else:
                    idx_jour += 1

            if not placed:
                # Fallback : placer sans contrainte géographique
                for ds in jours_ouverts:
                    if credits_restants[ds] >= credit_visite:
                        affectation[ds].append(p)
                        credits_restants[ds] -= credit_visite
                        break

    return affectation

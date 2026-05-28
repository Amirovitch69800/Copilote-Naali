CATALOGUE = [
    "Dream",
    "Magnésium +",
    "Zen",  # regroupe Zen, Zen Fraise, Zen Kids et toutes variantes
    "Gommes Anti Stress x42",
    "Gommes Anti Stress x60",
    "Sachet Anti Stress",
    "Cheveux - Pousse et Force",
    "Collagène Citron-Vert Menthe",
    "Cycle",
    "Ménopause",
    "Digestion",
    "Éclat - Teint et hydratation",
]

# Variantes Zen — toute référence commençant par "Zen" est considérée comme la même
ZEN_VARIANTS = lambda ref: ref.lower().startswith("zen")

POTENTIEL_ORDRE = {"Prioritaires": 0, "Secondaires": 1, "Non Prioritaires": 2}


def get_refs_presentes(pharmacie: dict, refs_cibles: list) -> list:
    """Retourne les références cibles déjà présentes dans le catalogue client.
    La référence 'Zen' matche toutes les variantes (Zen Fraise, Zen Kids, etc.)."""
    catalogue_raw = pharmacie.get("catalogue", pharmacie.get("catalogue_naali_reference", ""))
    catalogue = [r.strip() for r in catalogue_raw.split(";") if r.strip()]
    result = []
    for r in refs_cibles:
        if r == "Zen":
            if any(ZEN_VARIANTS(c) for c in catalogue):
                result.append(r)
        elif r in catalogue:
            result.append(r)
    return result


def get_refs_manquantes(pharmacie: dict, refs_cibles: list) -> list:
    """Retourne les références cibles manquantes dans le catalogue client."""
    presentes = set(get_refs_presentes(pharmacie, refs_cibles))
    return [r for r in refs_cibles if r not in presentes]


def calculer_groupes_dn(clients: list, refs_cibles: list) -> dict:
    """
    Pour chaque client, calcule :
    - refs_presentes = intersection(refs_cibles, catalogue_client)
    - refs_manquantes = refs_cibles - refs_presentes
    - score = len(refs_manquantes)

    Retourne 3 groupes :
    {
        "groupe_0": [...],  # 0/N — aucune référence → priorité haute 🔴
        "groupe_1": [...],  # X/N — partiel → priorité moyenne 🟡
        "groupe_2": [],     # N/N — déjà tout → masqué
    }
    """
    if not refs_cibles:
        # Sans filtre DN, calculer les manquantes sur l'ensemble du catalogue
        refs_cibles = CATALOGUE

    groupe_0 = []  # aucune référence cible
    groupe_1 = []  # partiel
    groupe_2 = []  # tout

    n = len(refs_cibles)

    for p in clients:
        pc = dict(p)
        presentes = get_refs_presentes(pc, refs_cibles)
        manquantes = get_refs_manquantes(pc, refs_cibles)
        score = len(manquantes)

        pc["refs_presentes"] = presentes
        pc["refs_manquantes"] = manquantes
        pc["score_dn"] = score
        pc["n_cibles"] = n

        if len(presentes) == 0:
            pc["groupe_dn"] = 0
            groupe_0.append(pc)
        elif score == 0:
            pc["groupe_dn"] = 2
            groupe_2.append(pc)
        else:
            pc["groupe_dn"] = 1
            groupe_1.append(pc)

    # Tri : score décroissant puis potentiel
    def sort_key(p):
        return (-p["score_dn"], POTENTIEL_ORDRE.get(p.get("potentiel", ""), 99))

    groupe_0.sort(key=sort_key)
    groupe_1.sort(key=sort_key)

    return {
        "groupe_0": groupe_0,
        "groupe_1": groupe_1,
        "groupe_2": groupe_2,
    }

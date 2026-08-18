#!/usr/bin/env python3
"""
Collecte des observations CPI et du dictionnaire des champs via l'API SDMX
publique du FMI, pour le DATASET COMPLET (tous pays, toutes catégories
COICOP), conformément au périmètre défini par le ticket.

⚠️ IMPORTANT — pourquoi ce script n'utilise PAS de wildcard :
Contrairement à ce que suggère la documentation générale SDMX 3.0 (case
vide = "toutes les valeurs"), l'instance Fusion Registry du FMI
(api.imf.org) renvoie un dataset VIDE dès qu'une position de la clé est
laissée vide ou remplacée par "*" — testé et confirmé le 18/08/2026 sur
plusieurs combinaisons (wildcard simple, double, avec "*").

La solution retenue : interroger d'abord l'endpoint /structure pour
récupérer la liste RÉELLE des codes pays et catégories COICOP valides,
puis construire la clé d'observations avec TOUS ces codes explicites,
joints par '+' (union), ce que l'API accepte parfaitement.

Canal : API SDMX 3.0 du FMI (api.imf.org/external/sdmx/3.0), accessible
via une clé d'abonnement technique gratuite (portail api.imf.org).

Usage :
    # Dataset complet (comportement par défaut, correspond au ticket) :
    python collect_cpi_data.py --api-key "..." --dsn "dbname=fmi ..."

    # Restreint pour un test rapide (pas de découverte de structure) :
    python collect_cpi_data.py --countries MRT --api-key "..." --no-db
"""

import argparse
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from openpyxl import Workbook

BASE_URL = "https://api.imf.org/external/sdmx/3.0"
AGENCY = "IMF.STA"
DATAFLOW = "CPI"
DSD_ID = "DSD_CPI"
DSD_VERSION = "5.0.0"
VERSION = "~"  # dernière version disponible pour les données

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Dictionnaire statique COICOP 1999 (nomenclature officielle FMI/ONU),
# utilisé pour enrichir field_name/field_description. Sert de repli si
# la découverte dynamique ne trouve pas de nom pour un code rencontré.
COICOP_1999_DICTIONARY = {
    "_T": ("All Items", "Indice général des prix à la consommation, tous postes confondus"),
    "01": ("Food and non-alcoholic beverages", "Produits alimentaires et boissons non alcoolisées"),
    "02": ("Alcoholic beverages, tobacco and narcotics", "Boissons alcoolisées, tabac et stupéfiants"),
    "03": ("Clothing and footwear", "Articles d'habillement et chaussures"),
    "04": ("Housing, water, electricity, gas and other fuels", "Logement, eau, électricité, gaz et autres combustibles"),
    "05": ("Furnishings, household equipment and routine household maintenance",
           "Meubles, articles de ménage et entretien courant du foyer"),
    "06": ("Health", "Santé"),
    "07": ("Transport", "Transport"),
    "08": ("Communication", "Communication"),
    "09": ("Recreation and culture", "Loisirs et culture"),
    "10": ("Education", "Éducation"),
    "11": ("Restaurants and hotels", "Restaurants et hôtels"),
    "12": ("Miscellaneous goods and services", "Biens et services divers"),
}


def fetch_structure(api_key):
    """Récupère la définition complète du DSD CPI (dimensions + codelists
    référencées), pour en extraire dynamiquement les codes pays et
    COICOP réellement valides."""
    url = f"{BASE_URL}/structure/datastructure/{AGENCY}/{DSD_ID}/{DSD_VERSION}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    resp = requests.get(url, headers=headers, params={"references": "all"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _find_codelist_ref_for_dimension(structure_json, dimension_id):
    """Cherche, dans dataStructures[].dataStructureComponents.dimensionList,
    la référence de codelist associée à une dimension (ex: 'COUNTRY')."""
    data = structure_json.get("data", {})
    for ds in data.get("dataStructures", []):
        dims = (
            ds.get("dataStructureComponents", {})
              .get("dimensionList", {})
              .get("dimensions", [])
        )
        for dim in dims:
            if dim.get("id") == dimension_id:
                enum = dim.get("localRepresentation", {}).get("enumeration")
                if enum:
                    # Peut être une URN complète ou un id direct.
                    return enum.split("=")[-1].split(".")[-1].split("(")[0]
    return None


def _extract_codes_from_codelist(structure_json, codelist_id=None, id_keyword=None):
    """Extrait la liste des codes (id) d'un codelist, identifié soit par
    son id exact, soit par un mot-clé présent dans son id (repli si la
    résolution exacte via dimensionList a échoué)."""
    data = structure_json.get("data", {})
    for cl in data.get("codelists", []):
        cl_id = cl.get("id", "")
        if codelist_id and cl_id == codelist_id:
            return [c["id"] for c in cl.get("codes", [])]
        if id_keyword and id_keyword.upper() in cl_id.upper():
            return [c["id"] for c in cl.get("codes", [])]
    return []


def discover_valid_codes(api_key):
    """Découvre dynamiquement les codes pays et COICOP valides pour le
    dataset CPI, en interrogeant l'endpoint /structure du FMI."""
    print("Découverte de la structure du dataset CPI (pays, catégories)...")
    structure_json = fetch_structure(api_key)

    country_cl_id = _find_codelist_ref_for_dimension(structure_json, "COUNTRY")
    countries = _extract_codes_from_codelist(structure_json, codelist_id=country_cl_id, id_keyword="COUNTRY")

    coicop_cl_id = _find_codelist_ref_for_dimension(structure_json, "COICOP_1999")
    coicop = _extract_codes_from_codelist(structure_json, codelist_id=coicop_cl_id, id_keyword="COICOP")

    print(f"  {len(countries)} code(s) pays trouvé(s).")
    print(f"  {len(coicop)} code(s) COICOP trouvé(s).")

    if not countries:
        print("⚠️  Aucun code pays trouvé automatiquement — vérifier la structure JSON.", file=sys.stderr)
    if not coicop:
        print("⚠️  Aucun code COICOP trouvé automatiquement — repli sur '_T' uniquement.", file=sys.stderr)
        coicop = ["_T"]

    return countries, coicop


def build_key_segment(values):
    """Construit un segment de clé SDMX : plusieurs codes joints par '+'
    (union). Une liste vide produit une chaîne vide (à éviter : l'API ne
    supporte pas les wildcards, voir note en tête de fichier)."""
    if not values:
        return ""
    return "+".join(values)


def build_data_url(countries, coicop, transformation, frequency):
    """Construit l'URL de requête selon l'ordre des dimensions du DSD CPI :
    COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY
    INDEX_TYPE est toujours "CPI" pour ce dataflow."""
    key = ".".join([
        build_key_segment(countries),
        "CPI",
        build_key_segment(coicop),
        build_key_segment(transformation),
        build_key_segment(frequency),
    ])
    return f"{BASE_URL}/data/dataflow/{AGENCY}/{DATAFLOW}/{VERSION}/{key}"


def fetch_observations_batch(api_key, countries, coicop, transformation, frequency,
                              start_period=None, end_period=None):
    """Récupère les observations pour UN lot de pays (voir fetch_observations
    pour la découpe en lots, nécessaire car l'API rejette les URL trop
    longues - confirmé le 18/08/2026 avec ~1600 caractères)."""
    url = build_data_url(countries, coicop, transformation, frequency)
    headers = {"Accept": "text/csv"}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key

    params = {}
    if start_period:
        params["c[TIME_PERIOD]"] = f"ge:{start_period}"
    if end_period:
        key = "c[TIME_PERIOD]"
        existing = params.get(key, "")
        le = f"le:{end_period}"
        params[key] = f"{existing}+{le}" if existing else le

    resp = requests.get(url, headers=headers, params=params, timeout=600)
    if resp.status_code >= 400:
        print(f"  ⚠️  Erreur {resp.status_code} pour ce lot : {resp.text[:300]}", file=sys.stderr)
        resp.raise_for_status()
    return resp.text


def fetch_observations(api_key, countries, coicop, transformation, frequency,
                        start_period=None, end_period=None, batch_size=15):
    """Récupère les observations CPI au format CSV, en découpant la liste
    de pays en lots (l'API rejette les URL trop longues au-delà d'environ
    1600-2000 caractères, testé le 18/08/2026)."""
    if not countries:
        countries = [None]  # un seul "lot" avec wildcard/absent

    batches = [countries[i:i + batch_size] for i in range(0, len(countries), batch_size)]
    print(f"Récupération en {len(batches)} lot(s) de {batch_size} pays maximum...")

    all_rows = []
    for i, batch in enumerate(batches, start=1):
        print(f"  Lot {i}/{len(batches)} ({len(batch)} pays)...")
        csv_text = fetch_observations_batch(
            api_key, batch, coicop, transformation, frequency,
            start_period, end_period,
        )
        batch_rows = parse_csv_to_rows(csv_text)
        print(f"    {len(batch_rows)} ligne(s) reçue(s).")
        all_rows.extend(batch_rows)

    return all_rows


def parse_csv_to_rows(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def build_field_dictionary(coicop_codes):
    dictionary = {}
    for code in coicop_codes:
        name, description = COICOP_1999_DICTIONARY.get(code, (code, None))
        dictionary[code] = {
            "field_id": code,
            "field_name": name,
            "field_description": description,
        }
    return dictionary


def build_rows(raw_rows, field_dict, run_id):
    rows = []
    for r in raw_rows:
        country = r.get("COUNTRY") or r.get("COUNTRY.ID") or ""
        time_period = r.get("TIME_PERIOD") or ""
        # Ignore les lignes "placeholder" vides renvoyées par l'API pour
        # les codes sans aucune donnée CPI (agrégats régionaux, entités
        # historiques comme DDR/SUN/YUG...).
        if not country and not time_period:
            continue

        coicop = r.get("COICOP_1999") or r.get("COICOP_1999.ID") or ""
        field = field_dict.get(coicop, {"field_id": coicop, "field_name": coicop, "field_description": None})
        obs_value_raw = r.get("OBS_VALUE") or r.get("Obs_value") or ""
        try:
            obs_value = float(obs_value_raw) if obs_value_raw not in ("", None) else None
        except ValueError:
            obs_value = None

        rows.append({
            "run_id": run_id,
            "field_id": field["field_id"],
            "field_name": field["field_name"],
            "field_description": field["field_description"],
            "country": country,
            "coicop_1999": coicop,
            "type_of_transformation": r.get("TYPE_OF_TRANSFORMATION") or r.get("TYPE_OF_TRANSFORMATION.ID") or "",
            "frequency": r.get("FREQUENCY") or r.get("FREQUENCY.ID") or "",
            "time_period": time_period,
            "obs_value": obs_value,
        })
    return rows


def save_json(rows, filename):
    import json
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path


EXCEL_MAX_ROWS = 1_048_576  # limite native du format .xlsx (avec marge de sécurité)
EXCEL_SAFETY_MARGIN = 900_000  # on n'exporte plus localement au-delà (en-tête inclus)


def save_excel(rows, filename):
    if len(rows) > EXCEL_SAFETY_MARGIN:
        print(
            f"⚠️  {len(rows)} lignes dépassent la limite Excel ({EXCEL_MAX_ROWS} lignes max) — "
            f"export Excel local ignoré. Le fichier SharePoint est alimenté séparément "
            f"depuis PostgreSQL par refresh_sharepoint_cpi.py.",
            file=sys.stderr,
        )
        return None

    path = OUTPUT_DIR / filename
    wb = Workbook()
    ws = wb.active
    ws.title = "donnees"
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row[h] for h in headers])
    wb.save(path)
    return path


def save_postgres(rows, run_id, dsn, chunk_size=20000):
    """Insère les lignes en base par paquets, pour éviter un timeout ou
    une consommation mémoire excessive sur de très gros volumes."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(dsn)
    total_inserted = 0
    try:
        with conn.cursor() as cur:
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO cpi.donnees (
                        run_id, field_id, field_name, field_description,
                        country, coicop_1999, type_of_transformation,
                        frequency, time_period, obs_value
                    ) VALUES %s
                    """,
                    [
                        (r["run_id"], r["field_id"], r["field_name"], r["field_description"],
                         r["country"], r["coicop_1999"], r["type_of_transformation"],
                         r["frequency"], r["time_period"], r["obs_value"])
                        for r in chunk
                    ],
                )
                conn.commit()
                total_inserted += len(chunk)
                print(f"    ...{total_inserted}/{len(rows)} ligne(s) insérée(s)")
        return total_inserted
    finally:
        conn.close()


def create_log_run(dsn, run_id, pipeline, date_debut, statut, nb_collectes):
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cpi.logs (
                    run_id, pipeline, date_debut, statut, nb_elements_collectes
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (run_id, pipeline, date_debut, statut, nb_collectes),
            )
        conn.commit()
    finally:
        conn.close()


def update_log_run(dsn, run_id, date_fin, statut, nb_persistes, message_erreur=None):
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cpi.logs
                SET date_fin = %s, statut = %s,
                    nb_elements_persistes = %s, message_erreur = %s
                WHERE run_id = %s
                """,
                (date_fin, statut, nb_persistes, message_erreur, run_id),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    import uuid

    parser = argparse.ArgumentParser(
        description="Collecte le dataset CPI complet (tous pays, toutes catégories) via l'API SDMX du FMI."
    )
    parser.add_argument("--countries", nargs="*", default=None,
                         help="Codes pays ISO3 à restreindre (ex: MRT). Par défaut : découverte automatique de TOUS les pays.")
    parser.add_argument("--coicop", nargs="*", default=None,
                         help="Codes COICOP à restreindre (ex: _T 01). Par défaut : découverte automatique de TOUTES les catégories.")
    parser.add_argument("--transformation", nargs="*", default=["IX"],
                         help="Types de transformation (défaut : IX, indice).")
    parser.add_argument("--frequency", nargs="*", default=["M"],
                         help="Fréquences (défaut : M, mensuelle).")
    parser.add_argument("--start-period", default=None)
    parser.add_argument("--end-period", default=None)
    parser.add_argument("--batch-size", type=int, default=15,
                         help="Nombre de pays par requête (défaut : 15, pour éviter les URL trop longues rejetées par l'API).")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--no-db", action="store_true")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    date_debut = datetime.now(timezone.utc)

    countries = args.countries
    coicop = args.coicop

    if not countries or not coicop:
        discovered_countries, discovered_coicop = discover_valid_codes(args.api_key)
        countries = countries or discovered_countries
        coicop = coicop or discovered_coicop

    scope_desc = (
        f"pays={len(countries)} code(s) | coicop={len(coicop)} code(s) | "
        f"transformation={args.transformation} | frequency={args.frequency}"
    )
    print(f"Interrogation de l'API SDMX FMI — {scope_desc}")

    try:
        raw_rows = fetch_observations(
            args.api_key, countries, coicop,
            args.transformation, args.frequency,
            args.start_period, args.end_period,
            batch_size=args.batch_size,
        )
    except requests.HTTPError as e:
        print(f"Erreur HTTP : {e}", file=sys.stderr)
        if not args.no_db and args.dsn:
            create_log_run(args.dsn, run_id, "collect_cpi_data", date_debut, "FAILED", 0)
            update_log_run(args.dsn, run_id, datetime.now(timezone.utc), "FAILED", 0, str(e))
        sys.exit(1)

    print(f"{len(raw_rows)} ligne(s) brute(s) récupérée(s) au total.")

    field_dict = build_field_dictionary(coicop)

    rows = build_rows(raw_rows, field_dict, run_id)

    json_path = save_json(rows, "cpi_donnees.json")
    print(f"JSON : {json_path}")
    excel_path = save_excel(rows, "cpi_donnees.xlsx")
    if excel_path:
        print(f"Excel : {excel_path}")

    statut = "SUCCESS"
    nb_persistes = 0
    message_erreur = None

    if not args.no_db:
        if not args.dsn:
            print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
            sys.exit(1)

        create_log_run(args.dsn, run_id, "collect_cpi_data", date_debut, "RUNNING", len(rows))

        try:
            nb_persistes = save_postgres(rows, run_id, args.dsn)
            print(f"✅ {nb_persistes} ligne(s) insérée(s) dans cpi.donnees.")
        except Exception as e:
            statut = "FAILED"
            message_erreur = str(e)
            print(f"Erreur PostgreSQL : {e}", file=sys.stderr)

        update_log_run(args.dsn, run_id, datetime.now(timezone.utc), statut, nb_persistes, message_erreur)

    print(f"Résumé : run_id={run_id} | {len(rows)} observation(s) traitée(s) | statut={statut}")


if __name__ == "__main__":
    main()
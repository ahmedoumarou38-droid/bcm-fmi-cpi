import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.imf.org/external/sdmx/3.0"
AGENCY = "IMF.STA"
DATAFLOW = "CPI"
VERSION = "~"  

OUTPUT_DIR = Path(__file__).parent / "output" 
OUTPUT_DIR.mkdir(exist_ok=True)


def build_data_url(countries, coicop, transformation, frequency):
    """Construit l'URL de requête selon l'ordre des dimensions du DSD CPI :
    COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY"""
    key = f"{countries}.CPI.{coicop}.{transformation}.{frequency}"
    return f"{BASE_URL}/data/dataflow/{AGENCY}/{DATAFLOW}/{VERSION}/{key}"


def fetch_observations(api_key, countries, coicop, transformation, frequency,
                        start_period=None, end_period=None):
    """Récupère les observations au format CSV (plus simple à parser que XML)."""
    url = build_data_url(countries, coicop, transformation, frequency)
    params = {}
    if start_period:
        params["c[TIME_PERIOD]"] = f"ge:{start_period}"
    if end_period:
        existing = params.get("c[TIME_PERIOD]", "")
        params["c[TIME_PERIOD]"] = f"{existing}+le:{end_period}" if existing else f"le:{end_period}"

    headers = {"Accept": "text/csv"}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key

    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.text


def parse_csv_to_rows(csv_text):
    """Parse la réponse CSV en liste de dicts, sans dépendance pandas."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)



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


def fetch_field_dictionary(api_key, coicop_codes):
    """Construit le dictionnaire des champs (ID, Name, Description) pour les
    codes COICOP_1999 présents dans les données, à partir de la nomenclature
    statique COICOP_1999_DICTIONARY. Les codes non répertoriés utilisent le
    code lui-même comme nom (dégradation propre plutôt qu'un échec)."""
    dictionary = {}
    for code in coicop_codes:
        name, description = COICOP_1999_DICTIONARY.get(code, (code, None))
        dictionary[code] = {
            "field_id": code,
            "field_name": name,
            "field_description": description,
        }
    return dictionary


def save_json(rows: list, path_name: str) -> Path:
    path = OUTPUT_DIR / path_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path


def save_excel(rows: list, path_name: str) -> Path:
    from openpyxl import Workbook

    path = OUTPUT_DIR / path_name
    wb = Workbook()
    ws = wb.active
    ws.title = "donnees"
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h) for h in headers])
    wb.save(path)
    return path


def save_postgres(rows: list, run_id: str, dsn: str) -> int:
    import psycopg2

    conn = psycopg2.connect(dsn)
    inserted = 0
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO cpi.donnees (
                        run_id, field_id, field_name, field_description,
                        country, coicop_1999, type_of_transformation,
                        frequency, time_period, obs_value
                    ) VALUES (
                        %(run_id)s, %(field_id)s, %(field_name)s, %(field_description)s,
                        %(country)s, %(coicop_1999)s, %(type_of_transformation)s,
                        %(frequency)s, %(time_period)s, %(obs_value)s
                    )
                    """,
                    row,
                )
                inserted += 1
        conn.commit()
        print(f"✅ {inserted} ligne(s) insérée(s) dans cpi.donnees.")
    finally:
        conn.close()
    return inserted


def create_log_run(dsn: str, run_id: str, pipeline: str, date_debut, statut,
                    nb_collectes):
    """Crée la ligne initiale dans cpi.logs AVANT l'insertion des données
    (contrainte FK : cpi.donnees.run_id référence cpi.logs.run_id)."""
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


def update_log_run(dsn: str, run_id: str, date_fin, statut,
                    nb_persistes, message_erreur=None):
    """Met à jour la ligne cpi.logs avec le résultat final de l'exécution."""
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
    parser = argparse.ArgumentParser(description="Collecte des observations CPI (FMI, API SDMX)")
    parser.add_argument("--countries", default="MRT",
                         help="Codes pays ISO3 séparés par des virgules (ex: MRT,DZA,MAR). Défaut : MRT")
    parser.add_argument("--coicop", default="_T",
                         help="Code COICOP_1999 (défaut : _T = All Items)")
    parser.add_argument("--transformation", default="IX",
                         help="Type de transformation (défaut : IX = Index)")
    parser.add_argument("--frequency", default="M",
                         help="Fréquence : M (mensuel), Q (trimestriel), A (annuel). Défaut : M")
    parser.add_argument("--start-period", help="Période de début (ex: 2020-M01)")
    parser.add_argument("--end-period", help="Période de fin (ex: 2025-M12)")
    parser.add_argument("--api-key", default=os.environ.get("IMF_API_KEY"),
                         help="Clé d'abonnement API FMI (ou variable d'env IMF_API_KEY)")
    parser.add_argument("--dsn", help="DSN PostgreSQL")
    parser.add_argument("--no-db", action="store_true", help="N'écrit pas en base, seulement JSON + Excel")
    args = parser.parse_args()

    if not args.api_key:
        print("Erreur : clé API requise (--api-key ou variable d'env IMF_API_KEY)", file=sys.stderr)
        sys.exit(1)

    run_id = str(uuid.uuid4())
    date_debut = datetime.now(timezone.utc)

    countries_key = "+".join(c.strip() for c in args.countries.split(","))

    print(f"Interrogation de l'API SDMX FMI pour {args.countries}...")
    try:
        csv_text = fetch_observations(
            args.api_key, countries_key, args.coicop, args.transformation,
            args.frequency, args.start_period, args.end_period,
        )
    except requests.HTTPError as e:
        print(f"Erreur HTTP : {e}", file=sys.stderr)
        if not args.no_db and args.dsn:
            create_log_run(args.dsn, run_id, "collect_cpi_data", date_debut, "FAILED", 0)
            update_log_run(args.dsn, run_id, datetime.now(timezone.utc), "FAILED", 0, str(e))
        sys.exit(1)

    raw_rows = parse_csv_to_rows(csv_text)
    print(f"{len(raw_rows)} ligne(s) brute(s) récupérée(s).")

    print("Construction du dictionnaire des champs (COICOP_1999)...")
    coicop_codes = {r.get("COICOP_1999") for r in raw_rows if r.get("COICOP_1999")}
    field_dict = fetch_field_dictionary(args.api_key, coicop_codes)

    # Structuration finale conforme au schéma cpi.donnees
    rows = []
    for r in raw_rows:
        coicop = r.get("COICOP_1999", "")
        field_info = field_dict.get(coicop, {"field_id": coicop, "field_name": coicop, "field_description": None})
        rows.append({
            "run_id": run_id,
            "field_id": field_info["field_id"],
            "field_name": field_info["field_name"],
            "field_description": field_info["field_description"],
            "country": r.get("COUNTRY"),
            "coicop_1999": coicop,
            "type_of_transformation": r.get("TYPE_OF_TRANSFORMATION"),
            "frequency": r.get("FREQUENCY"),
            "time_period": r.get("TIME_PERIOD"),
            "obs_value": float(r["OBS_VALUE"]) if r.get("OBS_VALUE") not in (None, "") else None,
        })

    json_path = save_json(rows, "cpi_donnees.json")
    excel_path = save_excel(rows, "cpi_donnees.xlsx")
    print(f"JSON : {json_path}")
    print(f"Excel : {excel_path}")

    statut = "SUCCESS"
    nb_persistes = 0
    message_erreur = None

    if not args.no_db:
        if not args.dsn:
            print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
            sys.exit(1)

        
        create_log_run(args.dsn, run_id, "collect_cpi_data", date_debut,
                        "RUNNING", len(rows))

        
        try:
            nb_persistes = save_postgres(rows, run_id, args.dsn)
        except Exception as e:
            statut = "FAILED"
            message_erreur = str(e)
            print(f"Erreur PostgreSQL : {e}", file=sys.stderr)

        # 3) Mettre à jour le log avec le résultat final.
        update_log_run(args.dsn, run_id, datetime.now(timezone.utc),
                        statut, nb_persistes, message_erreur)

    print(f"\nRésumé : run_id={run_id} | {len(rows)} observation(s) traitée(s) | statut={statut}")


if __name__ == "__main__":
    main()

import argparse
import sys as _sys_early

try:
    _sys_early.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys_early.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
VERSION = "~"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

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
    url = f"{BASE_URL}/structure/datastructure/{AGENCY}/{DSD_ID}/{DSD_VERSION}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    resp = requests.get(url, headers=headers, params={"references": "all"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _find_codelist_ref_for_dimension(structure_json, dimension_id):
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
                    return enum.split("=")[-1].split(".")[-1].split("(")[0]
    return None


def _extract_codes_from_codelist(structure_json, codelist_id=None, id_keyword=None):
    data = structure_json.get("data", {})
    for cl in data.get("codelists", []):
        cl_id = cl.get("id", "")
        if codelist_id and cl_id == codelist_id:
            return [c["id"] for c in cl.get("codes", [])]
        if id_keyword and id_keyword.upper() in cl_id.upper():
            return [c["id"] for c in cl.get("codes", [])]
    return []


def discover_valid_codes(api_key):
    print("Découverte de la structure du dataset CPI (pays, catégories)...")
    structure_json = fetch_structure(api_key)

    country_cl_id = _find_codelist_ref_for_dimension(structure_json, "COUNTRY")
    countries = _extract_codes_from_codelist(structure_json, codelist_id=country_cl_id, id_keyword="COUNTRY")

    coicop_cl_id = _find_codelist_ref_for_dimension(structure_json, "COICOP_1999")
    coicop = _extract_codes_from_codelist(structure_json, codelist_id=coicop_cl_id, id_keyword="COICOP")

    print(f"  {len(countries)} code(s) pays trouvé(s).")
    print(f"  {len(coicop)} code(s) COICOP trouvé(s).")

    if not countries:
        print("⚠️  Aucun code pays trouvé automatiquement.", file=sys.stderr)
    if not coicop:
        print("⚠️  Aucun code COICOP trouvé automatiquement — repli sur '_T'.", file=sys.stderr)
        coicop = ["_T"]

    return countries, coicop


def build_key_segment(values):
    if not values:
        return ""
    return "+".join(values)


def build_data_url(countries, coicop, transformation, frequency):
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
    if not countries:
        countries = [None]

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
        dictionary[code] = {"name": name, "description": description}
    return dictionary


DATA_COLUMNS = [
    "logs_id",
    "country_id", "country", "country_description",
    "coicop_1999_id", "coicop_1999", "coicop_1999_description",
    "type_of_transformation_id", "type_of_transformation",
    "frequency_id", "frequency",
    "time_period", "obs_value",
]


def build_rows(raw_rows, field_dict):
    rows = []
    for r in raw_rows:
        country_id = r.get("COUNTRY") or r.get("COUNTRY.ID") or ""
        time_period = r.get("TIME_PERIOD") or ""
        if not country_id and not time_period:
            continue

        coicop_id = r.get("COICOP_1999") or r.get("COICOP_1999.ID") or ""
        field = field_dict.get(coicop_id, {"name": coicop_id, "description": None})
        obs_value_raw = r.get("OBS_VALUE") or r.get("Obs_value") or ""
        try:
            obs_value = float(obs_value_raw) if obs_value_raw not in ("", None) else None
        except ValueError:
            obs_value = None

        rows.append({
            "country_id": country_id,
            "country": None,
            "country_description": None,
            "coicop_1999_id": coicop_id,
            "coicop_1999": field["name"],
            "coicop_1999_description": field["description"],
            "type_of_transformation_id": r.get("TYPE_OF_TRANSFORMATION") or r.get("TYPE_OF_TRANSFORMATION.ID") or "",
            "type_of_transformation": None,
            "frequency_id": r.get("FREQUENCY") or r.get("FREQUENCY.ID") or "",
            "frequency": None,
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


EXCEL_MAX_ROWS = 1_048_576
EXCEL_SAFETY_MARGIN = 900_000


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
    ws.title = "data"
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row[h] for h in headers])
    wb.save(path)
    return path


def insert_log(dsn, request_mode, start_date, end_date, status,
                collected_count, persisted_count, error_message=None):
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cpi.logs (
                    request_mode, start_date, end_date, status,
                    collected_elements_count, persisted_elements_count,
                    error_message
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (request_mode, start_date, end_date, status,
                 collected_count, persisted_count, error_message),
            )
            logs_id = cur.fetchone()[0]
        conn.commit()
        return logs_id
    finally:
        conn.close()


def update_log(dsn, logs_id, status, persisted_count, error_message=None):
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cpi.logs
                SET status = %s, collected_elements_count = %s,
                    persisted_elements_count = %s, error_message = %s,
                    end_date = %s
                WHERE id = %s
                """,
                (status, persisted_count, persisted_count, error_message,
                 datetime.now(timezone.utc), logs_id),
            )
        conn.commit()
    finally:
        conn.close()


def save_postgres(rows, logs_id, dsn, chunk_size=20000):
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
                    f"""
                    INSERT INTO cpi.data ({", ".join(DATA_COLUMNS)})
                    VALUES %s
                    """,
                    [
                        tuple([logs_id] + [r[c] for c in DATA_COLUMNS if c != "logs_id"])
                        for r in chunk
                    ],
                )
                conn.commit()
                total_inserted += len(chunk)
                print(f"    ...{total_inserted}/{len(rows)} ligne(s) insérée(s)")
        return total_inserted
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Collecte le dataset CPI complet (tous pays, toutes catégories) via l'API SDMX du FMI."
    )
    parser.add_argument("--countries", nargs="*", default=None)
    parser.add_argument("--coicop", nargs="*", default=None)
    parser.add_argument("--transformation", nargs="*", default=["IX"])
    parser.add_argument("--frequency", nargs="*", default=["M"])
    parser.add_argument("--start-period", default=None)
    parser.add_argument("--end-period", default=None)
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--no-db", action="store_true")
    args = parser.parse_args()

    start_date = datetime.now(timezone.utc)

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
            insert_log(args.dsn, "API", start_date, datetime.now(timezone.utc), "FAILED", 0, 0, str(e))
        sys.exit(1)

    print(f"{len(raw_rows)} ligne(s) brute(s) récupérée(s) au total.")

    field_dict = build_field_dictionary(coicop)
    rows = build_rows(raw_rows, field_dict)

    json_path = save_json(rows, "cpi_donnees.json")
    print(f"JSON : {json_path}")
    excel_path = save_excel(rows, "cpi_donnees.xlsx")
    if excel_path:
        print(f"Excel : {excel_path}")

    if args.no_db:
        print(f"Résumé : {len(rows)} observation(s) traitée(s) | status=SUCCESS (--no-db, rien en base)")
        return

    if not args.dsn:
        print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
        sys.exit(1)

    end_date = datetime.now(timezone.utc)

    logs_id = insert_log(args.dsn, "API", start_date, end_date, "SUCCESS", len(rows), len(rows))

    try:
        nb_persistes = save_postgres(rows, logs_id, args.dsn)
        print(f"✅ {nb_persistes} ligne(s) insérée(s) dans cpi.data.")
        status = "SUCCESS"
    except Exception as e:
        status = "FAILED"
        print(f"Erreur PostgreSQL : {e}", file=sys.stderr)
        update_log(args.dsn, logs_id, "FAILED", 0, str(e))
        print(f"Résumé : id={logs_id} (cpi.logs) | {len(rows)} observation(s) traitée(s) | status=FAILED")
        sys.exit(1)

    print(f"Résumé : id={logs_id} (cpi.logs) | {len(rows)} observation(s) traitée(s) | status={status}")


if __name__ == "__main__":
    main()
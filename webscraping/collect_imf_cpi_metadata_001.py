
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from openpyxl import Workbook

DATASET_URL = "https://data.imf.org/en/datasets/IMF.STA:CPI"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

EXPECTED_FIELDS = {
    "Dataset name": "dataset_name",
    "ID": "dataset_id",
    "Frequency": "frequency",
    "Agency": "agency",
    "Version": "version",
    "Dataset Description": "dataset_description",
    "Geographical Coverage": "geographical_coverage",
    "Full Description": "full_description",
    "Publisher": "publisher",
    "Department": "department",
    "Contact Point": "contact_point",
    "Topic Dataset": "topic_dataset",
    "Keywords Dataset": "keywords_dataset",
    "Language": "language",
    "Publication Date": "publication_date",
    "Update Date": "update_date",
    "Short Source Citation": "short_source_citation",
    "Full Source Citation": "full_source_citation",
    "License": "license",
    "Suggested Citation": "suggested_citation",
}

DATE_FIELDS = {"publication_date", "update_date"}
COMBINED_LABEL_VALUE_FIELDS = {"Dataset name", "ID", "Agency", "Version"}


def parse_site_date(raw: str):
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%b %d, %Y - %I:%M %p")
    except ValueError:
        return None


def fetch_metadata_html(headed: bool, dump_html: bool) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()

        page.goto(DATASET_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("text=Download", timeout=30000)

        page.click("text=Metadata")

        try:
            page.wait_for_selector("text=Dataset name", timeout=30000)
        except Exception:
            page.click("text=Metadata")
            page.wait_for_selector("text=Dataset name", timeout=30000)

        html = page.content()

        if dump_html:
            debug_path = OUTPUT_DIR / "metadata_debug.html"
            debug_path.write_text(html, encoding="utf-8")
            print(f"HTML brut sauvegardé : {debug_path}")

        browser.close()
        return html


def extract_value_container(label_element):
    container = label_element.find_next_sibling()
    if container is None and label_element.parent is not None:
        container = label_element.parent.find_next_sibling()
    return container


def extract_leaf_paragraphs(container) -> str:
    if container is None:
        return ""
    paragraphs = container.find_all("p")
    values = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
    return ", ".join(values)


def parse_combined_label_value(text: str, label: str) -> str:
    prefix = f"{label}:"
    if text.strip().startswith(prefix):
        return text.strip()[len(prefix):].strip()
    return text.strip()


def extract_metadata_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    for label, column in EXPECTED_FIELDS.items():
        if label in COMBINED_LABEL_VALUE_FIELDS:
            node = soup.find(string=lambda s: s and s.strip().startswith(f"{label}:"))
            if node:
                result[column] = parse_combined_label_value(str(node), label)

    freq_label = soup.find("div", title="Frequency")
    if freq_label:
        freq_container = freq_label.find_next_sibling()
        freq_value = extract_leaf_paragraphs(freq_container)
        if freq_value:
            result["frequency"] = freq_value

    for label, column in EXPECTED_FIELDS.items():
        if label in COMBINED_LABEL_VALUE_FIELDS or column == "frequency":
            continue
        label_node = soup.find(string=lambda s, lbl=label: s and s.strip() == lbl)
        if label_node is None:
            continue
        h4 = label_node.parent
        container = extract_value_container(h4)
        value = extract_leaf_paragraphs(container)
        if value:
            result[column] = value

    return result


def check_structure_drift(found_fields: dict):
    expected_count = len(EXPECTED_FIELDS)
    found_count = len(found_fields)

    print(f"Champs attendus : {expected_count} | Champs trouvés : {found_count}")

    if found_count != expected_count:
        missing = [label for label, col in EXPECTED_FIELDS.items() if col not in found_fields]
        print("⚠️  ALERTE DÉRIVE DE STRUCTURE ⚠️", file=sys.stderr)
        print(f"Champs manquants : {missing}", file=sys.stderr)
        return False
    return True


def save_json(data: dict, filename: str):
    path = OUTPUT_DIR / filename
    serializable = {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in data.items()
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    return path


def save_excel(data: dict, filename: str):
    path = OUTPUT_DIR / filename
    wb = Workbook()
    ws = wb.active
    ws.title = "metadata"
    ws.append(list(data.keys()))
    ws.append([v.isoformat() if isinstance(v, datetime) else v for v in data.values()])
    wb.save(path)
    return path


def save_postgres(data: dict, dsn: str):
    """Upsert dans cpi.metadata (ON CONFLICT sur dataset_id)."""
    import psycopg2

    now = datetime.now(timezone.utc)
    row = dict(data)
    for field in DATE_FIELDS:
        if field in row and isinstance(row[field], str):
            parsed = parse_site_date(row[field])
            row[field] = parsed
    row["created_at"] = now
    row["updated_at"] = now

    columns = list(row.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)

    update_cols = [c for c in columns if c not in ("dataset_id", "created_at")]
    update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO cpi.metadata ({col_list})
                VALUES ({placeholders})
                ON CONFLICT (dataset_id) DO UPDATE SET {update_clause}
                """,
                [row[c] for c in columns],
            )
        conn.commit()
    finally:
        conn.close()


def insert_log(dsn, request_mode, start_date, end_date, status,
                collected_count, persisted_count, error_message=None):
    """Insère UN enregistrement final dans cpi.logs (pas d'état
    intermédiaire), pour tracer l'exécution du scraping — cohérent avec
    la structure validée en BCMDG-235 (request_mode, status en
    énumération, comptages égaux)."""
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
            new_log_id = cur.fetchone()[0]
        conn.commit()
        return new_log_id
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Collecte la section Metadata du dataset CPI (IMF Data Portal)."
    )
    parser.add_argument("--no-db", action="store_true", help="Ne pas écrire en base (test).")
    parser.add_argument("--dsn", default=None, help="Chaîne de connexion PostgreSQL.")
    parser.add_argument("--headed", action="store_true", help="Navigateur visible (debug).")
    parser.add_argument("--dump-html", action="store_true", help="Sauvegarder le HTML brut.")
    args = parser.parse_args()

    start_date = datetime.now(timezone.utc)

    print("Ouverture du dataset CPI et récupération du panneau Metadata...")
    html = fetch_metadata_html(args.headed, args.dump_html)

    print("Extraction des champs...")
    fields = extract_metadata_fields(html)

    ok = check_structure_drift(fields)
    if not ok:
        print("⚠️  Poursuite malgré la dérive détectée (champs manquants laissés vides).", file=sys.stderr)

    json_path = save_json(fields, "cpi_metadata.json")
    print(f"JSON : {json_path}")
    excel_path = save_excel(fields, "cpi_metadata.xlsx")
    print(f"Excel : {excel_path}")

    if args.no_db:
        print(f"Résumé : {len(fields)}/{len(EXPECTED_FIELDS)} champ(s) collecté(s) | status=SUCCESS (--no-db, rien en base)")
        return

    if not args.dsn:
        print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
        sys.exit(1)

    end_date = datetime.now(timezone.utc)
    nb_champs = len(fields)

    try:
        save_postgres(fields, args.dsn)
        print("✅ Écrit dans cpi.metadata (upsert sur dataset_id).")
        status = "SUCCESS"
        new_log_id = insert_log(args.dsn, "Web Scraping", start_date, end_date, status, nb_champs, nb_champs)
    except Exception as e:
        status = "FAILED"
        print(f"Erreur PostgreSQL : {e}", file=sys.stderr)
        new_log_id = insert_log(args.dsn, "Web Scraping", start_date, datetime.now(timezone.utc), status, 0, 0, str(e))
        print(f"Résumé : id={new_log_id} (cpi.logs) | {nb_champs}/{len(EXPECTED_FIELDS)} champ(s) métier collecté(s) | status=FAILED")
        sys.exit(1)

    print(f"Résumé : id={new_log_id} (cpi.logs) | {nb_champs}/{len(EXPECTED_FIELDS)} champ(s) métier collecté(s) | status={status}")


if __name__ == "__main__":
    main()
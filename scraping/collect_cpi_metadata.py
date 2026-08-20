
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
    "Agency": "agency",
    "Version": "version",
    "Dataset Description": "dataset_description",
    "Full Description": "full_description",
    "Frequency": "frequency",
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
    "Geographical Coverage": "geographical_coverage",
    "License": "license",
    "Suggested Citation": "suggested_citation",
}

DATE_FIELDS = {"publication_date", "update_date"}


COMBINED_LABEL_VALUE_FIELDS = {"Dataset name", "ID", "Agency", "Version"}


def parse_site_date(raw: str):
    """Convertit une date du site (ex: 'Aug 05, 2026 - 6:46 AM') en
    datetime Python. Retourne None si le format ne correspond pas."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%b %d, %Y - %I:%M %p")
    except ValueError:
        return None


def fetch_metadata_html(headed: bool, dump_html: bool) -> str:
    """Ouvre le dataset CPI dans un navigateur headless, clique sur le
    lien "Metadata", et retourne le HTML du panneau une fois chargé."""
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
    """Trouve le conteneur de valeur associé à un libellé, en suivant le
    DOM (sibling suivant, ou parent puis sibling suivant pour les
    libellés imbriqués dans un h4)."""
    container = label_element.find_next_sibling()
    if container is None and label_element.parent is not None:
        container = label_element.parent.find_next_sibling()
    return container


def extract_leaf_paragraphs(container) -> str:
    """Récupère tout le texte des balises <p> feuilles d'un conteneur,
    jointes par ', ' (gère les champs multi-valeurs comme Keywords)."""
    if container is None:
        return ""
    paragraphs = container.find_all("p")
    values = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
    return ", ".join(values)


def parse_combined_label_value(text: str, label: str) -> str:
    """Extrait la valeur d'un nœud texte combiné 'Label: Value'."""
    prefix = f"{label}:"
    if text.strip().startswith(prefix):
        return text.strip()[len(prefix):].strip()
    return text.strip()


def extract_metadata_fields(html: str) -> dict:
    """Parse le HTML et extrait les champs attendus. Retourne un dict
    {colonne_db: valeur}."""
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # 1) Champs combinés "Label: Value" sur un seul nœud (Dataset name, ID, Agency, Version)
    for label, column in EXPECTED_FIELDS.items():
        if label in COMBINED_LABEL_VALUE_FIELDS:
            node = soup.find(string=lambda s: s and s.strip().startswith(f"{label}:"))
            if node:
                result[column] = parse_combined_label_value(str(node), label)

    # 2) Frequency : n'est PAS dans le panneau Metadata (sidebar), mais dans une
    # carte séparée toujours visible sur la page (structure DOM différente) :
    # <div title="Frequency" class="...MetadataLabel...">Frequency:</div>
    # <div class="...MetadataValue...."><p>Annual, Monthly, Quarterly</p></div>
    freq_label = soup.find("div", title="Frequency")
    if freq_label:
        freq_container = freq_label.find_next_sibling()
        freq_value = extract_leaf_paragraphs(freq_container)
        if freq_value:
            result["frequency"] = freq_value

    # 3) Tous les autres champs standards du panneau Metadata (sidebar).
    # Comparaison avec .strip() : certains libellés du site ont un espace
    # final parasite (ex: "Full Source Citation ", "Suggested Citation "),
    # qui casse une comparaison d'égalité stricte.
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
    """Compare le nombre de champs attendus au nombre trouvés, et alerte
    explicitement en cas d'écart (dérive de structure du site)."""
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
    """Upsert dans cpi.metadata (ON CONFLICT sur dataset_id, toujours
    UNIQUE dans le nouveau schéma). created_at et updated_at sont
    explicitement fixés à la même valeur à chaque exécution (insertion
    OU mise à jour), conformément au feedback."""
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


def main():
    parser = argparse.ArgumentParser(
        description="Collecte la section Metadata du dataset CPI (IMF Data Portal)."
    )
    parser.add_argument("--no-db", action="store_true", help="Ne pas écrire en base (test).")
    parser.add_argument("--dsn", default=None, help="Chaîne de connexion PostgreSQL.")
    parser.add_argument("--headed", action="store_true", help="Navigateur visible (debug).")
    parser.add_argument("--dump-html", action="store_true", help="Sauvegarder le HTML brut.")
    args = parser.parse_args()

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

    if not args.no_db:
        if not args.dsn:
            print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
            sys.exit(1)
        save_postgres(fields, args.dsn)
        print("✅ Écrit dans cpi.metadata (upsert sur dataset_id).")

    print(f"Résumé : {len(fields)}/{len(EXPECTED_FIELDS)} champ(s) collecté(s).")


if __name__ == "__main__":
    main()
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DATASET_URL = "https://data.imf.org/en/datasets/IMF.STA:CPI"
DATASET_ID = "IMF.STA:CPI"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


EXPECTED_FIELDS = {
    "dataset_name": ["dataset name", "name"],
    "dataset_id": ["id", "dataset id"],
    "agency": ["agency"],
    "version": ["version"],
    "description_courte": ["dataset description", "description"],
    "description_complete": ["full description", "description complète"],
    "frequency": ["frequency"],
    "publisher": ["publisher"],
    "department": ["department"],
    "contact_point": ["contact point"],
    "topic": ["topic", "topic dataset", "topical data set", "topical dataset"],
    "keywords": ["keywords", "keywords dataset", "dataset keywords"],
    "language": ["language"],
    "publication_date": ["publication date"],
    "update_date": ["update date"],
    "short_source_citation": ["short source citation"],
    "full_source_citation": ["full source citation"],
    "geographical_coverage": ["geographical coverage"],
    "license": ["license"],
    "suggested_citation": ["suggested citation"],
}


def fetch_metadata_html(headless: bool = True) -> str:
    """Ouvre la page CPI, clique sur 'Metadata', renvoie le HTML du panneau."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(DATASET_URL, wait_until="domcontentloaded", timeout=60000)

        
        page.wait_for_selector("text=Download", timeout=30000)

        
        page.get_by_text("Metadata", exact=True).first.click()

        
        try:
            page.wait_for_selector("text=Dataset name", timeout=30000)
        except Exception:
            print("Premier essai timeout, nouvelle tentative de clic...", file=sys.stderr)
            page.get_by_text("Metadata", exact=True).first.click()
            page.wait_for_selector("text=Dataset name", timeout=30000)

        html = page.content()
        browser.close()
        return html


def extract_fields(html: str) -> tuple[dict, int, int]:
    """
    Parcourt le DOM et tente d'associer chaque libellé connu à sa valeur.
    Stratégie label -> valeur : on cherche l'élément texte qui correspond au
    libellé, puis on prend le texte du prochain élément frère/enfant utile.
    Renvoie (donnees, nb_champs_attendus, nb_champs_trouves).
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {key: None for key in EXPECTED_FIELDS}

    
    combined_label_map = {
        "dataset name": "dataset_name",
        "id": "dataset_id",
        "agency": "agency",
        "version": "version",
    }
    for el in soup.find_all(True):
        if el.find(True) is not None:
            continue  # pas une feuille
        text = el.get_text(strip=True)
        if ":" not in text:
            continue
        label_part, _, value_part = text.partition(":")
        key = combined_label_map.get(label_part.strip().lower())
        if key and value_part.strip():
            result[key] = value_part.strip()

   
    leaves = [el for el in soup.find_all(True) if el.find(True) is None and el.get_text(strip=True)]

    def normalize(txt: str) -> str:
        return txt.strip().lower().rstrip(":")

    all_known_labels = {v for vs in EXPECTED_FIELDS.values() for v in vs}
    
    boundary_labels = all_known_labels | {
        "geographical coverage", "license", "suggested citation",
    }

    def find_value_container(label_el):
        """Trouve le conteneur de valeur associé à un libellé, en s'appuyant
        sur la structure DOM réelle (frère du libellé, ou frère du parent du
        libellé selon la structure — carte résumé vs panneau détaillé)."""
        sib = label_el.find_next_sibling()
        if sib is not None and sib.get_text(strip=True):
            return sib
        parent = label_el.parent
        if parent is not None:
            sib2 = parent.find_next_sibling()
            if sib2 is not None and sib2.get_text(strip=True):
                return sib2
        return None

    for key, label_variants in EXPECTED_FIELDS.items():
        for el in leaves:
            if normalize(el.get_text()) not in label_variants:
                continue
            container = find_value_container(el)
            if container is None:
                break
            
            sub_values = [
                sub.get_text(strip=True)
                for sub in container.find_all(True)
                if sub.find(True) is None and sub.get_text(strip=True)
            ]
            if not sub_values:
                text = container.get_text(strip=True)
                if text:
                    sub_values = [text]
            if sub_values:
                result[key] = ", ".join(sub_values)
            break

    nb_trouves = sum(1 for v in result.values() if v)
    return result, len(EXPECTED_FIELDS), nb_trouves


def check_drift(nb_attendus: int, nb_trouves: int) -> None:
    """Signale une dérive de structure si le nb de champs trouvés diffère."""
    if nb_trouves < nb_attendus:
        manquants = nb_attendus - nb_trouves
        print(
            f"⚠️  ALERTE DÉRIVE DE STRUCTURE : {nb_trouves}/{nb_attendus} champs "
            f"trouvés ({manquants} manquant(s)). La mise en page du site a "
            f"peut-être changé — vérifier avec --dump-html.",
            file=sys.stderr,
        )


def parse_site_date(raw: str):
    """Convertit une date au format du site FMI ('Aug 05, 2026 - 6:46 AM')
    en objet date() Python (format ISO une fois sérialisé)."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%b %d, %Y - %I:%M %p").date()
    except ValueError:
        print(f"⚠️  Impossible de parser la date '{raw}', valeur conservée telle quelle.", file=sys.stderr)
        return raw


def save_json(data: dict) -> Path:
    path = OUTPUT_DIR / "cpi_metadata.json"
    
    serializable = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in data.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    return path


def save_excel(data: dict) -> Path:
    from openpyxl import Workbook

    path = OUTPUT_DIR / "cpi_metadata.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "metadata"
    ws.append(["champ", "valeur"])
    for k, v in data.items():
        ws.append([k, v.isoformat() if hasattr(v, "isoformat") else v])
    wb.save(path)
    return path


def save_postgres(data: dict, dsn: str) -> None:
    import psycopg2

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cpi.metadata (
                    dataset_id, dataset_name, agency, version,
                    description_courte, description_complete, frequency,
                    publisher, department, contact_point, topic, keywords,
                    language, publication_date, update_date,
                    short_source_citation, full_source_citation,
                    geographical_coverage, license, suggested_citation
                ) VALUES (
                    %(dataset_id)s, %(dataset_name)s, %(agency)s, %(version)s,
                    %(description_courte)s, %(description_complete)s, %(frequency)s,
                    %(publisher)s, %(department)s, %(contact_point)s, %(topic)s, %(keywords)s,
                    %(language)s, %(publication_date)s, %(update_date)s,
                    %(short_source_citation)s, %(full_source_citation)s,
                    %(geographical_coverage)s, %(license)s, %(suggested_citation)s
                )
                ON CONFLICT (dataset_id) DO UPDATE SET
                    dataset_name = EXCLUDED.dataset_name,
                    version = EXCLUDED.version,
                    description_courte = EXCLUDED.description_courte,
                    description_complete = EXCLUDED.description_complete,
                    frequency = EXCLUDED.frequency,
                    update_date = EXCLUDED.update_date,
                    geographical_coverage = EXCLUDED.geographical_coverage,
                    license = EXCLUDED.license,
                    suggested_citation = EXCLUDED.suggested_citation
                """,
                data,
            )
        conn.commit()
        print("✅ Insertion/mise à jour dans cpi.metadata réussie.")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Collecte des métadonnées CPI (FMI)")
    parser.add_argument("--dsn", help="DSN PostgreSQL (ex: 'dbname=fmi user=postgres password=... host=localhost')")
    parser.add_argument("--no-db", action="store_true", help="N'écrit pas en base, seulement JSON + Excel")
    parser.add_argument("--dump-html", action="store_true", help="Sauvegarde le HTML brut du panneau pour debug")
    parser.add_argument("--headed", action="store_true", help="Lance le navigateur en mode visible (debug)")
    args = parser.parse_args()

    print("Ouverture du navigateur et récupération du panneau Metadata...")
    html = fetch_metadata_html(headless=not args.headed)

    if args.dump_html:
        debug_path = OUTPUT_DIR / "metadata_debug.html"
        debug_path.write_text(html, encoding="utf-8")
        print(f"HTML brut sauvegardé : {debug_path}")

    print("Extraction des champs...")
    data, nb_attendus, nb_trouves = extract_fields(html)
    check_drift(nb_attendus, nb_trouves)

    data["dataset_id"] = data.get("dataset_id") or DATASET_ID  # secours si absent du panneau

    
    data["publication_date"] = parse_site_date(data.get("publication_date"))
    data["update_date"] = parse_site_date(data.get("update_date"))

    data["_collected_at"] = datetime.now(timezone.utc).isoformat()

    json_path = save_json(data)
    excel_path = save_excel(data)
    print(f"JSON : {json_path}")
    print(f"Excel : {excel_path}")

    if not args.no_db:
        if not args.dsn:
            print("Erreur : --dsn requis (ou utiliser --no-db)", file=sys.stderr)
            sys.exit(1)
        save_postgres(data, args.dsn)

    print(f"\nRésumé : {nb_trouves}/{nb_attendus} champs extraits.")


if __name__ == "__main__":
    main()
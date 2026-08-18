
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


DEFAULT_OUTPUT = Path(__file__).parent / "output" / "IMF - Consumer Price Index (CPI).xlsx"


DEFAULT_COICOP_FILTER = ["_T"]

EXCEL_SAFETY_MARGIN = 900_000  # marge sous la limite native d'Excel (1 048 576)

HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def fetch_metadata(dsn: str):
    """Récupère toutes les colonnes de cpi.metadata."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM cpi.metadata ORDER BY dataset_id;")
            return cur.fetchall()
    finally:
        conn.close()


def get_latest_successful_run(dsn: str, pipeline: str = "collect_cpi_data"):
    """Retourne le run_id du DERNIER run réussi du pipeline de collecte,
    pour ne pas agréger tout l'historique cumulé de cpi.donnees."""
    import psycopg2

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, date_fin, nb_elements_persistes
                FROM cpi.logs
                WHERE pipeline = %s AND statut = 'SUCCESS'
                ORDER BY date_fin DESC
                LIMIT 1;
                """,
                (pipeline,),
            )
            row = cur.fetchone()
            return row  # (run_id, date_fin, nb_elements_persistes) ou None
    finally:
        conn.close()


def fetch_donnees(dsn: str, run_id: str, coicop_filter=None):
    """Récupère les colonnes de cpi.donnees pour UN run précis, avec un
    filtre optionnel sur coicop_1999 (voir DEFAULT_COICOP_FILTER)."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = """
                SELECT run_id, field_id, field_name, field_description,
                       country, coicop_1999, type_of_transformation,
                       frequency, time_period, obs_value
                FROM cpi.donnees
                WHERE run_id = %s
            """
            params = [run_id]
            if coicop_filter:
                query += " AND coicop_1999 = ANY(%s)"
                params.append(coicop_filter)
            query += " ORDER BY country, coicop_1999, time_period;"
            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def write_sheet(ws, rows):
    """Écrit une liste de dicts (colonnes homogènes) dans une feuille,
    avec en-têtes stylés et largeur de colonnes ajustée."""
    if not rows:
        ws.append(["Aucune donnée disponible"])
        return

    headers = list(rows[0].keys())
    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for row in rows:
        ws.append([row[h] for h in headers])

    for col_idx, header in enumerate(headers, start=1):
        max_len = max(
            [len(str(header))] + [len(str(row[header])) for row in rows if row[header] is not None]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)

    ws.freeze_panes = "A2"


def build_workbook(metadata_rows, donnees_rows):
    wb = Workbook()

    ws_meta = wb.active
    ws_meta.title = "Metadata"
    write_sheet(ws_meta, metadata_rows)

    ws_data = wb.create_sheet("Data")
    write_sheet(ws_data, donnees_rows)

    return wb


def refresh_sharepoint_file(dsn: str, output_path: Path, coicop_filter):
    print("Connexion à la base et lecture de cpi.metadata...")
    metadata_rows = fetch_metadata(dsn)
    print(f"  {len(metadata_rows)} ligne(s) metadata.")

    print("Recherche du dernier run réussi de collect_cpi_data...")
    latest_run = get_latest_successful_run(dsn)
    if not latest_run:
        print("Erreur : aucun run réussi trouvé dans cpi.logs pour collect_cpi_data.", file=sys.stderr)
        sys.exit(1)
    run_id, date_fin, nb_persistes = latest_run
    print(f"  Dernier run : {run_id} (terminé le {date_fin}, {nb_persistes} ligne(s) collectée(s))")

    if coicop_filter:
        print(f"⚠️  Filtre temporaire actif : coicop_1999 IN {coicop_filter} "
              f"(voir note en tête de script — périmètre à valider avec l'équipe)")

    print("Lecture de cpi.donnees pour ce run...")
    donnees_rows = fetch_donnees(dsn, run_id, coicop_filter)
    print(f"  {len(donnees_rows)} ligne(s) donnees.")

    if len(donnees_rows) > EXCEL_SAFETY_MARGIN:
        print(
            f"❌ {len(donnees_rows)} lignes dépassent la marge de sécurité Excel "
            f"({EXCEL_SAFETY_MARGIN}). Fichier NON généré — resserrer le filtre "
            f"(coicop_filter) ou attendre la décision d'équipe sur le périmètre.",
            file=sys.stderr,
        )
        sys.exit(1)

    wb = build_workbook(metadata_rows, donnees_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Fichier régénéré : {output_path}")

    return len(metadata_rows), len(donnees_rows)


def main():
    parser = argparse.ArgumentParser(
        description="Alimente le fichier SharePoint CPI depuis la base PostgreSQL (dernier run uniquement)."
    )
    parser.add_argument("--dsn", required=True, help="Chaîne de connexion PostgreSQL")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Chemin de destination (dossier SharePoint synchronisé localement). "
             f"Par défaut : {DEFAULT_OUTPUT} (chemin temporaire, à remplacer)",
    )
    parser.add_argument(
        "--coicop", nargs="*", default=DEFAULT_COICOP_FILTER,
        help="Filtre temporaire sur les catégories COICOP (défaut : _T uniquement, "
             "pour respecter la limite Excel en attendant la décision d'équipe). "
             "Passer --coicop sans argument pour désactiver le filtre (⚠️ dépassera "
             "probablement la limite Excel avec le périmètre complet).",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    coicop_filter = args.coicop if args.coicop else None

    start = datetime.now(timezone.utc)
    try:
        nb_metadata, nb_donnees = refresh_sharepoint_file(args.dsn, output_path, coicop_filter)
    except PermissionError as e:
        print(
            f"Erreur : impossible d'écrire le fichier. Assure-toi qu'il n'est pas "
            f"ouvert dans Excel. Détail : {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)

    duration = (datetime.now(timezone.utc) - start).total_seconds()
    print(
        f"Résumé : metadata={nb_metadata} ligne(s) | donnees={nb_donnees} ligne(s) "
        f"| durée={duration:.1f}s | statut=SUCCESS"
    )


if __name__ == "__main__":
    main()
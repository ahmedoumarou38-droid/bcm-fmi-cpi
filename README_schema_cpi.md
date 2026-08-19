# Schéma cible IMF / CPI — Documentation

**Base de données :** `imf`
**Schéma :** `cpi`
**Script de création :** `sql/create_schema_imf_cpi_001.sql` (idempotent, rejouable)

## Comment lancer le script

**Via pgAdmin (recommandé) :**
1. Créer la base `imf` (clic-droit sur "Databases" > Create > Database > nom `imf`)
2. Se connecter à `imf`, ouvrir le Query Tool
3. Coller le contenu de `sql/create_schema_imf_cpi_001.sql` et exécuter (F5)

**Via psql (si disponible dans le PATH) :**
```bash
psql -U postgres -h localhost -c "CREATE DATABASE imf;"
psql -U postgres -h localhost -d imf -f sql/create_schema_imf_cpi_001.sql
```

## Table `cpi.metadata`

Informations descriptives du dataset CPI (une ligne par dataset).

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| id | BIGSERIAL | PK | Champ technique |
| dataset_name | TEXT | NOT NULL | |
| dataset_id | VARCHAR(50) | NOT NULL, UNIQUE | ex : "CPI" |
| frequency | VARCHAR(200) | | ex : "Annual, Monthly, Quarterly" |
| agency | VARCHAR(100) | | |
| version | VARCHAR(50) | | |
| dataset_description | TEXT | | |
| geographical_coverage | TEXT | | |
| full_description | TEXT | | |
| publisher | VARCHAR(255) | | |
| department | VARCHAR(255) | | |
| contact_point | VARCHAR(255) | | |
| topic_dataset | TEXT | | |
| keywords_dataset | TEXT | | |
| language | VARCHAR(100) | | |
| publication_date | TIMESTAMP | | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| update_date | TIMESTAMP | | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| short_source_citation | TEXT | | |
| full_source_citation | TEXT | | |
| license | TEXT | | |
| suggested_citation | TEXT | | |
| created_at | TIMESTAMP | NOT NULL, défaut now() | Champ technique |
| updated_at | TIMESTAMP | NOT NULL, défaut now() | Champ technique — égal à created_at |

## Table `cpi.logs`

Historique des exécutions des pipelines de collecte.

| Colonne | Type | Contraintes | Notes |
|---|---|---|---|
| id | BIGSERIAL | PK | Champ technique — remplace l'ancien `run_id` texte |
| pipeline | VARCHAR(100) | NOT NULL | |
| start_date | TIMESTAMP | NOT NULL | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| end_date | TIMESTAMP | | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| status | VARCHAR(20) | NOT NULL, CHECK IN ('SUCCESS','FAILED') | Voir point ouvert ci-dessous (RUNNING) |
| collected_elements_count | INTEGER | CHECK ≥ 0 | |
| persisted_elements_count | INTEGER | CHECK ≥ 0 | |
| error_message | TEXT | | |
| created_at | TIMESTAMP | NOT NULL, défaut now() | Champ technique |
| updated_at | TIMESTAMP | NOT NULL, défaut now() | Champ technique — égal à created_at |

**Contrainte de cohérence des dates :** `end_date IS NULL OR end_date >= start_date`
⚠️ Le feedback demande littéralement `CHECK (start_date > end_date)`, ce qui empêcherait toute exécution normale. Corrigé en sens inverse — **à confirmer**.

## Table `cpi.data`

Observations CPI détaillées, avec l'ensemble des dimensions et métadonnées associées du dataset (structure alignée sur l'export complet du Data Explorer du FMI). Pour chaque dimension SDMX, trois colonnes suivent la convention `<dimension>_id` (code), `<dimension>` (libellé), `<dimension>_description` (description longue) — ex : `country_id` / `country` / `country_description`.

| Colonne | Type | Notes |
|---|---|---|
| id | BIGSERIAL | PK, champ technique |
| logs_id | BIGINT | FK → `cpi.logs(id)` ON DELETE RESTRICT — ajouté après `id`, défini dans la section "Relations" du feedback (absent de la liste énumérée des colonnes) |
| country_id / country / country_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| index_type_id / index_type / index_type_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| coicop_1999_id / coicop_1999 / coicop_1999_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| type_of_transformation_id / type_of_transformation / type_of_transformation_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| frequency_id / frequency / frequency_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| time_period | VARCHAR(20) | |
| obs_value | DOUBLE PRECISION | |
| scale_id / scale / scale_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| precision_id / precision / precision_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| decimals_displayed_id / decimals_displayed / decimals_displayed_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| reporting_period_type_id / reporting_period_type / reporting_period_type_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| transformation_id / transformation / transformation_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| unit_id / unit / unit_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| derivation_type_id / derivation_type / derivation_type_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| overlap_id / overlap / overlap_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| reference_period | VARCHAR(50) | |
| common_reference_period | VARCHAR(50) | |
| status | VARCHAR(50) | Statut de l'observation (distinct de `logs.status`) |
| ifs_flag | VARCHAR(20) | |
| doi | VARCHAR(255) | |
| full_description | TEXT | |
| author | VARCHAR(255) | |
| publisher_id / publisher / publisher_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| department_id / department / department_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| contact_point | VARCHAR(255) | |
| topic_id / topic / topic_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| topic_dataset_id / topic_dataset / topic_dataset_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| keywords | TEXT | |
| keywords_dataset | TEXT | |
| language_id / language / language_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| publication_date | TIMESTAMP | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| update_date | TIMESTAMP | Format ISO `YYYY-MM-DDTHH:MM:SS` |
| methodology_id / methodology / methodology_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| methodology_notes | TEXT | |
| access_sharing_level_id / access_sharing_level / access_sharing_level_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| access_sharing_notes | TEXT | |
| security_classification_id / security_classification / security_classification_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| source_id / source / source_description | VARCHAR(50) / VARCHAR(255) / TEXT | |
| short_source_citation | TEXT | |
| full_source_citation | TEXT | |
| license | TEXT | |
| suggested_citation | TEXT | |
| key_indicator | VARCHAR(20) | |
| series_name | VARCHAR(255) | |
| created_at | TIMESTAMP | NOT NULL, défaut now() — champ technique |
| updated_at | TIMESTAMP | NOT NULL, défaut now() — champ technique, égal à created_at |

## Relations

```
cpi.logs (id) ──< cpi.data (logs_id)   [ON DELETE RESTRICT]
```

## Index

- `idx_data_logs_id` sur `cpi.data(logs_id)`
- `idx_data_country_time_period` sur `cpi.data(country, time_period)`

## Choix de conception

- **Formats de date** : tous les champs date/datetime sont en `TIMESTAMP`, format ISO 8601 (`YYYY-MM-DDTHH:MM:SS`).
- **Longueur des champs texte** : descriptions et contenus longs en `TEXT` (illimité) ; codes courts en `VARCHAR(50)` ; libellés/noms en `VARCHAR(255)`.
- **Clés primaires techniques** : `BIGSERIAL` sur les 3 tables.
- **Convention triplet** : chaque dimension SDMX de `cpi.data` est représentée par 3 colonnes (code / libellé / description), reflétant fidèlement la structure du Data Explorer FMI.
- **Idempotence** : `IF NOT EXISTS` partout, sauf `CREATE DATABASE` (limitation PostgreSQL, à exécuter séparément).

## Points à confirmer avec l'équipe

1. Sens de la contrainte de cohérence des dates (`end_date >= start_date` vs `start_date > end_date` tel qu'écrit littéralement)
2. Le statut `RUNNING` (utilisé actuellement par les scripts Python) n'est pas dans la liste autorisée (`SUCCESS`, `FAILED`) — implique une adaptation des scripts Python (suppression de l'état intermédiaire) si la contrainte reste stricte
3. `cpi.data.logs_id` : colonne ajoutée d'après la section "Relations" du feedback, absente de la liste énumérée des colonnes elle-même — à confirmer que le positionnement (juste après `id`) convient
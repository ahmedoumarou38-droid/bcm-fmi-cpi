# Documentation - Schéma CPI (base de données FMI)

## Contexte

Ce document décrit la structure de la base de données créée pour recevoir les données du dataset **CPI** (Consumer Price Index) du FMI : métadonnées, dictionnaire des champs, observations et journalisation des exécutions du pipeline de collecte.

- **SGBD** : PostgreSQL
- **Base de données** : `FMI`
- **Schéma** : `cpi`
- **Script de création** : `sql/001_create_schema_cpi.sql`
- **Script de collecte metadata** : `scraping/collect_cpi_metadata.py`
- **Diagramme HTML** : `schema_cpi_base_donnees.html`

L'architecture en schémas (un schéma par dataset FMI) permet d'ajouter facilement d'autres jeux de données (WEO, GDD, PCPS, etc.) dans la même base `FMI` sans refonte, en créant simplement un nouveau schéma.

---

## Schéma relationnel

```text
LOGS                         DONNEES
----                         -------
run_id (PK) <---------------- run_id (FK)
pipeline                     id (PK)
date_debut                   field_id
date_fin                     field_name
statut                       field_description
nb_elements_collectes         country
nb_elements_persistes        coicop_1999
message_erreur               type_of_transformation
                              frequency
                              time_period
                              obs_value

METADATA
--------
dataset_id (PK)
dataset_name
agency
version
description_courte
description_complete
frequency
publisher
department
contact_point
topic
keywords
language
publication_date
update_date
short_source_citation
full_source_citation
```

**Relation clé** : `donnees.run_id` référence `logs.run_id` (contrainte `fk_donnees_run`). Chaque exécution du pipeline (une ligne dans `logs`) peut produire plusieurs lignes d'observations dans `donnees`, ce qui permet de tracer précisément quelle exécution a produit quelles données (audit, rollback ciblé sur un `run_id`).

> Note : `donnees` porte sa propre clé primaire technique (`id`, auto-incrémentée) et non `run_id`, car une exécution génère naturellement plusieurs observations (plusieurs pays, périodes, champs).

---

## Table `metadata`

Informations descriptives sur le dataset (une ligne par dataset/version).

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| dataset_id | VARCHAR(50) | **PK**, NOT NULL | Identifiant du dataset |
| dataset_name | VARCHAR(150) | NOT NULL | Nom du dataset |
| agency | VARCHAR(100) | NOT NULL | Agence source (ex: FMI) |
| version | VARCHAR(20) | | Version du dataset |
| description_courte | TEXT | | Description courte |
| description_complete | TEXT | | Description complète |
| frequency | VARCHAR(20) | | Fréquence des données (ex: monthly) |
| publisher | VARCHAR(150) | | Éditeur du dataset |
| department | VARCHAR(150) | | Département responsable |
| contact_point | VARCHAR(150) | | Point de contact |
| topic | VARCHAR(150) | | Thématique |
| keywords | TEXT | | Mots-clés |
| language | VARCHAR(10) | | Langue |
| publication_date | DATE | | Date de publication |
| update_date | DATE | | Date de dernière mise à jour |
| short_source_citation | TEXT | | Citation courte de la source |
| full_source_citation | TEXT | | Citation complète de la source |

---

## Table `logs`

Historique des exécutions du pipeline de collecte.

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| run_id | VARCHAR(50) | **PK**, NOT NULL | Identifiant unique de l'exécution |
| pipeline | VARCHAR(100) | NOT NULL | Nom du pipeline exécuté |
| date_debut | TIMESTAMP | NOT NULL | Horodatage de début |
| date_fin | TIMESTAMP | CHECK | Horodatage de fin, supérieur ou égal à `date_debut` si renseigné |
| statut | VARCHAR(20) | NOT NULL, CHECK | Statut : `SUCCESS`, `FAILED`, `RUNNING`, `PARTIAL` |
| nb_elements_collectes | INTEGER | CHECK | Nombre d'éléments collectés, positif ou nul |
| nb_elements_persistes | INTEGER | CHECK | Nombre d'éléments réellement enregistrés, positif ou nul |
| message_erreur | TEXT | | Message d'erreur éventuel |

---

## Table `donnees`

Dictionnaire des champs et observations, tracées par exécution.

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| id | BIGSERIAL | **PK**, NOT NULL | Identifiant technique auto-incrémenté |
| run_id | VARCHAR(50) | **FK** -> `logs.run_id`, NOT NULL | Exécution ayant produit la ligne |
| field_id | VARCHAR(50) | | Identifiant du champ |
| field_name | VARCHAR(150) | | Nom du champ |
| field_description | TEXT | | Description du champ |
| country | VARCHAR(10) | | Code pays |
| coicop_1999 | VARCHAR(20) | | Code de classification COICOP 1999 |
| type_of_transformation | VARCHAR(50) | | Type de transformation appliquée |
| frequency | VARCHAR(20) | | Fréquence de l'observation |
| time_period | VARCHAR(20) | | Période temporelle de l'observation |
| obs_value | DOUBLE PRECISION | | Valeur observée |

**Index** :

- `idx_donnees_run_id` sur `run_id` : accélère les requêtes d'audit/rollback par exécution.
- `idx_donnees_country_period` sur `(country, time_period)` : accélère les requêtes d'analyse par pays/période.

---

## Contraintes d'intégrité résumées

- Toutes les clés primaires (`dataset_id`, `run_id`, `id`) sont `NOT NULL` par définition.
- `metadata.dataset_name` et `metadata.agency` sont obligatoires.
- `logs.statut` est contraint aux valeurs `SUCCESS`, `FAILED`, `RUNNING`, `PARTIAL` (contrainte `chk_logs_statut`).
- `logs.nb_elements_collectes` et `logs.nb_elements_persistes` doivent être positifs ou nuls lorsqu'ils sont renseignés.
- `logs.date_fin` doit être supérieure ou égale à `logs.date_debut` lorsqu'elle est renseignée.
- `donnees.run_id` doit obligatoirement correspondre à un `run_id` existant dans `logs` (contrainte `fk_donnees_run`, `ON DELETE RESTRICT` : un log ne peut pas être supprimé tant que des données lui sont rattachées).

---

## Collecte Metadata CPI

Le script `scraping/collect_cpi_metadata.py` exécute le rendu JavaScript du portail IMF Data avec Playwright, parse le DOM final avec BeautifulSoup, vérifie le nombre de champs metadata attendus, puis écrit les résultats dans `cpi.metadata` si une connexion PostgreSQL est fournie.

Exécution sans écriture PostgreSQL, pour test et export SharePoint manuel :

```bash
scraping/venv/Scripts/python.exe scraping/collect_cpi_metadata.py --no-db
```

Exécution avec insertion dans PostgreSQL :

```bash
scraping/venv/Scripts/python.exe scraping/collect_cpi_metadata.py --dsn "dbname=FMI user=postgres password=postgres host=localhost port=5432"
```

Sorties locales créées par défaut dans `scraping/output/` :

- `cpi_metadata.json`
- `cpi_metadata.xlsx`

Le fichier Excel peut être déposé dans le fichier SharePoint existant. L'écriture directe SharePoint nécessite une connexion ou un connecteur SharePoint.

---

## Rejeu du script SQL sur un autre environnement

```bash
# 1. Créer la base (une seule fois)
psql -U postgres -c 'CREATE DATABASE "FMI";'

# 2. Exécuter le script de création du schéma
psql -U postgres -d FMI -f sql/001_create_schema_cpi.sql

# 3. Vérifier
psql -U postgres -d FMI -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'cpi';"
```

Le script utilise `CREATE SCHEMA IF NOT EXISTS` et `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`. Il est donc rejouable sans erreur sur un environnement où le schéma existe déjà.
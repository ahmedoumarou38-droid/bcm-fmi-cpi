# Documentation - Schéma CPI (Base de données FMI)

## Contexte

Ce document décrit la structure de la base de données créée pour recevoir les données du dataset **CPI** (Consumer Price Index) du FMI : métadonnées, dictionnaire des champs, observations, et journalisation des exécutions du pipeline de collecte.

- **SGBD** : PostgreSQL
- **Base de données** : `FMI`
- **Schéma** : `cpi`
- **Script de création** : `sql/001_create_schema_cpi.sql`

L'architecture en schémas (un schéma par dataset FMI) permet d'ajouter facilement d'autres jeux de données (WEO, GDD, PCPS, etc.) dans la même base `FMI` sans refonte, en créant simplement un nouveau schéma.

---

## Schéma relationnel

```
METADATA                    LOGS                         DONNEES
--------                    ----                         -------
dataset_id (PK)                                          id (PK)
agency                      run_id (PK) <----------------- run_id (FK)
version                     pipeline                     field_id
description_courte          date_debut                   field_name
frequency                   date_fin                     field_description
publisher                   statut                       country
department                  nb_elements_collectes         coicop_1999
contact_point                nb_elements_persistes        type_of_transformation
topic                       message_erreur                frequency
keywords                                                  time_period
language                                                  obs_value
publication_date
update_date
source_citation
```

**Relation clé** : `donnees.run_id` référence `logs.run_id` (contrainte `fk_donnees_run`). Chaque exécution du pipeline (une ligne dans `logs`) peut produire plusieurs lignes d'observations dans `donnees`, ce qui permet de tracer précisément quelle exécution a produit quelles données (audit, rollback ciblé sur un `run_id`).

> Note : `donnees` porte sa propre clé primaire technique (`id`, auto-incrémentée) et non `run_id`, car une exécution génère naturellement plusieurs observations (plusieurs pays, périodes, champs).

---

## Table `metadata`

Informations descriptives sur le dataset (une ligne par dataset/version).

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| dataset_id | VARCHAR(50) | **PK**, NOT NULL | Identifiant du dataset |
| agency | VARCHAR(100) | | Agence source (ex: FMI) |
| version | VARCHAR(20) | | Version du dataset |
| description_courte | TEXT | | Description courte |
| frequency | VARCHAR(20) | | Fréquence des données (ex: monthly) |
| publisher | VARCHAR(150) | | Éditeur du dataset |
| department | VARCHAR(150) | | Département responsable |
| contact_point | VARCHAR(150) | | Point de contact |
| topic | VARCHAR(150) | | Thématique |
| keywords | TEXT | | Mots-clés |
| language | VARCHAR(10) | | Langue |
| publication_date | DATE | | Date de publication |
| update_date | DATE | | Date de dernière mise à jour |
| source_citation | TEXT | | Citation de la source |

---

## Table `logs`

Historique des exécutions du pipeline de collecte.

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| run_id | VARCHAR(50) | **PK**, NOT NULL | Identifiant unique de l'exécution |
| pipeline | VARCHAR(100) | NOT NULL | Nom du pipeline exécuté |
| date_debut | TIMESTAMP | NOT NULL | Horodatage de début |
| date_fin | TIMESTAMP | | Horodatage de fin |
| statut | VARCHAR(20) | NOT NULL, CHECK | Statut : `SUCCESS`, `FAILED`, `RUNNING`, `PARTIAL` |
| nb_elements_collectes | INTEGER | | Nombre d'éléments collectés |
| nb_elements_persistes | INTEGER | | Nombre d'éléments réellement enregistrés |
| message_erreur | TEXT | | Message d'erreur éventuel |

---

## Table `donnees`

Dictionnaire des champs et observations, tracées par exécution.

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| id | BIGSERIAL | **PK**, NOT NULL | Identifiant technique auto-incrémenté |
| run_id | VARCHAR(50) | **FK** → logs.run_id, NOT NULL | Exécution ayant produit la ligne |
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
- `idx_donnees_run_id` sur `run_id` — accélère les requêtes d'audit/rollback par exécution
- `idx_donnees_country_period` sur `(country, time_period)` — accélère les requêtes d'analyse par pays/période

---

## Contraintes d'intégrité résumées

- Toutes les clés primaires (`dataset_id`, `run_id`, `id`) sont `NOT NULL` par définition.
- `logs.statut` est contraint aux valeurs `SUCCESS`, `FAILED`, `RUNNING`, `PARTIAL` (contrainte `chk_statut`).
- `donnees.run_id` doit obligatoirement correspondre à un `run_id` existant dans `logs` (contrainte `fk_donnees_run`, `ON DELETE RESTRICT` : un log ne peut pas être supprimé tant que des données lui sont rattachées).

---

## Rejeu du script sur un autre environnement

```bash
# 1. Créer la base (une seule fois)
psql -U postgres -c 'CREATE DATABASE "FMI";'

# 2. Exécuter le script de création du schéma
psql -U postgres -d FMI -f sql/001_create_schema_cpi.sql

# 3. Vérifier
psql -U postgres -d FMI -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'cpi';"
```

Le script utilise `CREATE SCHEMA IF NOT EXISTS` et `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, il est donc rejouable sans erreur même si le schéma existe déjà.

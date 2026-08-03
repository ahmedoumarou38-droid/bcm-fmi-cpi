-- =====================================================================
-- Ticket : Création du schéma CPI (dataset FMI) - Base de données FMI
-- SGBD cible : PostgreSQL
-- =====================================================================

-- 1. Création de la base de données (à exécuter une seule fois, hors transaction)
-- Décommente si la base n'existe pas encore :
-- CREATE DATABASE "FMI";

-- 2. Connecte-toi à la base FMI avant de continuer (\c FMI dans psql,
--    ou sélectionne la connexion "FMI" dans SQLTools)

-- 3. Création du schéma dédié au dataset CPI
CREATE SCHEMA IF NOT EXISTS cpi;

SET search_path TO cpi;

-- ---------------------------------------------------------------------
-- Table METADATA : informations descriptives sur le dataset (1 ligne
-- par dataset/version)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cpi.metadata (
    dataset_id          VARCHAR(50)  NOT NULL,
    agency              VARCHAR(100),
    version             VARCHAR(20),
    description_courte  TEXT,
    frequency           VARCHAR(20),
    publisher           VARCHAR(150),
    department          VARCHAR(150),
    contact_point       VARCHAR(150),
    topic               VARCHAR(150),
    keywords            TEXT,
    language            VARCHAR(10),
    publication_date    DATE,
    update_date         DATE,
    source_citation     TEXT,
    CONSTRAINT pk_metadata PRIMARY KEY (dataset_id)
);

-- ---------------------------------------------------------------------
-- Table LOGS : historique des exécutions du pipeline de collecte
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cpi.logs (
    run_id                  VARCHAR(50)  NOT NULL,
    pipeline                VARCHAR(100) NOT NULL,
    date_debut              TIMESTAMP    NOT NULL,
    date_fin                TIMESTAMP,
    statut                  VARCHAR(20)  NOT NULL,
    nb_elements_collectes   INTEGER,
    nb_elements_persistes   INTEGER,
    message_erreur          TEXT,
    CONSTRAINT pk_logs PRIMARY KEY (run_id),
    CONSTRAINT chk_statut CHECK (statut IN ('SUCCESS','FAILED','RUNNING','PARTIAL'))
);

-- ---------------------------------------------------------------------
-- Table DONNEES : dictionnaire des champs + observations, tracées par
-- run_id (lien vers logs). Une exécution produit plusieurs lignes,
-- donc run_id est ici une clé étrangère, pas une clé primaire.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cpi.donnees (
    id                      BIGSERIAL    NOT NULL,
    run_id                  VARCHAR(50)  NOT NULL,
    field_id                VARCHAR(50),
    field_name              VARCHAR(150),
    field_description       TEXT,
    country                 VARCHAR(10),
    coicop_1999             VARCHAR(20),
    type_of_transformation  VARCHAR(50),
    frequency               VARCHAR(20),
    time_period             VARCHAR(20),
    obs_value               DOUBLE PRECISION,
    CONSTRAINT pk_donnees PRIMARY KEY (id),
    CONSTRAINT fk_donnees_run
        FOREIGN KEY (run_id) REFERENCES cpi.logs (run_id)
        ON DELETE RESTRICT
);

-- Index pour l'audit / le rollback par run, et les requêtes fréquentes
CREATE INDEX IF NOT EXISTS idx_donnees_run_id ON cpi.donnees (run_id);
CREATE INDEX IF NOT EXISTS idx_donnees_country_period ON cpi.donnees (country, time_period);

-- ---------------------------------------------------------------------
-- Vérification rapide
-- ---------------------------------------------------------------------
-- \dt cpi.*
-- \d cpi.metadata
-- \d cpi.logs
-- \d cpi.donnees
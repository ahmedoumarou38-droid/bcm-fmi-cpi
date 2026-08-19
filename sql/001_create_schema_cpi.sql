
CREATE SCHEMA IF NOT EXISTS cpi;


CREATE TABLE IF NOT EXISTS cpi.metadata (
    id                      BIGSERIAL PRIMARY KEY,
    dataset_name            TEXT NOT NULL,
    dataset_id              VARCHAR(50) NOT NULL UNIQUE,
    frequency               VARCHAR(200),
    agency                  VARCHAR(100),
    version                 VARCHAR(50),
    dataset_description     TEXT,
    geographical_coverage   TEXT,
    full_description        TEXT,
    publisher                VARCHAR(255),
    department              VARCHAR(255),
    contact_point            VARCHAR(255),
    topic_dataset            TEXT,
    keywords_dataset          TEXT,
    language                 VARCHAR(100),
    publication_date          TIMESTAMP,
    update_date               TIMESTAMP,
    short_source_citation      TEXT,
    full_source_citation       TEXT,
    license                   TEXT,
    suggested_citation          TEXT,
    created_at                TIMESTAMP NOT NULL DEFAULT now(),
    updated_at                TIMESTAMP NOT NULL DEFAULT now()
);

COMMENT ON TABLE cpi.metadata IS 'Informations descriptives du dataset CPI (une ligne par dataset).';

-- -----------------------------------------------------------------------------
-- Table cpi.logs (créée avant cpi.data car référencée par sa FK)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cpi.logs (
    id                          BIGSERIAL PRIMARY KEY,
    pipeline                    VARCHAR(100) NOT NULL,
    start_date                  TIMESTAMP NOT NULL,
    end_date                    TIMESTAMP,
    status                      VARCHAR(20) NOT NULL,
    collected_elements_count    INTEGER,
    persisted_elements_count    INTEGER,
    error_message                TEXT,
    created_at                   TIMESTAMP NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT chk_logs_status
        CHECK (status IN ('SUCCESS', 'FAILED')),
    CONSTRAINT chk_logs_dates
        CHECK (end_date IS NULL OR end_date >= start_date),  -- voir note en tête de fichier
    CONSTRAINT chk_logs_collected_nonneg
        CHECK (collected_elements_count IS NULL OR collected_elements_count >= 0),
    CONSTRAINT chk_logs_persisted_nonneg
        CHECK (persisted_elements_count IS NULL OR persisted_elements_count >= 0)
);

COMMENT ON TABLE cpi.logs IS 'Historique des exécutions des pipelines de collecte CPI.';


CREATE TABLE IF NOT EXISTS cpi.data (
    id                                  BIGSERIAL PRIMARY KEY,
    logs_id                             BIGINT NOT NULL,

    country_id                          VARCHAR(50),
    country                             VARCHAR(255),
    country_description                 TEXT,

    index_type_id                       VARCHAR(50),
    index_type                          VARCHAR(255),
    index_type_description              TEXT,

    coicop_1999_id                      VARCHAR(50),
    coicop_1999                         VARCHAR(255),
    coicop_1999_description             TEXT,

    type_of_transformation_id           VARCHAR(50),
    type_of_transformation              VARCHAR(255),
    type_of_transformation_description  TEXT,

    frequency_id                        VARCHAR(50),
    frequency                           VARCHAR(255),
    frequency_description               TEXT,

    time_period                         VARCHAR(20),
    obs_value                           DOUBLE PRECISION,

    scale_id                            VARCHAR(50),
    scale                               VARCHAR(255),
    scale_description                   TEXT,

    precision_id                        VARCHAR(50),
    precision                           VARCHAR(255),
    precision_description               TEXT,

    decimals_displayed_id               VARCHAR(50),
    decimals_displayed                  VARCHAR(255),
    decimals_displayed_description      TEXT,

    reporting_period_type_id            VARCHAR(50),
    reporting_period_type               VARCHAR(255),
    reporting_period_type_description   TEXT,

    transformation_id                   VARCHAR(50),
    transformation                      VARCHAR(255),
    transformation_description          TEXT,

    unit_id                             VARCHAR(50),
    unit                                VARCHAR(255),
    unit_description                    TEXT,

    derivation_type_id                  VARCHAR(50),
    derivation_type                     VARCHAR(255),
    derivation_type_description         TEXT,

    overlap_id                          VARCHAR(50),
    overlap                             VARCHAR(255),
    overlap_description                 TEXT,

    reference_period                    VARCHAR(50),
    common_reference_period             VARCHAR(50),
    status                              VARCHAR(50),
    ifs_flag                            VARCHAR(20),
    doi                                 VARCHAR(255),
    full_description                    TEXT,
    author                              VARCHAR(255),

    publisher_id                        VARCHAR(50),
    publisher                           VARCHAR(255),
    publisher_description               TEXT,

    department_id                       VARCHAR(50),
    department                          VARCHAR(255),
    department_description              TEXT,

    contact_point                       VARCHAR(255),

    topic_id                            VARCHAR(50),
    topic                               VARCHAR(255),
    topic_description                   TEXT,

    topic_dataset_id                    VARCHAR(50),
    topic_dataset                       VARCHAR(255),
    topic_dataset_description           TEXT,

    keywords                            TEXT,
    keywords_dataset                    TEXT,

    language_id                         VARCHAR(50),
    language                            VARCHAR(255),
    language_description                TEXT,

    publication_date                    TIMESTAMP,
    update_date                         TIMESTAMP,

    methodology_id                      VARCHAR(50),
    methodology                         VARCHAR(255),
    methodology_description             TEXT,
    methodology_notes                   TEXT,

    access_sharing_level_id             VARCHAR(50),
    access_sharing_level                VARCHAR(255),
    access_sharing_level_description    TEXT,
    access_sharing_notes                TEXT,

    security_classification_id          VARCHAR(50),
    security_classification             VARCHAR(255),
    security_classification_description TEXT,

    source_id                           VARCHAR(50),
    source                               VARCHAR(255),
    source_description                  TEXT,

    short_source_citation               TEXT,
    full_source_citation                TEXT,
    license                             TEXT,
    suggested_citation                  TEXT,
    key_indicator                       VARCHAR(20),
    series_name                         VARCHAR(255),

    created_at                          TIMESTAMP NOT NULL DEFAULT now(),
    updated_at                          TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT fk_data_logs
        FOREIGN KEY (logs_id) REFERENCES cpi.logs(id)
        ON DELETE RESTRICT
);

COMMENT ON TABLE cpi.data IS 'Observations CPI détaillées (dimensions SDMX complètes + métadonnées associées), liées à leur exécution via logs_id.';


CREATE INDEX IF NOT EXISTS idx_data_logs_id ON cpi.data(logs_id);
CREATE INDEX IF NOT EXISTS idx_data_country_time_period ON cpi.data(country, time_period);


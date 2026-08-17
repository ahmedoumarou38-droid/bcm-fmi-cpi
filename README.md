# BCM FMI CPI - Infrastructure Data Governance

## 📋 Contexte

Ce projet met en place une infrastructure de **gouvernance des données** pour le dataset **CPI** (Consumer Price Index) du Fonds Monétaire International (FMI). Il automatise la collecte des métadonnées et des observations depuis l'API SDMX du FMI, les persiste dans une base de données PostgreSQL structurée, et documente le processus via une journalisation détaillée.

**Objectif** : Créer une base de données FMI extensible et maintenable pour accueillir d'autres datasets (WEO, GDD, PCPS, etc.) en complément du CPI.

---

## 🏗️ Structure du projet

```
bcm-fmi-cpi/
├── README.md                           # Ce fichier
├── README_schema_cpi.md                # Documentation détaillée du schéma CPI
├── schema_cpi_base_donnees.html        # Diagramme ER interactif
│
├── sql/                                # Scripts de création et configuration BD
│   ├── 001_create_schema_cpi.sql       # Création du schéma CPI (tables, vues, logs)
│   └── 002_add_extra_metadata_fields.sql # Enrichissement des colonnes metadata
│
├── scraping/                           # Scripts Python de collecte de données
│   ├── collect_cpi_metadata.py         # Récupération des métadonnées depuis SDMX
│   ├── collect_cpi_data.py             # Récupération des observations de CPI
│   └── output/                         # Résultats des exécutions
│       ├── cpi_metadata.json           # Métadonnées collectées
│       └── metadata_debug.html         # Rapport HTML de debug
│
├── .vscode/                            # Configuration VS Code
└── .gitignore                          # Fichiers ignorés par Git
```

---

## 🗄️ Architecture Base de Données

### Schéma CPI

Le schéma `cpi` dans PostgreSQL (base `FMI`) comprend :

#### Tables principales

1. **`metadata`** - Métadonnées du dataset CPI
   - `dataset_id`, `dataset_name`, `agency`, `version`
   - `description_courte`, `description_complete`
   - `frequency`, `publisher`, `department`
   - `contact_point`, `topic`, `keywords`, `language`
   - `publication_date`

2. **`donnees`** - Observations de CPI
   - `id` (PK), `run_id` (FK), `field_id`, `field_name`
   - `country`, `coicop_1999`, `type_of_transformation`
   - `frequency`, `time_period`, `obs_value`
   - Index sur `(country, time_period)` pour requêtes rapides

3. **`logs`** - Journalisation du pipeline
   - `run_id` (PK), `pipeline`, `date_debut`, `date_fin`
   - `statut` (success/error), `nb_elements_collectes`
   - `nb_elements_persistes`, `message_erreur`

#### Avantages de cette architecture

- ✅ Séparation claire : métadonnées, données, logs
- ✅ Traçabilité complète avec `run_id`
- ✅ Extensible : un schéma par dataset FMI
- ✅ Audit trail : tous les runs enregistrés

---

## 🚀 Installation et utilisation

### Prérequis

- **PostgreSQL** 12+ avec la base `FMI` créée
- **Python** 3.8+
- **pip** (gestionnaire de paquets Python)

### 1️⃣ Initialiser la base de données

```bash
# Créer le schéma CPI dans PostgreSQL
psql -U postgres -d FMI -f sql/001_create_schema_cpi.sql

# Ajouter les métadonnées enrichies (optionnel)
psql -U postgres -d FMI -f sql/002_add_extra_metadata_fields.sql
```

### 2️⃣ Configurer l'environnement Python

```bash
cd scraping
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/macOS

pip install -r requirements.txt  # Si requirements.txt existe
# Sinon :
pip install requests psycopg2-binary
```

### 3️⃣ Collecter les métadonnées CPI

```bash
python collect_cpi_metadata.py \
  --api-key "YOUR_IMF_API_KEY" \
  --dsn "dbname=FMI user=postgres password=PASSWORD host=localhost"
```

**Résultat** : Les métadonnées sont sauvegardées dans `output/cpi_metadata.json`

### 4️⃣ Collecter les observations CPI

```bash
python collect_cpi_data.py \
  --countries "MRT,ALB,DZA" \
  --api-key "YOUR_IMF_API_KEY" \
  --dsn "dbname=FMI user=postgres password=PASSWORD host=localhost"
```

**Options disponibles** :
- `--countries`: Code ISO des pays (ex. `MRT`, `ALB`, `DZA`)
- `--start-period`: Période de début (ex. `2020-01`)
- `--end-period`: Période de fin (ex. `2023-12`)
- `--coicop`: Classification COICOP 1999 (par défaut `IX`)
- `--transformation`: Type de transformation (par défaut `PC_CP`)
- `--frequency`: Fréquence des données (par défaut `M` pour mensuel)

### 5️⃣ Vérifier les résultats

```bash
# Afficher les journaux d'exécution
psql -U postgres -d FMI -c "SELECT * FROM cpi.logs ORDER BY date_debut DESC LIMIT 5;"

# Compter les observations collectées
psql -U postgres -d FMI -c "SELECT COUNT(*) as total_observations FROM cpi.donnees;"

# Lister les pays disponibles
psql -U postgres -d FMI -c "SELECT DISTINCT country FROM cpi.donnees ORDER BY country;"
```

---

## 📊 Requêtes utiles

### Exemple 1 : CPI par pays et période

```sql
SELECT 
    country,
    time_period,
    obs_value as cpi_value,
    type_of_transformation
FROM cpi.donnees
WHERE country = 'MRT' 
  AND time_period >= '2020-01'
  AND type_of_transformation = 'PC_CP'
ORDER BY time_period;
```

### Exemple 2 : Historique des exécutions

```sql
SELECT 
    run_id,
    pipeline,
    date_debut,
    date_fin,
    statut,
    nb_elements_persistes,
    message_erreur
FROM cpi.logs
ORDER BY date_debut DESC;
```

### Exemple 3 : Variation du CPI mensuelle

```sql
WITH ranked_data AS (
    SELECT 
        country,
        time_period,
        obs_value,
        LAG(obs_value) OVER (PARTITION BY country ORDER BY time_period) as prev_value
    FROM cpi.donnees
    WHERE type_of_transformation = 'PC_CP'
)
SELECT 
    country,
    time_period,
    obs_value,
    ROUND(((obs_value - prev_value) / prev_value * 100)::numeric, 2) as variation_pct
FROM ranked_data
WHERE country = 'MRT' AND prev_value IS NOT NULL
ORDER BY time_period DESC
LIMIT 12;
```

---

## 🔑 Authentification API IMF

Pour utiliser les scripts de collecte, vous avez besoin d'une **clé API IMF SDMX** :

1. Accédez à https://www.imf.org/external/datamapper/api/v1/
2. Inscrivez-vous pour obtenir une clé API
3. Utilisez `--api-key "YOUR_KEY"` dans les commandes

> ⚠️ **Sécurité** : Ne commitez jamais votre clé API. Utilisez des variables d'environnement :
> ```bash
> export IMF_API_KEY="YOUR_KEY"
> python collect_cpi_data.py --api-key $IMF_API_KEY
> ```

---

## 📚 Documentation complète

- **[README_schema_cpi.md](./README_schema_cpi.md)** : Documentation détaillée du schéma et des tables
- **[schema_cpi_base_donnees.html](./schema_cpi_base_donnees.html)** : Diagramme ER interactif

---

## 🛠️ Maintenance et support

### Ajouter un nouveau dataset FMI

1. Créer un nouveau schéma : `sql/003_create_schema_WEO.sql`
2. Adapter les scripts de collecte pour le nouveau dataset
3. Mettre à jour la documentation

### Troubleshooting

| Problème | Solution |
|----------|----------|
| **Erreur de connexion PostgreSQL** | Vérifier le DSN : `dbname=FMI user=postgres password=... host=localhost` |
| **Clé API invalide** | Renouveler la clé depuis https://www.imf.org |
| **Timeout lors de la collecte** | Augmenter `timeout=60` dans les requêtes API |
| **Données manquantes** | Vérifier les paramètres `--start-period` et `--end-period` |

---

## 📝 License

Projet de gouvernance des données - FMI Dataset Management
2026

---

## 👥 Contributeurs

- Ahmed Oumarou (@ahmedoumarou38-droid)
- Équipe Data Governance

---

**Dernière mise à jour** : 2026-08-17

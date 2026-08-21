# BCM — Pipeline de données IMF CPI

Pipeline automatisé de collecte et de mise à disposition du dataset **CPI (Consumer Price Index)** du FMI, pour la Direction de la Gouvernance des Données de la BCM.

Ce projet couvre 4 tickets Jira, résumés ci-dessous. Chaque section explique **quoi**, **pourquoi**, et surtout **comment lancer**.

---

## 📁 Structure du projet

```
bcm-fmi-cpi/
├── sql/
│   ├── create_schema_imf_cpi_001.sql   → Ticket 1 : création de la base
│   └── README_schema_imf_cpi.md        → Documentation détaillée du schéma
├── scraping/
│   ├── collect_cpi_metadata.py         → Ticket 2 : collecte des métadonnées
│   ├── collect_cpi_data.py             → Ticket 3 : collecte des observations
│   ├── venv/                            → Environnement Python (à créer, voir plus bas)
│   └── output/                          → Fichiers générés localement (JSON, Excel)
└── sharepoint/
    ├── refresh_sharepoint_cpi.py       → Ticket 4 : alimentation SharePoint
    └── output/                          → Fichier local de secours
```

---

## ⚙️ Prérequis (à faire une seule fois)

1. **PostgreSQL** installé, avec un accès admin (utilisateur `postgres`)
2. **Python 3.11+** installé
3. **pgAdmin** (recommandé, pour visualiser la base)
4. Créer l'environnement virtuel Python et installer les dépendances :

```powershell
cd scraping
python -m venv venv
venv\Scripts\python.exe -m pip install requests openpyxl psycopg2-binary playwright beautifulsoup4
venv\Scripts\python.exe -m playwright install chromium
```

5. **Si tu es sur le réseau BCM** (proxy d'entreprise), installe aussi ceci pour éviter les erreurs SSL :

```powershell
venv\Scripts\python.exe -m pip install pip-system-certs
```

---

## 🎫 Ticket 1 — Conception de la base de données

**Quoi :** Base PostgreSQL `imf`, schéma `cpi`, avec 3 tables : `metadata`, `data`, `logs`.

**Pourquoi :** Structure cible pour stocker tout ce que les autres scripts collectent.

**Comment lancer :**

```powershell
# 1. Créer la base (une seule fois)
psql -U postgres -h localhost -c "CREATE DATABASE imf;"

# 2. Exécuter le script de création (rejouable sans risque)
psql -U postgres -h localhost -d imf -f sql/create_schema_imf_cpi_001.sql
```

*(Si `psql` n'est pas reconnu, ouvre pgAdmin, connecte-toi à la base `imf`, colle le contenu du fichier `.sql` dans le Query Tool, et exécute avec F5.)*

📄 Détails complets des colonnes, contraintes, choix techniques : voir `sql/README_schema_imf_cpi.md`

---

## 🎫 Ticket 2 — Collecte Metadata (Web Scraping)

**Quoi :** Récupère les 20 champs descriptifs du dataset CPI (nom, description, fréquence, citations...) depuis le site du FMI, et les écrit dans `cpi.metadata`.

**Comment ça marche :** Navigateur headless (Playwright) qui ouvre la page du dataset, clique sur "Metadata", puis extrait le texte avec BeautifulSoup.

**Comment lancer :**

```powershell
cd scraping

# Test sans écrire en base
venv\Scripts\python.exe collect_cpi_metadata.py --no-db

# Écriture réelle en base
venv\Scripts\python.exe collect_cpi_metadata.py --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"
```

**Options utiles :**
- `--headed` : ouvre le navigateur visible (pour déboguer)
- `--dump-html` : sauvegarde le HTML brut de la page (utile si le site change et que le script rate des champs)

**Résultat attendu :** `Champs attendus : 20 | Champs trouvés : 20`

---

## 🎫 Ticket 3 — Collecte des observations (API SDMX)

**Quoi :** Récupère toutes les observations CPI (valeurs de l'indice, par pays et par catégorie) via l'API officielle du FMI, et les écrit dans `cpi.data`.

**Comment ça marche :** Le script découvre automatiquement la liste des pays et catégories valides, puis interroge l'API par lots (l'API refuse les requêtes trop larges d'un coup).

**Comment lancer :**

```powershell
cd scraping

# Collecte complète (tous pays, toutes catégories) — prend plusieurs minutes
venv\Scripts\python.exe collect_cpi_data.py --api-key "TA_CLE_API" --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"

# Test rapide sur un seul pays (quelques secondes)
venv\Scripts\python.exe collect_cpi_data.py --countries MRT --coicop _T --api-key "TA_CLE_API" --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"
```

**Où obtenir une clé API :** créer un compte gratuit sur [portal.api.imf.org](https://portal.api.imf.org), s'abonner à l'API SDMX 3.0.

**⚠️ Limite connue :** seules 13 colonnes sur les 92 de `cpi.data` sont remplies par ce script (celles que l'API fournit réellement). Les colonnes restantes (unité, publisher, topic...) proviennent normalement du Data Explorer du FMI, pas de l'API brute.

**Résultat attendu :** `✅ [nombre] ligne(s) insérée(s) dans cpi.data.` suivi de `statut=SUCCESS`

---

## 🎫 Ticket 4 — Alimentation SharePoint

**Quoi :** Régénère le fichier Excel `IMF - Consumer Price Index (CPI).xlsx` utilisé par les rapports Power BI, à partir des données de la base PostgreSQL.

**Comment ça marche :** Lit `cpi.metadata` et `cpi.data` (dernier run réussi uniquement), reconstruit un fichier Excel à 3 onglets (Metadata, Fields, Data) avec les mêmes noms de colonnes que le fichier original, et écrase le fichier existant sur SharePoint (aucun doublon créé).

**Prérequis spécifique :** avoir un compte BCM synchronisé avec SharePoint via OneDrive (le dossier apparaît alors comme un dossier local classique sur le PC).

**Comment lancer :**

```powershell
cd sharepoint

venv_ou_chemin_vers\python.exe refresh_sharepoint_cpi.py --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost" --output "C:\Users\TON_NOM\OneDrive - BCM\Monographie des visuels\Données publiques\IMF\IMF - Consumer Price Index (CPI).xlsx"
```

**⚠️ Avant de lancer :** vérifie que le fichier n'est ouvert dans Excel nulle part (ni sur ton PC, ni dans le navigateur), sinon erreur "permission refusée".

**Automatisation :** une tâche planifiée Windows (Planificateur de tâches) relance ce script tous les jours à 07h00. Voir "Alimentation SharePoint CPI" dans le Planificateur.

**Résultat attendu :** `Résumé : metadata=1 ligne(s) | data=[nombre] ligne(s) | statut=SUCCESS`

---

## 🔑 Où trouver les informations sensibles

| Info | Valeur / emplacement |
|---|---|
| Mot de passe PostgreSQL | à demander au Data Steward référent |
| Clé API FMI | à régénérer sur portal.api.imf.org si besoin |
| Compte BCM (SharePoint) | à demander au responsable Data Governance |

⚠️ Ne jamais committer de mot de passe ou de clé API en clair dans ce dépôt Git.

---

## 🩺 Problèmes fréquents

| Symptôme | Cause probable | Solution |
|---|---|---|
| Erreur SSL / `ConnectionResetError` avec l'API du FMI | Proxy d'inspection du réseau BCM | Installer `pip-system-certs` (voir Prérequis) |
| `permission denied` en écrivant le fichier Excel | Fichier ouvert ailleurs | Fermer le fichier partout avant de relancer |
| `psql` non reconnu dans PowerShell | Pas dans le PATH Windows | Utiliser pgAdmin à la place |
| Erreur de colonne SQL (`la colonne "X" n'existe pas`) | Base pas à jour avec le dernier schéma | Relancer `create_schema_imf_cpi_001.sql` |
| Champs manquants lors du scraping metadata | Le site du FMI a changé sa structure | Relancer avec `--dump-html` et examiner le HTML généré |

---

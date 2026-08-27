# BCM — Pipeline de données IMF CPI

Pipeline automatisé de collecte et de mise à disposition du dataset **CPI (Consumer Price Index)** du FMI, pour la Direction de la Gouvernance des Données de la BCM.

Ce projet couvre 4 tickets Jira, résumés ci-dessous. Chaque section explique **quoi**, **pourquoi**, et surtout **comment lancer**.

---

## 📁 Structure du projet

```
bcm-fmi-cpi/
├── sql/
│   ├── create_schema_imf_cpi_001.sql          → Ticket 1 : création de la base (schéma final)
│   ├── 002_corrections_feedback_240826.sql    → Migration à jouer sur une base existante
│   └── README_schema_imf_cpi.md               → Documentation détaillée du schéma
├── webscraping/
│   ├── collect_imf_cpi_metadata_001.py        → Ticket 2 : collecte des métadonnées
│   ├── LANCEMENT_collect_imf_cpi_metadata_001.md
│   ├── venv/                                   → Environnement Python (à créer, voir plus bas)
│   └── output/                                 → Fichiers générés localement (JSON, Excel horodatés)
├── api/
│   ├── collect_imf_cpi_data_001.py            → Ticket 3 : collecte des observations
│   ├── LANCEMENT_collect_imf_cpi_data_001.md
│   ├── COLONNES_COMMUNES_data_explorer_vs_api.md
│   └── output/
└── sharepoint/
    ├── refresh_imf_cpi_001.py                 → Ticket 4 : alimentation SharePoint
    ├── LANCEMENT_refresh_imf_cpi_001.md
    ├── run_refresh.bat                         → Utilisé par la tâche planifiée (voir Ticket 4)
    ├── task_log.txt                            → Log généré par run_refresh.bat à chaque exécution
    └── output/                                 → Copie locale (hors OneDrive) avant transfert
```

---

## ⚙️ Prérequis (à faire une seule fois)

1. **PostgreSQL** installé, avec un accès admin (utilisateur `postgres`)
2. **Python 3.11+** installé
3. **pgAdmin** (recommandé, pour visualiser la base)
4. Créer l'environnement virtuel Python et installer les dépendances (un seul venv suffit, partagé par les 3 scripts — voir note plus bas) :

```powershell
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

**Comment lancer (nouvelle base) :**

```powershell
psql -U postgres -h localhost -c "CREATE DATABASE imf;"
psql -U postgres -h localhost -d imf -f sql/create_schema_imf_cpi_001.sql
```

**Sur une base existante déjà créée avec une version antérieure du schéma**, jouer plutôt la migration :

```powershell
psql -U postgres -h localhost -d imf -f sql/002_corrections_feedback_240826.sql
```

*(Si `psql` n'est pas reconnu, ouvre pgAdmin, connecte-toi à la base `imf`, colle le contenu du fichier `.sql` dans le Query Tool, et exécute avec F5.)*

📄 Détails complets des colonnes, contraintes, choix techniques, champs obligatoires : voir `sql/README_schema_imf_cpi.md`

---

## 🎫 Ticket 2 — Collecte Metadata (Web Scraping)

**Quoi :** Récupère les 20 champs métier du dataset CPI (nom, description, fréquence, citations...) depuis le site du FMI, et les écrit dans `cpi.metadata`.

**Comment lancer :**

```powershell
cd webscraping

# Test sans écrire en base
venv\Scripts\python.exe collect_imf_cpi_metadata_001.py --no-db

# Écriture réelle en base
venv\Scripts\python.exe collect_imf_cpi_metadata_001.py --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"
```

**Résultat attendu :** `Champs métier attendus : 20 | Champs métier trouvés : 20`, puis `Résumé : id=[X] (cpi.logs) | 20/20 champ(s) métier collecté(s) | status=SUCCESS`

**Comportement important :** si une dérive de structure du site est détectée (moins de 20 champs trouvés), le script **bloque l'insertion en base** (`sys.exit(1)`) plutôt que d'écrire des données incomplètes — un log `FAILED` est quand même enregistré dans `cpi.logs` pour traçabilité.

**Fichiers générés :** `output/imf_cpi_metadata_YYYYMMDDTHHMMSS.json` et `.xlsx` (un nouveau fichier horodaté à chaque exécution — pas de suppression automatique des anciens).

📄 Détails et requêtes de vérification pgAdmin : voir `webscraping/LANCEMENT_collect_imf_cpi_metadata_001.md`

---

## 🎫 Ticket 3 — Collecte des observations (API SDMX)

**Quoi :** Récupère toutes les observations CPI via l'API officielle du FMI, et les écrit dans `cpi.data`.

**Comment lancer :**

```powershell
cd api

# Collecte complète (tous pays, toutes catégories) — plusieurs minutes
venv_ou_chemin_vers\python.exe collect_imf_cpi_data_001.py --api-key "TA_CLE_API" --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"

# Test rapide sur un seul pays (quelques secondes)
venv_ou_chemin_vers\python.exe collect_imf_cpi_data_001.py --countries MRT --coicop _T --api-key "TA_CLE_API" --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost"
```

**Où obtenir une clé API :** compte gratuit sur [portal.api.imf.org](https://portal.api.imf.org), abonnement à l'API SDMX 3.0.

**⚠️ Limite connue :** seules 13 colonnes sur les 92 de `cpi.data` sont remplies (celles que l'API fournit réellement). Comparaison complète avec le Data Explorer (8 colonnes communes sur 88 dans le fichier de référence) : voir `api/COLONNES_COMMUNES_data_explorer_vs_api.md`.

**Résultat attendu :** `✅ [nombre] ligne(s) insérée(s) dans cpi.data.` puis `Résumé : id=[X] (cpi.logs) | [nombre] observation(s) traitée(s) | status=SUCCESS`

📄 Détails et requêtes de vérification pgAdmin : voir `api/LANCEMENT_collect_imf_cpi_data_001.md`

---

## 🎫 Ticket 4 — Alimentation SharePoint

**Quoi :** Régénère le fichier Excel `IMF - Consumer Price Index (CPI).xlsx` utilisé par les rapports Power BI, à partir de `cpi.metadata` et `cpi.data` (dernier run réussi uniquement).

**Comment ça marche :**
1. Génère le fichier **localement d'abord**, dans `sharepoint/output/` (hors dossier synchronisé OneDrive) — évite tout conflit d'écriture pendant la génération
2. Remplace ensuite le fichier de destination de façon **atomique** (`os.replace`, via un fichier `.tmp` intermédiaire)
3. **Vérifie par hash SHA-256 + taille** que le remplacement a bien tenu, avec plusieurs tentatives si besoin

**Comment lancer (test manuel) :**

```powershell
cd sharepoint
venv_ou_chemin_vers\python.exe refresh_imf_cpi_001.py --dsn "dbname=imf user=postgres password=TON_MOT_DE_PASSE host=localhost" --output "C:\Users\TON_NOM\OneDrive - BCM\Monographie des visuels\Données publiques\IMF\IMF - Consumer Price Index (CPI).xlsx"
```

**⚠️ Avant de lancer :** vérifie que le fichier n'est ouvert dans Excel nulle part (ni sur ton PC, ni dans le navigateur), sinon `PermissionError`.

**Résultat attendu :** `✅ Vérification réussie (hash + taille) après [X]s`, puis `Résumé : metadata=1 ligne(s) | data=[nombre] ligne(s) | statut=SUCCESS`

**Automatisation :** tâche planifiée Windows **"Alimentation SharePoint CPI"**, **mensuelle, le 15 à 05h00** (pas quotidienne). Options de sécurité : **"N'exécuter que si un utilisateur a ouvert une session"** (obligatoire, voir piège ci-dessous). Action : pointe vers `sharepoint/run_refresh.bat` (pas directement vers `python.exe` — voir pourquoi ci-dessous).

Pour tester la tâche immédiatement sans changer sa planification :

```powershell
Start-ScheduledTask -TaskName "Alimentation SharePoint CPI"
```

Puis vérifier, **de préférence directement sur le portail SharePoint dans le navigateur** (l'Explorateur Windows et son cache peuvent afficher une information périmée ou trompeuse) :

```powershell
Get-FileHash "C:\...\IMF - Consumer Price Index (CPI).xlsx" -Algorithm SHA256
Get-Item "C:\...\IMF - Consumer Price Index (CPI).xlsx" | Select-Object LastWriteTime, Length
```

📄 Détails et requêtes de vérification : voir `sharepoint/LANCEMENT_refresh_imf_cpi_001.md`

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
| Erreur de colonne SQL (`la colonne "X" n'existe pas`) | Base pas à jour avec le dernier schéma | Rejouer `002_corrections_feedback_240826.sql` |
| Champs manquants lors du scraping metadata | Le site du FMI a changé sa structure | Relancer avec `--dump-html` et examiner le HTML généré |
| `MemoryError` en générant le fichier Excel SharePoint | Trop de lignes (~200k+ × 88 colonnes) pour le mode openpyxl normal | Déjà corrigé dans le script (mode `write_only=True`) |
| `UnicodeEncodeError` silencieux, tâche planifiée qui échoue sans rien écrire | Emoji (⚠️) incompatible avec l'encodage par défaut en exécution non-interactive | Déjà corrigé (`sys.stdout.reconfigure(encoding="utf-8")` en tête de script) |
| Tâche planifiée : "Il semble que des arguments aient été inclus dans la zone Programme" | Chemin avec espace non protégé par des guillemets dans "Programme/script" | Toujours entourer le chemin complet de guillemets `"..."` |
| Le fichier SharePoint ne se met jamais à jour malgré `statut=SUCCESS` | **Piège le plus sournois rencontré** : le caractère accentué "é" (dans "Données publiques") mal interprété par `cmd.exe` selon l'encodage actif, créant un **second dossier mal nommé** (`Donn├®es publiques`) dans lequel le script écrivait réellement, au lieu du bon dossier synchronisé | `run_refresh.bat` commence désormais par `chcp 65001` (force l'UTF-8) — **ne jamais retirer cette ligne**. Si le problème revient, vérifier dans l'Explorateur qu'il n'existe pas un dossier « Données publiques » dupliqué avec des caractères bizarres à côté du bon |
| La tâche planifiée semble tourner indéfiniment, processus `python.exe` qui s'accumulent sans jamais se terminer | Le script tentait d'arrêter/relancer OneDrive.exe (`taskkill`) pour éviter un conflit de synchronisation, mais le Planificateur exécute la tâche dans une session "Services" séparée sans les droits nécessaires pour agir sur OneDrive — la commande restait bloquée indéfiniment | Cette logique a été retirée du script (remplacée par la vérification hash + remplacement atomique, qui n'a pas besoin de toucher à OneDrive). Si des processus `python.exe` fantômes s'accumulent, les arrêter depuis une invite **administrateur** : `taskkill /f /im python.exe` |
| "Dernier résultat d'exécution" de la tâche planifiée peu fiable ou périmé dans l'interface graphique | Affichage en cache du Planificateur de tâches | Utiliser `Get-ScheduledTaskInfo` en PowerShell à la place, ou consulter `task_log.txt` |

---

## 📌 Notes de fiabilité (Ticket 4)

Le fichier SharePoint étant partagé et synchronisé via OneDrive, plusieurs couches de vérification ont été nécessaires pour garantir une mise à jour fiable :
- Écriture d'abord dans un dossier **local non synchronisé**, puis remplacement atomique du fichier final
- Vérification par **hash SHA-256** (pas seulement la date, qui peut être trompeuse) après chaque remplacement, avec plusieurs tentatives automatiques
- **Toujours vérifier le résultat final directement sur le portail SharePoint en ligne**, jamais uniquement dans l'Explorateur Windows local
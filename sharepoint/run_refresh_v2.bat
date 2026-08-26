@echo off
chcp 65001 >nul
cd /d "C:\Users\pc\OneDrive - BCM\Bureau\Data Gouvernance\bcm-fmi-cpi\sharepoint"
"C:\Users\pc\OneDrive - BCM\Bureau\Data Gouvernance\bcm-fmi-cpi\webscraping\venv\Scripts\python.exe" refresh_imf_cpi_001.py --dsn "dbname=imf user=postgres password=46317239 host=localhost" --output "C:\Users\pc\OneDrive - BCM\Monographie des visuels\Données publiques\IMF\IMF - Consumer Price Index (CPI).xlsx" > "C:\Users\pc\OneDrive - BCM\Bureau\Data Gouvernance\bcm-fmi-cpi\sharepoint\task_log.txt" 2>&1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
pyinstaller .\CRS_FATCA_XML_Generator.spec --noconfirm
Write-Host "Executavel esperado em dist\CRS_FATCA_XML_Generator\CRS_FATCA_XML_Generator.exe"

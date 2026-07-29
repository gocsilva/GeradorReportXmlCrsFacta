@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
pyinstaller CRS_FATCA_XML_Generator.spec --noconfirm
echo.
echo Executavel esperado em dist\CRS_FATCA_XML_Generator\CRS_FATCA_XML_Generator.exe
endlocal

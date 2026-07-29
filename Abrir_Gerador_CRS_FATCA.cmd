@echo off
setlocal
cd /d "%~dp0"
if not defined LOCALAPPDATA (
  set "CIINTEGRACAO_DATA_DIR=%TEMP%\CRS_FATCA_XML_Generator"
) else (
  set "CIINTEGRACAO_DATA_DIR=%LOCALAPPDATA%\CRS_FATCA_XML_Generator"
)
if exist "CRS_FATCA_XML_Generator.exe" (
  start "" /D "%~dp0" "%~dp0CRS_FATCA_XML_Generator.exe"
) else if exist "dist\CRS_FATCA_XML_Generator\CRS_FATCA_XML_Generator.exe" (
  start "" /D "%~dp0dist\CRS_FATCA_XML_Generator" "%~dp0dist\CRS_FATCA_XML_Generator\CRS_FATCA_XML_Generator.exe"
) else (
  echo Nao foi encontrado CRS_FATCA_XML_Generator.exe nesta pasta.
  echo Copie a pasta inteira do pacote, mantendo o .cmd, o .exe e a pasta _internal juntos.
  pause
)
endlocal

# Como baixar pelo GitHub

## Opcao recomendada

1. Abra a pagina do repositorio no GitHub.
2. Clique em **Releases**.
3. Baixe o arquivo `CRS_FATCA_XML_Generator_Portable_ZeroConfig_20260729_190459.zip`.
4. Extraia o ZIP no computador.
5. Abra a pasta extraida e execute `Abrir_Gerador_CRS_FATCA.cmd`.

O pacote nao precisa de permissao de administrador. Depois de abrir, selecione o Excel e clique em **Executar agora**.

## Pelo codigo fonte

Para executar ou reconstruir a partir do codigo:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH="src"
python -m crs_fatca_generator.app
```

Para gerar o executavel portatil:

```powershell
.\build_exe.ps1
```

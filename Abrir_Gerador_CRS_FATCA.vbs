Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
exe1 = fso.BuildPath(base, "CRS_FATCA_XML_Generator.exe")
exe2 = fso.BuildPath(base, "dist\CRS_FATCA_XML_Generator\CRS_FATCA_XML_Generator.exe")
Set env = shell.Environment("PROCESS")
If env("LOCALAPPDATA") <> "" Then
  env("CIINTEGRACAO_DATA_DIR") = fso.BuildPath(env("LOCALAPPDATA"), "CRS_FATCA_XML_Generator")
Else
  env("CIINTEGRACAO_DATA_DIR") = fso.BuildPath(env("TEMP"), "CRS_FATCA_XML_Generator")
End If
If fso.FileExists(exe1) Then
  shell.Run """" & exe1 & """", 1, False
ElseIf fso.FileExists(exe2) Then
  shell.Run """" & exe2 & """", 1, False
Else
  MsgBox "Nao foi encontrado CRS_FATCA_XML_Generator.exe nesta pasta. Copie a pasta inteira do pacote, mantendo o .cmd, o .exe e a pasta _internal juntos.", 48, "CRS/FATCA XML Generator"
End If

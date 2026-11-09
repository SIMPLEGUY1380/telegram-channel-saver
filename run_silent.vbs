Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
WshShell.Run "cmd.exe /c """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\run_auto.bat""", 0, False

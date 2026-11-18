' Starts Gipsy Hub with no window. Put a shortcut to this file in
' shell:startup to run the hub automatically when you log in.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\gipsy_hub.py""", 0, False

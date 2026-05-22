' 双击启动翻译助手 — WScript.Shell.Run 创建的进程完全独立，
' 不属于任何控制台进程组，关闭任何终端窗口都不会被牵连。
Option Explicit
Dim sh, scriptDir
Set sh = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
' 第二个参数 0 = 隐藏窗口（pythonw 本来也没控制台，双保险）
' 第三个参数 False = 不等待子进程结束
sh.Run "pythonw.exe """ & scriptDir & "\main.py""", 0, False

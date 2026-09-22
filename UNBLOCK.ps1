<#
  UNBLOCK.ps1 - clears Windows Mark-of-the-Web from this whole folder.

  Windows tags every file that arrives from the internet and refuses to run them,
  which produces "These files can't be opened - your Internet security settings
  prevented one or more files from being opened."

  Run this once with:
      powershell -ExecutionPolicy Bypass -File .\UNBLOCK.ps1

  Then START.bat will work normally.
#>
Set-Location -Path $PSScriptRoot
Write-Host ""
Write-Host "  Clearing the downloaded-file flag from:"
Write-Host "    $PSScriptRoot"
Write-Host ""

$files = Get-ChildItem -Path $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue
$files | Unblock-File -ErrorAction SilentlyContinue

$still = @($files | ForEach-Object {
    Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
}).Count

Write-Host "  Processed $($files.Count) files."
if ($still -eq 0) {
    Write-Host "  Done - nothing is blocked any more." -ForegroundColor Green
    Write-Host "  You can now double-click START.bat."
} else {
    Write-Host "  $still file(s) are still flagged." -ForegroundColor Yellow
    Write-Host "  Your organisation may block .bat files by policy. Use instead:"
    Write-Host "      powershell -ExecutionPolicy Bypass -File .\START.ps1"
}
Write-Host ""
Read-Host "  Press Enter to close"

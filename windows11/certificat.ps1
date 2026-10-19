# Approuve (ou retire, avec -Retirer) le certificat qui signe le paquet du menu Windows 11.
# À lancer en administrateur via approuver-certificat.bat / retirer-certificat.bat.
#
# Le certificat est créé par installer-win11.bat sur ce PC, pour la signature de code
# uniquement, et sa clé privée n'est pas exportable. L'approuver = l'ajouter au magasin
# « Personnes autorisées » de l'ordinateur, seul moyen pour Windows d'accepter un paquet
# MSIX qui n'est pas signé par un éditeur reconnu.
param([switch]$Retirer)

$ErrorActionPreference = "Stop"
$store = "Cert:\LocalMachine\TrustedPeople"
$subject = "CN=QuickConvert"

function Confirm-Choice([string]$question) {
    return (Read-Host "$question (o/n)") -match '^[oOyY]'
}

if ($Retirer) {
    $certs = @(Get-ChildItem $store | Where-Object { $_.Subject -eq $subject -and $_.Issuer -eq $subject })
    if ($certs.Count -eq 0) {
        Write-Host "Aucun certificat QuickConvert approuvé sur cet ordinateur."
        exit 0
    }
    $certs | Format-List Subject, Thumbprint, NotAfter
    if (-not (Confirm-Choice "Retirer l'approbation de ce certificat ?")) { exit 1 }
    $certs | Remove-Item
    Write-Host "Certificat retiré des Personnes autorisées."
    exit 0
}

$cer = Join-Path $PSScriptRoot "bin\QuickConvert.cer"
if (-not (Test-Path $cer)) {
    Write-Host "Introuvable : $cer"
    Write-Host "Lancer d'abord installer-win11.bat (il crée le certificat)."
    exit 1
}
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $cer
if ($cert.Subject -ne $subject) {
    Write-Host "Certificat inattendu ($($cert.Subject)) : abandon."
    exit 1
}
Write-Host "Certificat créé par installer-win11.bat pour signer le menu Windows 11 de QuickConvert :"
$cert | Format-List Subject, Thumbprint, NotAfter
Write-Host "Il va être ajouté aux « Personnes autorisées » de l'ordinateur ($store)."
if (-not (Confirm-Choice "Continuer ?")) { exit 1 }
Import-Certificate -FilePath $cer -CertStoreLocation $store | Out-Null
Write-Host ""
Write-Host "Certificat approuvé. Relancer maintenant installer-win11.bat (sans droits administrateur)."

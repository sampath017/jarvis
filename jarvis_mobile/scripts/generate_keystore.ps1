# Generate Upload Keystore for Jarvis
# This script will generate a new keystore file in the android/app directory.
# WARNING: Keep this file safe and do not lose the passwords!

$keystorePath = "android/app/upload-keystore.jks"
$password = "jarvis123" # Default password for demonstration, USER SHOULD CHANGE THIS

if (Test-Path $keystorePath) {
    Write-Host "Keystore already exists at $keystorePath" -ForegroundColor Yellow
    exit
}

Write-Host "Generating keystore at $keystorePath..." -ForegroundColor Cyan

keytool -genkey -v -keystore $keystorePath `
        -storetype JKS -keyalg RSA -keysize 2048 -validity 10000 `
        -alias upload `
        -storepass $password -keypass $password `
        -dname "CN=Sampath, OU=Development, O=Jarvis, L=Bangalore, S=Karnataka, C=IN"

Write-Host "Keystore generated successfully!" -ForegroundColor Green
Write-Host "Password: $password" -ForegroundColor Magenta

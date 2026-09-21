param(
    [string]$Python = "python",
    [string]$Entorno = (Join-Path $PSScriptRoot '.venv-distribucion'),
    [string]$Salida = (Join-Path $PSScriptRoot 'dist'),
    [string]$Certificado = "",
    [string]$ContraseñaCertificado = ""
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Este paquete debe construirse en Windows.' }
$pythonFenix = Join-Path $Entorno 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonFenix)) {
    & $Python -m venv $Entorno
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de construcción.' }
}
& $pythonFenix -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Utiliza Python 3.12 de 64 bits'"
if ($LASTEXITCODE -ne 0) { throw 'Versión de Python no compatible con esta construcción.' }
& $pythonFenix -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }

$rutaNavegadoresAnterior = $env:PLAYWRIGHT_BROWSERS_PATH
$bytecodeAnterior = $env:PYTHONDONTWRITEBYTECODE
$datosAnteriores = $env:FENIX_DATA_DIR
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = '0'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $pythonFenix -m playwright install --only-shell chromium
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar Chromium.' }
    $carpetaPlaywrightFenix = & $pythonFenix -c "import pathlib,playwright; print(pathlib.Path(playwright.__file__).parent / 'driver' / 'package' / '.local-browsers')"
    $carpetaPlaywrightFenix = (Resolve-Path -LiteralPath $carpetaPlaywrightFenix).Path
    $raizEntornoFenix = (Resolve-Path -LiteralPath $Entorno).Path
    if (-not $carpetaPlaywrightFenix.StartsWith($raizEntornoFenix + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'La carpeta de navegadores no pertenece al entorno de construcción.'
    }
    # Playwright considera instalada una carpeta aunque una ejecución anterior
    # haya dejado Chromium incompleto. Verificar el ejecutable real y reparar
    # esa instalación antes de pasársela a PyInstaller.
    $shellChromium = Get-ChildItem -LiteralPath $carpetaPlaywrightFenix -Recurse -File -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue
    if (-not $shellChromium) {
        Get-ChildItem -LiteralPath $carpetaPlaywrightFenix -Directory -Filter 'chromium_headless_shell-*' |
            Remove-Item -Recurse -Force
        & $pythonFenix -m playwright install --only-shell chromium
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo reparar Chromium Headless Shell.' }
        $shellChromium = Get-ChildItem -LiteralPath $carpetaPlaywrightFenix -Recurse -File -Filter 'chrome-headless-shell.exe' -ErrorAction SilentlyContinue
        if (-not $shellChromium) { throw 'Chromium Headless Shell quedó incompleto después de reinstalarlo.' }
    }
    # Una ejecución anterior puede haber descargado Chrome completo. Fénix
    # trabaja siempre en modo headless y solo necesita la variante Shell.
    Get-ChildItem -LiteralPath $carpetaPlaywrightFenix -Directory -Filter 'chromium-*' |
        Remove-Item -Recurse -Force
    & $pythonFenix -m PyInstaller --clean --noconfirm --distpath $Salida --workpath (Join-Path $Entorno 'build') (Join-Path $PSScriptRoot 'Fenix.spec')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir Fenix.exe.' }
    $carpetaFenix = Join-Path $Salida 'Fenix'
    $env:FENIX_DATA_DIR = Join-Path $Entorno ('diagnostico-' + [guid]::NewGuid().ToString('N'))
    $diagnosticoFenix = Start-Process -FilePath (Join-Path $carpetaFenix 'Fenix.exe') -ArgumentList '--diagnostico' -WindowStyle Hidden -PassThru
    if (-not $diagnosticoFenix.WaitForExit(60000)) {
        $diagnosticoFenix.Kill()
        throw 'El diagnóstico del ejecutable no terminó dentro de un minuto.'
    }
    if ($diagnosticoFenix.ExitCode -ne 0) {
        throw "El ejecutable no pasó el diagnóstico. Revisa $env:FENIX_DATA_DIR\logs antes de distribuirlo."
    }
    # La firma Authenticode es la medida que más reduce los falsos positivos
    # del antivirus. Es opcional para desarrollo, pero se aplica antes de
    # comprimir cuando se proporciona un certificado real de la organización.
    if ($Certificado) {
        $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if (-not $signtool) { throw 'Se indicó un certificado, pero no se encontró signtool.exe.' }
        $argumentosFirma = @('sign', '/fd', 'SHA256', '/td', 'SHA256', '/tr', 'http://timestamp.digicert.com')
        if ($ContraseñaCertificado) { $argumentosFirma += @('/f', $Certificado, '/p', $ContraseñaCertificado) }
        else { $argumentosFirma += @('/f', $Certificado) }
        $argumentosFirma += (Join-Path $carpetaFenix 'Fenix.exe')
        & $signtool.Source @argumentosFirma
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo firmar Fenix.exe.' }
        Write-Host 'Fenix.exe firmado con Authenticode (SHA-256).'
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LEEME_BETA.txt') -Destination $carpetaFenix
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination $carpetaFenix
    Push-Location $PSScriptRoot
    try { $versionFenix = & $pythonFenix -c "from configuracion import VERSION; print(VERSION)" }
    finally { Pop-Location }
    $zipFenix = Join-Path $Salida "Fenix-$versionFenix-windows-x64.zip"
    Compress-Archive -LiteralPath $carpetaFenix -DestinationPath $zipFenix -Force
    Get-FileHash -LiteralPath $zipFenix -Algorithm SHA256
    Write-Host "Beta generada: $zipFenix"
} finally {
    $env:PLAYWRIGHT_BROWSERS_PATH = $rutaNavegadoresAnterior
    $env:PYTHONDONTWRITEBYTECODE = $bytecodeAnterior
    $env:FENIX_DATA_DIR = $datosAnteriores
}

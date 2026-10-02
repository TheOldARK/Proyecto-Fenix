param(
    [string]$Python = "python",
    [string]$Entorno = (Join-Path $PSScriptRoot '..\.venv-distribucion'),
    [string]$Salida = (Join-Path $PSScriptRoot '..\dist\store')
)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($env:OS -ne 'Windows_NT') { throw 'El paquete MSIX debe construirse en Windows.' }
if (Test-Path -LiteralPath $Salida) {
    if (Get-ChildItem -LiteralPath $Salida -Force | Select-Object -First 1) {
        throw "La carpeta de salida no está vacía: $Salida. Elige otra con -Salida."
    }
} else {
    New-Item -ItemType Directory -Path $Salida -Force | Out-Null
}
$salidaAbsoluta = [System.IO.Path]::GetFullPath($Salida)
if (-not $salidaAbsoluta.StartsWith($raiz + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'La salida MSIX debe permanecer dentro del repositorio.'
}

# Reutiliza el proceso probado para generar el cliente Windows completo.
$compilador = Join-Path $raiz 'construir_windows.ps1'
& $compilador -Python $Python -Entorno $Entorno -Salida (Join-Path $raiz 'dist\store-cliente')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir el cliente Windows.' }

$pythonFenix = Join-Path $Entorno 'Scripts\python.exe'
$versionFenix = (& $pythonFenix -c "from configuracion import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or $versionFenix -notmatch '^\d+\.\d+\.\d+$') {
    throw "Versión de Fénix no compatible con MSIX: $versionFenix"
}
$versionPaquete = "$versionFenix.0"
$distFenix = Join-Path $raiz 'dist\store-cliente\Fenix'
if (-not (Test-Path -LiteralPath (Join-Path $distFenix 'Fenix.exe'))) {
    throw 'La compilación no dejó Fenix.exe en el directorio esperado.'
}

$kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
$makeappx = Get-ChildItem -LiteralPath $kits -Filter MakeAppx.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\MakeAppx\.exe$' } |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'No se encontró MakeAppx.exe del Windows SDK.' }

$stageRaiz = Join-Path $raiz 'build\msix-store'
New-Item -ItemType Directory -Path $stageRaiz -Force | Out-Null
$stage = Join-Path $stageRaiz ([guid]::NewGuid().ToString('N'))
$paquete = Join-Path $stage 'Package'
$assets = Join-Path $paquete 'Assets'
New-Item -ItemType Directory -Path $assets -Force | Out-Null
Copy-Item -LiteralPath $distFenix -Destination (Join-Path $paquete 'Fenix') -Recurse

# No distribuimos el actualizador de descarga dentro de la edición Store.
$app = Join-Path $paquete 'Fenix'
$updater = Join-Path $app 'updater'
if (Test-Path -LiteralPath $updater) {
    $updaterReal = (Resolve-Path -LiteralPath $updater).Path
    $appReal = (Resolve-Path -LiteralPath $app).Path
    if (-not $updaterReal.StartsWith($appReal + [System.IO.Path]::DirectorySeparatorChar,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'La carpeta del actualizador quedó fuera del paquete.'
    }
    Remove-Item -LiteralPath $updaterReal -Recurse -Force
}
Set-Content -LiteralPath (Join-Path $app 'fenix-store-package.marker') -Value 'Microsoft Store edition' -Encoding ascii

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'AppxManifest.xml') -Raw
$manifest = $manifest.Replace('__VERSION__', $versionPaquete)
Set-Content -LiteralPath (Join-Path $paquete 'AppxManifest.xml') -Value $manifest -Encoding utf8

Add-Type -AssemblyName System.Drawing
$origen = [System.Drawing.Bitmap]::new((Join-Path $raiz 'recursos\logo.png'))
try {
    foreach ($asset in @(@{Name='StoreLogo.png'; Width=50; Height=50},
                         @{Name='Square44x44Logo.png'; Width=44; Height=44},
                         @{Name='Square150x150Logo.png'; Width=150; Height=150})) {
        $bitmap = [System.Drawing.Bitmap]::new($asset.Width, $asset.Height,
            [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        try {
            $grafico = [System.Drawing.Graphics]::FromImage($bitmap)
            try {
                $grafico.Clear([System.Drawing.Color]::FromArgb(24, 24, 24))
                $grafico.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $grafico.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $margen = [Math]::Max(2, [int]($asset.Width * 0.08))
                $lienzo = [System.Drawing.Rectangle]::new($margen, $margen,
                    $asset.Width - 2 * $margen, $asset.Height - 2 * $margen)
                $grafico.DrawImage($origen, $lienzo)
            } finally { $grafico.Dispose() }
            $bitmap.Save((Join-Path $assets $asset.Name), [System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $bitmap.Dispose() }
    }
} finally { $origen.Dispose() }

$msix = Join-Path $salidaAbsoluta "Fenix-$versionFenix-windows-x64-store.msix"
if (Test-Path -LiteralPath $msix) { throw "El paquete ya existe y no se sobrescribirá: $msix" }
& $makeappx.FullName pack /d $paquete /p $msix /h SHA256
if ($LASTEXITCODE -ne 0) { throw 'MakeAppx no pudo crear el paquete Store.' }

# Comprueba que el paquete se puede abrir y contiene identidad, ejecutable y recursos.
$verificacion = Join-Path $stage 'verificacion'
& $makeappx.FullName unpack /p $msix /d $verificacion
if ($LASTEXITCODE -ne 0) { throw 'No se pudo volver a abrir el paquete MSIX generado.' }
$manifestExtraido = Get-Content -LiteralPath (Join-Path $verificacion 'AppxManifest.xml') -Raw
if ($manifestExtraido -notmatch 'FenixUN-Horario\.FenixHorarios' -or
    $manifestExtraido -notmatch [regex]::Escape($versionPaquete) -or
    $manifestExtraido -notmatch '<DisplayName>Fenix Horarios</DisplayName>' -or
    $manifestExtraido -notmatch 'VisualElements DisplayName="Fenix Horarios"' -or
    -not (Test-Path -LiteralPath (Join-Path $verificacion 'Fenix\Fenix.exe')) -or
    -not (Test-Path -LiteralPath (Join-Path $verificacion 'Fenix\fenix-store-package.marker'))) {
    throw 'El MSIX no contiene la identidad, versión o ejecutable esperado.'
}
Get-FileHash -LiteralPath $msix -Algorithm SHA256
Write-Host "MSIX listo para Partner Center: $msix"

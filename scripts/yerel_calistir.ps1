#Requires -Version 5.1
<#
.SYNOPSIS
    IptalBey yerel fiyat kontrolu (KR-014): Netflix / YouTube gibi Turkiye IP'si
    gerektiren sayfalari bu bilgisayardan kontrol eder.

.DESCRIPTION
    Gorev Zamanlayici her gun calistirir (bkz. yerel_kurulum.ps1 -Kaydet).
    1. Ayri klonda (varsayilan %USERPROFILE%\IptalBey\veri-yerel) main'e gecer ve gunceller.
       Calisma deposunu klon olarak VERMEYIN: `git checkout -f main` commit edilmemis degisiklikleri siler.
    2. requirements.txt degistiyse pip install yapar; klonun .venv'indeki Python ile
       `scripts/fiyat_kontrol.py --yerel` calistirir.
    3. Tum ciktiyi %USERPROFILE%\IptalBey\loglar\YYYY-MM-DD.log dosyasina yazar; 30 gunden
       eski loglari siler. GEMINI_API_KEY degeri loga asla yazilmaz (gecerse *** ile maskelenir).
    Pencere acmaz: komutlar CreateNoWindow ile calistirilir; gorev conhost --headless ile baslatilir.

    Cikis kodlari: 0 tamam, 1 fiyat kontrolunde basarisiz islem, 2 GEMINI_API_KEY yok,
    3 klon yok, 4 git guncellemesi basarisiz, 5 Python ortami yok, 9 beklenmeyen hata.
#>
[CmdletBinding()]
param(
    [string]$KlonYolu = (Join-Path $env:USERPROFILE 'IptalBey\veri-yerel'),
    [string]$LogKlasoru = (Join-Path $env:USERPROFILE 'IptalBey\loglar'),
    [int]$LogGun = 30
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $LogKlasoru | Out-Null
$script:LogDosyasi = Join-Path $LogKlasoru ((Get-Date -Format 'yyyy-MM-dd') + '.log')

# setx ile tanimlanan anahtar, gorev servisinin eski ortam kopyasinda olmayabilir: kullanici kaydindan oku.
if (-not $env:GEMINI_API_KEY) {
    $kullaniciAnahtari = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
    if ($kullaniciAnahtari) { $env:GEMINI_API_KEY = $kullaniciAnahtari }
}
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# Gizli gorevde git/GCM kimlik sormaya kalkmasin (soru penceresi takilip zaman asimina dusmesin).
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'

function Write-Log {
    param([AllowEmptyString()][string]$Metin)
    if ($null -eq $Metin) { $Metin = '' }
    if ($env:GEMINI_API_KEY) { $Metin = $Metin.Replace($env:GEMINI_API_KEY, '***') }
    Add-Content -Path $script:LogDosyasi -Value $Metin -Encoding UTF8
}

function ConvertTo-Argument {
    param([string]$Deger)
    if ($Deger -eq '') { return '""' }
    if ($Deger -notmatch '[\s"]') { return $Deger }
    return '"' + ($Deger -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Invoke-Komut {
    <# Komutu pencere acmadan calistirir, stdout+stderr'i loga yazar, cikis kodunu dondurur. #>
    param([string]$Dosya, [string[]]$Argumanlar, [string]$Klasor)
    Write-Log ("> " + $Dosya + " " + ($Argumanlar -join ' '))
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Dosya
    $psi.Arguments = (($Argumanlar | ForEach-Object { ConvertTo-Argument $_ }) -join ' ')
    $psi.WorkingDirectory = $Klasor
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $islem = [System.Diagnostics.Process]::Start($psi)
    $cikti = $islem.StandardOutput.ReadToEndAsync()
    $hata = $islem.StandardError.ReadToEndAsync()
    $islem.WaitForExit()
    if ($cikti.Result) { Write-Log $cikti.Result.TrimEnd() }
    if ($hata.Result) { Write-Log $hata.Result.TrimEnd() }
    return $islem.ExitCode
}

function Start-ActionsKontrol {
    <# GitHub Actions zamanlamasi (cron) 2026-11-16/17 hic calismadi (KR-023).
       Bugun Actions'ta fiyat kontrolu yoksa bu bilgisayardan tetiklenir.
       Ayni gun ikinci kosu sayaclari artirmaz; hata durumunda yerel kosu etkilenmez. #>
    param([string]$Klasor)
    try {
        $gh = Get-Command gh -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Source
        $bugun = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
        Push-Location $Klasor
        try {
            $tarihler = & $gh run list --workflow fiyat-kontrol.yml --limit 10 --json createdAt --jq '.[].createdAt' 2>$null
        }
        finally { Pop-Location }
        if (@($tarihler | Where-Object { $_ -like "$bugun*" }).Count -gt 0) {
            Write-Log 'Actions fiyat kontrolu bugun zaten calismis; tetiklenmedi.'
            return
        }
        $ghKod = Invoke-Komut $gh @('workflow', 'run', 'fiyat-kontrol.yml') $Klasor
        if ($ghKod -ne 0) { Write-Log "UYARI: Actions tetiklenemedi (gh cikis kodu $ghKod)." }
        else { Write-Log 'Actions fiyat kontrolu tetiklendi.' }
    }
    catch { Write-Log ('UYARI: Actions tetikleme atlandi: ' + $_.Exception.Message) }
}

$kod = 9
try {
    Write-Log ("=== IptalBey yerel fiyat kontrolu basladi: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + " ===")
    if (-not (Test-Path (Join-Path $KlonYolu '.git'))) {
        Write-Log "HATA: klon bulunamadi: $KlonYolu (once yerel_kurulum.ps1 calistirin)"
        $kod = 3
    }
    elseif (-not (Test-Path (Join-Path $KlonYolu '.git\iptalbey-yerel-klon'))) {
        Write-Log "HATA: $KlonYolu yerel_kurulum.ps1'in actigi ayri klon degil (isaret yok); calisma deposuna dokunulmaz."
        $kod = 3
    }
    else {
        # Onceki kosu yarida kaldiysa (rebase / fiyat dali) temizle; commit'ler korunur.
        $gitKlasoru = Join-Path $KlonYolu '.git'
        if ((Test-Path (Join-Path $gitKlasoru 'rebase-merge')) -or (Test-Path (Join-Path $gitKlasoru 'rebase-apply'))) {
            Invoke-Komut 'git' @('rebase', '--abort') $KlonYolu | Out-Null
        }
        $gitKod = Invoke-Komut 'git' @('checkout', '-f', 'main') $KlonYolu
        if ($gitKod -eq 0) { $gitKod = Invoke-Komut 'git' @('pull', '--rebase', 'origin', 'main') $KlonYolu }
        if ($gitKod -ne 0) {
            Write-Log "HATA: klon guncellenemedi (git cikis kodu $gitKod)"
            $kod = 4
        }
        else {
            $python = Join-Path $KlonYolu '.venv\Scripts\python.exe'
            if (-not (Test-Path $python)) {
                Write-Log "HATA: Python ortami yok: $python (yerel_kurulum.ps1 calistirin)"
                $kod = 5
            }
            else {
                # requirements.txt degistiyse bagimliliklari yenile (karma .venv icinde tutulur).
                $gereksinim = Join-Path $KlonYolu 'requirements.txt'
                $karmaDosyasi = Join-Path $KlonYolu '.venv\requirements.sha256'
                $yeniKarma = (Get-FileHash $gereksinim -Algorithm SHA256).Hash
                $eskiKarma = ''
                if (Test-Path $karmaDosyasi) { $eskiKarma = (Get-Content $karmaDosyasi -Raw).Trim() }
                $pipKod = 0
                if ($yeniKarma -ne $eskiKarma) {
                    Write-Log 'requirements.txt degisti; pip install calistiriliyor.'
                    $pipKod = Invoke-Komut $python @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', 'requirements.txt') $KlonYolu
                    if ($pipKod -eq 0) { Set-Content -Path $karmaDosyasi -Value $yeniKarma -Encoding ASCII }
                    else { Write-Log "UYARI: pip install basarisiz (cikis kodu $pipKod); mevcut ortamla devam ediliyor." }
                }
                $kod = Invoke-Komut $python @('scripts/fiyat_kontrol.py', '--yerel') $KlonYolu
                if ($kod -eq 2) { Write-Log 'HATA: GEMINI_API_KEY tanimli degil; kontrol yapilmadi.' }
                Start-ActionsKontrol $KlonYolu
            }
        }
    }
}
catch {
    Write-Log ("HATA (beklenmeyen): " + $_.Exception.Message)
    $kod = 9
}
finally {
    Write-Log ("=== bitti, cikis kodu ${kod}: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + " ===")
    try {
        $sinir = (Get-Date).AddDays(-$LogGun)
        Get-ChildItem -Path $LogKlasoru -Filter '*.log' -File |
            Where-Object { $_.LastWriteTime -lt $sinir } |
            Remove-Item -Force
    }
    catch { }
}
exit $kod

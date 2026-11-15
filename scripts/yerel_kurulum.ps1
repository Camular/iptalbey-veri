#Requires -Version 5.1
<#
.SYNOPSIS
    IptalBey yerel fiyat kontrolu kurulumu (KR-014; Windows PowerShell 5.1).

.DESCRIPTION
    Kurulum (her calistirmada guvenle tekrarlanabilir):
      - Ayri klon: %LOCALAPPDATA%\IptalBey\veri-yerel (yoksa git clone; varsa dokunulmaz).
      - Klonun git kimligi parametreden (-GitName, -GitEmail) klonun yerel ayarina yazilir.
      - Klonda .venv (python -m venv) ve `pip install -r requirements.txt`.
      - gh girisi ve GEMINI_API_KEY (kullanici ortam degiskeni) kontrol edilir; yoksa uyarilir.
    -Kaydet : ayrica Gorev Zamanlayici gorevini kaydeder (her gun 10:00, kacirilirsa ilk firsatta,
              yalniz kullanici oturumu acikken, yukseltilmemis, pilde de, ag varsa, 15 dk sinir).
    -Kaldir : gorevi siler (klon ve loglar kalir).

    UYARI: -KlonYolu yalnizca bu ise ayrilmis bir klon olmalidir. Calistiginiz depoyu (ornegin
    yoneticinin veri\ klasoru) VERMEYIN: gunluk kosu orada `git checkout -f main` ve
    `git pull --rebase` yapar, commit edilmemis degisiklikler kaybolur. Betik klonu acarken
    .git\iptalbey-yerel-klon isaretini yazar; bu isareti olmayan mevcut bir depoyu (kurulum da,
    gunluk kosu da) reddeder.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\yerel_kurulum.ps1 -GitName Camular -GitEmail 123+Camular@users.noreply.github.com -Kaydet

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\yerel_kurulum.ps1 -Kaldir
#>
[CmdletBinding(DefaultParameterSetName = 'Kur')]
param(
    [Parameter(ParameterSetName = 'Kur')][string]$GitName,
    [Parameter(ParameterSetName = 'Kur')][string]$GitEmail,
    [Parameter(ParameterSetName = 'Kur')][switch]$Kaydet,
    [Parameter(ParameterSetName = 'Kaldir', Mandatory = $true)][switch]$Kaldir,
    [string]$KlonYolu = (Join-Path $env:LOCALAPPDATA 'IptalBey\veri-yerel'),
    [string]$DepoUrl = 'https://github.com/Camular/iptalbey-veri.git',
    [string]$Saat = '10:00'
)

$ErrorActionPreference = 'Stop'
$GorevAdi = 'IptalBey Fiyat Kontrol (Yerel)'

function Invoke-Git {
    param([string[]]$Argumanlar)
    & git @Argumanlar
    if ($LASTEXITCODE -ne 0) { throw ("git " + ($Argumanlar -join ' ') + " basarisiz (cikis kodu $LASTEXITCODE)") }
}

function Find-Python {
    <# Python 3.10+ yorumlayicisinin komutunu dondurur (py -3 ya da python). #>
    $adaylar = @(@('py', '-3'), @('python'))
    foreach ($aday in $adaylar) {
        $exe = $aday[0]
        $ek = @($aday | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        # PS 5.1 yerel komut argumanlarindaki cift tirnaklari bozar: tirnaksiz kod (3.12 -> 312).
        $onceki = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $surum = & $exe @ek -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>$null
        $cikis = $LASTEXITCODE
        $ErrorActionPreference = $onceki
        if ($cikis -eq 0 -and "$surum" -match '^\d+$' -and [int]"$surum" -ge 310) { return , $aday }
    }
    throw 'Python 3.10 veya ustu bulunamadi (python.org ya da winget install Python.Python.3.12).'
}

$IsaretDosyasi = 'iptalbey-yerel-klon'  # .git icinde; yalnizca bu betigin actigi klonlarda bulunur

function Assert-AyriKlon {
    <# KlonYolu'ndaki depo bu betigin actigi ayri klon olmali (calisma deposu verilirse degisiklikler kaybolur). #>
    if ((Test-Path (Join-Path $KlonYolu '.git')) -and -not (Test-Path (Join-Path $KlonYolu ".git\$IsaretDosyasi"))) {
        throw "KlonYolu ($KlonYolu) bu betigin actigi ayri klon degil (calisma deposu olabilir). Ayri ve bos bir yol verin (varsayilan: %LOCALAPPDATA%\IptalBey\veri-yerel)."
    }
}

function Install-YerelKlon {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git bulunamadi.' }
    Assert-AyriKlon
    if (Test-Path (Join-Path $KlonYolu '.git')) {
        Write-Host "Klon zaten var, dokunulmadi: $KlonYolu"
    }
    else {
        New-Item -ItemType Directory -Force -Path (Split-Path $KlonYolu -Parent) | Out-Null
        Invoke-Git @('clone', $DepoUrl, $KlonYolu)
        Set-Content -Path (Join-Path $KlonYolu ".git\$IsaretDosyasi") -Value 'IptalBey yerel fiyat kontrolu klonu (yerel_kurulum.ps1)' -Encoding ASCII
    }

    if ($GitName) { Invoke-Git @('-C', $KlonYolu, 'config', '--local', 'user.name', $GitName) }
    if ($GitEmail) { Invoke-Git @('-C', $KlonYolu, 'config', '--local', 'user.email', $GitEmail) }
    $ad = (& git -C $KlonYolu config --local --get user.name)
    $eposta = (& git -C $KlonYolu config --local --get user.email)
    if (-not $ad -or -not $eposta) {
        throw 'Klonun git kimligi yok: -GitName ve -GitEmail verin (GitHub noreply adresi).'
    }
    Write-Host "Klon git kimligi: $ad <$eposta>"

    $venvPython = Join-Path $KlonYolu '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        $py = Find-Python
        $exe = $py[0]
        $ek = @($py | Select-Object -Skip 1)
        & $exe @ek -m venv (Join-Path $KlonYolu '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'python -m venv basarisiz.' }
    }
    $gereksinim = Join-Path $KlonYolu 'requirements.txt'
    & $venvPython -m pip install --disable-pip-version-check -q -r $gereksinim
    if ($LASTEXITCODE -ne 0) { throw 'pip install basarisiz.' }
    # yerel_calistir.ps1 bu karma degisince pip install'i tekrarlar.
    Set-Content -Path (Join-Path $KlonYolu '.venv\requirements.sha256') -Value (Get-FileHash $gereksinim -Algorithm SHA256).Hash -Encoding ASCII
    Write-Host "Python ortami hazir: $venvPython"

    if (Get-Command gh -ErrorAction SilentlyContinue) {
        # PS 5.1: yerel komutun stderr'i Stop altinda hata sayilir; Continue ile calistir.
        $onceki = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & gh auth status *> $null
        $ghGiris = $LASTEXITCODE
        if ($ghGiris -eq 0) {
            # git push / fetch, gh girisini kullansin (parola sormadan).
            & gh auth setup-git *> $null
            $ghGit = $LASTEXITCODE
        }
        $ErrorActionPreference = $onceki
        if ($ghGiris -ne 0) {
            Write-Warning 'gh girisi yok: "gh auth login" ile giris yapin, sonra bu betigi yeniden calistirin (gh auth setup-git icin).'
        }
        elseif ($ghGit -ne 0) { Write-Warning 'gh auth setup-git basarisiz; git push parola isteyebilir.' }
        else { Write-Host 'gh girisi tamam; git kimlik bilgisi gh uzerinden (gh auth setup-git).' }
    }
    else {
        Write-Warning 'gh (GitHub CLI) bulunamadi: winget install GitHub.cli, sonra gh auth login.'
    }

    if (-not [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')) {
        Write-Warning 'GEMINI_API_KEY kullanici ortam degiskeni yok: setx GEMINI_API_KEY "<anahtar>" ile tanimlayin. Anahtar yoksa gunluk kosu hata kodu 2 ile biter ve loga yazar.'
    }
}

function Register-YerelGorev {
    Assert-AyriKlon
    $calistir = Join-Path $KlonYolu 'scripts\yerel_calistir.ps1'
    if (-not (Test-Path $calistir)) { throw "Bulunamadi: $calistir (klon guncel mi?)" }
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $conhost = Join-Path $env:WINDIR 'System32\conhost.exe'
    $psArgs = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$calistir`""
    # conhost --headless: konsol penceresi hic acilmaz.
    $eylem = New-ScheduledTaskAction -Execute $conhost -Argument "--headless `"$powershell`" $psArgs" -WorkingDirectory $KlonYolu
    $tetik = New-ScheduledTaskTrigger -Daily -At $Saat
    $ayarlar = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
    # Interactive: yalniz kullanici oturumu acikken, parola saklanmaz; Limited: yukseltilmemis.
    $kimlik = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $GorevAdi -Action $eylem -Trigger $tetik -Settings $ayarlar -Principal $kimlik `
        -Description 'IptalBey: Netflix/YouTube fiyatlarini Turkiye IP ile kontrol eder (KR-014).' -Force | Out-Null
    Write-Host "Gorev kaydedildi: '$GorevAdi' (her gun $Saat). Hemen denemek icin: Start-ScheduledTask -TaskName '$GorevAdi'"
    Write-Host ("Loglar: " + (Join-Path $env:LOCALAPPDATA 'IptalBey\loglar'))
}

function Unregister-YerelGorev {
    if (Get-ScheduledTask -TaskName $GorevAdi -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $GorevAdi -Confirm:$false
        Write-Host "Gorev silindi: '$GorevAdi'. Klon ($KlonYolu) ve loglar yerinde duruyor; isterseniz elle silin."
    }
    else {
        Write-Host "Gorev zaten yok: '$GorevAdi'."
    }
}

if ($PSCmdlet.ParameterSetName -eq 'Kaldir') {
    Unregister-YerelGorev
    return
}
Install-YerelKlon
if ($Kaydet) { Register-YerelGorev }
else { Write-Host 'Kurulum tamam. Gunluk gorevi kaydetmek icin ayni komutu -Kaydet ile calistirin.' }

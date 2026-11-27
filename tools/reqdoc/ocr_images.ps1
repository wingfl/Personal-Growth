param(
    [string]$Dir
)
$Paths = @(Get-ChildItem -Path $Dir -File | Where-Object { $_.Extension -match '^\.(jpe?g|png|bmp|tif?f)$' } | Sort-Object Name | ForEach-Object { $_.FullName })
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$lang = [Windows.Globalization.Language]::new("zh-Hans-CN")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) { Write-Error "no OCR engine"; exit 1 }

foreach ($p in $Paths) {
    $full = (Resolve-Path $p).Path
    Write-Output "===== IMAGE: $full ====="
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    Write-Output ("SIZE: " + $decoder.PixelWidth + " x " + $decoder.PixelHeight)
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    foreach ($line in $result.Lines) {
        $words = @()
        foreach ($w in $line.Words) {
            $words += ("{0}@{1},{2},{3},{4}" -f $w.Text, [int]$w.BoundingRect.X, [int]$w.BoundingRect.Y, [int]$w.BoundingRect.Width, [int]$w.BoundingRect.Height)
        }
        Write-Output ("LINE: " + ($words -join "  "))
    }
    $stream.Dispose()
}

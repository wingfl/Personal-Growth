param(
    [string]$Dir,
    [string]$Out
)
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

$rows = New-Object System.Collections.Generic.List[string]
$rows.Add("image`twidth`theight`tline`tx`ty`tw`th`ttext")

foreach ($f in (Get-ChildItem -Path $Dir -File | Where-Object { $_.Extension -match '^\.(jpe?g|png|bmp|tif?f)$' } | Sort-Object Name)) {
    $full = $f.FullName
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $W = $decoder.PixelWidth; $H = $decoder.PixelHeight
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $i = 0
    foreach ($line in $result.Lines) {
        $i++
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            $rows.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`t{7}`t{8}" -f $f.Name, $W, $H, $i, [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $w.Text))
        }
    }
    $stream.Dispose()
}
[System.IO.File]::WriteAllLines($Out, $rows, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("rows: " + $rows.Count + " -> " + $Out)

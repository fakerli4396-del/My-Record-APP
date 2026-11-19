
param([string]$ImagePath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod } | Select-Object -First 1
function Await($operation, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $language = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]::new('zh-Hans-CN')
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) { throw 'Chinese OCR language is unavailable' }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $words = @()
    foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            $box = $word.BoundingRect
            $words += @{text=$word.Text;x=$box.X;y=$box.Y;w=$box.Width;h=$box.Height}
        }
    }

    $englishLanguage = [Windows.Globalization.Language]::new('en-US')
    $englishEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($englishLanguage)
    $numeric = @()
    if ($null -ne $englishEngine) {
        $englishResult = Await ($englishEngine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        foreach ($line in $englishResult.Lines) {
            foreach ($word in $line.Words) {
                if ($word.Text -match '^[0-9.,%]+$') {
                    $box = $word.BoundingRect
                    $numeric += @{text=$word.Text;x=$box.X;y=$box.Y;w=$box.Width;h=$box.Height}
                }
            }
        }
    }
    @{words=$words;numeric=$numeric;text=$result.Text} | ConvertTo-Json -Depth 5 -Compress
} finally { $stream.Dispose() }

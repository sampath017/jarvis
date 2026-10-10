$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskScenes = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'scenes.json') -Raw | ConvertFrom-Json
$taskSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $taskSynth.SelectVoice('Microsoft Zira Desktop')
    $taskSynth.Rate = 0
    $taskSynth.Volume = 100
    for ($taskSceneIndex = 0; $taskSceneIndex -lt $taskScenes.Count; $taskSceneIndex++) {
        $taskAudioPath = Join-Path $PSScriptRoot ('audio/{0:d2}.wav' -f $taskSceneIndex)
        $taskSynth.SetOutputToWaveFile($taskAudioPath)
        $taskSynth.Speak($taskScenes[$taskSceneIndex].narration)
        $taskSynth.SetOutputToNull()
        Write-Output ('Narrated {0}: {1}' -f ($taskSceneIndex + 1), $taskScenes[$taskSceneIndex].title)
    }
} finally {
    $taskSynth.Dispose()
}

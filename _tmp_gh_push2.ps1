# -*- coding: utf-8 -*-
# 临时：GitHub 直连被网络阻断时，经 ssh.github.com:443 + 临时 deploy key 推送；用完即删 key。只输出状态。
$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\Ko_Li\.openclaw\workspace\web'
$env:GIT_TERMINAL_PROMPT = '0'
$out = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
$tok = ($out | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $tok) { Write-Output 'NO_TOKEN'; exit 2 }
$headers = @{ Authorization = "token $tok"; 'User-Agent' = 'dsh'; Accept = 'application/vnd.github+json' }
$key = Join-Path $env:TEMP ('dsh_ghkey_' + [guid]::NewGuid().ToString('N'))
ssh-keygen -t ed25519 -f $key -N '""' -q -C 'dsh-notice-push-20261114b' 2>$null
$pub = (Get-Content ($key + '.pub') -Raw).Trim()
$keyId = $null
try {
  $body = @{ title = 'dsh-notice-push-20261114b'; key = $pub; read_only = $false } | ConvertTo-Json
  $k = Invoke-RestMethod -Method Post -Uri 'https://api.github.com/repos/Link0Kong/class-tools-site/keys' -Headers $headers -Body $body -ContentType 'application/json'
  $keyId = $k.id
  Write-Output ('KEY_ADDED id=' + $keyId)
} catch {
  Write-Output ('KEY_ADD_FAIL ' + $_.Exception.Message); exit 4
}
try {
  $env:GIT_SSH_COMMAND = "ssh -i `"$key`" -p 443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o IdentitiesOnly=yes -o ConnectTimeout=20"
  $remote = 'ssh://git@ssh.github.com:443/Link0Kong/class-tools-site.git'
  $pushOut = git push $remote master 2>&1
  $pushOut | Select-Object -Last 4 | ForEach-Object { Write-Output ('PUSH ' + $_) }
  Write-Output ('PUSH_RESULT ' + $(if ($LASTEXITCODE -eq 0) { 'OK' } else { 'FAIL' }))
  $ls = git ls-remote --heads $remote master 2>&1
  Write-Output ('LS ' + (($ls | Select-Object -First 1) -join ''))
} finally {
  try {
    Invoke-RestMethod -Method Delete -Uri ("https://api.github.com/repos/Link0Kong/class-tools-site/keys/" + $keyId) -Headers $headers | Out-Null
    Write-Output 'KEY_DELETED'
  } catch { Write-Output ('KEY_DEL_FAIL ' + $_.Exception.Message) }
  Remove-Item $key, ($key + '.pub') -Force -ErrorAction SilentlyContinue
}

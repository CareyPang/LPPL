param([switch]$NoBrowser, [int]$Port = 0, [string]$Directory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$demoRoot = [IO.Path]::GetFullPath($Directory)
if (-not [IO.File]::Exists((Join-Path $demoRoot 'home.html'))) { throw 'home.html is missing from the demo folder' }
$rootPrefix = $demoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$listener.Start()
$localPort = $listener.LocalEndpoint.Port
$demoUrl = "http://127.0.0.1:$localPort/home.html?demo=1"
Write-Host "LPPL local demonstration: $demoUrl"
Write-Host 'Keep this window open. Close it or press Ctrl+C to stop.'
Write-Host 'Only this computer can connect. No account, installation, or cloud publication.'
if (-not $NoBrowser) { Start-Process $demoUrl }
$mime = @{'.html'='text/html; charset=utf-8';'.js'='text/javascript; charset=utf-8';'.css'='text/css; charset=utf-8';'.json'='application/json; charset=utf-8';'.webp'='image/webp';'.png'='image/png';'.jpg'='image/jpeg';'.svg'='image/svg+xml';'.mp4'='video/mp4';'.woff2'='font/woff2';'.ico'='image/x-icon'}
try {
  while ($true) {
    $client = $listener.AcceptTcpClient()
    $client.ReceiveTimeout = 4000
    $client.SendTimeout = 10000
    $stream = $client.GetStream()
    try {
      $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 4096, $true)
      $request = $reader.ReadLine()
      if (-not $request) { continue }
      $parts = $request.Split(' ')
      $headers = @{}
      $headerBytes = $request.Length
      while ($line = $reader.ReadLine()) {
        $headerBytes += $line.Length
        if ($headerBytes -gt 16384) { throw 'Header too large' }
        $colon = $line.IndexOf(':')
        if ($colon -gt 0) { $headers[$line.Substring(0,$colon).ToLowerInvariant()] = $line.Substring($colon+1).Trim() }
      }
      $status = '200 OK'; $body = $null; $file = $null; $start = [long]0; $length = [long]0; $extra = ''
      if ($parts.Length -ne 3 -or $parts[0] -notin @('GET','HEAD')) {
        $status = '405 Method Not Allowed'; $body = [Text.Encoding]::UTF8.GetBytes('Read-only local demo server')
      } else {
        $urlPath = [Uri]::UnescapeDataString(($parts[1] -split '\?',2)[0])
        if ($urlPath -eq '/') { $urlPath = '/home.html' }
        $file = [IO.Path]::GetFullPath((Join-Path $demoRoot $urlPath.TrimStart('/').Replace('/',[IO.Path]::DirectorySeparatorChar)))
        if (-not $file.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -or -not [IO.File]::Exists($file)) {
          $status = '404 Not Found'; $body = [Text.Encoding]::UTF8.GetBytes('Demo file not found'); $file = $null
        } else {
          $length = (Get-Item -LiteralPath $file).Length
          $total = $length
          if ($headers.ContainsKey('range')) {
            if ($headers['range'] -match '^bytes=(\d+)-(\d*)$') {
              $start = [long]$Matches[1]
              $end = if ($Matches[2]) { [Math]::Min([long]$Matches[2],$total-1) } else { $total-1 }
              if ($start -ge $total -or $end -lt $start) { $status = '416 Range Not Satisfiable' }
              else { $status = '206 Partial Content'; $length = $end-$start+1; $extra = "Content-Range: bytes $start-$end/$total`r`n" }
            } else { $status = '416 Range Not Satisfiable' }
            if ($status.StartsWith('416')) { $body = [byte[]]@(); $file = $null; $extra = "Content-Range: bytes */$total`r`n" }
          }
        }
      }
      if ($null -ne $body) { $length = $body.Length }
      $type = if ($file -and $mime.ContainsKey([IO.Path]::GetExtension($file))) { $mime[[IO.Path]::GetExtension($file)] } else { 'text/plain; charset=utf-8' }
      $head = "HTTP/1.1 $status`r`nContent-Type: $type`r`nContent-Length: $length`r`nAccept-Ranges: bytes`r`nCache-Control: no-cache`r`nConnection: close`r`n$extra`r`n"
      $bytes = [Text.Encoding]::ASCII.GetBytes($head)
      $stream.Write($bytes,0,$bytes.Length)
      if ($parts[0] -ne 'HEAD') {
        if ($file) {
          $inputFile = [IO.File]::OpenRead($file)
          try {
            [void]$inputFile.Seek($start,[IO.SeekOrigin]::Begin)
            $buffer = [byte[]]::new(65536)
            $remaining = $length
            while ($remaining -gt 0) {
              $read = $inputFile.Read($buffer,0,[int][Math]::Min($buffer.Length,$remaining))
              if ($read -eq 0) { break }
              $stream.Write($buffer,0,$read)
              $remaining -= $read
            }
          } finally { $inputFile.Dispose() }
        } elseif ($body.Length) { $stream.Write($body,0,$body.Length) }
      }
    } catch { Write-Verbose $_.Exception.Message }
    finally { $stream.Dispose(); $client.Dispose() }
  }
} finally { $listener.Stop() }

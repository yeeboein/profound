# Builds Profound's logo files from the mascot pixel art (buddy_idle.png).
# Pixel-perfect: the sprite is cropped to its visible pixels and only ever scaled in clean steps
# (x1, x1.5, x2, x2.5, x3 ...) with nearest-neighbour, so no icon size is ever blurry.
# Writes logo.png (256px), icon.ico (multi-size) and vscode_ext\icon.png (128px).
Add-Type -AssemblyName System.Drawing
$d = $PSScriptRoot
$full = [System.Drawing.Bitmap]::FromFile("$d\buddy_idle.png")

# crop to the visible pixels and centre in a square
$minx = 999; $miny = 999; $maxx = -1; $maxy = -1
for ($x = 0; $x -lt $full.Width; $x++) { for ($y = 0; $y -lt $full.Height; $y++) {
    if ($full.GetPixel($x, $y).A -gt 20) { $minx = [Math]::Min($minx, $x); $miny = [Math]::Min($miny, $y); $maxx = [Math]::Max($maxx, $x); $maxy = [Math]::Max($maxy, $y) } } }
$bw = $maxx - $minx + 1; $bh = $maxy - $miny + 1; $side = [Math]::Max($bw, $bh)
$sq = New-Object System.Drawing.Bitmap $side, $side
$g = [System.Drawing.Graphics]::FromImage($sq); $g.Clear([System.Drawing.Color]::Transparent)
$g.InterpolationMode = 'NearestNeighbor'; $g.PixelOffsetMode = 'Half'
$dst = New-Object System.Drawing.Rectangle ([int][Math]::Floor(($side - $bw) / 2)), ([int][Math]::Floor(($side - $bh) / 2)), $bw, $bh
$g.DrawImage($full, $dst, $minx, $miny, $bw, $bh, [System.Drawing.GraphicsUnit]::Pixel); $g.Dispose(); $full.Dispose()

function Render([int]$size) {
    $sc = [Math]::Floor($size / $side * 2) / 2          # largest clean half-step that fits
    if ($sc -lt 1) { $sc = $size / $side }
    $w = [int][Math]::Round($side * $sc); $o = [int][Math]::Floor(($size - $w) / 2)
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $gg = [System.Drawing.Graphics]::FromImage($bmp); $gg.Clear([System.Drawing.Color]::Transparent)
    $gg.InterpolationMode = 'NearestNeighbor'; $gg.PixelOffsetMode = 'Half'
    $gg.DrawImage($sq, $o, $o, $w, $w); $gg.Dispose()
    return $bmp
}

(Render 256).Save("$d\logo.png", [System.Drawing.Imaging.ImageFormat]::Png)
(Render 128).Save("$d\vscode_ext\icon.png", [System.Drawing.Imaging.ImageFormat]::Png)
# sizes Windows asks for at 100% / 125% / 150% / 200% scaling (taskbar, title bar, Alt+Tab, Explorer)
$sizes = 16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256
function Get-IcoBmp($bmp) {
    # classic icon bitmap entry: BITMAPINFOHEADER + 32-bit BGRA pixels (bottom-up) + 1-bit AND mask
    $w = $bmp.Width; $h = $bmp.Height; $maskRow = [int]([Math]::Ceiling($w / 32.0)) * 4
    $ms = New-Object System.IO.MemoryStream; $wr = New-Object System.IO.BinaryWriter $ms
    $wr.Write([uint32]40); $wr.Write([int32]$w); $wr.Write([int32]($h * 2)); $wr.Write([uint16]1); $wr.Write([uint16]32)
    $wr.Write([uint32]0); $wr.Write([uint32]($w * $h * 4 + $maskRow * $h)); $wr.Write([int32]0); $wr.Write([int32]0); $wr.Write([uint32]0); $wr.Write([uint32]0)
    for ($y = $h - 1; $y -ge 0; $y--) { for ($x = 0; $x -lt $w; $x++) {
        $c = $bmp.GetPixel($x, $y); $wr.Write([byte]$c.B); $wr.Write([byte]$c.G); $wr.Write([byte]$c.R); $wr.Write([byte]$c.A) } }
    for ($y = $h - 1; $y -ge 0; $y--) {
        $row = New-Object byte[] $maskRow
        for ($x = 0; $x -lt $w; $x++) { if ($bmp.GetPixel($x, $y).A -lt 128) { $i = [int][Math]::Floor($x / 8); $row[$i] = $row[$i] -bor (0x80 -shr ($x % 8)) } }
        $wr.Write($row)
    }
    $wr.Flush(); return , $ms.ToArray()
}
$pngs = @()
foreach ($sz in $sizes) {
    $b = Render $sz
    if ($sz -ge 256) {
        $ms = New-Object System.IO.MemoryStream
        $b.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $pngs += , $ms.ToArray()
    } else {
        $pngs += , (Get-IcoBmp $b)
    }
    $b.Dispose()
}
$fs = [System.IO.File]::Create("$d\icon.ico"); $bw2 = New-Object System.IO.BinaryWriter $fs
$bw2.Write([uint16]0); $bw2.Write([uint16]1); $bw2.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $sz = $sizes[$i]; $dim = if ($sz -ge 256) { 0 } else { $sz }
    $bw2.Write([byte]$dim); $bw2.Write([byte]$dim); $bw2.Write([byte]0); $bw2.Write([byte]0)
    $bw2.Write([uint16]1); $bw2.Write([uint16]32); $bw2.Write([uint32]$pngs[$i].Length); $bw2.Write([uint32]$offset)
    $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $bw2.Write($p) }
$bw2.Close(); $sq.Dispose()
Write-Host "sprite cropped to ${bw}x${bh}; icon.ico sizes: $($sizes -join ', ')"

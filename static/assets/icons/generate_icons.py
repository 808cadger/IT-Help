"""Run once to generate PNG icons from the SVG.
Requires: pip install cairosvg  OR  pip install Pillow (with rsvg)
Fallback: creates simple colored PNG squares if cairosvg not available.
"""
import struct, zlib, os

ICON_DIR = os.path.dirname(os.path.abspath(__file__))

def make_png(size, filename):
    """Generate a minimal PNG — dark bg with blue 'IT' text block."""
    bg   = (26, 29, 36)     # --bg
    blue = (59, 130, 246)   # --accent

    def px(r, g, b): return bytes([r, g, b])

    rows = []
    for y in range(size):
        row = b'\x00'  # filter byte
        for x in range(size):
            # Rounded square background
            margin = size // 12
            corner = size // 5
            dx = min(x, size-1-x) - margin
            dy = min(y, size-1-y) - margin
            in_bg = dx >= 0 and dy >= 0

            # Blue rectangle in center (represents monitor)
            mx, my = size // 4, size // 3
            mw, mh = size // 2, size // 3
            in_rect = mx <= x <= mx+mw and my <= y <= my+mh

            # Stand
            sw = size // 5
            sx = (size - sw) // 2
            in_stand = sx <= x <= sx+sw and (my+mh) <= y <= (my+mh + size//10)

            if not in_bg:
                row += px(0, 0, 0)
            elif in_rect or in_stand:
                row += px(*blue)
            else:
                row += px(*bg)
        rows.append(row)

    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    raw = zlib.compress(b''.join(rows))
    ihdr_data = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)

    png = (
        b'\x89PNG\r\n\x1a\n' +
        chunk(b'IHDR', ihdr_data) +
        chunk(b'IDAT', raw) +
        chunk(b'IEND', b'')
    )
    path = os.path.join(ICON_DIR, filename)
    with open(path, 'wb') as f:
        f.write(png)
    print(f"Generated {filename}")

if __name__ == '__main__':
    try:
        import cairosvg
        svg_path = os.path.join(ICON_DIR, 'icon.svg')
        cairosvg.svg2png(url=svg_path, write_to=os.path.join(ICON_DIR, 'icon-192.png'), output_width=192, output_height=192)
        cairosvg.svg2png(url=svg_path, write_to=os.path.join(ICON_DIR, 'icon-512.png'), output_width=512, output_height=512)
        print("Generated icons from SVG using cairosvg.")
    except ImportError:
        make_png(192, 'icon-192.png')
        make_png(512, 'icon-512.png')
        print("Generated fallback icons (install cairosvg for high-quality icons).")

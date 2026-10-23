"""Forecast maps in the style of the old Foreca server: banded temperature / rain / cloud, wind arrows with the
speed written in the selected unit, weather symbols with temperatures. Fields come from Open-Meteo (one grid
request, hourly, free for non-commercial use); each animation frame is 3 h further on."""
import datetime as dt
import io
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

import maps

GN = 8                      # forecast grid is GN x GN points covering the view plus a margin
MARGIN = 0.15
STEP_H = 3                  # hours between animation frames
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
try:
    F11 = ImageFont.truetype(FONT, 11)
    F10 = ImageFont.truetype(FONT, 10)
except OSError:
    F11 = F10 = ImageFont.load_default()
VARS = "temperature_2m,precipitation,cloud_cover,wind_speed_10m,wind_direction_10m,weather_code"


def px_to_latlon(px, py, z):
    n = 256.0 * 2 ** z
    lon = px / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n))))
    return lat, lon


def grid_positions(w, h):
    """pixel coordinates (view space) of the GN grid lines, margin included"""
    xs = np.linspace(-MARGIN * w, (1 + MARGIN) * w, GN)
    ys = np.linspace(-MARGIN * h, (1 + MARGIN) * h, GN)
    return xs, ys


def fetch_grid(lat, lon, w, h, nframes, z=maps.ZOOM):
    """-> (times [utc datetime], dict var -> array [frame, row, col])"""
    cx, cy = maps.world_px(lat, lon, z)
    xs, ys = grid_positions(w, h)
    pts = [px_to_latlon(cx - w / 2.0 + x, cy - h / 2.0 + y, z) for y in ys for x in xs]
    pts = [(max(min(a, 85.0), -85.0), ((b + 180) % 360) - 180) for a, b in pts]
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&hourly=%s&forecast_days=3"
           "&wind_speed_unit=ms&timezone=GMT" % (",".join("%.3f" % p[0] for p in pts),
                                                 ",".join("%.3f" % p[1] for p in pts), VARS))
    d = json.loads(maps.fetch(url, 1800))
    if isinstance(d, dict):
        d = [d]
    t0 = d[0]["hourly"]["time"]
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    i0 = t0.index(now.strftime("%Y-%m-%dT%H:00"))
    idx = [i0 + STEP_H * k for k in range(nframes)]
    out = {}
    for v in VARS.split(","):
        a = np.array([[(x if x is not None else 0.0) for x in p["hourly"][v]] for p in d], dtype="float32")  # [pt, hour]
        out[v] = a[:, idx].T.reshape(len(idx), GN, GN)
    times = [now + dt.timedelta(hours=STEP_H * k) for k in range(nframes)]
    return times, out


def interp(grid, w, h):
    """bilinear upsample of the GN x GN grid to the w x h view (grid spans the view plus margin)"""
    gx = (np.arange(w) + MARGIN * w) / (w * (1 + 2 * MARGIN)) * (GN - 1)
    gy = (np.arange(h) + MARGIN * h) / (h * (1 + 2 * MARGIN)) * (GN - 1)
    x0 = np.clip(np.floor(gx).astype(int), 0, GN - 2); fx = (gx - x0)[None, :]
    y0 = np.clip(np.floor(gy).astype(int), 0, GN - 2); fy = (gy - y0)[:, None]
    a = grid[y0][:, x0]; b = grid[y0][:, x0 + 1]; c = grid[y0 + 1][:, x0]; d = grid[y0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def sample(grid, px, py, w, h):
    gx = (px + MARGIN * w) / (w * (1 + 2 * MARGIN)) * (GN - 1)
    gy = (py + MARGIN * h) / (h * (1 + 2 * MARGIN)) * (GN - 1)
    x0 = int(min(max(math.floor(gx), 0), GN - 2)); y0 = int(min(max(math.floor(gy), 0), GN - 2))
    fx, fy = gx - x0, gy - y0
    return float((grid[y0, x0] * (1 - fx) + grid[y0, x0 + 1] * fx) * (1 - fy) +
                 (grid[y0 + 1, x0] * (1 - fx) + grid[y0 + 1, x0 + 1] * fx) * fy)


def muted_base(lat, lon, w, h, z=maps.ZOOM):
    cx, cy = maps.world_px(lat, lon, z)
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    tx0, ty0 = int(x0 // 256), int(y0 // 256)
    tx1, ty1 = int((x0 + w - 1) // 256), int((y0 + h - 1) // 256)
    base = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (225, 225, 225))
    n = 2 ** z
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if 0 <= ty < n:
                try:
                    b = maps.fetch("https://tile.openstreetmap.org/%d/%d/%d.png" % (z, tx % n, ty), 7 * 86400)
                    base.paste(Image.open(io.BytesIO(b)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
                except Exception:
                    pass
    base = ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.3)).enhance(1.07)
    left, top = int(round(x0 - tx0 * 256)), int(round(y0 - ty0 * 256))
    return base.crop((left, top, left + w, top + h)).convert("RGBA")


# ---- colour tables ---------------------------------------------------------------------------
TEMP_STOPS = [(-20, (120, 0, 160)), (-10, (40, 60, 200)), (0, (0, 170, 230)), (6, (0, 180, 130)),
              (12, (120, 200, 60)), (16, (250, 230, 40)), (22, (250, 150, 30)), (28, (220, 40, 30)),
              (36, (150, 0, 40))]


def temp_colour(t):
    if t <= TEMP_STOPS[0][0]:
        return TEMP_STOPS[0][1]
    for (t0, c0), (t1, c1) in zip(TEMP_STOPS, TEMP_STOPS[1:]):
        if t <= t1:
            f = (t - t0) / float(t1 - t0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
    return TEMP_STOPS[-1][1]


RAIN_BANDS = [(0.1, (170, 210, 255, 120)), (0.3, (110, 170, 255, 160)), (1.0, (50, 110, 240, 185)),
              (2.0, (25, 60, 200, 205)), (4.0, (110, 40, 190, 215)), (8.0, (200, 30, 150, 225))]
CLOUD_BANDS = [(20, (255, 255, 255, 70)), (40, (232, 238, 248, 115)), (60, (200, 208, 224, 155)),
               (80, (160, 170, 190, 180)), (95, (118, 128, 152, 200))]
WIND_BANDS = [(3, (30, 150, 60)), (6, (200, 150, 0)), (10, (230, 100, 0)), (15, (210, 30, 30)), (1e9, (140, 0, 130))]


def band_layer(field, bands):
    """RGBA layer: pixel gets the colour of the highest band threshold it reaches (nothing below the first)"""
    h, w = field.shape
    out = np.zeros((h, w, 4), dtype="uint8")
    for thr, col in bands:
        out[field >= thr] = col
    return Image.fromarray(out, "RGBA")


def halo_text(dr, xy, text, font, fill=(0, 0, 0), halo=(255, 255, 255)):
    x, y = xy
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        dr.text((x + ox, y + oy), text, font=font, fill=halo)
    dr.text((x, y), text, font=font, fill=fill)


def centred(dr, cx, y, text, font, **kw):
    wd = dr.textlength(text, font=font)
    halo_text(dr, (cx - wd / 2.0, y), text, font, **kw)


def conv_t(c, u):
    return int(round(c * 9.0 / 5.0 + 32)) if u == 2 else int(round(c))


def conv_w(ms, u):
    if u == 3:
        return int(round(ms * 3.6))
    if u in (1, 2):
        return int(round(ms * 2.23694))
    return int(round(ms))


# ---- renderers -------------------------------------------------------------------------------
def draw_marker(img):
    w, h = img.size
    dr = ImageDraw.Draw(img)
    dr.ellipse((w // 2 - 3, h // 2 - 3, w // 2 + 3, h // 2 + 3), outline=(0, 0, 0), fill=(255, 255, 255))


def render_temp(base, F, k, u):
    w, h = base.size
    t = interp(F["temperature_2m"][k], w, h)
    q = np.floor(t / 2.0) * 2.0                                            # 2 degree bands
    rgb = np.zeros((h, w, 4), dtype="uint8")
    lut = {}
    for v in np.unique(q):
        lut[v] = temp_colour(float(v) + 1.0) + (165,)
    for v, col in lut.items():
        rgb[q == v] = col
    edge = np.zeros((h, w), dtype=bool)
    edge[:, 1:] |= q[:, 1:] != q[:, :-1]
    edge[1:, :] |= q[1:, :] != q[:-1, :]
    rgb[edge] = (60, 60, 60, 150)                                          # zone delineation
    img = Image.alpha_composite(base, Image.fromarray(rgb, "RGBA"))
    dr = ImageDraw.Draw(img)
    for fy in (0.2, 0.5, 0.8):
        for fx in (0.2, 0.5, 0.8):
            px, py = fx * w, fy * h
            centred(dr, px, py - 6, "%d" % conv_t(sample(F["temperature_2m"][k], px, py, w, h), u), F11)
    return img


def render_rain(base, F, k, u):
    w, h = base.size
    r = interp(F["precipitation"][k], w, h)
    return Image.alpha_composite(base, band_layer(r, RAIN_BANDS))


def render_cloud(base, F, k, u):
    w, h = base.size
    c = interp(F["cloud_cover"][k], w, h)
    return Image.alpha_composite(base, band_layer(c, CLOUD_BANDS))


def arrow(dr, cx, cy, to_deg, col, ln=15):
    a = math.radians(to_deg)
    dx, dy = math.sin(a), -math.cos(a)                                     # screen: north = up
    x1, y1 = cx - dx * ln / 2, cy - dy * ln / 2
    x2, y2 = cx + dx * ln / 2, cy + dy * ln / 2
    dr.line((x1, y1, x2, y2), fill=(255, 255, 255), width=4)
    dr.line((x1, y1, x2, y2), fill=col, width=2)
    px, py = -dy, dx
    head = [(x2 + dx * 3, y2 + dy * 3), (x2 - dx * 5 + px * 4, y2 - dy * 5 + py * 4), (x2 - dx * 5 - px * 4, y2 - dy * 5 - py * 4)]
    dr.polygon(head, fill=(255, 255, 255))
    dr.polygon([(x2 + dx * 1, y2 + dy * 1), (x2 - dx * 4 + px * 3, y2 - dy * 4 + py * 3), (x2 - dx * 4 - px * 3, y2 - dy * 4 - py * 3)], fill=col)


def render_wind(base, F, k, u):
    w, h = base.size
    img = Image.alpha_composite(base, Image.new("RGBA", base.size, (255, 255, 255, 70)))
    dr = ImageDraw.Draw(img)
    spd, dirn = F["wind_speed_10m"][k], F["wind_direction_10m"][k]
    uu = -spd * np.sin(np.radians(dirn)); vv = -spd * np.cos(np.radians(dirn))      # vector the wind blows towards
    cols, rows = 5, 5
    for j in range(rows):
        for i in range(cols):
            px, py = (i + 0.5) * w / cols, (j + 0.5) * h / rows
            su, sv = sample(uu, px, py, w, h), sample(vv, px, py, w, h)
            s = math.hypot(su, sv)
            to_deg = (math.degrees(math.atan2(su, sv)) + 360) % 360
            col = next(c for thr, c in WIND_BANDS if s < thr)
            arrow(dr, px, py - 5, to_deg, col)
            centred(dr, px, py + 4, "%d" % conv_w(s, u), F10, fill=col)
    return img


def sym_kind(code, cloud):
    if code >= 95:
        return "thunder"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (45, 48):
        return "fog"
    if code == 0 or cloud < 20:
        return "sun"
    if code in (1, 2) or cloud < 70:
        return "partly"
    return "cloud"


def draw_cloud_shape(dr, x, y, col=(235, 238, 245), edge=(110, 120, 140)):
    for ox, oy, r in ((-7, 2, 6), (0, -2, 8), (8, 2, 6)):
        dr.ellipse((x + ox - r, y + oy - r, x + ox + r, y + oy + r), fill=col, outline=edge)
    dr.rectangle((x - 8, y, x + 9, y + 8), fill=col)
    dr.ellipse((x - 14, y - 1, x - 2, y + 9), fill=col)
    dr.ellipse((x + 3, y - 1, x + 15, y + 9), fill=col)


def draw_sun(dr, x, y, r=7):
    for a in range(0, 360, 45):
        ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
        dr.line((x + ax * (r + 2), y + ay * (r + 2), x + ax * (r + 6), y + ay * (r + 6)), fill=(240, 170, 0), width=2)
    dr.ellipse((x - r, y - r, x + r, y + r), fill=(255, 215, 40), outline=(230, 150, 0))


def draw_symbol(dr, x, y, kind):
    if kind == "sun":
        draw_sun(dr, x, y)
    elif kind == "partly":
        draw_sun(dr, x - 5, y - 4, 6)
        draw_cloud_shape(dr, x + 3, y + 3)
    elif kind == "cloud":
        draw_cloud_shape(dr, x, y, col=(205, 210, 222))
    elif kind == "fog":
        for i in range(4):
            dr.line((x - 12, y - 8 + i * 5, x + 12, y - 8 + i * 5), fill=(130, 140, 155), width=2)
    else:
        draw_cloud_shape(dr, x, y - 4, col=(175, 182, 198))
        if kind == "rain":
            for dx in (-8, 0, 8):
                dr.line((x + dx, y + 8, x + dx - 3, y + 15), fill=(40, 100, 230), width=2)
        elif kind == "snow":
            for dx in (-8, 0, 8):
                dr.ellipse((x + dx - 2, y + 10, x + dx + 2, y + 14), fill=(255, 255, 255), outline=(90, 120, 170))
        elif kind == "thunder":
            dr.polygon([(x + 2, y + 5), (x - 5, y + 13), (x, y + 13), (x - 3, y + 20), (x + 6, y + 10), (x + 1, y + 10)], fill=(255, 210, 0), outline=(200, 130, 0))


def render_symb(base, F, k, u):
    w, h = base.size
    img = Image.alpha_composite(base, Image.new("RGBA", base.size, (255, 255, 255, 60)))
    dr = ImageDraw.Draw(img)
    for fy in (0.2, 0.5, 0.8):
        for fx in (0.2, 0.5, 0.8):
            px, py = fx * w, fy * h
            code = int(round(sample(F["weather_code"][k], px, py, w, h)))
            # weather codes do not interpolate; take the nearest grid point instead
            gx = int(round((px + MARGIN * w) / (w * (1 + 2 * MARGIN)) * (GN - 1)))
            gy = int(round((py + MARGIN * h) / (h * (1 + 2 * MARGIN)) * (GN - 1)))
            code = int(F["weather_code"][k][gy, gx])
            cloud = float(F["cloud_cover"][k][gy, gx])
            draw_symbol(dr, px, py - 4, sym_kind(code, cloud))
            centred(dr, px, py + 12, "%d" % conv_t(sample(F["temperature_2m"][k], px, py, w, h), u), F11)
    return img


RENDERERS = {"temp": render_temp, "rain": render_rain, "cloud": render_cloud, "wind": render_wind, "symb": render_symb}


def render_set(kinds, lat, lon, w, h, units, nframes):
    """{kind: [(utc datetime, png bytes)]}"""
    times, F = fetch_grid(lat, lon, w, h, nframes)
    base = muted_base(lat, lon, w, h)
    out = {}
    for kind in kinds:
        frames = []
        for k, tm in enumerate(times):
            img = RENDERERS[kind](base, F, k, units)
            draw_marker(img)
            buf = io.BytesIO()
            img.convert("RGB").quantize(64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(buf, "PNG", optimize=True)
            frames.append((tm, buf.getvalue()))
        out[kind] = frames
    return out

"""Map images for the legacy Foreca app: RainViewer radar over an OpenStreetMap base,
cropped to the phone screen around the location (the old server did the same with gd2 maps)."""
import io, json, math, threading, time, urllib.request
from PIL import Image, ImageDraw, ImageEnhance

import os as _o
UA = "foreca-s60-bridge/1.0 (%s)" % _o.environ.get("BRIDGE_CONTACT", "set BRIDGE_CONTACT to your email or URL")   # tile servers want a way to reach you
ZOOM = 6                      # RainViewer free tiles stop at z7; z6 shows ~400 km across
_lock = threading.Lock()
_cache = {}                   # url -> (time, bytes)


def fetch(url, ttl):
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read()
    with _lock:
        if len(_cache) > 400:
            _cache.clear()
        _cache[url] = (now, data)
    return data


def radar_frames():
    d = json.loads(fetch("https://api.rainviewer.com/public/weather-maps.json", 120))
    return d["host"], d["radar"]["past"]          # [{time, path}], oldest first


def world_px(lat, lon, z):
    n = 256 * 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def render_radar(lat, lon, w, h, host, frame, z=ZOOM):
    cx, cy = world_px(lat, lon, z)
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    tx0, ty0 = int(x0 // 256), int(y0 // 256)
    tx1, ty1 = int((x0 + w - 1) // 256), int((y0 + h - 1) // 256)
    base = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (230, 230, 230))
    rad = Image.new("RGBA", base.size, (0, 0, 0, 0))
    n = 2 ** z
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not 0 <= ty < n:
                continue
            tx_w = tx % n
            ox, oy = (tx - tx0) * 256, (ty - ty0) * 256
            try:
                b = fetch("https://tile.openstreetmap.org/%d/%d/%d.png" % (z, tx_w, ty), 7 * 86400)
                base.paste(Image.open(io.BytesIO(b)).convert("RGB"), (ox, oy))
            except Exception:
                pass
            try:
                r = fetch("%s%s/256/%d/%d/%d/2/1_1.png" % (host, frame["path"], z, tx_w, ty), 600)
                rad.paste(Image.open(io.BytesIO(r)).convert("RGBA"), (ox, oy))
            except Exception:
                pass
    base = ImageEnhance.Brightness(ImageEnhance.Contrast(ImageEnhance.Color(base).enhance(1.6)).enhance(1.35)).enhance(0.9)  # firm up pale OSM land/sea so the coast reads on a small screen
    base.paste(rad, (0, 0), rad)
    left, top = int(round(x0 - tx0 * 256)), int(round(y0 - ty0 * 256))
    img = base.crop((left, top, left + w, top + h))
    dr = ImageDraw.Draw(img)
    px, py = w // 2, h // 2                         # location marker, same style as the old server
    dr.ellipse((px - 3, py - 3, px + 3, py + 3), outline=(0, 0, 0), fill=(255, 255, 255))
    out = io.BytesIO()
    img.quantize(128).save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------- coastline overlay ----
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("BRIDGE_DATA") or next((d for d in (_os.path.join(_HERE, "data"), _os.path.join(_HERE, "..", "data"))
                                                if _os.path.isdir(d)), _os.path.join(_HERE, "data"))


def _load_lines(fname):
    out = []
    try:
        for f in json.load(open(_os.path.join(_DATA, fname)))["features"]:
            g = f["geometry"]
            parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for pts in parts:
                lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
                out.append(((min(lons), min(lats), max(lons), max(lats)), pts))
    except (OSError, KeyError, ValueError):
        pass
    return out


_COAST = _load_lines("ne_50m_coastline.geojson")
_BORDERS = _load_lines("ne_50m_admin_0_boundary_lines_land.geojson")


def draw_geography(img, lat, lon, z=ZOOM):
    """vector coastlines (bright) and country borders (faint) from Natural Earth, centred on lat/lon"""
    w, h = img.size
    cx, cy = world_px(lat, lon, z)
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    dlon = 360.0 * w / (256 * 2 ** z) * 0.6 + 1
    dlat = dlon
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    for lines, col, wd in ((_BORDERS, (255, 255, 255, 110), 1), (_COAST, (255, 235, 120, 230), 1)):
        for (bx0, by0, bx1, by1), pts in lines:
            if bx1 < lon - dlon or bx0 > lon + dlon or by1 < lat - dlat or by0 > lat + dlat:
                continue
            xy = []
            for plon, plat in pts:
                px, py = world_px(max(min(plat, 85.0), -85.0), plon, z)
                xy.append((px - x0, py - y0))
            dr.line(xy, fill=col, width=wd)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


# ------------------------------------------------- natural-look base for infrared-only regions ----
import numpy as _np


def _load_polys(fname):
    out = []
    try:
        for f in json.load(open(_os.path.join(_DATA, fname)))["features"]:
            g = f["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for rings in polys:
                lons = [p[0] for p in rings[0]]; lats = [p[1] for p in rings[0]]
                out.append(((min(lons), min(lats), max(lons), max(lats)), rings))
    except (OSError, KeyError, ValueError):
        pass
    return out


_LAND = _load_polys("ne_50m_land.geojson")
_LAKES = _load_polys("ne_50m_lakes.geojson")
SEA, LAND_COL, LAKE = (38, 74, 120), (104, 124, 86), (38, 74, 120)


def land_sea(w, h, lat, lon, z=ZOOM):
    """sea / land picture from Natural Earth polygons, centred on lat/lon"""
    cx, cy = world_px(lat, lon, z)
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    dlon = 360.0 * w / (256 * 2 ** z) * 0.6 + 1
    img = Image.new("RGB", (w, h), SEA)
    dr = ImageDraw.Draw(img)

    def proj(ring):
        return [(world_px(max(min(a, 85.0), -85.0), b, z)[0] - x0, world_px(max(min(a, 85.0), -85.0), b, z)[1] - y0)
                for b, a in ring]
    for polys, col in ((_LAND, LAND_COL), (_LAKES, LAKE)):
        for (bx0, by0, bx1, by1), rings in polys:
            if bx1 < lon - dlon or bx0 > lon + dlon or by1 < lat - dlon or by0 > lat + dlon:
                continue
            dr.polygon(proj(rings[0]), fill=col)
            for hole in rings[1:]:
                dr.polygon(proj(hole), fill=SEA if col == LAND_COL else LAND_COL)
    return img


def ir_to_natural(im, lat, lon, w, h):
    """GIBS infrared uses a false-colour key (cold cloud = blue/green/yellow/red). Turn it into white cloud over land and sea."""
    a = _np.asarray(im.convert("RGB"), dtype="float32")
    sat = a.max(axis=2) - a.min(axis=2)
    grey = a.mean(axis=2)
    alpha = _np.clip((grey - 128.0) / 100.0, 0.0, 1.0) * 0.85            # warm surface -> clear, colder -> more cloud
    alpha = _np.where(sat > 25, 1.0, alpha)                              # coloured pixels are the coldest, highest tops
    base = _np.asarray(land_sea(w, h, lat, lon), dtype="float32")
    cloud = _np.where((sat > 25)[..., None], 255.0, 214.0 + 41.0 * _np.clip((grey - 128.0) / 127.0, 0, 1)[..., None])
    out = base * (1 - alpha[..., None]) + cloud * alpha[..., None]
    return Image.fromarray(out.astype("uint8"), "RGB")


# ---------------------------------------------------------------- satellite ----
import datetime as _dt
import re as _re
import urllib.parse as _up

EUM = "https://view.eumetsat.int/geoserver/wms"
GIBS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi"


def sat_source(lon):
    """(wms url, layer, time step minutes) by longitude: Meteosat (EUMETSAT) where it sees, else Himawari/GOES (NASA GIBS)"""
    if -65 <= lon <= 65:
        return EUM, "mtg_fd:rgb_geocolour", 10
    if 65 < lon < 100:
        return EUM, "msg_iodc:rgb_natural", 15
    if lon >= 100 or lon > 160:
        return GIBS, "Himawari_AHI_Band13_Clean_Infrared", 10
    if lon < -115:
        return GIBS, "GOES-West_ABI_GeoColor", 10
    return GIBS, "GOES-East_ABI_GeoColor", 10


def sat_latest(url, layer):
    """newest available time string for a WMS layer (the 'default' of its time dimension), cached"""
    caps = fetch(url + "?" + _up.urlencode(dict(service="WMS", version="1.3.0", request="GetCapabilities")), 600)
    t = caps.decode("utf-8", "replace")
    i = t.find("<Name>%s</Name>" % layer)
    if i < 0:
        raise ValueError("layer %s not in capabilities" % layer)
    m = _re.search(r'<Dimension[^>]*name="time"[^>]*>', t[i:i + 6000])
    if not m:
        raise ValueError("no time dimension")
    d = _re.search(r'default="([^"]+)"', m.group(0))
    return d.group(1)


def _shift(ts, minutes):
    ms = ".000" if ".000" in ts else ""
    d = _dt.datetime.strptime(ts.replace(".000", ""), "%Y-%m-%dT%H:%M:%SZ") - _dt.timedelta(minutes=minutes)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ms + "Z"


def sat_frames(lon, count, spacing=30):
    """[(utc datetime, TIME string)] oldest first, `spacing` minutes apart, newest = latest available"""
    url, layer, step = sat_source(lon)
    latest = sat_latest(url, layer)
    times = [_shift(latest, spacing * k) for k in range(count)][::-1]
    return [(_dt.datetime.strptime(x.replace(".000", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc), x)
            for x in times]


def render_sat(lat, lon, w, h, timestr, z=ZOOM):
    url, layer, _ = sat_source(lon)
    cx, cy = world_px(lat, lon, z)
    n = 256.0 * 2 ** z
    full = 20037508.342789244

    def m(px, py):
        return (px / n - 0.5) * 2 * full, (0.5 - py / n) * 2 * full
    xa, yb = m(cx - w / 2.0, cy - h / 2.0)
    xb, ya = m(cx + w / 2.0, cy + h / 2.0)
    q = dict(service="WMS", version="1.3.0", request="GetMap", layers=layer, styles="", crs="EPSG:3857",
             bbox="%f,%f,%f,%f" % (xa, ya, xb, yb), width=w, height=h, format="image/png", time=timestr)
    data = fetch(url + "?" + _up.urlencode(q), 1800)
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    if im.getchannel("A").getextrema()[1] == 0:
        raise ValueError("empty satellite frame")           # time not available for this layer
    if layer.startswith("Himawari"):
        img = ir_to_natural(im, lat, lon, w, h)
    else:
        bg = Image.new("RGBA", im.size, (20, 30, 50, 255))  # dark backdrop where there is no data
        img = Image.alpha_composite(bg, im).convert("RGB")
    img = draw_geography(img, lat, lon, z)
    dr = ImageDraw.Draw(img)
    px, py = w // 2, h // 2
    dr.ellipse((px - 3, py - 3, px + 3, py + 3), outline=(0, 0, 0), fill=(255, 255, 255))
    out = io.BytesIO()
    img.quantize(128).save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------- OpenWeather layers ----
def _owm_key():
    try:
        for l in open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "owm.env")):
            if l.startswith("OWM_KEY="):
                return l.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


OWM_KEY = _owm_key()
OWM_ALPHA = 1.8
OWM_LAYERS = {"temp": "temp_new", "rain": "precipitation_new", "wind": "wind_new", "cloud": "clouds_new"}


def render_owm(layer, lat, lon, w, h, z=ZOOM):
    """OpenWeather current-conditions tile layer over the (firmed-up) OSM base, cropped around lat/lon"""
    cx, cy = world_px(lat, lon, z)
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    tx0, ty0 = int(x0 // 256), int(y0 // 256)
    tx1, ty1 = int((x0 + w - 1) // 256), int((y0 + h - 1) // 256)
    base = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (230, 230, 230))
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    n = 2 ** z
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not 0 <= ty < n:
                continue
            ox, oy = (tx - tx0) * 256, (ty - ty0) * 256
            try:
                b = fetch("https://tile.openstreetmap.org/%d/%d/%d.png" % (z, tx % n, ty), 7 * 86400)
                base.paste(Image.open(io.BytesIO(b)).convert("RGB"), (ox, oy))
            except Exception:
                pass
            r = fetch("https://tile.openweathermap.org/map/%s/%d/%d/%d.png?appid=%s" % (layer, z, tx % n, ty, OWM_KEY), 600)
            ov.paste(Image.open(io.BytesIO(r)).convert("RGBA"), (ox, oy))
    base = ImageEnhance.Brightness(ImageEnhance.Contrast(ImageEnhance.Color(base).enhance(1.6)).enhance(1.35)).enhance(0.9)
    ov.putalpha(ov.getchannel("A").point(lambda a: min(255, int(a * OWM_ALPHA))))   # OpenWeather tiles are faint; strengthen
    base.paste(ov, (0, 0), ov)
    left, top = int(round(x0 - tx0 * 256)), int(round(y0 - ty0 * 256))
    img = base.crop((left, top, left + w, top + h))
    dr = ImageDraw.Draw(img)
    px, py = w // 2, h // 2
    dr.ellipse((px - 3, py - 3, px + 3, py + 3), outline=(0, 0, 0), fill=(255, 255, 255))
    out = io.BytesIO()
    img.quantize(128).save(out, "PNG", optimize=True)
    return out.getvalue()

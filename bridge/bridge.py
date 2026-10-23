#!/usr/bin/env python3
"""Bridge: legacy Foreca mobile app (S60 v1.4.x, http://pw.foreca.com/fd/) -> current Foreca Weather API.

Reproduces login.php (location search) and data-loc.php (zip of #-delimited .dat files).
Formats taken from the legacy PHP source (see ./legacy). Maps are not provided.
"""
import datetime, io, json, os, re, sys, time, zipfile, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo
import maps
import fieldmaps
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://weatherapi.foreca.net/api/v1"
LANGS = {1: "en", 2: "fr", 3: "de", 5: "it", 9: "fi", 16: "ru", 54: "el"}
LOGF = os.path.join(HERE, "bridge.log")


def load_key():
    for line in open(os.path.join(HERE, "foreca.env")):
        if line.startswith("FORECA_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("FORECA_KEY missing")


KEY = load_key()
_cache = {}


def api(path, ttl=600):
    now = time.time()
    hit = _cache.get(path)
    if hit and now - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    _cache[path] = (now, data)
    return data


def log(msg):
    with open(LOGF, "a") as f:
        f.write(time.strftime("%F %T ") + msg + "\n")


# timezone -> ISO country code (lowercase), from tzdata
TZCC = {}
try:
    for l in open("/usr/share/zoneinfo/zone.tab"):
        if l.startswith("#"):
            continue
        p = l.rstrip("\n").split("\t")
        if len(p) >= 3:
            TZCC[p[2]] = p[0].lower()
except OSError:
    pass


# ---- unit helpers (mirror units.php; base: C, m/s, mm, m, hPa) ----
def rnd(v):
    if v is None or v == "":
        return ""
    return int(v + 0.5) if v > 0 else int(v - 0.5)


def c2f(c): return 9.0 / 5.0 * c + 32
def ms2kmh(v): return v * 3.6
def ms2mph(v): return v * 2.23694
def mm2in(v): return v / 25.4
def m2mi(v): return 0.000621371192 * v
def hpa2in(v): return v / 33.8639


def ts(local_iso):
    """'2026-10-23T08:00+02:00' or '2026-10-23' -> YYYYMMDDHHMMSS (local)"""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)(?:T(\d\d):(\d\d))?", local_iso)
    return "%s%s%s%s%s00" % (m.group(1), m.group(2), m.group(3), m.group(4) or "12", m.group(5) or "00")


def conv_temp(t, u):
    return rnd(c2f(t)) if u == 2 else rnd(t)


def conv_wind(w, u):
    if u == 3: return rnd(ms2kmh(w))
    if u in (1, 2): return rnd(ms2mph(w))
    return rnd(w)


def conv_rain(r, u):
    if u in (1, 2):
        return "%.2f" % mm2in(r)
    return rnd(r)


def val(x):
    return "" if x is None else x


def sym(x):
    return x or ""


def location_info(q):
    loc = q.get("location")
    lon, lat = q.get("lon"), q.get("lat")
    if loc and loc.isdigit():
        try:
            return int(loc), api("/location/%s" % loc, 86400)
        except urllib.error.HTTPError:
            pass  # old/unknown id -> fall back to lon/lat below
    if lon and lat:
        info = api("/location/%s,%s" % (lon, lat), 86400)
        return int(q.get("id") or loc or info["id"]), info
    return None, None


def radar_pics(q, info, lid, u):
    """radar map PNGs (prodid 4): type digit 1 = latest frame, 2 = animation (last 8 frames)"""
    t = q.get("type", "")
    if not re.match(r"^\d{7}$", t) or t[0] not in "12":
        return []
    try:
        w = min(max(int(q.get("scrw", 200)), 1), 400)
        h = min(max(int(q.get("scrh", 230)), 1), 400)
        lat = float(q.get("lat") or info["lat"])
        lon = float(q.get("lon") or info["lon"])
        host, frames = maps.radar_frames()
        frames = frames[-8:] if t[0] == "2" else frames[-1:]
        tz = ZoneInfo(info.get("timezone") or "UTC")
        with ThreadPoolExecutor(max_workers=8) as ex:
            pngs = list(ex.map(lambda fr: maps.render_radar(lat, lon, w, h, host, fr), frames))
        return [("4_%s_%s_%d.png" % (lid, datetime.datetime.fromtimestamp(fr["time"], tz).strftime("%Y%m%d%H%M%S"), u), png)
                for fr, png in zip(frames, pngs)]
    except Exception as e:
        log("MAP ERROR %r" % (e,))
        return []


def sat_pics(q, info, lid, u):
    """satellite map PNGs (prodid 256, 7th type digit): 1 = latest frame, 2 = animation (8 frames, 30 min apart)"""
    t = q.get("type", "")
    if not re.match(r"^\d{7}$", t) or t[6] not in "12":
        return []
    try:
        w = min(max(int(q.get("scrw", 200)), 1), 400)
        h = min(max(int(q.get("scrh", 230)), 1), 400)
        lat = float(q.get("lat") or info["lat"])
        lon = float(q.get("lon") or info["lon"])
        tz = ZoneInfo(info.get("timezone") or "UTC")
        def one(ft):
            try:
                return maps.render_sat(lat, lon, w, h, ft[1])
            except Exception as e:
                log("SAT frame %s skipped: %r" % (ft[1], e))
                return None
        fts = maps.sat_frames(lon, 8 if t[6] == "2" else 1)
        with ThreadPoolExecutor(max_workers=8) as ex:
            pngs = list(ex.map(one, fts))
        return [("256_%s_%s_%d.png" % (lid, ft[0].astimezone(tz).strftime("%Y%m%d%H%M%S"), u), png)
                for ft, png in zip(fts, pngs) if png]
    except Exception as e:
        log("SAT ERROR %r" % (e,))
        return []


def owm_pics(q, info, lid, u):
    """OpenWeather current-conditions maps: temp (prodid 8, 2nd type digit), rain (16, 3rd), wind (64, 5th), cloud (128, 6th).
    Only a current frame exists, so 'animated' requests also get one image."""
    t = q.get("type", "")
    if not re.match(r"^\d{7}$", t) or not maps.OWM_KEY:
        return []
    want = [(8, "temp", 1), (16, "rain", 2), (64, "wind", 4), (128, "cloud", 5)]
    want = [(pid, name) for pid, name, idx in want if t[idx] in "12"]
    if not want:
        return []
    try:
        w = min(max(int(q.get("scrw", 200)), 1), 400)
        h = min(max(int(q.get("scrh", 230)), 1), 400)
        lat = float(q.get("lat") or info["lat"])
        lon = float(q.get("lon") or info["lon"])
        now = datetime.datetime.now(ZoneInfo(info.get("timezone") or "UTC"))
        stamp = now.replace(minute=now.minute // 10 * 10, second=0).strftime("%Y%m%d%H%M%S")

        def one(item):
            try:
                return maps.render_owm(maps.OWM_LAYERS[item[1]], lat, lon, w, h)
            except Exception as e:
                log("OWM %s skipped: %r" % (item[1], e))
                return None
        with ThreadPoolExecutor(max_workers=4) as ex:
            pngs = list(ex.map(one, want))
        return [("%d_%s_%s_%d.png" % (pid, lid, stamp, u), png) for (pid, _), png in zip(want, pngs) if png]
    except Exception as e:
        log("OWM ERROR %r" % (e,))
        return []


def field_pics(q, info, lid, u):
    """forecast maps drawn from a gridded forecast (fieldmaps.py): temp 8, rain 16, symbols 32, wind 64, cloud 128.
    type digit 1 = first frame, 2 = 8 frames 3 h apart. Falls back to OpenWeather current-conditions tiles."""
    t = q.get("type", "")
    if not re.match(r"^\d{7}$", t):
        return []
    want = [(pid, name, int(t[idx])) for pid, name, idx in ((8, "temp", 1), (16, "rain", 2), (32, "symb", 3), (64, "wind", 4), (128, "cloud", 5))
            if t[idx] in "12"]
    if not want:
        return []
    try:
        w = min(max(int(q.get("scrw", 200)), 1), 400)
        h = min(max(int(q.get("scrh", 230)), 1), 400)
        lat = float(q.get("lat") or info["lat"])
        lon = float(q.get("lon") or info["lon"])
        tz = ZoneInfo(info.get("timezone") or "UTC")
        res = fieldmaps.render_set([n for _, n, _ in want], lat, lon, w, h, u, 8 if any(m == 2 for _, _, m in want) else 1)
        out = []
        for pid, name, mode in want:
            for tm, png in (res[name] if mode == 2 else res[name][:1]):
                out.append(("%d_%s_%s_%d.png" % (pid, lid, tm.astimezone(tz).strftime("%Y%m%d%H%M%S"), u), png))
        return out
    except Exception as e:
        log("FIELD ERROR %r - falling back to OpenWeather tiles" % (e,))
        return owm_pics(q, info, lid, u)


def build_zip(q):
    u = int(q.get("measure", "0")) if re.match(r"^[0123]$", q.get("measure", "")) else 0
    lid, info = location_info(q)
    if info is None:
        return None
    api_id = info["id"]
    name = info["name"]

    cur = api("/current/%s" % api_id)["current"]
    fc3 = api("/forecast/3hourly/%s?periods=8&dataset=full" % api_id)["forecast"]
    fcd = api("/forecast/daily/%s?periods=10&dataset=full" % api_id)["forecast"]

    # 1: observations
    o = ["#time#station_name#temp#windc#dewp#rhum#rain#visibility#pres#winds#windd#symbol#station_distance#station_direction"]
    pres = ""
    if cur.get("pressure") is not None:
        pres = "%.1f" % (hpa2in(cur["pressure"]) if u in (1, 2) else cur["pressure"])
    vis = ""
    if cur.get("visibility") is not None:
        vis = rnd(m2mi(cur["visibility"])) if u == 2 else cur["visibility"]
    o.append("#".join(str(x) for x in [
        ts(cur["time"]), name,
        conv_temp(cur["temperature"], u), conv_temp(cur.get("feelsLikeTemp", cur["temperature"]), u),
        conv_temp(cur["dewPoint"], u) if cur.get("dewPoint") is not None else "",
        val(cur.get("relHumidity")), rnd(cur.get("precipRate") or 0) if u in (0, 3) else "%.2f" % mm2in(cur.get("precipRate") or 0),
        vis, pres, conv_wind(cur["windSpeed"], u), val(cur.get("windDir")), sym(cur.get("symbol")), "", ""]))

    # 2: spot forecast
    s = ["#time#temp#rain#windd#winds#rhum#symbol"]
    for f in fc3[:8]:
        s.append("#".join(str(x) for x in [
            ts(f["time"]), conv_temp(f["temperature"], u), conv_rain(f.get("precipAccum") or 0, u),
            val(f.get("windDir")), conv_wind(f["windSpeed"], u), val(f.get("relHumidity")), sym(f.get("symbol"))]))

    # 512: 10 day forecast
    d = ["#time#temp_min#temp_max#winds#windd#rain#rainp#symbol#rhum"]
    for f in fcd[:10]:
        rh = f.get("minRelHumidity")
        if rh is not None and rh > 100: rh = 100
        d.append("#".join(str(x) for x in [
            ts(f["date"]), conv_temp(f["minTemp"], u), conv_temp(f["maxTemp"], u),
            conv_wind(f["maxWindSpeed"], u), val(f.get("windDir")), conv_rain(f.get("precipAccum") or 0, u),
            val(f.get("precipProb")), sym(f.get("symbol")), val(rh)]))

    with ThreadPoolExecutor(max_workers=3) as ex:
        jobs = [ex.submit(f, q, info, lid, u) for f in (radar_pics, sat_pics, field_pics)]
        pics = [p for j in jobs for p in j.result()]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in pics:
            z.writestr(name, data)
        z.writestr("1_%s_%d.dat" % (lid, u), "\n".join(o) + "\n")
        z.writestr("2_%s_%d.dat" % (lid, u), "\n".join(s) + "\n")
        z.writestr("512_%s_%d.dat" % (lid, u), "\n".join(d) + "\n")
    return buf.getvalue()


def do_search(q):
    query = q.get("search", "")
    if len(query) < 2:
        return ""
    lang = LANGS.get(int(q["lang"]), "en") if q.get("lang", "").isdigit() else "en"
    cc = (q.get("country") or q.get("county") or "").lower()
    res = api("/location/search/%s?lang=%s" % (urllib.parse.quote(query), lang), 3600)["locations"][:100]
    api_v2 = float((re.match(r"\d+(?:\.\d+)?", q.get("ver", "") or "") or re.match(r"(0)", "0")).group()) >= 1.4
    out = []
    for l in res:
        c = TZCC.get(l.get("timezone", ""), "")
        if cc and c != cc:
            continue
        label = l["name"]
        area = l.get("state") or l.get("adminArea2") or l.get("adminArea")
        if area and area != l["name"]:
            label += ", " + area
        label += ", " + l.get("country", "")
        row = [str(l["id"]), c, label]
        if api_v2:
            row += [str(l["lat"]), str(l["lon"])]
        out.append(";".join(row))
    return "\n".join(out) + ("\n" if out else "")


class H(BaseHTTPRequestHandler):
    server_version = "nginx"

    def log_message(self, *a):
        pass

    def reply(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(n, 65536)).decode("utf-8", "replace")
        self.do_GET(body)

    def do_GET(self, body=""):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
        q.update({k: v[0] for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items()})
        safe = {k: v for k, v in q.items() if k not in ("imei", "imsi", "guid")}
        log("%s %s %s" % (self.client_address[0], u.path, safe))
        try:
            if u.path.endswith("/login.php"):
                if not q.get("search"):
                    return self.reply(200, "text/plain", "Internal error.\n")
                return self.reply(200, "text/plain", do_search(q))
            if u.path.endswith("/data-loc.php") or u.path.endswith("/data3.php"):
                if "type" not in q:
                    return self.reply(200, "text/plain", "")
                z = build_zip(q)
                if z is None:
                    return self.reply(200, "text/plain", "ERROR: Location missing.\n")
                return self.reply(200, "application/zip", z)
            return self.reply(404, "text/plain", "not found\n")
        except Exception as e:
            log("ERROR %r" % (e,))
            return self.reply(200, "text/plain", "ERROR: Internal error.\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

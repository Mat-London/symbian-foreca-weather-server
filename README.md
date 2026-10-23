# Symbian weather server for the Foreca weather app

*Foreca for Nokia S60 / Symbian – revived: a bridge server to the current Foreca Weather API, a SIS patcher, and radar, satellite and forecast maps.*

The old **Foreca Weather app for Nokia S60** (v1.4.x) kept working for about 15 years after Foreca stopped supporting
it. On 23 October 2026 it died with *"Invalid server response"*: the legacy server `pw.foreca.com/fd/*.php` stopped
running its PHP. This project brings it back:

1. a small **bridge server** that speaks the app's old protocol and fetches the data from the current
   [Foreca Weather API](https://developer.foreca.com/) (free key for private use), and
2. a **SIS patcher** that points the app at your server instead of `pw.foreca.com`
   (or, at home, a DNS override that needs no patching at all).

It also brings back the **maps**, which the Foreca API's free plan does not include: radar, satellite, temperature,
rain, wind, cloud and weather-symbol maps, drawn as forward-looking 8-frame animations, in the selected units.

Tested on a **Nokia E52** with **Foreca 1.4.4** (S60 3rd Edition). Other models/versions may work if the SIS layout
matches; the patcher checks its assumptions and stops if they don't hold.

> Not affiliated with Foreca. No Foreca code, graphics or app binaries are in this repository – bring your own SIS.
> See [NOTICE.md](NOTICE.md) for data sources and their terms.

## What you need

* a machine that stays on (Linux, Python 3.9+, Apache/nginx for the web side) reachable from your phone
* a **Foreca Weather API token** (Foreca offers free access for private use – see developer.foreca.com)
* your own copy of the **Foreca 1.4.4 E52 Weather.sis**
* a phone that can install an unsigned SIS (the patched file has no signature; use your usual route – e.g. RomPatcher+ –
  or sign it yourself)

## Part 1 – run the bridge

```bash
git clone https://github.com/Mat-London/symbian-foreca-weather-server && cd symbian-foreca-weather-server
pip install -r bridge/requirements.txt          # Pillow + numpy (Debian/Ubuntu: apt install python3-pil python3-numpy)
bash data/fetch_data.sh                         # Natural Earth coastlines/land for the map overlays
cp bridge/foreca.env.example bridge/foreca.env  # put your token in it, then: chmod 600 bridge/foreca.env
export BRIDGE_CONTACT=you@example.com           # OpenStreetMap-style tile servers want a way to reach you
python3 bridge/bridge.py 8099                   # listens on 127.0.0.1:8099
```

Test it:

```bash
curl "http://127.0.0.1:8099/fd/login.php?lang=1&search=paris&ver=1.4.3"
# 102988507;fr;Paris, France;48.8534;2.3488 ...
curl -X POST -d "location=102988507&type=2222222&measure=0&scrw=240&scrh=245&ver=1.4.3" \
     -o test.zip http://127.0.0.1:8099/fd/data-loc.php && unzip -l test.zip
```

Put a web server in front so the phone can reach it – see `deploy/apache-http.conf.example` (and
`deploy/apache-https.conf.example`) – and run the bridge as a service (`deploy/foreca-bridge.service.example`).
The bridge logs every request (without IMEI/IMSI/GUID) to `bridge/bridge.log`.

## Part 2 – point the app at your server

### Option A – DNS override (no patching, home Wi-Fi only)

The unpatched app calls plain HTTP to `pw.foreca.com`. If your router/Pi-hole/dnsmasq answers
`pw.foreca.com -> <your server>` and your web server has a vhost for `pw.foreca.com` on port 80, the original SIS
just works while the phone is on your Wi-Fi.

### Option B – patch the SIS (works anywhere)

The server name is baked into the app's code as a UTF-16 string, so the patch replaces `pw.foreca.com` with a host
of **exactly the same length – 13 characters** – that you control (for example `pw.example.io`). Make the DNS name
resolve to your server.

```bash
python3 tools/build_foreca_sis.py "Foreca 1.4.4 E52 Weather.sis" Foreca_patched.sis pw.example.io http
python3 tools/verify_sis.py       "Foreca 1.4.4 E52 Weather.sis" Foreca_patched.sis pw.example.io
```

`verify_sis.py` ends with `changed images 2` and `identical file records 75 of 77`. One `MISMATCH` line for the
`c:\data\2000E024\*.*` wildcard record is expected and harmless (that record is left untouched).

* `http` build: the app calls `http://pw.example.io/fd/…` (same layout as the original). **This is the one confirmed working.**
* `https` build: calls `https://pw.example.io/…` (root paths). Needs a phone with working TLS 1.2+ and current root
  certificates (for S60 see [nnproject.cc/tls](https://nnproject.cc/tls/)). Experimental – not re-tested after the
  bridge's first bug fixes.

What the patcher does: decompresses the app's executables (Symbian's own deflate, ported in `tools/symdeflate.py`),
swaps the host, stores the image uncompressed, recomputes the E32 header CRC and the SIS hashes/lengths/CRC16s,
drops the signature chain and bumps the version so it installs over the original. If the build number is
already higher on the phone, uninstall the old Foreca first.

## Part 3 – install and use

Install the patched SIS, open Foreca, search for a place or use GPS. If the app misbehaves after earlier failed
attempts, delete the contents of `C:\Data\2000E024\` (and `E:\Data\2000E024\`) and try again – the app caches per location.

## The maps

| App view | Source | Notes |
|---|---|---|
| Radar | [RainViewer](https://www.rainviewer.com/api.html) over OpenStreetMap | last ~80 min, free tier |
| Satellite | EUMETSAT Meteosat/MTG (lon -65..100), NASA GIBS GOES/Himawari elsewhere | + coastline/border overlay; Asia-Pacific infrared is redrawn as white cloud over land/sea |
| Temperature, rain, wind, cloud, symbols | [Open-Meteo](https://open-meteo.com/) grid, drawn by `bridge/fieldmaps.py` | 8 frames, 3 h apart; wind/temperature numbers follow the app's units |

The Foreca API's own map product is not part of the free plan (`403 Product unavailable on your plan`); if you have
it, `bridge/maps.py` is the place to swap tile sources.

Not implemented: the country/city browsing list (search works), `update.txt`, map legends.

## Repository layout

```
bridge/    bridge.py (protocol server), maps.py (radar, satellite), fieldmaps.py (forecast maps)
tools/     build_foreca_sis.py, verify_sis.py, symdeflate.py, e32crc.py
deploy/    Apache + systemd examples
docs/      PROTOCOL.md – what the app sends and expects
data/      fetch_data.sh (downloads Natural Earth data; not committed)
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Invalid server response" | bridge down, wrong host/DNS, or the web server isn't proxying `/fd/` – check `bridge.log` and the web server's access log |
| App crashes on launch, nothing in the logs | stale cached data on the phone (see Part 3) |
| Requests reach the server but weather is empty | Foreca token wrong/expired – see `bridge.log` for `ERROR` lines |
| A map view is blank | that source failed or has no coverage; `bridge.log` shows `SAT`/`FIELD`/`MAP` errors |

## Licence

MIT (see [LICENSE](LICENSE)); `tools/symdeflate.py` is EPL 1.0. See [NOTICE.md](NOTICE.md).

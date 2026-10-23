# The legacy Foreca mobile protocol (S60 app v1.4.x)

The old app talks plain HTTP to `http://pw.foreca.com/fd/`. Two endpoints matter. The bridge implements both.

## `login.php` – location search

`GET /fd/login.php?lang=1&search=paris&ver=1.4.3[&country=FR]`

Returns one location per line, `;`-separated:

```
id;country;name[;lat;lon]
102988507;fr;Paris, France;48.8534;2.3488
```

`lat;lon` are only expected when `ver` >= 1.4. `country` is a lower-case ISO code. With no `search` the
original returned a zip of the country/city lists (not implemented here; search works without it).

## `data-loc.php` – the weather package

`POST /fd/data-loc.php` (form-encoded body, also accepted as query string):

| parameter | meaning |
|---|---|
| `location` | Foreca location id (searched places) |
| `lat`, `lon`, `id` | GPS position and the app's own id (GPS locations) |
| `lang` | language |
| `measure` | units: `0` metric (m/s), `1` imperial (mph, deg C), `2` US (mph, deg F), `3` km/h |
| `scrw`, `scrh` | phone screen size; maps are cut to this size |
| `type` | 7 digits, one per map: radar, temperature, rain, symbols, wind, cloud, satellite. `0` = none, `1` = single image, `2` = animation |

The reply is a **zip** containing:

* `1_<id>_<units>.dat` – current observation
* `2_<id>_<units>.dat` – 8-entry spot forecast
* `512_<id>_<units>.dat` – 10-day forecast
* map images `<prodid>_<id>_<YYYYMMDDHHMMSS>_<units>.png` (local time of the location)

`.dat` files are `#`-delimited with a header line starting `#`:

```
1:   #time#station_name#temp#windc#dewp#rhum#rain#visibility#pres#winds#windd#symbol#station_distance#station_direction
2:   #time#temp#rain#windd#winds#rhum#symbol
512: #time#temp_min#temp_max#winds#windd#rain#rainp#symbol#rhum
```

Times are local, `YYYYMMDDHHMMSS` (daily rows use 12:00:00). `symbol` is a Foreca code such as `d320` / `n310`
(day/night, cloud, precipitation), which the current Foreca API still uses. Wind speed unit follows `measure`;
temperatures are Fahrenheit only for `measure=2`.

Map product ids: `4` radar, `8` temperature, `16` rain, `32` symbols, `64` wind, `128` cloud, `256` satellite.
The original server rendered unit-specific images (km/h wind, mph wind, Fahrenheit temperature), so numbers drawn
on a map have to match `measure`. Animations have up to 8 frames.

## Errors the app tolerates

The app caches the last package per location. A reply that is not a valid zip (for example an HTML error page) has been
observed to make the app crash on launch afterwards; clear `C:\Data\2000E024\` on the phone if that happens.

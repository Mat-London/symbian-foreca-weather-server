# Third-party notices

* `tools/symdeflate.py` is a Python port of the Symbian e32tools Huffman/inflater code and remains under the
  **Eclipse Public License 1.0** (Symbian Foundation source). Everything else is MIT.
* **No Foreca code, graphics or application binaries are included.** You must supply your own copy of the
  Foreca app SIS. This project is not affiliated with or endorsed by Foreca.
* Data sources used at runtime, each under its own terms (please read them and keep your use light and personal):
  * Foreca Weather API - your own API token, used under Foreca's terms for private use.
  * [Open-Meteo](https://open-meteo.com/) - forecast grids for the temperature/rain/wind/cloud/symbol maps (free for non-commercial use).
  * [RainViewer](https://www.rainviewer.com/api.html) - radar tiles.
  * [EUMETSAT EUMETView](https://view.eumetsat.int/) - Meteosat / MTG satellite imagery (Europe, Africa, west Asia).
  * [NASA GIBS](https://earthdata.nasa.gov/gibs) - Himawari and GOES imagery (Asia-Pacific, Americas).
  * [OpenStreetMap](https://www.openstreetmap.org/copyright) tiles as the base map - (c) OpenStreetMap contributors, ODbL.
    Respect the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) and set `BRIDGE_CONTACT`.
  * [Natural Earth](https://www.naturalearthdata.com/) coastlines, borders, land and lakes - public domain (downloaded by `data/fetch_data.sh`).
  * OpenWeather tiles - optional fallback only.

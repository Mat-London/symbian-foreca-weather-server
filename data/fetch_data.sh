#!/bin/bash
# Download the Natural Earth (public domain) coastline, border, land and lake data used for the map overlays.
cd "$(dirname "$0")" || exit 1
B=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
for f in ne_50m_coastline ne_50m_admin_0_boundary_lines_land ne_50m_land ne_50m_lakes; do
  curl -fsSL -o "$f.geojson" "$B/$f.geojson" && echo "ok $f" || echo "FAILED $f"
done

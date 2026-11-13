"""GeoJSON points. Inputs are bounded to a loose West Bengal bounding box."""

from typing import Any

from pydantic import BaseModel, Field

# Loose bbox around West Bengal (lat 21.5-27.3, lng 85.8-89.9) with a small margin.
LAT_MIN, LAT_MAX = 21.4, 27.4
LNG_MIN, LNG_MAX = 85.7, 90.0


class GeoPoint(BaseModel):
    lat: float = Field(ge=LAT_MIN, le=LAT_MAX)
    lng: float = Field(ge=LNG_MIN, le=LNG_MAX)

    def to_geojson(self) -> dict[str, Any]:
        return {"type": "Point", "coordinates": [self.lng, self.lat]}


def point_out(geo: dict[str, Any]) -> GeoPoint:
    lng, lat = geo["coordinates"]
    return GeoPoint.model_construct(lat=lat, lng=lng)


def parse_near(value: str | None) -> GeoPoint | None:
    """'lat,lng' query param → GeoPoint (raises ValueError on bad input)."""
    if not value:
        return None
    try:
        lat_s, lng_s = value.split(",")
        return GeoPoint(lat=float(lat_s), lng=float(lng_s))
    except ValueError as exc:
        raise ValueError("near must be 'lat,lng' inside West Bengal") from exc

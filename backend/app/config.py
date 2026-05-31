"""Shared configuration: filesystem paths, defaults and environment values."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ASSETS_DIR = PROJECT_ROOT / "assets"

# Directory the production deployment lives in (used by the admin restart hook).
DEPLOY_DIR = Path("/home/jrpg/Japan-RPG")

# Public origin allowed for CORS / used for the login CSRF check.  Empty means
# cross-origin requests are blocked (Starlette default for an empty list).
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "")

DEFAULT_SCENARIO = """\
Der Spieler heißt {player_name} und ist auf einem Sabbatical in Shimokitazawa, Tokio.
Er hat Aoi (林あおい) online in einem Sprachaustausch-Forum kennengelernt.
Heute treffen sie sich zum ersten Mal persönlich. Aoi zeigt {player_name} die Gegend \
und hilft ihm, sein Japanisch in echten Alltagssituationen zu verbessern.

SPIELSTART:
Aoi trifft {player_name} am Südausgang des Bahnhofs Shimokitazawa. \
Es ist ein sonniger Nachmittag. \
Sie erkennt ihn sofort und ruft fröhlich nach ihm. \
Aoi begrüßt {player_name} auf Japanisch — einfaches, anfängerfreundliches Japanisch. \
Sie ist aufgeregt, ihn endlich persönlich zu treffen, nachdem sie monatelang online gechattet haben. \
Verwende character=aoi, expression=happy, background=shimokitazawa_station. \
Dies ist die ERSTE Begegnung — halte den Ton freundlich aber noch etwas formell.\
"""

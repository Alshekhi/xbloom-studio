"""Brew Stories: a line about each pour, and between pours a story about the coffee.

Shown only. A brew's texts are planned from its recipe (`plan`), written from
the content shipped here and the bag's Coffee Lab record (`content`,
`compose`), remembered across brews (`memory`), and published as the brew
moves on (`runtime`, `entities`).
"""
from __future__ import annotations

MODES = ["off", "built_in", "agent"]
# The languages the stories are written in (content/<lang>.json). Until one is
# picked, Home Assistant's own if it is one of these, otherwise English.
LANGUAGES = ["en", "ar"]

# How fast the machine pours, ml/s: a recipe's flow rate setting does not
# predict it (3.0 set, about 3.3 to 3.6 measured), so the plan uses what was
# measured.
POUR_PACE_ML_S = 3.3
# A story part needs about this long on screen to be read.
MIN_READ_S = 30

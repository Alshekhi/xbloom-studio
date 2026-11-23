"""What xbloom_brew_started carries — a contract consumers rely on."""
from custom_components.xbloom import brew_started_payload

RECIPE = {"dose_g": 17.0, "grinder_size": 50.0, "pours": [
    {"volume_ml": 30.0, "temperature_c": 92.0, "flow_rate": 3.2, "pause_s": 20},
    {"volume_ml": 225.0, "temperature_c": 92.0, "flow_rate": 3.2, "pause_s": 0},
]}


def test_the_payload_keeps_its_keys_and_adds_the_brews_settings():
    payload = brew_started_payload("R", 2, RECIPE, {"run_id": "x", "bean_id": "b"})
    assert {"recipe_name", "total_pours", "recipe_water_ml", "pours", "run_id", "bean_id"} <= set(payload)
    assert payload["recipe_water_ml"] == 255
    assert payload["settings"] == {"grind": 50.0, "water_ml": 255.0, "ratio": 15.0,
                                   "temperature_c": 92.0, "flow_rate": 3.2, "dose_g": 17.0}

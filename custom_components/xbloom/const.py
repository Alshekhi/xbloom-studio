"""Constants for the xBloom Studio integration.

BLE-only by default; an optional cloud layer (recipe sync + firmware check)
activates once the user logs in with an xBloom account.
"""

DOMAIN = "xbloom"

# Config entry data keys — machine (BLE)
CONF_PRODUCT_ID = "product_id"  # serial number tail (e.g. "ABC123")
CONF_BLE_NAME = "ble_name"      # advertised BLE name (e.g. "XBLOOM ABC123")
CONF_BLE_ADDRESS = "ble_address"  # Bluetooth address, learned from the name once

# Config entry data keys — optional cloud account. Stored under a single
# `cloud` sub-dict in entry.data so a logged-out entry has no cloud key at all.
CONF_CLOUD = "cloud"
CONF_CLOUD_EMAIL = "email"         # account email (also used for re-login)
CONF_CLOUD_PASSWORD = "password"   # stored ONLY if the user opts in (remember)
CONF_CLOUD_MEMBER_ID = "member_id"  # member.tableId from the login response
CONF_CLOUD_TOKEN = "token"          # session token for the recipe API
CONF_CLOUD_REMEMBER = "remember"    # whether the password is stored for auto-refresh

# Firmware flashing is off by default: the OTA transfer is validated byte-exact
# against a real capture but not yet proven on live hardware, and a flash can
# brick the machine. The Install button appears only once the user arms this.
CONF_ENABLE_FLASHING = "enable_firmware_flashing"  # entry.data flag

# Coffee Lab — bag inventory and brew records — is off unless switched on, so
# an install that only wants the machine sees none of it. entry.data flag.
CONF_COFFEE_LAB = "coffee_lab"

# The brewers offered when recording a brew made without the machine; the
# person edits the list. Seeded with brand names only, which read the same in
# any language. entry.data.
CONF_BREWERS = "coffee_lab_brewers"
DEFAULT_BREWERS = ("V60", "Chemex", "AeroPress", "Kalita Wave", "Clever")

# Where brew callbacks may be sent, by name: {name: {"url", "secret"}}. A caller
# names one; it never gives a URL. entry.data.
CONF_CALLBACK_TARGETS = "callback_targets"

# Sent when anything Coffee Lab shows has changed; its entities re-read.
SIGNAL_COFFEE_LAB_UPDATED = f"{DOMAIN}_coffee_lab_updated"

# How long a Connect (live) session may sit idle before HA auto-disconnects,
# handing the machine back to the iOS app. There is no upstream value to mirror
# (the app leans on the phone OS killing the link when it backgrounds; HA's link
# lives on the always-on host), so this is a deployment choice. The library gives
# the default (mode_listener.IDLE_TIMEOUT_SEC); this overrides it. entry.data.
CONF_IDLE_TIMEOUT = "idle_timeout_s"


# Firmware updates

**Read this before you enable it.** Firmware flashing is **opt-in and off by default**, and it is the one feature here that can
permanently damage your machine. Enable it only if you accept that.

The update is downloaded from xBloom, its MD5 is verified before anything is sent, and every
block is acknowledged by the machine as it's written. That makes a bad flash unlikely — it
does not make it impossible. **Bluetooth is a wireless link, and a wireless link can drop.**
If it drops in the middle of a firmware write, the machine can be left unbootable, with no
way to recover it from Home Assistant.

If you choose to use it:

- Keep the machine powered and close to the Bluetooth adapter for the whole flash.
- Never start a flash during a brew, or when you're about to leave the house.
- Don't restart Home Assistant while one is running.

**You do this entirely at your own risk.** This is unofficial software talking to an
undocumented protocol that was worked out by inspection, and it is not endorsed by or
connected to xBloom in any way. The authors and contributors accept **no responsibility and
no liability** for any damage to your machine, loss of warranty, or any other loss arising
from using this integration — the firmware updater above all. If that isn't a risk you want
to take, leave the feature switched off; everything else works without it.

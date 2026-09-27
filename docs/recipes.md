# Recipes

## Optional: xBloom cloud sign-in

The same **Configure** menu has **Sign in to xBloom cloud**. Sign in with your xBloom account to sync recipes: once signed in, the cloud becomes the home for your recipes and every create, edit, and delete is written back to your account. If you already have local recipes, you'll be asked whether to upload them or discard them.

Tick **Remember my credentials** to store your password locally (in `.storage`, next to the session token) so the session refreshes itself when the token expires. It's only ever sent to xBloom's sign-in endpoint. Leave it unticked for more privacy: only the token is kept, and you'll be prompted to sign in again when it expires. Use **Sign out of xBloom cloud** to clear everything and return to the local library (your synced recipes stay cached locally). The cloud is entirely optional; leaving it out keeps the integration BLE-only.

## Keeping recipes in sync

Recipe sync is event-driven, not polled: changes you make in Home Assistant apply immediately, and the Configure recipe lists pull fresh from the cloud each time you open them. A recipe you added or edited on your phone shows up in the dashboard dropdowns after you press the **Refresh Recipes** button.

## Archiving a recipe

A recipe you are not using can be archived instead of deleted: it leaves the
recipe list and is kept whole in Home Assistant, to restore later. Signed in
to the xBloom cloud, you choose whether it also leaves the cloud — kept there,
it stays in the xBloom app and is only hidden in Home Assistant. Restoring
puts it back where the library is: signed in, in the cloud (created again if
it was removed, under a new cloud id, so an older share link to it no longer
works); signed out, in the local library.

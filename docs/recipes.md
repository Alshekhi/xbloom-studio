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

## Community recipes

### Signed in to the xBloom account

Signed in, the **Community** tab offers what the xBloom app's Recipes tab
offers the account — chosen by xBloom for it, so its country's roasters and
pods: **For You**, one recipe at a time, with **Another** to ask for a
different one; **Trending Recipes**; and **Tea Recipes**. Each shows the
recipe and, for a pod, its coffee, and **Add** puts it in your recipe
library. xPod recipes are marked as such and shown unless **Show xPod
Recipes** is turned off. Signed out, these are not shown.

### The community hub

xBloom's [community hub](https://collective.xbloom.com) holds recipes people
have shared. The integration searches and reads it without an account, and
offers Studio recipes only.

On the dashboard's **Community** tab, type a keyword in **Community Search**,
narrow it with **Community Origin** and order it with **Community Sort**
(newest, most liked or most downloaded), then press **Search Community**.
**Community Matches** says how many recipes matched, and **Community Recipe**
lists them; picking one reads it in full — the coffee it was made for, its
dose, ratio, grind and pours — into that select's attributes, where the
dashboard shows it. **Add Community Recipe** puts it in your recipe
library — in the cloud when you are signed in — where it brews like any other.

**Suggest Community Recipe** fills the picker without a search, choosing the
most downloaded Studio recipe for the origin and process of the bag in use, then for its
origin alone, then any. A recipe already in your library, or one needing more
coffee than the bag has left, is passed over, and recipes for the drippers your
library already uses come first. **Drink**, beside it, keeps them to hot or
iced recipes. Among those, the recipes sharing most with
the bag lead: its process, a varietal, its roast, and the flavors named in its
roaster notes. The picked recipe's `fits` says which it shares.

The actions are `xbloom.search_community`, `xbloom.get_community_recipe` and
`xbloom.suggest_community`, each returning what it found as a response.

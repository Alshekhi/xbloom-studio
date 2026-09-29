# Automations

There are two ways to get spoken brew announcements: import a ready-made
blueprint, or write your own automation. Most people want the blueprints.

The events and states an automation can trigger on are listed in
[Events](events.md).

## Ready-made blueprints

Three blueprints ship with the integration. Each one is configured entirely
through form fields — pick a speaker, pick a language, done — with no YAML to
edit.

| Blueprint | What it does | Import |
|---|---|---|
| **Brew announcements** | Announces the coffee ready, or a brew that could not start, to the whole home; the brew starting, each step of it, and a cancellation can go to a speaker by the machine, the only one that says the recipe name. | [Import][bp-brew] |
| **Live-session announcements** | Speaks live feedback while you turn the machine's knobs — weight, grind size, temperature, which module you're on. Needs the **Connect** switch on. | [Import][bp-live] |
| **Machine fault announcements** | Speaks up when the machine runs out of water or beans, or reports a dose or gear problem. | [Import][bp-fault] |

[bp-brew]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Fbrew_announce.yaml
[bp-live]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Flive_control_announce.yaml
[bp-fault]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Fmachine_fault_announce.yaml

Each **Import** link opens the blueprint straight in your own Home Assistant. If
a link doesn't work, the files are in
[`blueprints/automation/xbloom/`](../blueprints/automation/xbloom/) — copy them into
`config/blueprints/automation/`, or paste the raw URL into **Settings →
Automations & Scenes → Blueprints → Import Blueprint**.

**Every blueprint speaks through whatever you have.** The **How to announce**
field offers three choices:

- **Alexa** — via the [Alexa Media Player](https://github.com/alandtse/alexa_media_player) custom integration.
- **Speaker (TTS)** — any TTS engine (Piper, Google Translate, Cloud) on any media player.
- **Notify service** — any `notify.*` service, so the text arrives as a phone notification instead of speech.

All three are **bilingual, English or Arabic**, chosen per automation. You can
import a blueprint more than once — for example, English on the kitchen speaker
and Arabic on another.

## Write your own

The blueprints cover the common jobs. Write your own if you want different
wording, a different service, or a trigger they don't offer. These are the
starting points people ask for most.

Every example speaks through `tts.speak`. Replace that action with any `notify.*`
service to get a phone notification instead — the triggers and templates are the
same either way.

### Announce the brew from start to finish

The main one. Without it a brew is silent: the machine grinds, pauses, pours, and finishes
with nothing to tell you which stage you're at or when to come back. This narrates the whole
cycle, and names the recipe if Home Assistant started the brew.

```yaml
alias: Narrate the xBloom brew
triggers:
  - trigger: event
    event_type: xbloom_brew_started
    id: started
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: grinding
    id: grinding
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: brewing
    id: pouring
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: done
    id: ready
actions:
  - variables:
      message: >-
        {% if trigger.id == 'started' %}
          Starting {{ trigger.event.data.get('recipe_name') or 'your coffee' }}
        {% elif trigger.id == 'grinding' %}Grinding the beans
        {% elif trigger.id == 'pouring' %}Pouring
        {% else %}Your coffee is ready{% endif %}
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.kitchen
      message: "{{ message }}"
```

The three status triggers work whether you started the brew from Home Assistant or by hand
on the machine. The `xbloom_brew_started` trigger is the only one that knows the recipe
name, and it fires only for brews Home Assistant started.

**Want just the ending?** Keep the `ready` trigger and drop the other three.

### Say something when the machine needs you

A brew that stalls because the tank ran dry looks exactly like a brew that's still working.
This is the difference between waiting two minutes and waiting twenty.

```yaml
alias: xBloom needs attention
triggers:
  - trigger: state
    entity_id: sensor.xbloom_studio_machine_status
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state not in ['ok', 'unknown', 'unavailable'] }}"
actions:
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.kitchen
      message: >-
        {% set s = trigger.to_state.state %}
        {% if s == 'no_water' %}The xBloom is out of water
        {% elif s == 'no_beans' %}The xBloom is out of beans
        {% elif s == 'gear_position_error' %}Check the xBloom's dripper position
        {% else %}The xBloom reported a dose or water problem{% endif %}
```

### Start the coffee without walking to the machine

`xbloom.start_brew` with no fields brews whatever `select.xbloom_studio_recipe` is set to,
which is all a dashboard button or a voice assistant needs. The optional fields rescale the
recipe **for that brew only** — your saved recipe is never modified.

```yaml
alias: Morning coffee
triggers:
  - trigger: time
    at: "06:45:00"
conditions:
  - condition: state
    entity_id: sensor.xbloom_studio_brew_status
    state: idle
actions:
  - action: xbloom.start_brew
    data:
      recipe_name: Ethiopia Yirgacheffe
      dose: 18
      ratio: 16
```

`grind_size` overrides the grind for one brew, and `use_preground: true` skips the grinder
entirely. Drop the `data:` block completely to just brew the selected recipe as saved.

> The **Connect** switch holds the Bluetooth link open so the machine can stream live
> feedback. While it's on, the official iOS app can't connect. Turn it off when you're done
> if you want to use the app.

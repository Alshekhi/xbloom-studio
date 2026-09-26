"""Build the example dashboard in each language from one layout.

    python3 dashboard/build.py

The cards are the same in every language; only the dashboard's own text —
headings, the few lines built from data, confirmations — differs, and it lives
in TEXT below. Entity names and states are translated by Home Assistant
itself. Edit the layout or the text here, then rebuild; never edit the built
files by hand, or the languages drift apart.
"""
from __future__ import annotations

from pathlib import Path

import yaml

HERE = Path(__file__).parent

TEXT = {
    "en": {
        "view_brew": "Brew", "view_stats": "Stats", "view_bags": "Bags", "view_xbloom": "xBloom",
        "h_now": "Right now", "h_in_progress": "Brew in progress", "h_bag": "Current bag",
        "h_brew": "Brew with the xBloom", "h_adjust": "Adjust this brew",
        "h_save": "Save as a new recipe", "h_manual": "Manual brew", "h_stats": "Coffee stats",
        "h_by_brewer": "By brewer", "h_bags": "Bags on hand", "h_connection": "Connection & status",
        "h_modules": "Modules", "h_grinder": "Grinder", "h_brewer": "Brewer", "h_scale": "Scale",
        "h_library": "Recipe library", "h_settings": "Settings", "h_tools": "Connection tools",
        "h_voice": "Voice announcements", "h_updates": "Updates", "h_events": "Recent machine events",
        "go_home": "Return the machine to its home screen to brew a recipe.",
        "show_advanced": "Show brew adjustments", "show_per_pour": "Show each pour",
        "show_manual": "Show manual brew",
        "confirm_stop": "Stop the brew in progress?", "confirm_record": "Record this manual brew?",
        "confirm_run": "Run the chosen action on the selected recipe?",
        "add_recipes": "Add or edit recipes", "add_bags": "Add or edit bags",
        "h_archive": "Archived recipes",
        "this_brew": "This brew", "coffee": "Coffee", "water": "Water", "ratio": "Ratio",
        "pour": "Pour", "temp": "Temp", "pick_recipe": "Pick a recipe to see its pours.",
        "coffee_used": "Coffee used", "water_brewed": "Water brewed",
        "previous": "Brews in the period before", "other": "Other",
        "h_charts": "Brew history", "brews_daily": "Brews per day", "brews_monthly": "Brews per month",
        "coffee_weekly": "Coffee used per week", "water_weekly": "Water brewed per week",
        "xbloom_brews": "xBloom", "manual_brews": "Manual",
        "sep": ", ", "g": "g", "ml": "ml",
        "in_use": "in use", "unopened": "unopened", "open": "open", "g_left": "g left",
        "not_tracked": "not tracked", "no_bags": "No open or unopened bags.",
        "speak_brew": "Speak brew progress", "speak_faults": "Speak machine faults",
        "speak_live": "Speak live readings",
    },
    "ar": {
        "view_brew": "التحضير", "view_stats": "الإحصاءات", "view_bags": "الأكياس", "view_xbloom": "xBloom",
        "h_now": "الآن", "h_in_progress": "تحضير جار", "h_bag": "الكيس الحالي",
        "h_brew": "التحضير بماكينة xBloom", "h_adjust": "تعديل هذا التحضير",
        "h_save": "حفظ كوصفة جديدة", "h_manual": "تحضير يدوي", "h_stats": "إحصاءات القهوة",
        "h_by_brewer": "حسب أداة التحضير", "h_bags": "الأكياس المتوفرة", "h_connection": "الاتصال والحالة",
        "h_modules": "الوحدات", "h_grinder": "المطحنة", "h_brewer": "وحدة الصب", "h_scale": "الميزان",
        "h_library": "مكتبة الوصفات", "h_settings": "الإعدادات", "h_tools": "أدوات الاتصال",
        "h_voice": "الإعلانات الصوتية", "h_updates": "التحديثات", "h_events": "أحدث أحداث الماكينة",
        "go_home": "أعد الماكينة إلى شاشتها الرئيسية لتحضير وصفة.",
        "show_advanced": "إظهار تعديلات التحضير", "show_per_pour": "إظهار كل صبة",
        "show_manual": "إظهار التحضير اليدوي",
        "confirm_stop": "إيقاف التحضير الجاري؟", "confirm_record": "تسجيل هذا التحضير اليدوي؟",
        "confirm_run": "تنفيذ الإجراء المختار على الوصفة المختارة؟",
        "add_recipes": "إضافة الوصفات أو تعديلها", "add_bags": "إضافة الأكياس أو تعديلها",
        "h_archive": "الوصفات المؤرشفة",
        "this_brew": "هذا التحضير", "coffee": "القهوة", "water": "الماء", "ratio": "النسبة",
        "pour": "الصبة", "temp": "الحرارة", "pick_recipe": "اختر وصفة لعرض صباتها.",
        "coffee_used": "القهوة المستخدمة", "water_brewed": "الماء المستخدم",
        "previous": "التحضيرات في الفترة السابقة", "other": "أخرى",
        "h_charts": "سجل التحضير", "brews_daily": "التحضيرات يوميا", "brews_monthly": "التحضيرات شهريا",
        "coffee_weekly": "القهوة المستخدمة أسبوعيا", "water_weekly": "الماء المستخدم أسبوعيا",
        "xbloom_brews": "xBloom", "manual_brews": "يدوي",
        "sep": "، ", "g": "غ", "ml": "مل",
        "in_use": "قيد الاستخدام", "unopened": "غير مفتوح", "open": "مفتوح", "g_left": "غ متبقية",
        "not_tracked": "غير متتبع", "no_bags": "لا توجد أكياس مفتوحة أو غير مفتوحة.",
        "speak_brew": "إعلان سير التحضير", "speak_faults": "إعلان أعطال الماكينة",
        "speak_live": "إعلان القراءات المباشرة",
    },
}

E = "xbloom_studio"
# Bags and recipes are added and edited in the integration's Configure.
INTEGRATION = "/config/integrations/integration/xbloom"
BUSY = ("grinding", "brewing")
MODULES = ("grinder", "brewer", "scale")


def heading(text: str) -> dict:
    # A markdown heading, not a heading card: only this renders a real <h2>,
    # so moving between sections by heading works.
    return {"type": "markdown", "text_only": True, "content": f"## {text}"}


def tile(entity: str, **extra) -> dict:
    card = {"type": "tile", "entity": entity, "icon_tap_action": {"action": "none"}}
    card.update(extra)
    return card


def press(entity: str, confirm: str | None = None, **extra) -> dict:
    action = {"action": "perform-action", "perform_action": "button.press", "target": {"entity_id": entity}}
    if confirm:
        action["confirmation"] = {"text": confirm}
    return tile(entity, hide_state=True, tap_action=action, **extra)


def toggle(entity: str, **extra) -> dict:
    return tile(entity, tap_action={"action": "toggle"}, **extra)


def select(entity: str, **extra) -> dict:
    return tile(entity, features=[{"type": "select-options"}], **extra)


def slider(entity: str, **extra) -> dict:
    return tile(entity, features=[{"type": "numeric-input", "style": "slider"}], **extra)


def present(entity: str) -> list[dict]:
    """Shown only when the entity exists and has something to show.

    A missing entity reads as unavailable, so this also hides Coffee Lab's
    cards while Coffee Lab is off.
    """
    return [{"condition": "state", "entity": entity, "state_not": s} for s in ("unavailable", "unknown")]


def is_(entity: str, state: str) -> dict:
    return {"condition": "state", "entity": entity, "state": state}


def not_busy() -> list[dict]:
    return [{"condition": "state", "entity": f"sensor.{E}_brew_status", "state_not": s} for s in BUSY]


def at_home() -> list[dict]:
    return [
        *({"condition": "state", "entity": f"sensor.{E}_current_module", "state_not": m} for m in MODULES),
        *not_busy(),
    ]


def section(title: str, cards: list[dict], visibility: list[dict] | None = None) -> dict:
    out = {"type": "grid", "cards": [heading(title), *cards]}
    if visibility:
        out["visibility"] = visibility
    return out


def brew_view(t: dict) -> dict:
    bag = f"select.{E}_coffee_bag"
    manual = "input_boolean.xbloom_show_manual_brew"
    return {"title": t["view_brew"], "path": "brew", "icon": "mdi:coffee", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_now"], [
            tile(f"sensor.{E}_brew_status"),
            tile(f"binary_sensor.{E}_in_range"),
            tile(bag, visibility=present(bag)),
            tile(f"sensor.{E}_coffee_left", visibility=present(f"sensor.{E}_coffee_left")),
        ]),
        section(t["h_in_progress"], [
            tile(f"sensor.{E}_current_recipe", visibility=present(f"sensor.{E}_current_recipe")),
            tile(f"sensor.{E}_current_pour"),
            press(f"button.{E}_pause_brew"),
            press(f"button.{E}_resume_brew"),
            press(f"button.{E}_cancel_brew", t["confirm_stop"]),
        ], [{"condition": "or", "conditions": [is_(f"sensor.{E}_brew_status", s) for s in BUSY]}]),
        section(t["h_bag"], [
            select(bag),
            {"type": "markdown", "content": (
                "{% set a = states['" + bag + "'].attributes if states['" + bag + "'] else {} %}"
                "{{ [a.get('roaster'), [a.get('country'), a.get('region')] | select | join('" + t["sep"] + "'), a.get('process')]"
                " | select | join(' · ') }}"
                "{% if a.get('roaster_notes') %}\n\n{{ a.get('roaster_notes') }}{% endif %}"
            ), "visibility": present(bag)},
            tile(f"sensor.{E}_last_brew_counted", visibility=[is_(f"sensor.{E}_last_brew_counted", "flagged")]),
        # Not hidden while no bag is chosen: this is where one is chosen.
        ], present(bag)[:1]),
        section(t["h_brew"], [
            select(f"select.{E}_recipe"),
            press(f"button.{E}_start_brew", grid_options={"columns": 6}),
            press(f"button.{E}_refresh_recipes", grid_options={"columns": 6}),
            # With Coffee Lab kept in Notion, bags changed there are re-read here.
            press(f"button.{E}_refresh_coffee_bags", visibility=[
                {"condition": "state", "entity": f"button.{E}_refresh_coffee_bags", "state_not": "unavailable"},
            ]),
            toggle("input_boolean.xbloom_show_advanced", name=t["show_advanced"]),
        ], at_home()),
        section(t["h_brew"], [
            {"type": "markdown", "text_only": True, "content": t["go_home"]},
        ], [
            {"condition": "or", "conditions": [is_(f"sensor.{E}_current_module", m) for m in MODULES]},
            *not_busy(),
        ]),
        section(t["h_adjust"], [
            toggle(f"switch.{E}_use_grinder"),
            slider(f"number.{E}_brew_grind_size", visibility=[is_(f"switch.{E}_use_grinder", "on")]),
            slider(f"number.{E}_brew_ratio"),
            slider(f"number.{E}_brew_dose", visibility=present(f"number.{E}_brew_dose")),
            {"type": "markdown", "content": (
                f"{{% set rdose = state_attr('select.{E}_recipe','dose_g') | float(0) %}}\n"
                f"{{% set dose = states('number.{E}_brew_dose') | float(rdose) %}}\n"
                f"{{% set ratio = states('number.{E}_brew_ratio') | float(0) %}}\n"
                "{% set water = dose * ratio %}\n"
                f"{{% set wu = states('select.{E}_weight_unit') %}}\n"
                f"### {t['this_brew']}\n"
                f"{{% if wu == 'oz' %}}- **{t['coffee']}:** {{{{ (dose * 0.035274) | round(2) }}}} oz\n"
                f"- **{t['water']}:** {{{{ (water * 0.033814) | round(1) }}}} oz\n"
                f"{{% else %}}- **{t['coffee']}:** {{{{ dose | round(1) }}}} {t['g']}\n"
                f"- **{t['water']}:** {{{{ water | round(0) | int }}}} {t['ml']}\n"
                f"{{% endif %}}- **{t['ratio']}:** 1:{{{{ ratio | round(1) }}}}"
            )},
            toggle("input_boolean.xbloom_show_per_pour", name=t["show_per_pour"]),
            {"type": "markdown", "visibility": [is_("input_boolean.xbloom_show_per_pour", "on")], "content": (
                f"{{% set pours = state_attr('select.{E}_recipe','pours') or [] %}}\n"
                f"{{% set rdose = state_attr('select.{E}_recipe','dose_g') | float(0) %}}\n"
                f"{{% set dose = states('number.{E}_brew_dose') | float(rdose) %}}\n"
                f"{{% set ratio = states('number.{E}_brew_ratio') | float(0) %}}\n"
                "{% set ns = namespace(orig=0) %}\n"
                "{% for p in pours %}{% set ns.orig = ns.orig + (p.volume_ml | float(0)) %}{% endfor %}\n"
                "{% set factor = (dose * ratio / ns.orig) if ns.orig > 0 else 0 %}\n"
                f"{{% set tu = states('select.{E}_temperature_unit') %}}\n"
                f"{{% set wu = states('select.{E}_weight_unit') %}}\n"
                f"{{% if pours %}}| {t['pour']} | {t['water']} | {t['temp']} |\n|:--:|:--:|:--:|\n"
                "{% for p in pours %}| {{ loop.index }} | {% set v = (p.volume_ml | float(0)) * factor %}"
                "{% if wu == 'oz' %}{{ (v * 0.033814) | round(2) }} oz{% else %}{{ v | round(0) | int }} " + t["ml"] + "{% endif %} | "
                "{% set c = p.temperature_c | float(0) %}{% if tu == 'f' %}{{ (c * 9 / 5 + 32) | round(0) | int }}°F"
                "{% else %}{{ c | round(0) | int }}°C{% endif %} |\n"
                f"{{% endfor %}}{{% else %}}_{t['pick_recipe']}_{{% endif %}}"
            )},
        ], [is_("input_boolean.xbloom_show_advanced", "on"), *at_home()]),
        section(t["h_save"], [
            tile(f"text.{E}_new_recipe_name"),
            press(f"button.{E}_save_as_new_recipe"),
        ], [is_("input_boolean.xbloom_show_advanced", "on"), *at_home()]),
        section(t["h_manual"], [
            toggle(manual, name=t["show_manual"]),
            select(f"select.{E}_manual_brewer", visibility=[is_(manual, "on")], grid_options={"columns": 6}),
            slider(f"number.{E}_manual_brew_dose", visibility=[is_(manual, "on")], grid_options={"columns": 6}),
            press(f"button.{E}_record_manual_brew", t["confirm_record"], visibility=[is_(manual, "on")]),
            tile(f"sensor.{E}_last_brew_counted", visibility=[is_(manual, "on"), *present(f"sensor.{E}_last_brew_counted")]),
        ], present(f"select.{E}_manual_brewer")[:1]),
    ]}


def stats_view(t: dict) -> dict:
    stats = f"sensor.{E}_brews"
    return {"title": t["view_stats"], "path": "stats", "icon": "mdi:chart-bar", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_stats"], [
            select(f"select.{E}_stats_period"),
            tile(stats),
            {"type": "markdown", "content": (
                f"{{% set a = states['{stats}'].attributes if states['{stats}'] else {{}} %}}"
                f"- **{t['coffee_used']}:** {{{{ a.get('coffee_g', 0) | round(0) | int }}}} {t['g']}\n"
                f"{{% if a.get('water_ml') %}}- **{t['water_brewed']}:** {{{{ a.get('water_ml') | round(0) | int }}}} {t['ml']}\n{{% endif %}}"
                f"- **{t['previous']}:** {{{{ (a.get('previous_period') or {{}}).get('brews', 0) }}}}"
            )},
        ], present(stats)[:1]),
        section(t["h_by_brewer"], [
            {"type": "markdown", "content": (
                f"{{% for name, n in (state_attr('{stats}','by_brewer') or {{}}).items() %}}"
                f"- **{{{{ '{t['other']}' if name == 'other' else name }}}}**: {{{{ n }}}}\n{{% endfor %}}"
            )},
        ], [{"condition": "numeric_state", "entity": stats, "above": 0}]),
        section(t["h_charts"], [
            chart(t["brews_daily"], "day", 30, [
                ("xbloom:brews_xbloom", t["xbloom_brews"]), ("xbloom:brews_manual", t["manual_brews"])]),
            chart(t["brews_monthly"], "month", 365, [
                ("xbloom:brews_xbloom", t["xbloom_brews"]), ("xbloom:brews_manual", t["manual_brews"])]),
            chart(t["coffee_weekly"], "week", 90, [("xbloom:coffee_used", t["coffee_used"])]),
            chart(t["water_weekly"], "week", 90, [("xbloom:water_brewed", t["water_brewed"])]),
        ], present(stats)[:1]),
    ]}


def chart(title: str, period: str, days: int, series: list[tuple[str, str]]) -> dict:
    """A bar chart of what the brew record adds up to per period.

    The integration keeps these statistics from the record itself, so the
    chart covers every brew recorded, not only those since it was added.
    """
    return {
        "type": "statistics-graph", "title": title, "chart_type": "bar",
        "period": period, "days_to_show": days, "stat_types": ["change"],
        "entities": [{"entity": sid, "name": name} for sid, name in series],
    }


def bags_view(t: dict) -> dict:
    bags = f"sensor.{E}_coffee_bags"
    bag = f"select.{E}_coffee_bag"
    return {"title": t["view_bags"], "path": "bags", "icon": "mdi:shopping", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_bags"], [
            {"type": "markdown", "content": (
                f"{{% set current = state_attr('{bag}','id') %}}"
                f"{{% for b in state_attr('{bags}','bags') or [] %}}"
                f"- **{{{{ b.name }}}}**{{{{ ' ({t['in_use']})' if b.id == current }}}} — "
                f"{{{{ '{t['unopened']}' if b.status == 'unopened' else '{t['open']}' }}}}{t['sep']}"
                f"{{{{ (b.remaining_g | round(0) | int ~ ' {t['g_left']}') if b.remaining_g is not none else '{t['not_tracked']}' }}}}\n"
                f"{{% else %}}{t['no_bags']}{{% endfor %}}"
            )},
            select(bag),
            press(f"button.{E}_refresh_coffee_bags", visibility=[
                {"condition": "state", "entity": f"button.{E}_refresh_coffee_bags", "state_not": "unavailable"},
            ]),
            {"type": "markdown", "text_only": True, "content": f"[{t['add_bags']}]({INTEGRATION})"},
        ], present(bags)[:1]),
    ]}


def archive_view(t: dict) -> dict:
    """The archived recipes, as a subview: no tab, opened from the library."""
    return {"title": t["h_archive"], "path": "archive", "subview": True, "type": "sections",
            "max_columns": 2, "sections": [
        # The page's title names it; a heading would say it again.
        {"type": "grid", "cards": [
            select(f"select.{E}_archived_recipe"),
            press(f"button.{E}_restore_archived_recipe"),
        ], "visibility": present(f"select.{E}_archived_recipe")},
    ]}


def xbloom_view(t: dict) -> dict:
    live = is_(f"switch.{E}_connect", "on")
    on = lambda module: [live, is_(f"sensor.{E}_current_module", module), *not_busy()]  # noqa: E731
    back = press(f"button.{E}_back_to_home")
    voice = [
        ("automation.xbloom_brew_announcements", t["speak_brew"]),
        ("automation.xbloom_machine_fault_announcements", t["speak_faults"]),
        ("automation.xbloom_live_control_announcements", t["speak_live"]),
    ]
    return {"title": t["view_xbloom"], "path": "xbloom", "icon": "mdi:coffee-maker", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_connection"], [
            toggle(f"switch.{E}_connect"),
            press(f"button.{E}_refresh_status"),
            tile(f"sensor.{E}_status_updated"),
            tile(f"sensor.{E}_brew_status"),
            tile(f"sensor.{E}_machine_status"),
            tile(f"sensor.{E}_current_module", visibility=present(f"sensor.{E}_current_module")),
        ], at_home()),
        section(t["h_modules"], [
            press(f"button.{E}_go_to_grinder"),
            press(f"button.{E}_go_to_brewer"),
            press(f"button.{E}_go_to_scale"),
        ], [live, *at_home()]),
        section(t["h_grinder"], [
            back,
            slider(f"number.{E}_grind_size"),
            slider(f"number.{E}_grind_speed"),
            press(f"button.{E}_grind"),
        ], on("grinder")),
        section(t["h_brewer"], [
            back,
            slider(f"number.{E}_brew_temperature"),
            select(f"select.{E}_brew_pattern"),
            slider(f"number.{E}_brew_volume"),
            slider(f"number.{E}_brew_flow_rate"),
            select(f"select.{E}_water_source"),
            press(f"button.{E}_brew_standalone"),
        ], on("brewer")),
        section(t["h_scale"], [
            back,
            tile(f"sensor.{E}_scale_weight", visibility=present(f"sensor.{E}_scale_weight")),
            press(f"button.{E}_tare_scale"),
        ], on("scale")),
        section(t["h_library"], [
            select(f"select.{E}_recipe"),
            select(f"select.{E}_recipe_action"),
            press(f"button.{E}_run_recipe_action", t["confirm_run"]),
            {"type": "markdown", "text_only": True, "content": f"[{t['add_recipes']}]({INTEGRATION})"},
            # The archive is a page of its own, reached from here, so what is
            # archived stays out of the library; the link shows only while
            # there is something in it.
            {"type": "markdown", "text_only": True, "content": f"[{t['h_archive']}](archive)",
             "visibility": present(f"select.{E}_archived_recipe")},
        ]),
        section(t["h_settings"], [
            select(f"select.{E}_mode"),
            select(f"select.{E}_temperature_unit"),
            select(f"select.{E}_weight_unit"),
        ]),
        section(t["h_tools"], [
            press(f"button.{E}_ble_connect"),
            press(f"button.{E}_ble_disconnect"),
            press(f"button.{E}_back_to_home"),
        ]),
        section(t["h_voice"], [
            toggle(entity, name=name, visibility=[
                {"condition": "state", "entity": entity, "state_not": "unavailable"}]) for entity, name in voice
        ], [{"condition": "or", "conditions": [
            {"condition": "state", "entity": entity, "state_not": "unavailable"} for entity, _ in voice]}]),
        section(t["h_updates"], [
            tile(f"update.{E}_update", features=[{"type": "update-actions"}],
                 visibility=[{"condition": "state", "entity": f"update.{E}_update", "state_not": "unavailable"}]),
            tile(f"update.{E}_firmware", features=[{"type": "update-actions"}],
                 visibility=[{"condition": "state", "entity": f"update.{E}_firmware", "state_not": "unavailable"}]),
        ]),
        section(t["h_events"], [
            {"type": "logbook", "target": {"entity_id": [f"sensor.{E}_brew_status", f"event.{E}_brew_event"]},
             "hours_to_show": 24},
        ]),
    ]}


def dashboard(lang: str) -> dict:
    t = TEXT[lang]
    return {"views": [brew_view(t), stats_view(t), bags_view(t), xbloom_view(t), archive_view(t)]}


def main() -> None:
    assert TEXT["en"].keys() == TEXT["ar"].keys(), "every language carries every string"
    for lang in TEXT:
        name = "dashboard-xbloom-studio.yaml" if lang == "en" else f"dashboard-xbloom-studio.{lang}.yaml"
        body = yaml.safe_dump(dashboard(lang), allow_unicode=True, sort_keys=False, width=100)
        (HERE / name).write_text(
            "# Built by dashboard/build.py — edit that, not this file.\n" + body, encoding="utf-8"
        )


if __name__ == "__main__":
    main()

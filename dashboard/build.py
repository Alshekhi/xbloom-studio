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
        "h_now": "Right now", "h_in_progress": "Brew in progress", "h_bag": "Current bag", "pods_left": "Pods left: {n}", "k_xpod": "xPod box", "k_tea": "tea",
        "h_brew": "Brew with the xBloom", "h_adjust": "Adjust this brew",
        "h_save": "Save as a new recipe", "h_manual": "Manual brew", "h_stats": "Coffee stats",
        "h_by_brewer": "By brewer", "h_bags": "Bags on hand", "h_connection": "Connection & status",
        "h_modules": "Modules", "h_grinder": "Grinder", "h_brewer": "Brewer", "h_scale": "Scale",
        "h_library": "Recipe library", "h_settings": "Settings", "h_tools": "Connection tools",
        "h_voice": "Voice announcements", "h_updates": "Updates", "h_events": "Recent machine events",
        "go_home": "Return the machine to its home screen to brew a recipe.",
        "show_advanced": "Show brew adjustments", "show_per_pour": "Show each pour",
        "preparing": "Preparing the recipe.", "need_bag": "Pick a bag to prepare this recipe.",
        "out_of_range": "The machine is out of range.", "need_water": "Fill the water tank.",
        "not_taken": "The machine did not take the recipe. Pick it again.",
        "show_manual": "Show manual brew",
        "confirm_stop": "Stop the brew in progress?", "confirm_record": "Record this manual brew?",
        "confirm_run": "Run the chosen action on the selected recipe?",
        "add_recipes": "Add or edit recipes", "add_bags": "Add or edit bags",
        "h_archive": "Archived recipes",
        "this_brew": "This brew", "coffee": "Coffee", "water": "Water", "ratio": "Ratio",
        "pour": "Pour", "of": "of", "brew_time": "Brew time", "temp": "Temp", "pick_recipe": "Pick a recipe to see its pours.",
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
        "view_community": "Community", "h_find": "Find a community recipe",
        "h_results": "Matching recipes", "h_picked": "Chosen recipe",
        "c_words": "Search words", "c_origin": "Origin", "c_sort": "Sort", "c_search": "Search",
        "c_recipe": "Recipe", "c_add": "Add to my recipes",
        "c_confirm_add": "Add this recipe to your library?",
        "c_none": "No recipes match.", "c_one": "1 recipe matches.",
        "c_many": "{n} recipes match.", "c_first": "The first {shown} are in the list below.",
        "c_by": "Shared by", "c_notes": "Notes", "c_grind": "grind", "c_at": "at",
        "c_rpm": "RPM", "c_pause": "Pause", "c_s": "s", "c_likes": "likes",
        "c_fits": "Like this bag", "f_process": "process", "f_varietal": "variety",
        "f_roast": "roast", "f_flavor": "tasting notes",
        "c_added": "Added to your recipes as **{name}**. Pick it on the Brew tab.",
        "c_suggest": "Suggest a recipe", "c_suggest_hub": "Suggest a community recipe",
        "h_for_you": "For you", "h_trending": "Trending recipes", "h_tea": "Tea recipes",
        "a_another": "Another", "a_pod": "Pod",
        "h_how_was": "How was it?", "r_verdict": "Verdict",
        "v_wanted": "Last time you wanted: {text}.", "v_use": "Use that change",
        "h_keep": "Keep this version?", "v_keep": "**{recipe}** {changes} is worth brewing again.",
        "v_make": "Make it the recipe", "v_new": "Save as a new recipe",
        "v_confirm_make": "Replace the saved recipe with this version?",
        "v_versions": "Versions with this bag:", "k_grind": "grind {value}", "k_ratio": "1:{value}",
        "k_dose": "{value} g", "verdict_again": "Again", "verdict_fine": "Fine",
        "verdict_not_again": "Not again",
        "h_buy_again": "Buy it again?", "b_question": "**{bag}** is finished.",
        "b_answer": "Buy again",
        "r_question": "**{recipe}** with {bag}{changes}.", "r_at": ", at ",
        "r_grind": "grind {value} instead of {saved}", "r_ratio": "ratio 1:{value} instead of 1:{saved}",
        "r_dose": "{value} g instead of {saved} g",
        "h_for_bag": "A recipe for this bag", "s_use": "Use this recipe",
        "s_own": "Brewed {times} {basis}.",
        "s_none": "None of your recipes has been brewed with coffee like this.",
        "s_hub": "From the community, shared by {by}. Using it adds it to your recipes.",
        "s_this_bag": "with this bag", "s_kind": "with {country} {process} coffee",
        "s_origin": "with coffee from {country}",
        "c_for": "Suggested for **{bag}**, matching {basis}.",
        "c_popular": "The most downloaded Studio recipes.",
    },
    "ar": {
        "view_brew": "التحضير", "view_stats": "الإحصاءات", "view_bags": "الأكياس", "view_xbloom": "xBloom",
        "h_now": "الآن", "h_in_progress": "تحضير جار", "h_bag": "الكيس الحالي", "pods_left": "الكبسولات المتبقية: {n}", "k_xpod": "علبة xPod", "k_tea": "شاي",
        "h_brew": "التحضير بماكينة xBloom", "h_adjust": "تعديل هذا التحضير",
        "h_save": "حفظ كوصفة جديدة", "h_manual": "تحضير يدوي", "h_stats": "إحصاءات القهوة",
        "h_by_brewer": "حسب أداة التحضير", "h_bags": "الأكياس المتوفرة", "h_connection": "الاتصال والحالة",
        "h_modules": "الوحدات", "h_grinder": "المطحنة", "h_brewer": "وحدة الصب", "h_scale": "الميزان",
        "h_library": "مكتبة الوصفات", "h_settings": "الإعدادات", "h_tools": "أدوات الاتصال",
        "h_voice": "الإعلانات الصوتية", "h_updates": "التحديثات", "h_events": "أحدث أحداث الماكينة",
        "go_home": "أعد الماكينة إلى شاشتها الرئيسية لتحضير وصفة.",
        "show_advanced": "إظهار تعديلات التحضير", "show_per_pour": "إظهار كل صبة",
        "preparing": "يجري تجهيز الوصفة.", "need_bag": "اختر كيسا لتجهيز هذه الوصفة.",
        "out_of_range": "الماكينة خارج النطاق.", "need_water": "املأ خزان الماء.",
        "not_taken": "لم تقبل الماكينة الوصفة. اخترها مرة أخرى.",
        "show_manual": "إظهار التحضير اليدوي",
        "confirm_stop": "إيقاف التحضير الجاري؟", "confirm_record": "تسجيل هذا التحضير اليدوي؟",
        "confirm_run": "تنفيذ الإجراء المختار على الوصفة المختارة؟",
        "add_recipes": "إضافة الوصفات أو تعديلها", "add_bags": "إضافة الأكياس أو تعديلها",
        "h_archive": "الوصفات المؤرشفة",
        "this_brew": "هذا التحضير", "coffee": "القهوة", "water": "الماء", "ratio": "النسبة",
        "pour": "الصبة", "of": "من", "brew_time": "زمن التحضير", "temp": "الحرارة", "pick_recipe": "اختر وصفة لعرض صباتها.",
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
        "view_community": "المجتمع", "h_find": "البحث عن وصفة من المجتمع",
        "h_results": "الوصفات المطابقة", "h_picked": "الوصفة المختارة",
        "c_words": "كلمات البحث", "c_origin": "المنشأ", "c_sort": "الترتيب", "c_search": "ابحث",
        "c_recipe": "الوصفة", "c_add": "أضفها إلى وصفاتي",
        "c_confirm_add": "إضافة هذه الوصفة إلى مكتبتك؟",
        "c_none": "لا توجد وصفات مطابقة.", "c_one": "وصفة واحدة تطابق البحث.",
        "c_many": "{n} وصفات تطابق البحث.", "c_first": "أول {shown} منها في القائمة أدناه.",
        "c_by": "شاركها", "c_notes": "النكهات", "c_grind": "درجة الطحن", "c_at": "بسرعة",
        "c_rpm": "دورة في الدقيقة", "c_pause": "الانتظار", "c_s": "ث", "c_likes": "إعجاب",
        "c_fits": "تشبه هذا الكيس في", "f_process": "المعالجة", "f_varietal": "السلالة",
        "f_roast": "درجة التحميص", "f_flavor": "النكهات",
        "c_added": "أضيفت إلى وصفاتك باسم **{name}**. اخترها من تبويب التحضير.",
        "c_suggest": "اقترح وصفة", "c_suggest_hub": "اقترح وصفة من المجتمع",
        "h_for_you": "مقترحة لك", "h_trending": "الوصفات الرائجة", "h_tea": "وصفات الشاي",
        "a_another": "اقتراح آخر", "a_pod": "الكبسولة",
        "h_how_was": "كيف كانت؟", "r_verdict": "الحكم",
        "v_wanted": "في المرة السابقة أردت: {text}.", "v_use": "استخدم هذا التعديل",
        "h_keep": "هل تحفظ هذه النسخة؟", "v_keep": "**{recipe}** {changes} تستحق التكرار.",
        "v_make": "اجعلها الوصفة", "v_new": "احفظها كوصفة جديدة",
        "v_confirm_make": "استبدال الوصفة المحفوظة بهذه النسخة؟",
        "v_versions": "النسخ مع هذا الكيس:", "k_grind": "درجة طحن {value}", "k_ratio": "1:{value}",
        "k_dose": "{value} غ", "verdict_again": "أكرّرها", "verdict_fine": "لا بأس بها",
        "verdict_not_again": "لن أكرّرها",
        "h_buy_again": "هل تشتريها مجددا؟", "b_question": "انتهى **{bag}**.",
        "b_answer": "الشراء مرة أخرى",
        "r_question": "**{recipe}** مع {bag}{changes}.", "r_at": "، ",
        "r_grind": "بدرجة طحن {value} بدل {saved}", "r_ratio": "بنسبة 1:{value} بدل 1:{saved}",
        "r_dose": "بجرعة {value} غ بدل {saved} غ",
        "h_for_bag": "وصفة لهذا الكيس", "s_use": "استخدم هذه الوصفة",
        "s_own": "حُضّرت {times} {basis}.",
        "s_none": "لم تُحضَّر أي وصفة من وصفاتك بقهوة مثل هذه.",
        "s_hub": "من المجتمع، شاركها {by}. استخدامها يضيفها إلى وصفاتك.",
        "s_this_bag": "مع هذا الكيس", "s_kind": "مع قهوة من {country} بمعالجة {process}",
        "s_origin": "مع قهوة من {country}",
        "c_for": "مقترحة لـ **{bag}**، بمطابقة {basis}.",
        "c_popular": "أكثر وصفات Studio تنزيلًا.",
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
    # The entity's own name, without the device's in front of it: "Start Brew",
    # not "xBloom Studio Start Brew". Still the translated name.
    card = {"type": "tile", "entity": entity, "name": {"type": "entity"}, "icon_tap_action": {"action": "none"}}
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
    kind = f"sensor.{E}_recipe_kind"
    manual = "input_boolean.xbloom_show_manual_brew"
    return {"title": t["view_brew"], "path": "brew", "icon": "mdi:coffee", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_now"], [
            tile(f"sensor.{E}_brew_status"),
            tile(f"binary_sensor.{E}_in_range"),
            tile(bag, visibility=present(bag)),
            tile(f"sensor.{E}_coffee_left", visibility=present(f"sensor.{E}_coffee_left")),
            # Only while a brew could not be saved; it is retried by itself.
            tile(f"sensor.{E}_waiting_brews", visibility=[
                {"condition": "numeric_state", "entity": f"sensor.{E}_waiting_brews", "above": 0}]),
        ]),
        # Due a while after a brew; never while one is running.
        section(t["h_how_was"], [
            {"type": "markdown", "text_only": True, "content": rating_card(t)},
            select(f"select.{E}_verdict", name=t["r_verdict"]),
        ], [*present(f"sensor.{E}_brew_to_rate"), *not_busy()]),
        section(t["h_buy_again"], [
            {"type": "markdown", "text_only": True, "content": ESCAPE + t["b_question"].replace(
                "{bag}", f"{{{{ e(states('sensor.{E}_finished_bag')) }}}}")},
            select(f"select.{E}_buy_again", name=t["b_answer"]),
        ], [*present(f"sensor.{E}_finished_bag"), *not_busy()]),
        section(t["h_keep"], [
            {"type": "markdown", "text_only": True, "content": keep_card(t)},
            press(f"button.{E}_make_version_the_recipe", t["v_confirm_make"], name=t["v_make"]),
            press(f"button.{E}_save_version_as_new_recipe", name=t["v_new"]),
        ], [*present(f"sensor.{E}_version_to_keep"), *not_busy()]),
        section(t["h_in_progress"], [
            tile(f"sensor.{E}_current_recipe", visibility=present(f"sensor.{E}_current_recipe")),
            # "Pour 2 of 3", once the pours have begun.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set p = 'sensor.{E}_current_pour' %}}{{% set total = state_attr(p, 'total_pours') %}}"
                f"**{t['pour']} {{{{ states(p) }}}}{{% if total %}} {t['of']} {{{{ total }}}}{{% endif %}}**"
            ), "visibility": [{"condition": "numeric_state", "entity": f"sensor.{E}_current_pour", "above": 0}]},
            # Minutes and seconds, "2:28"; it re-renders as the sensor ticks.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set s = states('sensor.{E}_brew_time') | int(0) %}}"
                f"**{t['brew_time']} {{{{ s // 60 }}}}:{{{{ '%02d' % (s % 60) }}}}**"
            ), "visibility": present(f"sensor.{E}_brew_time")},
            # One of the two, by whether the machine reports the brew paused.
            press(f"button.{E}_pause_brew", visibility=[is_(f"binary_sensor.{E}_brew_paused", "off")]),
            press(f"button.{E}_resume_brew", visibility=[is_(f"binary_sensor.{E}_brew_paused", "on")]),
            press(f"button.{E}_cancel_brew", t["confirm_stop"]),
        ], [{"condition": "or", "conditions": [is_(f"sensor.{E}_brew_status", s) for s in BUSY]}]),
        section(t["h_bag"], [
            # The picker for what the picked recipe draws from: a bag of
            # coffee, an xPod box, or a tea.
            select(bag, visibility=[
                {"condition": "state", "entity": kind, "state_not": k} for k in ("xpod", "tea")
            ]),
            select(f"select.{E}_xpod_box", visibility=[is_(kind, "xpod")]),
            {"type": "markdown", "text_only": True, "content": (
                "{% set n = state_attr('select." + E + "_xpod_box', 'pods_left') %}"
                "{% if n is not none %}" + t["pods_left"].replace("{n}", "{{ n }}") + "{% endif %}"
            ), "visibility": [is_(kind, "xpod"), *present(f"select.{E}_xpod_box")]},
            select(f"select.{E}_tea", visibility=[is_(kind, "tea")]),
            {"type": "markdown", "content": (
                "{% set a = states['" + bag + "'].attributes if states['" + bag + "'] else {} %}"
                "{{ [a.get('roaster'), [a.get('country'), a.get('region')] | select | join('" + t["sep"] + "'), a.get('process'), a.get('varietal'), a.get('roast')]"
                " | select | join(' · ') }}"
                "{% if a.get('roaster_notes') %}\n\n{{ a.get('roaster_notes') }}{% endif %}"
            ), "visibility": present(bag)},
            tile(f"sensor.{E}_last_brew_counted", visibility=[is_(f"sensor.{E}_last_brew_counted", "flagged")]),
        # Not hidden while no bag is chosen: this is where one is chosen.
        ], present(bag)[:1]),
        # Asked for here, where the bag is chosen. Nothing reaches the machine
        # until a recipe is used: picking one is what prepares it.
        section(t["h_for_bag"], [
            press(f"button.{E}_suggest_recipe", name=t["c_suggest"]),
            # Every suggestion, your own first; the card below says why the
            # chosen one was suggested, and Use picks it for brewing.
            select(f"select.{E}_suggested_recipe", visibility=present(f"select.{E}_suggested_recipe")),
            {"type": "markdown", "content": suggestion_card(t, bag),
             "visibility": present(f"sensor.{E}_recipe_suggestions")},
            press(f"button.{E}_use_suggested_recipe", name=t["s_use"],
                  visibility=present(f"select.{E}_suggested_recipe")),
        ], [*present(bag), *at_home()]),
        section(t["h_brew"], [
            select(f"select.{E}_recipe"),
            # What was asked for last time with this bag; one press sets it as
            # this brew's adjustment, the saved recipe untouched.
            {"type": "markdown", "text_only": True, "content": next_change_card(t),
             "visibility": present(f"sensor.{E}_next_change")},
            press(f"button.{E}_use_next_change", name=t["v_use"],
                  visibility=present(f"sensor.{E}_next_change")),
            # While a picked recipe is not yet ready: that it is being prepared,
            # or what stops it. Plain text, not a button; once ready it gives
            # way to Start Brew.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set r = state_attr('binary_sensor.{E}_recipe_ready', 'reason') %}}"
                f"{{% if state_attr('binary_sensor.{E}_recipe_ready', 'preparing') %}}{t['preparing']}"
                f"{{% elif r is none %}}{t['not_taken']}"
                f"{{% elif r == 'no_bag' %}}{t['need_bag']}"
                f"{{% elif r in ['machine_not_found', 'machine_unreachable'] %}}{t['out_of_range']}"
                f"{{% elif r == 'refused_not_on_home_screen' %}}{t['go_home']}"
                f"{{% elif r == 'refused_no_water' %}}{t['need_water']}"
                f"{{% else %}}{t['not_taken']}{{% endif %}}"
            ), "visibility": [*present(f"select.{E}_recipe"), is_(f"binary_sensor.{E}_recipe_ready", "off")]},
            # Only once the machine holds the picks: a start is then instant.
            press(f"button.{E}_start_brew", grid_options={"columns": 6},
                  visibility=[is_(f"binary_sensor.{E}_recipe_ready", "on")]),
            press(f"button.{E}_cancel_preparation", grid_options={"columns": 6},
                  visibility=present(f"select.{E}_recipe")),
            press(f"button.{E}_refresh_recipes", grid_options={"columns": 6}),
            # With Coffee Lab kept in Notion, bags changed there are re-read here.
            press(f"button.{E}_refresh_coffee_bags", visibility=[
                {"condition": "state", "entity": f"button.{E}_refresh_coffee_bags", "state_not": "unavailable"},
            ]),
            toggle("input_boolean.xbloom_show_advanced", name=t["show_advanced"],
                   visibility=present(f"select.{E}_recipe")),
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
        ], [is_("input_boolean.xbloom_show_advanced", "on"), *present(f"select.{E}_recipe"), *at_home()]),
        section(t["h_save"], [
            tile(f"text.{E}_new_recipe_name"),
            press(f"button.{E}_save_as_new_recipe"),
        ], [is_("input_boolean.xbloom_show_advanced", "on"), *present(f"select.{E}_recipe"), *at_home()]),
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
                f"{{% set current = [state_attr('{bag}','id'), state_attr('select.{E}_xpod_box','id'), state_attr('select.{E}_tea','id')] %}}"
                f"{{% for b in state_attr('{bags}','bags') or [] %}}"
                f"- **{{{{ b.name }}}}**"
                f"{{% if b.kind == 'xpod' %}} ({t['k_xpod']}){{% elif b.kind == 'tea' %}} ({t['k_tea']}){{% endif %}}"
                f"{{{{ ' ({t['in_use']})' if b.id in current }}}} — "
                f"{{{{ '{t['unopened']}' if b.status == 'unopened' else '{t['open']}' }}}}{t['sep']}"
                f"{{% if b.kind == 'xpod' %}}{{{{ ('" + t['pods_left'].replace('{n}', "' ~ b.pods_left ~ '") + "') if b.pods_left is not none else '{t['not_tracked']}' }}}}"
                f"{{% else %}}{{{{ (b.remaining_g | round(0) | int ~ ' {t['g_left']}') if b.remaining_g is not none else '{t['not_tracked']}' }}}}{{% endif %}}\n"
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


# Hub text was typed by strangers. Backslash-escaping every character markdown
# or HTML reads makes it print as written: no link, no image fetched, no tag.
ESCAPE = (
    "{% macro e(s) %}{{ (s or '') | string | regex_replace("
    "'([\\\\\\\\`*_{}\\\\[\\\\]()<>#+!|~])', '\\\\\\\\\\\\1') }}{% endmacro %}"
)


def matches_sentence(t: dict, sensor: str, picker: str) -> str:
    """How many recipes the last search found, counted the language's way."""
    n = "n"
    if t is TEXT["ar"]:
        # Arabic counted-noun agreement: one, two, three to ten, then eleven and up.
        count = (
            f"{{% if n == 0 %}}{t['c_none']}{{% elif n == 1 %}}{t['c_one']}"
            "{% elif n == 2 %}وصفتان تطابقان البحث."
            "{% elif n <= 10 %}{{ n }} وصفات تطابق البحث."
            "{% else %}{{ n }} وصفة تطابق البحث.{% endif %}"
        )
    else:
        count = (
            f"{{% if n == 0 %}}{t['c_none']}{{% elif n == 1 %}}{t['c_one']}"
            f"{{% else %}}{t['c_many'].replace('{n}', '{{ n }}')}{{% endif %}}"
        )
    first = t["c_first"].replace("{shown}", "{{ shown }}")
    return (
        f"{{% set {n} = states('{sensor}') | int(0) %}}"
        f"{{% set shown = state_attr('{picker}', 'shown') | int(0) %}}"
        f"{count}{{% if 0 < shown < n %}} {first}{{% endif %}}"
    )


def picked_card(t: dict, picker: str) -> str:
    """The chosen recipe: who shared it, what it is, and its pours."""
    added = t["c_added"].replace("{name}", "{{ e(added) }}")
    basis = (
        "{{ e(state_attr('" + picker + "', 'matched_origin')) }}"
        "{% if state_attr('" + picker + "', 'matched_process') %} · "
        "{{ e(state_attr('" + picker + "', 'matched_process')) }}{% endif %}"
    )
    suggested = t["c_for"].replace("{bag}", "{{ e(state_attr('" + picker + "', 'suggested_for')) }}").replace("{basis}", basis)
    return (
        ESCAPE
        + f"{{% set a = state_attr('{picker}', 'picked') or {{}} %}}"
        + f"{{% set added = state_attr('{picker}', 'added') %}}"
        + "{% if added %}" + added + "\n\n{% endif %}"
        # Why this one: the bag it was suggested for, or the fallback.
        + f"{{% if state_attr('{picker}', 'suggested') %}}"
        + f"{{% if state_attr('{picker}', 'suggested_for') and state_attr('{picker}', 'matched_origin') %}}{suggested}"
        + f"{{% else %}}{t['c_popular']}{{% endif %}}\n\n{{% endif %}}"
        + f"{t['c_by']} {{{{ 'xBloom' if a.get('official') else e(a.get('author')) }}}}"
        + f"{{% set about = (a.get('origin') or []) + (a.get('process') or []) + (a.get('varietal') or []) + ([a.get('roast')] if a.get('roast') else []) %}}"
        + "{% if about %} · {% for x in about %}{{ e(x) }}{% if not loop.last %} · {% endif %}{% endfor %}{% endif %}"
        + f"{{% if a.get('likes') %}} · {{{{ a.get('likes') }}}} {t['c_likes']}{{% endif %}}\n\n"
        + f"{{% if a.get('flavor') %}}**{t['c_notes']}:** "
        + f"{{% for x in a.get('flavor') %}}{{{{ e(x) }}}}{{% if not loop.last %}}{t['sep']}{{% endif %}}{{% endfor %}}\n\n{{% endif %}}"
        # What a suggested recipe shares with the bag; the names are ours, not the hub's.
        + "{% set fits = a.get('fits') or {} %}{% if fits %}**" + t["c_fits"] + ":** "
        + "{{ [" + ", ".join(
            f"('{t['f_' + f]}' if fits.get('{f}') else '')" for f in ("process", "varietal", "roast", "flavor")
        ) + "] | select | join('" + t["sep"] + "') }}\n\n{% endif %}"
        + "{% if a.get('description') %}{{ e(a.get('description')) }}\n\n{% endif %}"
        + recipe_lines(t)
    )


def recipe_lines(t: dict) -> str:
    """A recipe's dose, ratio, grind and pours, read from `a`."""
    return (
        f"{{% if a.get('dose_g') %}}**{t['coffee']}:** {{{{ a.get('dose_g') | round(1) }}}} {t['g']}"
        + f"{{% if a.get('ratio') %}} · **{t['ratio']}:** 1:{{{{ a.get('ratio') | round(1) }}}}{{% endif %}}"
        + f"{{% if a.get('grind_size') %}} · {t['c_grind']} {{{{ a.get('grind_size') | round(0) | int }}}} {t['c_at']} {{{{ a.get('rpm') }}}} {t['c_rpm']}{{% endif %}}\n\n{{% endif %}}"
        + f"{{% set pours = a.get('pours') or [] %}}{{% if pours %}}"
        + f"| {t['pour']} | {t['water']} | {t['temp']} | {t['c_pause']} |\n|:--:|:--:|:--:|:--:|\n"
        + "{% for p in pours %}| {{ loop.index }} | {{ p.volume_ml | round(0) | int }} " + t["ml"]
        + " | {{ p.temperature_c | round(0) | int }}°C | {{ p.pause_s | int(0) }} " + t["c_s"] + " |\n{% endfor %}{% endif %}"
    )


def account_card(t: dict, entity: str, with_name: bool = False) -> str:
    """A Trending, Tea or For You recipe: its pod's coffee when it has one, then the recipe."""
    return (
        ESCAPE
        + f"{{% set a = states['{entity}'].attributes if states['{entity}'] is defined else {{}} %}}"
        + (f"### {{{{ e(states('{entity}')) }}}}\n\n" if with_name else "")
        + "{% set c = a.get('coffee') or {} %}{% if c.get('name') %}"
        + f"**{t['a_pod']}:** {{{{ e(c.get('name')) }}}}"
        + "{% for x in [c.get('origin'), c.get('process'), c.get('varietal')] if x %} · {{ e(x) }}{% endfor %}\n\n"
        + f"{{% if c.get('flavor') %}}**{t['c_notes']}:** {{{{ e(c.get('flavor')) }}}}\n\n{{% endif %}}{{% endif %}}"
        + recipe_lines(t)
    )


def _num(expr: str) -> str:
    return "{{ (" + expr + " | float) | round(1) | string | replace('.0', '') }}"


def version_words(t: dict, var: str) -> str:
    """One version in a few words: "grind 52 · 1:15 · 18 g", only what it has."""
    parts = []
    for key, text in (("grind", "k_grind"), ("ratio", "k_ratio"), ("dose_g", "k_dose")):
        before, after = t[text].split("{value}")
        number = f"(({var}.{key} | float) | round(1) | string | replace('.0', ''))"
        parts.append(f"(('{before}' ~ {number} ~ '{after}') if {var}.{key} is not none else '')")
    return "{{ [" + ", ".join(parts) + "] | select | join(' · ') }}"


def keep_card(t: dict) -> str:
    k = f"sensor.{E}_version_to_keep"
    change = (
        "{% if c.setting == 'grind' %}" + t["k_grind"]
        + "{% elif c.setting == 'ratio' %}" + t["k_ratio"]
        + "{% else %}" + t["k_dose"] + "{% endif %}"
    ).replace("{value}", _num("c.value"))
    changes = (
        f"{{% for c in state_attr('{k}', 'changes') or [] %}}" + change
        + "{% if not loop.last %}" + t["sep"] + "{% endif %}{% endfor %}"
    )
    return ESCAPE + t["v_keep"].replace("{recipe}", f"{{{{ e(states('{k}')) }}}}").replace("{changes}", changes)


def next_change_card(t: dict) -> str:
    n = f"sensor.{E}_next_change"
    return ESCAPE + t["v_wanted"].replace("{text}", f"**{{{{ e(states('{n}')) }}}}**")


def rating_card(t: dict) -> str:
    """The question: which recipe with which bag, and what was changed."""
    q = f"sensor.{E}_brew_to_rate"
    num = "{{ (c.%s | float) | round(1) | string | replace('.0', '') }}"
    change = (
        "{% if c.setting == 'grind' %}" + t["r_grind"]
        + "{% elif c.setting == 'ratio' %}" + t["r_ratio"]
        + "{% else %}" + t["r_dose"] + "{% endif %}"
    ).replace("{value}", num % "value").replace("{saved}", num % "saved")
    changes = (
        f"{{% set cs = state_attr('{q}', 'changes') or [] %}}{{% if cs %}}{t['r_at']}"
        "{% for c in cs %}" + change + "{% if not loop.last %}" + t["sep"] + "{% endif %}{% endfor %}{% endif %}"
    )
    return ESCAPE + t["r_question"].replace(
        "{recipe}", f"{{{{ e(states('{q}')) }}}}"
    ).replace(
        "{bag}", f"{{{{ e(state_attr('{q}', 'bag')) }}}}"
    ).replace("{changes}", changes)


def suggestion_card(t: dict, bag: str) -> str:
    """Why the suggestion chosen in the picker was suggested."""
    sugg = f"sensor.{E}_recipe_suggestions"
    if t is TEXT["ar"]:
        # Arabic counted-noun agreement for how many times it was brewed.
        times = ("{% if o.brews == 1 %}مرة واحدة{% elif o.brews == 2 %}مرتين"
                 "{% elif o.brews <= 10 %}{{ o.brews }} مرات{% else %}{{ o.brews }} مرة{% endif %}")
    else:
        times = "{% if o.brews == 1 %}once{% elif o.brews == 2 %}twice{% else %}{{ o.brews }} times{% endif %}"
    country = "{{ e(state_attr('" + bag + "', 'country')) }}"
    process = "{{ e(state_attr('" + bag + "', 'process')) }}"
    basis = (
        "{% if o.matched == 'this_bag' %}" + t["s_this_bag"]
        + "{% elif o.matched == 'origin_process' %}" + t["s_kind"].replace("{country}", country).replace("{process}", process)
        + "{% else %}" + t["s_origin"].replace("{country}", country) + "{% endif %}"
    )
    own = t["s_own"].replace("{times}", times).replace("{basis}", basis)
    pick = f"select.{E}_suggested_recipe"
    by = "{{ 'xBloom' if state_attr('" + pick + "', 'official') else e(state_attr('" + pick + "', 'author')) }}"
    hub_line = t["s_hub"].replace("{by}", by)
    verdicts = (
        "{% if v.verdict == 'again' %}" + t["verdict_again"]
        + "{% elif v.verdict == 'fine' %}" + t["verdict_fine"]
        + "{% else %}" + t["verdict_not_again"] + "{% endif %}"
    )
    versions = (
        "{% if o.versions %}\n\n" + t["v_versions"] + " "
        + "{% for v in o.versions %}" + version_words(t, "v") + " — " + verdicts
        + "{% if not loop.last %}; {% endif %}{% endfor %}.{% endif %}"
    )
    # Why the chosen suggestion was suggested; its name is in the picker.
    return (
        ESCAPE
        + f"{{% set source = state_attr('{pick}', 'source') %}}"
        + f"{{% set chosen = states('{pick}') %}}"
        + f"{{% set own = (state_attr('{sugg}', 'own') or []) | selectattr('name', 'eq', chosen) | list %}}"
        + "{% if source == 'own' and own %}{% set o = own[0] %}" + own + versions
        + "{% elif source == 'community' %}" + hub_line
        + f"{{% elif not (state_attr('{sugg}', 'own') or []) %}}" + t["s_none"] + "{% endif %}"
    )


def community_view(t: dict) -> dict:
    """Studio recipes others shared: suggest or search, read one, add it.

    Brewing stays on the Brew tab, through the same picker, bag and
    preparation as every other recipe.
    """
    sensor = f"sensor.{E}_community_matches"
    picker = f"select.{E}_community_recipe"
    trending, tea = f"select.{E}_trending_recipes", f"select.{E}_tea_recipes"
    for_you = f"sensor.{E}_for_you"
    return {"title": t["view_community"], "path": "community", "icon": "mdi:account-group",
            "type": "sections", "max_columns": 2, "sections": [
        # Signed in to the xBloom account: what the app's Recipes tab offers
        # it. Signed out, these entities are unavailable and the sections hidden.
        section(t["h_for_you"], [
            {"type": "markdown", "content": account_card(t, for_you, with_name=True)},
            press(f"button.{E}_another_for_you", name=t["a_another"]),
            press(f"button.{E}_add_for_you_recipe", t["c_confirm_add"], name=t["c_add"]),
        ], present(for_you)),
        section(t["h_trending"], [
            select(trending, name=t["c_recipe"]),
            {"type": "markdown", "content": account_card(t, trending)},
            press(f"button.{E}_add_trending_recipe", t["c_confirm_add"], name=t["c_add"]),
            toggle(f"switch.{E}_show_xpod_recipes"),
        ], present(trending)),
        section(t["h_tea"], [
            select(tea, name=t["c_recipe"]),
            {"type": "markdown", "content": account_card(t, tea)},
            press(f"button.{E}_add_tea_recipe", t["c_confirm_add"], name=t["c_add"]),
        ], present(tea)),
        section(t["h_find"], [
            # First: one press, a recipe to try with the bag in use.
            press(f"button.{E}_suggest_community_recipe", name=t["c_suggest_hub"]),
            tile(f"text.{E}_community_search", name=t["c_words"]),
            select(f"select.{E}_community_origin", name=t["c_origin"]),
            select(f"select.{E}_community_sort", name=t["c_sort"]),
            press(f"button.{E}_search_community", name=t["c_search"]),
            {"type": "markdown", "text_only": True, "content": matches_sentence(t, sensor, picker),
             "visibility": present(sensor)},
        ], present(f"text.{E}_community_search")[:1]),
        section(t["h_results"], [
            select(picker, name=t["c_recipe"]),
        ], [{"condition": "numeric_state", "entity": sensor, "above": 0}]),
        section(t["h_picked"], [
            {"type": "markdown", "content": picked_card(t, picker)},
            press(f"button.{E}_add_community_recipe", t["c_confirm_add"], name=t["c_add"]),
        ], [{"condition": "numeric_state", "entity": sensor, "above": 0}, *present(picker)]),
    ]}


def dashboard(lang: str) -> dict:
    t = TEXT[lang]
    return {"views": [brew_view(t), stats_view(t), bags_view(t), community_view(t), xbloom_view(t), archive_view(t)]}


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

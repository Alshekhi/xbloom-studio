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
        "machine": "Machine", "view_brew": "Brew", "view_stats": "Stats", "view_bags": "Bags", "view_xbloom": "xBloom",
        "stock_left": "{Kind} left: {n}", "stock_low_left": "Running low on {kind}: {n} left.",
        "stock_out": "No {kind} left.",
        "stock_about": "about {n}", "stock_at_least": "at least {n}", "stock_low": "Running low.", "h_stock": "Stock",
        "Kind_coffee": "Coffee", "Kind_tea": "Tea", "Kind_xpod": "xPods",
        "u_days": ("{n} day", "{n} days"), "u_cups": ("{n} cup", "{n} cups"),
        "u_bags": ("{n} bag", "{n} bags"), "u_packs": ("{n} pack", "{n} packs"),
        "u_pods": ("{n} pod", "{n} pods"), "u_boxes": ("{n} box", "{n} boxes"), "u_grams": "{n} g",
        "h_open_bags": "Open bags", "h_unopened_bags": "Unopened bags", "g_size": "{n} g",
        "d_roaster": "Roaster", "d_region": "Region", "d_producer": "Producer", "d_varietal": "Variety",
        "d_roast": "Roast", "d_roast_date": "Roasted", "d_altitude": "Altitude", "d_notes": "Tasting notes",
        "d_m": "{n} m", "d_link": "Shop page",
        "open_next": "Open next: {bag}", "past_best": "past its best", "h_opening": "Opening bags",
        "h_finish_a_bag": "Finish a bag", "f_chosen": "**{bag}**: {grams} g left",
        "f_chosen_unknown": "**{bag}**: amount not known", "f_confirm": "Finish this bag?",
        "brewers": "Brewers", "h_by_coffee": "By coffee", "h_by_recipe": "By recipe",
        "col_coffee": "Coffee", "col_cups": "Cups", "col_grams": "Grams", "col_recipe": "Recipe",
        "col_verdicts": "Verdicts", "h_by_month": "By month", "h_by_week": "By week", "col_month": "Month",
        "col_week": "Week of", "col_brews": "Brews",
        "months": ("January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"),
        "h_todays_cup": "Today's cup", "tc_line": "{cup}", "tc_sep": ", ", "tc_end": ".",
        "r_liked": "you liked it", "r_not_yesterday": "not the coffee you had last",
        "r_use_soon": "best used soon", "r_past_best": "past its best", "r_open_next": "time to open it", "r_last_cup": "the last cup of this bag",
        "r_rated_again": "rated Keep it like this with it", "r_brewed_with_bag": "brewed with it before",
        "r_like_this_coffee": "brewed with coffee like it", "r_community": "a community recipe",
        "stock_not_yet": "Not enough brews yet to tell how long the {kind} will last.",
        "stock_weigh": "Weigh the bags not counted yet to complete it.",
        "kind_coffee": "coffee", "kind_tea": "tea", "kind_xpod": "xPods",
        "h_now": "Right now", "h_in_progress": "Brew in progress", "h_bag": "Current bag", "pods_left": "Pods left: {n}", "k_xpod": "xPod box", "k_tea": "tea",
        "h_brew": "Brew with the xBloom", "h_adjust": "Adjust this brew",
        "h_save": "Save as a new recipe", "h_manual": "Manual brew", "h_stats": "Coffee stats",
        "h_connection": "Connection & status",
        "h_modules": "Modules", "h_grinder": "Grinder", "h_brewer": "Brewer", "h_scale": "Scale",
        "h_library": "Recipe library", "h_settings": "Settings", "h_stories": "Brew stories",
        "h_voice": "Voice announcements", "h_updates": "Updates", "h_events": "Recent machine events",
        "go_home": "Return the machine to its home screen to brew a recipe.",
        "show_advanced": "Show brew adjustments", "show_per_pour": "Show each pour",
        "preparing": "Preparing the recipe.", "need_bag": "Pick a bag to prepare this recipe.",
        "out_of_range": "The machine is out of range.", "need_water": "Add water.",
        "w_poured": "**Water poured:** {{ n }}{% if total %} of {{ total }}{% endif %} ml",
        "w_water": "**Water:** {% if left > 0 %}{{ left }} ml left{% else %}none left{% endif %}, {% if a.get('water_enough_to_finish') %}enough to finish{% else %}{{ short }} ml short{% endif %}",
        "not_taken": "The machine did not take the recipe. Pick it again.",
        "show_manual": "Show manual brew",
        "confirm_stop": "Stop the brew in progress?", "confirm_record": "Record this manual brew?",
        "confirm_archive": "Archive this recipe?",
        "confirm_archive_remove": "Archive this recipe and remove it from the xBloom cloud?",
        "confirm_delete": "Delete this recipe? It cannot be brought back.",
        "add_recipes": "Add or edit recipes", "add_bags": "Add or edit bags",
        "h_archive": "Archived recipes",
        "this_brew": "This brew", "coffee": "Coffee", "water": "Water", "ratio": "Ratio",
        "pour": "Pour", "of": "of", "st_waiting": "Waiting after pour", "st_draining": "Draining", "brew_time": "Brew time", "temp": "Temp", "pick_recipe": "Pick a recipe to see its pours.",
        "coffee_used": "Coffee used", "water_brewed": "Water brewed",
        "previous": "Brews in the period before", "other": "Other",
        "h_charts": "Brew history", "brews_daily": "Brews per day", "brews_monthly": "Brews per month",
        "coffee_weekly": "Coffee used per week", "water_weekly": "Water brewed per week",
        "xbloom_brews": "xBloom", "manual_brews": "Manual",
        "sep": ", ", "g": "g", "ml": "ml",
        "in_use": "in use", "unopened": "unopened", "open": "open", "g_left": "g left",
        "not_tracked": "not tracked", "no_bags": "No open or unopened bags.",
        "g_of": "{left} of {size} g left", "opened_0": "opened today", "opened_1": "opened yesterday",
        "opened_2": "opened 2 days ago", "opened_few": "opened {n} days ago", "opened_n": "opened {n} days ago",
        "speak_brew": "Speak brew progress", "speak_faults": "Speak machine faults",
        "speak_live": "Speak live readings",
        "view_community": "Community",
        "h_results": "Matching recipes",
        "c_words": "Search words", "c_origin": "Origin", "c_sort": "Sort", "c_search": "Search",
        "c_recipe": "Recipe", "c_add": "Add to my recipes",
        "c_confirm_add": "Add this recipe to your library?", "c_pours": "Pours", "c_desc_pours": "Description and pours",
        "c_none": "No recipes match.", "c_one": "1 recipe matches.",
        "c_many": "{n} recipes match.", "c_first": "The first {shown} are in the list below.",
        "c_by": "Shared by", "c_notes": "Tasting notes", "c_grind": "grind", "c_at": "at",
        "c_rpm": "RPM", "c_pause": "Pause", "c_s": "s", "c_likes": "likes",
        "c_fits": "Same as this bag", "f_process": "process", "f_varietal": "variety",
        "f_roast": "roast", "f_flavor": "tasting notes",
        "c_added": "Added to your recipes as **{name}**. Pick it on the Brew tab.",
        "c_suggest": "Suggest a recipe", "c_suggest_hub": "Suggest a community recipe",
        "a_another": "Another suggestion", "a_pod": "Pod", "a_tea": "Tea",
        "h_how_was": "How was it?", "r_verdict": "Verdict", "r_issue": "What was wrong", "w_which": "{recipe} with {bag}",
        "n_grind": "grind {value}", "n_ratio": "ratio 1:{value}", "n_dose": "{value} g of coffee",
        "v_wanted": "Last time you wanted: {text}.", "v_use": "Use that change",
        "h_keep": "Save this change?", "v_keep": "**{recipe}** {changes} is worth brewing again.",
        "v_make": "Update the saved recipe", "v_new": "Save as a new recipe",
        "v_leave": "Leave the recipe as it is",
        "v_confirm_make": "Change the saved recipe to these settings?",
        "v_versions": "Versions with this bag:", "k_grind": "grind {value}", "k_ratio": "1:{value}",
        "k_dose": "{value} g", "verdict_again": "Keep it like this", "verdict_fine": "Close, needs a tweak",
        "verdict_not_again": "Doesn't suit this coffee",
        "h_summary": "Summary", "h_recent": "Brews in this period",
        "y_days": "Days brewed", "y_of": "of", "y_streak": "Most days in a row",
        "y_cups": "Cups on a brewing day", "y_hot": "Usual hot cup", "y_iced": "Usual iced cup",
        "y_dose": "{dose} g at 1:{ratio}",         "y_time": "Usually brewed", "y_opened": "Bags opened",
        "t_morning": "in the morning", "t_afternoon": "in the afternoon", "t_evening": "in the evening",
        "t_night": "at night",
        "b_dose": "Dose", "b_water": "Water", "b_grind": "Grind",
        "b_flow": "Flow", "b_brewer": "Brewer", "b_next": "Next change",
        "b_review": "Needs review", "b_ml_s": "ml/s",
        "ts_body": "Body", "ts_acidity": "Acidity", "ts_sweetness": "Sweetness", "ts_clarity": "Clarity",
        "ts_hot_notes": "Hot", "ts_warm_notes": "Warm", "ts_cool_notes": "Cool",
        "ts_overall_notes": "Overall", "ts_finish": "Finish",
        "sv_light": "light", "sv_medium": "medium", "sv_full": "full", "sv_low": "low", "sv_high": "high",
        "h_buy_again": "Buy it again?", "b_question": "**{bag}** is finished.",
        "h_finish_bag": "Finish this bag?", "f_left": "**{bag}** has {grams} g left.",
        "b_answer": "Answer",
        "r_question": "**{recipe}** with {bag}{changes}.", "r_at": ", at ",
        "r_grind": "grind {value} instead of {saved}", "r_ratio": "ratio 1:{value} instead of 1:{saved}",
        "r_dose": "{value} g instead of {saved} g",
        "h_for_bag": "A recipe for this bag", "s_use": "Use this recipe",
        "s_own": "Brewed {times} {basis}.",
        "s_hub": "From the community, shared by {by}. Using it adds it to your recipes.",
        "s_this_bag": "with this bag", "s_kind": "with {country} {process} coffee",
        "s_origin": "with coffee from {country}",
        "c_for": "Suggested for **{bag}**, matching {basis}.",
        "c_popular": "The most downloaded Studio recipes.",
    },
    "ar": {
        "machine": "الآلة", "view_brew": "التحضير", "view_stats": "الإحصاءات", "view_bags": "الأكياس", "view_xbloom": "xBloom",
        "stock_left": "المتبقي من {Kind}: {n}", "stock_low_left": "مخزون {Kind} منخفض، والمتبقي {n}.",
        "stock_out": "نفد مخزون {Kind}.",
        "stock_about": "{n} تقريبًا", "stock_at_least": "{n} على الأقل", "stock_low": "الكمية منخفضة.", "h_stock": "المخزون",
        "Kind_coffee": "القهوة", "Kind_tea": "الشاي", "Kind_xpod": "كبسولات xPod",
        # One, two, three to ten, eleven and up.
        "u_days": ("يوم واحد", "يومان", "{n} أيام", "{n} يومًا"),
        "u_cups": ("كوب واحد", "كوبان", "{n} أكواب", "{n} كوبًا"),
        "u_bags": ("كيس واحد", "كيسان", "{n} أكياس", "{n} كيسًا"),
        "u_packs": ("عبوة واحدة", "عبوتان", "{n} عبوات", "{n} عبوة"),
        "u_pods": ("كبسولة واحدة", "كبسولتان", "{n} كبسولات", "{n} كبسولة"),
        "u_boxes": ("علبة واحدة", "علبتان", "{n} علب", "{n} علبة"), "u_grams": "{n} غ",
        "h_open_bags": "الأكياس المفتوحة", "h_unopened_bags": "الأكياس غير المفتوحة", "g_size": "{n} غ",
        "d_roaster": "المحمصة", "d_region": "المنطقة", "d_producer": "المُنتِج", "d_varietal": "الصنف",
        "d_roast": "درجة التحميص", "d_roast_date": "تاريخ التحميص", "d_altitude": "الارتفاع",
        "d_notes": "النكهات", "d_m": "{n} م", "d_link": "صفحة المتجر",
        "open_next": "افتح بعده: {bag}", "past_best": "تجاوز أفضل وقته", "h_opening": "فتح الأكياس",
        "h_finish_a_bag": "إنهاء كيس", "f_chosen": "**{bag}**: بقي {grams} غ",
        "f_chosen_unknown": "**{bag}**: الكمية غير معروفة", "f_confirm": "هل تنهي هذا الكيس؟",
        "brewers": "أدوات التحضير", "h_by_coffee": "حسب البن", "h_by_recipe": "حسب الوصفة",
        "col_coffee": "البن", "col_cups": "الأكواب", "col_grams": "الغرامات", "col_recipe": "الوصفة",
        "col_verdicts": "التقييمات", "h_by_month": "حسب الشهر", "h_by_week": "حسب الأسبوع", "col_month": "الشهر",
        "col_week": "أسبوع", "col_brews": "التحضيرات",
        "months": ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
                   "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"),
        "h_todays_cup": "كوب اليوم", "tc_line": "{cup}", "tc_sep": "، ", "tc_end": ".",
        "r_liked": "أعجبتك", "r_not_yesterday": "ليست آخر قهوة حضّرتها",
        "r_use_soon": "يحسن استخدامها قريبًا", "r_past_best": "تجاوزت أفضل وقتها", "r_open_next": "حان وقت فتحها", "r_last_cup": "آخر كوب من هذا الكيس",
        "r_rated_again": "قيّمت الوصفة معها بـ أعتمدها كما هي", "r_brewed_with_bag": "حضّرتها معها من قبل",
        "r_like_this_coffee": "حضّرتها مع قهوة مشابهة", "r_community": "وصفة من المجتمع",
        "stock_not_yet": "لا تكفي التحضيرات بعد لمعرفة كم يدوم {kind}.",
        "stock_weigh": "زن الأكياس التي لم تُحسب بعد لاكتماله.",
        "kind_coffee": "البن", "kind_tea": "الشاي", "kind_xpod": "كبسولات xPod",
        "h_now": "الآن", "h_in_progress": "تحضير جار", "h_bag": "الكيس الحالي", "pods_left": "الكبسولات المتبقية: {n}", "k_xpod": "علبة xPod", "k_tea": "شاي",
        "h_brew": "التحضير بماكينة xBloom", "h_adjust": "تعديل هذا التحضير",
        "h_save": "حفظ كوصفة جديدة", "h_manual": "تحضير يدوي", "h_stats": "إحصاءات القهوة",
        "h_connection": "الاتصال والحالة",
        "h_modules": "الوحدات", "h_grinder": "المطحنة", "h_brewer": "وحدة الصب", "h_scale": "الميزان",
        "h_library": "مكتبة الوصفات", "h_settings": "الإعدادات", "h_stories": "حكايات التحضير",
        "h_voice": "الإعلانات الصوتية", "h_updates": "التحديثات", "h_events": "أحدث أحداث الماكينة",
        "go_home": "أعد الماكينة إلى شاشتها الرئيسية لتحضير وصفة.",
        "show_advanced": "إظهار تعديلات التحضير", "show_per_pour": "إظهار كل صبة",
        "preparing": "يجري تجهيز الوصفة.", "need_bag": "اختر كيسا لتجهيز هذه الوصفة.",
        "out_of_range": "الماكينة خارج النطاق.", "need_water": "أضف ماءً.",
        "w_poured": "{% macro ml(n) %}{{ n }} {{ 'مليلتر' if n % 100 <= 2 else ('مليلترات' if n % 100 <= 10 else 'مليلترًا') }}{% endmacro %}**الماء المصبوب:** {% if total %}{{ n }} من {{ ml(total) }}{% else %}{{ ml(n) }}{% endif %}",
        "w_water": "{% macro ml(n) %}{{ n }} {{ 'مليلتر' if n % 100 <= 2 else ('مليلترات' if n % 100 <= 10 else 'مليلترًا') }}{% endmacro %}**الماء:** {% if left > 0 %}بقي {{ ml(left) }}{% else %}نفد{% endif %}، {% if a.get('water_enough_to_finish') %}يكفي لإكمال الوصفة{% else %}ينقص {{ ml(short) }}{% endif %}",
        "not_taken": "لم تقبل الماكينة الوصفة. اخترها مرة أخرى.",
        "show_manual": "إظهار التحضير اليدوي",
        "confirm_stop": "إيقاف التحضير الجاري؟", "confirm_record": "تسجيل هذا التحضير اليدوي؟",
        "confirm_archive": "أرشفة هذه الوصفة؟",
        "confirm_archive_remove": "أرشفة هذه الوصفة وحذفها من سحابة xBloom؟",
        "confirm_delete": "حذف هذه الوصفة؟ لا يمكن استعادتها.",
        "add_recipes": "إضافة الوصفات أو تعديلها", "add_bags": "إضافة الأكياس أو تعديلها",
        "h_archive": "الوصفات المؤرشفة",
        "this_brew": "هذا التحضير", "coffee": "القهوة", "water": "الماء", "ratio": "النسبة",
        "pour": "الصبة", "of": "من", "st_waiting": "انتظار بعد الصبة", "st_draining": "قيد التقطير", "brew_time": "زمن التحضير", "temp": "الحرارة", "pick_recipe": "اختر وصفة لعرض صباتها.",
        "coffee_used": "القهوة المستخدمة", "water_brewed": "الماء المستخدم",
        "previous": "التحضيرات في الفترة السابقة", "other": "أخرى",
        "h_charts": "سجل التحضير", "brews_daily": "التحضيرات يوميا", "brews_monthly": "التحضيرات شهريا",
        "coffee_weekly": "القهوة المستخدمة أسبوعيا", "water_weekly": "الماء المستخدم أسبوعيا",
        "xbloom_brews": "xBloom", "manual_brews": "يدوي",
        "sep": "، ", "g": "غ", "ml": "مل",
        "in_use": "قيد الاستخدام", "unopened": "غير مفتوح", "open": "مفتوح", "g_left": "غ متبقية",
        "not_tracked": "غير متتبع", "no_bags": "لا توجد أكياس مفتوحة أو غير مفتوحة.",
        "g_of": "متبقٍ {left} من {size} غ", "opened_0": "فُتح اليوم", "opened_1": "فُتح أمس",
        "opened_2": "فُتح قبل يومين", "opened_few": "فُتح قبل {n} أيام", "opened_n": "فُتح قبل {n} يومًا",
        "speak_brew": "إعلان سير التحضير", "speak_faults": "إعلان أعطال الماكينة",
        "speak_live": "إعلان القراءات المباشرة",
        "view_community": "المجتمع",
        "h_results": "الوصفات المطابقة",
        "c_words": "كلمات البحث", "c_origin": "المنشأ", "c_sort": "الترتيب", "c_search": "ابحث",
        "c_recipe": "الوصفة", "c_add": "أضفها إلى وصفاتي",
        "c_confirm_add": "إضافة هذه الوصفة إلى مكتبتك؟", "c_pours": "الصبات", "c_desc_pours": "الوصف والصبات",
        "c_none": "لا توجد وصفات مطابقة.", "c_one": "وصفة واحدة تطابق البحث.",
        "c_many": "{n} وصفات تطابق البحث.", "c_first": "أول {shown} منها في القائمة أدناه.",
        "c_by": "شاركها", "c_notes": "النكهات", "c_grind": "درجة الطحن", "c_at": "بسرعة",
        "c_rpm": "دورة في الدقيقة", "c_pause": "الانتظار", "c_s": "ث", "c_likes": "إعجاب",
        "c_fits": "تطابق هذا الكيس في", "f_process": "المعالجة", "f_varietal": "السلالة",
        "f_roast": "درجة التحميص", "f_flavor": "النكهات",
        "c_added": "أضيفت إلى وصفاتك باسم **{name}**. اخترها من تبويب التحضير.",
        "c_suggest": "اقترح وصفة", "c_suggest_hub": "اقترح وصفة من المجتمع",
       
        "a_another": "اقتراح آخر", "a_pod": "الكبسولة", "a_tea": "الشاي",
        "h_how_was": "كيف كانت؟", "r_verdict": "الحكم", "r_issue": "ما المشكلة", "w_which": "{recipe} مع {bag}",
        "n_grind": "درجة طحن {value}", "n_ratio": "نسبة 1:{value}", "n_dose": "{value} غ من البن",
        "v_wanted": "في المرة السابقة أردت: {text}.", "v_use": "استخدم هذا التعديل",
        "h_keep": "هل تحفظ هذا التعديل؟", "v_keep": "**{recipe}** {changes} تستحق التكرار.",
        "v_make": "حدّث الوصفة المحفوظة", "v_new": "احفظها كوصفة جديدة",
        "v_leave": "أبقِ الوصفة كما هي",
        "v_confirm_make": "تغيير الوصفة المحفوظة إلى هذه الإعدادات؟",
        "v_versions": "النسخ مع هذا الكيس:", "k_grind": "درجة طحن {value}", "k_ratio": "1:{value}",
        "k_dose": "{value} غ", "verdict_again": "أعتمدها كما هي", "verdict_fine": "قريبة، تحتاج تعديلًا",
        "verdict_not_again": "لا تناسب هذا البن",
        "h_summary": "الملخص", "h_recent": "تحضيرات هذه الفترة",
        "y_days": "أيام التحضير", "y_of": "من", "y_streak": "أطول أيام متتالية",
        "y_cups": "الأكواب في يوم التحضير", "y_hot": "كوبك الحار المعتاد", "y_iced": "كوبك البارد المعتاد",
        "y_dose": "{dose} غ بنسبة 1:{ratio}",         "y_time": "تحضّر عادةً", "y_opened": "أكياس فُتحت",
        "t_morning": "في الصباح", "t_afternoon": "بعد الظهر", "t_evening": "في المساء",
        "t_night": "في الليل",
        "b_dose": "الجرعة", "b_water": "الماء", "b_grind": "الطحن",
        "b_flow": "التدفق", "b_brewer": "أداة التحضير", "b_next": "التعديل القادم",
        "b_review": "يحتاج مراجعة", "b_ml_s": "مل/ث",
        "ts_body": "القوام", "ts_acidity": "الحموضة", "ts_sweetness": "الحلاوة", "ts_clarity": "الصفاء",
        "ts_hot_notes": "حارة", "ts_warm_notes": "دافئة", "ts_cool_notes": "باردة",
        "ts_overall_notes": "بشكل عام", "ts_finish": "الطعم الأخير",
        "sv_light": "خفيف", "sv_medium": "متوسط", "sv_full": "كامل", "sv_low": "منخفضة", "sv_high": "عالية",
        "h_buy_again": "هل تشتري هذا البن مجددًا؟", "b_question": "انتهى **{bag}**.",
        "h_finish_bag": "هل تنهي هذا الكيس؟", "f_left": "بقي في **{bag}** {grams} غ.",
        "b_answer": "الإجابة",
        "r_question": "**{recipe}** مع {bag}{changes}.", "r_at": "، ",
        "r_grind": "بدرجة طحن {value} بدل {saved}", "r_ratio": "بنسبة 1:{value} بدل 1:{saved}",
        "r_dose": "بجرعة {value} غ بدل {saved} غ",
        "h_for_bag": "وصفة لهذا الكيس", "s_use": "استخدم هذه الوصفة",
        "s_own": "حُضّرت {times} {basis}.",
        "s_hub": "من المجتمع، شاركها {by}. استخدامها يضيفها إلى وصفاتك.",
        "s_this_bag": "مع هذا الكيس", "s_kind": "مع قهوة من {country} بمعالجة {process}",
        "s_origin": "مع قهوة من {country}",
        "c_for": "مقترحة لـ **{bag}**، بمطابقة {basis}.",
        "c_popular": "أكثر وصفات Studio تنزيلًا.",
    },
}

E = "xbloom_studio"
# How the brew record names a brew made by the xBloom (coffee_lab.lab.XBLOOM_BREWER).
XBLOOM = "xBloom Studio"
# Unicode first-strong isolate and its end: a name between them keeps its own
# direction, so an Arabic name does not pull "(12)" or a separator into its
# right-to-left run.
ISO, PDI = "\u2068", "\u2069"
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
    # The dropdown shows what is chosen; a state line would only repeat it,
    # spoken twice, or read "Unknown" before anything is.
    extra.setdefault("hide_state", True)
    # No tap action either: the card is then its name and its dropdown, not
    # also a button repeating the name.
    extra.setdefault("tap_action", {"action": "none"})
    return tile(entity, features=[{"type": "select-options"}], **extra)


def slider(entity: str, **extra) -> dict:
    # No tap action: the card is its name, its value and the slider, not also
    # a button repeating the name.
    extra.setdefault("tap_action", {"action": "none"})
    return tile(entity, features=[{"type": "numeric-input", "style": "slider"}], **extra)


def present(entity: str) -> list[dict]:
    """Shown only when the entity exists and has something to show.

    A missing entity reads as unavailable, so this also hides Coffee Lab's
    cards while Coffee Lab is off.
    """
    return [{"condition": "state", "entity": entity, "state_not": s} for s in ("unavailable", "unknown")]


def is_(entity: str, state: str) -> dict:
    return {"condition": "state", "entity": entity, "state": state}


def is_not(entity: str, state: str) -> dict:
    return {"condition": "state", "entity": entity, "state_not": state}


def available(entity: str) -> list[dict]:
    """Shown while the entity exists, whatever it holds.

    For a select that waits for a pick: with nothing picked it reads
    `unknown`, which `present` would hide it by.
    """
    return [{"condition": "state", "entity": entity, "state_not": "unavailable"}]


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


TODAYS_CUP_REASONS = ('liked', 'not_yesterday', 'use_soon', 'past_best', 'open_next', 'rated_again', 'brewed_with_bag', 'like_this_coffee', 'community', 'last_cup')


def todays_cup_card(t: dict) -> str:
    """The bag, the recipe and the dose, then why, in one sentence.

    The reasons are codes; each is worded here, the first with a capital.
    """
    cup = f"sensor.{E}_todays_cup"
    words = "{" + ", ".join(f"'{k}': \"{t['r_' + k]}\"" for k in TODAYS_CUP_REASONS) + "}"
    named = lambda key: "('" + ISO + "' ~ e(a.get('" + key + "')) ~ '" + PDI + "')"  # noqa: E731
    return (
        ESCAPE
        + "{% set a = {" + ", ".join(f"'{k}': state_attr('{cup}', '{k}')" for k in ("bag", "recipe", "dose_g", "reasons")) + "} %}"
        + "{% set cup = [" + named("bag") + ", " + named("recipe") + " if a.get('recipe') else '',"
        " (((a.get('dose_g') or 0) | float | round(1) | string | replace('.0', '')) ~ ' " + t["g"] + "')"
        " if a.get('recipe') else ''] | select | join(' · ') %}"
        "{% set words = " + words + " %}{% set ns = namespace(said=[]) %}"
        "{% for r in a.get('reasons') or [] %}{% if r in words %}{% set ns.said = ns.said + [words[r]] %}"
        "{% endif %}{% endfor %}{% set why = ns.said | join(" + repr(t["tc_sep"]) + ") %}"
        + t["tc_line"].replace("{cup}", "{{ cup }}")
        + "{% if why %}\n\n{{ why[:1] | upper }}{{ why[1:] }}" + t["tc_end"] + "{% endif %}"
    )


def brew_view(t: dict) -> dict:
    bag = f"select.{E}_coffee_bag"
    kind = f"sensor.{E}_recipe_kind"
    manual = "input_boolean.xbloom_show_manual_brew"
    box, tea = f"select.{E}_xpod_box", f"select.{E}_tea"
    # Shown while the picked recipe draws from a bag of coffee.
    coffee = [{"condition": "state", "entity": kind, "state_not": k} for k in ("xpod", "tea")]

    # The recipe, and the section it is in, once what it brews from is
    # chosen — or with nothing to choose, or a recipe already picked.
    recipe_offered = {"condition": "or", "conditions": [
        is_(bag, "unavailable"),
        {"condition": "and", "conditions": present(f"select.{E}_recipe")},
        *({"condition": "and", "conditions": present(item)} for item in (bag, box, tea)),
    ]}

    def kind_or_none(k: str) -> dict:
        """The picked recipe draws from this kind, or no recipe is picked yet."""
        return {"condition": "or", "conditions": [
            is_(kind, k), is_(kind, "unknown"), is_(kind, "unavailable"),
        ]}
    return {"title": t["view_brew"], "path": "brew", "icon": "mdi:coffee", "type": "sections", "max_columns": 2, "sections": [
        # Today's cup: while the machine is idle, nothing is picked yet, and
        # there is a cup to offer.
        {"type": "grid", "cards": [
            heading(t["h_todays_cup"]),
            {"type": "markdown", "content": todays_cup_card(t)},
            press(f"button.{E}_use_todays_cup"),
            press(f"button.{E}_another_cup"),
            press(f"button.{E}_by_hand"),
        ], "visibility": [
            *present(f"sensor.{E}_todays_cup"),
            is_not(f"sensor.{E}_brew_status", "grinding"),
            is_not(f"sensor.{E}_brew_status", "brewing"),
            is_(f"select.{E}_recipe", "unknown"),
        ]},
        section(t["h_now"], [
            tile(f"sensor.{E}_brew_status"),
            tile(f"binary_sensor.{E}_in_range", name=t["machine"]),
            # What the picked recipe draws from: the bag, the xPod box or the tea.
            tile(f"sensor.{E}_coffee_left", visibility=[*present(f"sensor.{E}_coffee_left"), *coffee]),
            # Only when it is the bag's last cup: the dose that uses all of it.
            press(f"button.{E}_use_rest_of_bag", visibility=available(f"button.{E}_use_rest_of_bag")),
            tile(f"select.{E}_xpod_box", visibility=[is_(kind, "xpod"), *present(f"select.{E}_xpod_box")]),
            tile(f"select.{E}_tea", visibility=[is_(kind, "tea"), *present(f"select.{E}_tea")]),
            # What the picked recipe draws from, only while it is running low;
            # how much is left at any time is on the Bags tab.
            stock_low_card(t, "coffee", visibility=[*coffee, is_(f"binary_sensor.{E}_coffee_stock_low", "on")]),
            stock_low_card(t, "tea", visibility=[is_(kind, "tea"), is_(f"binary_sensor.{E}_tea_stock_low", "on")]),
            stock_low_card(t, "xpod", visibility=[is_(kind, "xpod"), is_(f"binary_sensor.{E}_xpod_stock_low", "on")]),
            # Only while a brew could not be saved; it is retried by itself.
            tile(f"sensor.{E}_waiting_brews", visibility=[
                {"condition": "numeric_state", "entity": f"sensor.{E}_waiting_brews", "above": 0}]),
        ]),
        # Due a while after a brew; never while one is running.
        section(t["h_how_was"], [
            {"type": "markdown", "text_only": True, "content": rating_card(t)},
            select(f"select.{E}_verdict", name=t["r_verdict"]),
        ], [*present(f"sensor.{E}_brew_to_rate"), *not_busy()]),
        # After a Fine: what was wrong sets what to change next time.
        section(t["r_issue"], [
            {"type": "markdown", "text_only": True, "content": ESCAPE + t["w_which"].replace(
                "{recipe}", f"{{{{ e(state_attr('select.{E}_what_was_wrong', 'recipe')) }}}}"
            ).replace("{bag}", f"{{{{ e(state_attr('select.{E}_what_was_wrong', 'bag')) }}}}")},
            # Named apart from the heading above it, or it is said twice.
            select(f"select.{E}_what_was_wrong", name=t["b_answer"]),
        ], [*available(f"select.{E}_what_was_wrong"), *not_busy()]),
        # A brew left the bag short of another cup: finish it, or keep it.
        section(t["h_finish_bag"], [
            {"type": "markdown", "text_only": True, "content": ESCAPE + t["f_left"].replace(
                "{bag}", ISO + f"{{{{ e(states('sensor.{E}_bag_to_finish')) }}}}" + PDI
            ).replace("{grams}", f"{{{{ (state_attr('sensor.{E}_bag_to_finish', 'remaining_g') or 0) | float | round(1) | string | replace('.0', '') }}}}")},
            press(f"button.{E}_finish_bag"),
            press(f"button.{E}_keep_bag"),
        ], [*present(f"sensor.{E}_bag_to_finish"), *not_busy()]),
        section(t["h_buy_again"], [
            {"type": "markdown", "text_only": True, "content": ESCAPE + t["b_question"].replace(
                "{bag}", f"{{{{ e(states('sensor.{E}_finished_bag')) }}}}")},
            select(f"select.{E}_buy_again", name=t["b_answer"]),
        ], [*present(f"sensor.{E}_finished_bag"), *not_busy()]),
        section(t["h_keep"], [
            {"type": "markdown", "text_only": True, "content": keep_card(t)},
            press(f"button.{E}_make_version_the_recipe", t["v_confirm_make"], name=t["v_make"]),
            press(f"button.{E}_save_version_as_new_recipe", name=t["v_new"]),
            press(f"button.{E}_leave_recipe_unchanged", name=t["v_leave"]),
        ], [*present(f"sensor.{E}_version_to_keep"), *not_busy()]),
        section(t["h_in_progress"], [
            tile(f"sensor.{E}_current_recipe", visibility=present(f"sensor.{E}_current_recipe")),
            # "Pour 2 of 3" while it pours, "Waiting after pour 2" between
            # pours, "Draining" after the last, once the pours have begun.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set p = 'sensor.{E}_current_pour' %}}{{% set total = state_attr(p, 'total_pours') %}}"
                f"{{% set stage = states('sensor.{E}_brew_stage') %}}"
                f"{{% if stage == 'waiting' %}}**{t['st_waiting']} {{{{ states(p) }}}}**"
                f"{{% elif stage == 'draining' %}}**{t['st_draining']}**"
                f"{{% else %}}**{t['pour']} {{{{ states(p) }}}}{{% if total %}} {t['of']} {{{{ total }}}}{{% endif %}}**{{% endif %}}"
            ), "visibility": [{"condition": "numeric_state", "entity": f"sensor.{E}_current_pour", "above": 0}]},
            # "Next Pour: in 15 seconds", counted down by Home Assistant itself.
            tile(f"sensor.{E}_next_pour", visibility=present(f"sensor.{E}_next_pour")),
            # The brew story: what this pour does, and the story part on screen.
            {"type": "markdown", "text_only": True, "show_empty": False, "content": ESCAPE + (
                f"{{% set s = 'sensor.{E}_brew_story' %}}"
                f"{{% if state_attr(s, 'now') %}}{{{{ e(state_attr(s, 'now')) }}}}{{% endif %}}"
                f"{{% if state_attr(s, 'story') %}}\n\n**{{{{ e(states(s)) }}}}**\n\n"
                f"{{{{ e(state_attr(s, 'story')) }}}}{{% endif %}}"
            ), "visibility": [{"condition": "state", "entity": f"sensor.{E}_brew_stage",
                               "state": ["pouring", "waiting", "draining"]}]},
            # Minutes and seconds, "2:28"; it re-renders as the sensor ticks.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set s = states('sensor.{E}_brew_time') | int(0) %}}"
                f"**{t['brew_time']} {{{{ s // 60 }}}}:{{{{ '%02d' % (s % 60) }}}}**"
            ), "visibility": present(f"sensor.{E}_brew_time")},
            # "Water poured: 310 of 500 ml", as the machine reports it.
            {"type": "markdown", "text_only": True, "content": (
                f"{{% set n = states('sensor.{E}_water_poured') | int(0) %}}"
                f"{{% set total = state_attr('sensor.{E}_water_poured', 'recipe_water_ml') %}}"
                + t["w_poured"]
            ), "visibility": present(f"sensor.{E}_water_poured")},
            # The water left and what the recipe still needs, once the
            # low-water switch has tripped; empty, and hidden, otherwise.
            {"type": "markdown", "text_only": True, "show_empty": False, "content": water_card(t),
             "visibility": [is_(f"sensor.{E}_machine_status", "no_water")]},
            # One of the two, by whether the machine reports the brew paused.
            press(f"button.{E}_pause_brew", visibility=[is_(f"binary_sensor.{E}_brew_paused", "off")]),
            press(f"button.{E}_resume_brew", visibility=[is_(f"binary_sensor.{E}_brew_paused", "on")]),
            press(f"button.{E}_cancel_brew", t["confirm_stop"]),
        ], [{"condition": "or", "conditions": [is_(f"sensor.{E}_brew_status", s) for s in BUSY]}]),
        section(t["h_bag"], [
            # The picker for what the picked recipe draws from: a bag of
            # coffee, an xPod box, or a tea.
            # Before a recipe is picked, every kind there is to choose from
            # shows, so a box or a tea can be chosen first too.
            select(bag, visibility=coffee),
            select(box, visibility=[kind_or_none("xpod"), is_not(box, "unavailable")]),
            {"type": "markdown", "text_only": True, "content": (
                "{% set n = state_attr('" + box + "', 'pods_left') %}"
                "{% if n is not none %}" + t["pods_left"].replace("{n}", "{{ n }}") + "{% endif %}"
            ), "visibility": [kind_or_none("xpod"), *present(box)]},
            select(tea, visibility=[kind_or_none("tea"), is_not(tea, "unavailable")]),
            {"type": "markdown", "content": (
                "{% set a = states['" + bag + "'].attributes if states['" + bag + "'] else {} %}"
                "{{ [a.get('roaster'), [a.get('country'), a.get('region')] | select | join('" + t["sep"] + "'), a.get('process'), a.get('varietal'), a.get('roast')]"
                " | select | join(' · ') }}"
                "{% if a.get('roaster_notes') %}\n\n{{ a.get('roaster_notes') }}{% endif %}"
            ), "visibility": [*present(bag), *coffee]},
            tile(f"sensor.{E}_last_brew_counted", visibility=[is_(f"sensor.{E}_last_brew_counted", "flagged")]),
            # A bag added or changed in Notion itself shows here at once.
            press(f"button.{E}_refresh_coffee_bags", visibility=[is_not(f"button.{E}_refresh_coffee_bags", "unavailable")]),
        # Not hidden while no bag is chosen: this is where one is chosen.
        ], present(bag)[:1]),
        # Asked for here, where the bag is chosen. Nothing reaches the machine
        # until a recipe is used: picking one is what prepares it.
        section(t["h_for_bag"], [
            # Hot or iced: what is suggested is only for that drink.
            select(f"select.{E}_drink"),
            press(f"button.{E}_suggest_recipe", name=t["c_suggest"]),
            # Every suggestion, your own first; the card below says why the
            # chosen one was suggested, and Use picks it for brewing.
            select(f"select.{E}_suggested_recipe", visibility=present(f"select.{E}_suggested_recipe")),
            {"type": "markdown", "content": suggestion_card(t, bag),
             "visibility": present(f"sensor.{E}_recipe_suggestions")},
            press(f"button.{E}_use_suggested_recipe", name=t["s_use"],
                  visibility=present(f"select.{E}_suggested_recipe")),
        ], [*present(bag), *at_home()]),
        # With Coffee Lab on, the recipe is offered once what it draws from is
        # chosen — or when there is nothing to choose, or a recipe is already
        # picked (from a suggestion, an assistant or an automation).
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
                  visibility=[is_(f"binary_sensor.{E}_recipe_ready", "on")]),
            # Signed in, a recipe added in the xBloom app is read again when a
            # bag is chosen; with no bag to choose, here.
            press(f"button.{E}_refresh_recipes", grid_options={"columns": 6}, visibility=[
                is_(bag, "unavailable"), is_not(f"button.{E}_refresh_recipes", "unavailable"),
            ]),
            toggle("input_boolean.xbloom_show_advanced", name=t["show_advanced"],
                   visibility=present(f"select.{E}_recipe")),
        ], [*at_home(), recipe_offered]),
        section(t["h_brew"], [
            {"type": "markdown", "text_only": True, "content": t["go_home"]},
        ], [
            {"condition": "or", "conditions": [is_(f"sensor.{E}_current_module", m) for m in MODULES]},
            *not_busy(),
        ]),
        section(t["h_adjust"], [
            toggle(f"switch.{E}_use_grinder"),
            # Moves the grind below, from the recipe's; the recipe is kept.
            select(f"select.{E}_taste", visibility=[is_(f"switch.{E}_use_grinder", "on")]),
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
                f"{{% else %}}- **{t['coffee']}:** {_num('dose')} {t['g']}\n"
                f"- **{t['water']}:** {{{{ water | round(0) | int }}}} {t['ml']}\n"
                f"{{% endif %}}- **{t['ratio']}:** 1:{_num('ratio')}"
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
        # A manual brew takes its coffee from the bag in use, so it is offered
        # only once one is chosen.
        ], present(bag)),
    ]}


def stats_view(t: dict) -> dict:
    stats = f"sensor.{E}_brews"
    history = f"sensor.{E}_brew_history"
    some = [{"condition": "numeric_state", "entity": stats, "above": 0}]
    return {"title": t["view_stats"], "path": "stats", "icon": "mdi:chart-bar", "type": "sections", "max_columns": 2, "sections": [
        section(t["h_stats"], [
            select(f"select.{E}_stats_period"),
            tile(stats),
            {"type": "markdown", "content": coffee_stats_card(t)},
        ], present(stats)[:1]),
        # Its heading is part of the card, so while the habits cannot be read
        # neither shows, rather than a heading over an empty card.
        {"type": "grid", "cards": [{"type": "markdown", "text_only": True, "show_empty": False,
                                    "content": summary_card(t)}], "visibility": some},
        {"type": "grid", "cards": [{"type": "markdown", "text_only": True, "show_empty": False,
                                    "content": by_coffee_card(t)}], "visibility": some},
        {"type": "grid", "cards": [{"type": "markdown", "text_only": True, "show_empty": False,
                                    "content": by_recipe_card(t)}], "visibility": some},
        section(t["h_recent"], [{"type": "markdown", "content": recent_card(t)}],
                [is_not(f"sensor.{E}_recent_brews", "unknown"), *present(f"sensor.{E}_recent_brews")[:1]]),
        # The history as numbers to read, then the same drawn as charts.
        section(t["h_charts"], [
            {"type": "markdown", "content": history_card(t)},
            chart(t["brews_daily"], "day", 30, [
                ("xbloom:brews_xbloom", t["xbloom_brews"]), ("xbloom:brews_manual", t["manual_brews"])]),
            chart(t["brews_monthly"], "month", 365, [
                ("xbloom:brews_xbloom", t["xbloom_brews"]), ("xbloom:brews_manual", t["manual_brews"])]),
            chart(t["coffee_weekly"], "week", 90, [("xbloom:coffee_used", t["coffee_used"])]),
            chart(t["water_weekly"], "week", 90, [("xbloom:water_brewed", t["water_brewed"])]),
        ], present(history)[:1]),
    ]}


def coffee_stats_card(t: dict) -> str:
    """The period's coffee, water, the period before, and the brewers in one line."""
    stats = f"sensor.{E}_brews"
    attr = lambda k: f"state_attr('{stats}', '{k}')"  # noqa: E731
    return (
        ESCAPE
        + f"- **{t['coffee_used']}:** {{{{ ({attr('coffee_g')} or 0) | round(0) | int }}}} {t['g']}\n"
        f"{{% if {attr('water_ml')} %}}- **{t['water_brewed']}:** {{{{ {attr('water_ml')} | round(0) | int }}}} {t['ml']}\n{{% endif %}}"
        f"- **{t['previous']}:** {{{{ ({attr('previous_period')} or {{}}).get('brews', 0) }}}}\n"
        f"{{% set brewers = {attr('by_brewer')} or {{}} %}}{{% if brewers %}}- **{t['brewers']}:** "
        "{% for name, n in brewers.items() %}" + ISO
        + f"{{{{ \"{t['other']}\" if name == 'other' else e(name) }}}}" + PDI
        + " ({{ n }}){% if not loop.last %}" + t["sep"] + "{% endif %}{% endfor %}\n{% endif %}"
    )


def by_coffee_card(t: dict) -> str:
    stats = f"sensor.{E}_brews"
    return (
        ESCAPE + f"{{% set rows = (state_attr('{stats}', 'habits') or {{}}).get('by_coffee') or [] %}}"
        f"{{% if rows %}}## {t['h_by_coffee']}\n\n"
        f"| {t['col_coffee']} | {t['col_cups']} | {t['col_grams']} |\n|---|---|---|\n"
        "{% for r in rows %}| " + ISO + "{{ e(r.get('name')) }}" + PDI
        + " | {{ r.get('brews', 0) }} | {{ (r.get('coffee_g') or 0) | round(0) | int }} |\n{% endfor %}{% endif %}"
    )


def verdict_counts(t: dict, var: str = "v") -> str:
    """The verdicts given, each with its count; none left as an empty place."""
    return "{{ [" + ", ".join(
        # Double quotes: a verdict can hold an apostrophe ("Doesn't").
        f"(\"{t['verdict_' + k]}\" ~ ' (' ~ {var}.get('{k}') ~ ')') if {var}.get('{k}') else ''"
        for k in ("again", "fine", "not_again")
    ) + "] | select | join(" + repr(t["sep"]) + ") }}"


def by_recipe_card(t: dict) -> str:
    stats = f"sensor.{E}_brews"
    return (
        ESCAPE + f"{{% set rows = (state_attr('{stats}', 'habits') or {{}}).get('by_recipe') or [] %}}"
        # The heading is part of the card, so neither shows with nothing to list.
        f"{{% if rows %}}## {t['h_by_recipe']}\n\n"
        f"| {t['col_recipe']} | {t['col_cups']} | {t['col_verdicts']} |\n|---|---|---|\n"
        "{% for r in rows %}{% set v = r.get('verdicts') or {} %}| " + ISO + "{{ e(r.get('name')) }}" + PDI
        + " | {{ r.get('brews', 0) }} | " + verdict_counts(t) + " |\n{% endfor %}{% endif %}"
    )


def history_card(t: dict) -> str:
    """Brews, coffee and water by month and by week: what the charts below draw."""
    history = f"sensor.{E}_brew_history"
    months = "[" + ", ".join(repr(m) for m in t["months"]) + "]"
    # No water recorded (manual brews) is a blank cell, as the stats above leave it out.
    row = (" | {{ r.get('brews', 0) }} | {{ (r.get('coffee_g') or 0) | round(0) | int }} " + t["g"]
           + " | {% if r.get('water_ml') %}{{ r.get('water_ml') | round(0) | int }} " + t["ml"] + "{% endif %} |\n")
    return (
        f"{{% set names = {months} %}}"
        f"{{% set this_year = ((state_attr('{history}', 'by_month') or [{{}}])[0].get('start') or '')[:4] %}}"
        f"{{% if state_attr('{history}', 'by_month') or state_attr('{history}', 'by_week') %}}"
        f"### {t['h_by_month']}\n\n| {t['col_month']} | {t['col_brews']} | {t['coffee']} | {t['water']} |\n|---|---|---|---|\n"
        f"{{% for r in state_attr('{history}', 'by_month') or [] %}}{{% set d = r.get('start') or '0000-01' %}}"
        "| {{ names[(d[5:7] | int) - 1] }} {{ d[:4] }}" + row + "{% endfor %}\n"
        f"### {t['h_by_week']}\n\n| {t['col_week']} | {t['col_brews']} | {t['coffee']} | {t['water']} |\n|---|---|---|---|\n"
        f"{{% for r in state_attr('{history}', 'by_week') or [] %}}{{% set d = r.get('start') or '0000-00-00' %}}"
        # The year only for a week of another year than this one.
        "| {{ d[8:10] }}/{{ d[5:7] }}{% if d[:4] != this_year %}/{{ d[:4] }}{% endif %}" + row + "{% endfor %}{% endif %}"
    )


def _n(expr: str) -> str:
    """A number as a person reads it: 17, not 17.0."""
    return "((" + expr + " | float) | round(1) | string | replace('.0', ''))"


def summary_card(t: dict) -> str:
    """What the period's brews show, a line for each habit there is."""
    stats = f"sensor.{E}_brews"
    usual = "".join(
        f"{{% if u.get('{drink}') %}}- **{t['y_' + drink]}:** "
        + t["y_dose"].replace("{dose}", "{{ " + _n(f"u['{drink}'].dose_g") + " }}")
                     .replace("{ratio}", "{{ " + _n(f"u['{drink}'].ratio") + " }}")
        + "\n{% endif %}"
        for drink in ("hot", "iced")
    )
    times = "".join(
        f"{{% {'if' if i == 0 else 'elif'} h.time_of_day == '{k}' %}}{t['t_' + k]}"
        for i, k in enumerate(("morning", "afternoon", "evening", "night"))
    ) + "{% endif %}"
    return (
        ESCAPE
        + f"{{% set h = state_attr('{stats}', 'habits') or {{}} %}}"
        + "{% if h %}{% set u = h.get('usual') or {} %}"
        + f"## {t['h_summary']}\n\n"
        + f"- **{t['y_days']}:** {{{{ h.get('days_brewed', 0) }}}} {t['y_of']} {{{{ h.get('days_in_period', 0) }}}}\n"
        + f"{{% if h.get('longest_streak_days', 0) > 1 %}}- **{t['y_streak']}:** {{{{ h.longest_streak_days }}}}\n{{% endif %}}"
        + f"{{% if h.get('cups_per_brewing_day') %}}- **{t['y_cups']}:** {{{{ {_n('h.cups_per_brewing_day')} }}}}\n{{% endif %}}"
        + usual
        + f"{{% if h.get('time_of_day') %}}- **{t['y_time']}:** {times}\n{{% endif %}}"
        + f"{{% if h.get('bags_opened') %}}- **{t['y_opened']}:** "
        + "{% for b in h.bags_opened %}" + ISO + "{{ e(b) }}" + PDI + "{% if not loop.last %}" + t["sep"] + "{% endif %}{% endfor %}{% endif %}"
        + "{% endif %}"
    )


def recent_card(t: dict) -> str:
    """The period's brews, each a line that opens to how it was made and tasted.

    A disclosure per brew: announced as collapsed or expanded and opened in
    place, so the list stays short to move through and each brew is one step
    from its detail.
    """
    recent = f"sensor.{E}_recent_brews"
    scale = "".join(
        f"{{% {'if' if i == 0 else 'elif'} val == '{k}' %}}{t['sv_' + k]}"
        for i, k in enumerate(("light", "medium", "full", "low", "high"))
    ) + "{% else %}{{ e(val) }}{% endif %}"
    tasting = "".join(
        f"{{% if ts.get('{k}') %}}{{% set val = ts.get('{k}') %}}- **{t['ts_' + k]}:** "
        + (scale if k in ("body", "acidity", "sweetness", "clarity") else "{{ e(val) }}")
        + "\n{% endif %}"
        for k in ("body", "acidity", "sweetness", "clarity",
                  "hot_notes", "warm_notes", "cool_notes", "overall_notes", "finish")
    )
    verdict = "".join(
        f"{{% {'if' if i == 0 else 'elif'} b.get('verdict') == '{k}' %}}{t['verdict_' + k]}"
        for i, k in enumerate(("again", "fine", "not_again"))
    ) + "{% endif %}"
    # Only the parts the brew has, so no line starts with a separator. Inside
    # the HTML of the summary markdown is not read, so names are escaped as
    # HTML there, not as markdown.
    summary = (
        "{% set when = as_datetime(b.get('brewed_at') or '', none) %}"
        "{% set verdict %}" + verdict + "{% endset %}"
        "{{ [when.strftime('%d/%m %H:%M') if when else '', ('\u2068' ~ b.recipe ~ '\u2069') if b.get('recipe') else '', ('\u2068' ~ b.bag ~ '\u2069') if b.get('bag') else '',"
        " verdict] | select | join(' · ') | escape }}"
    )
    rows = (
        f"{{% if b.get('dose_g') %}}- **{t['b_dose']}:** {{{{ {_n('b.dose_g')} }}}} {t['g']}"
        f"{{% if b.get('ratio') %}} · 1:{{{{ {_n('b.ratio')} }}}}{{% endif %}}\n{{% endif %}}"
        f"{{% if b.get('water_ml') %}}- **{t['b_water']}:** {{{{ b.water_ml | round(0) | int }}}} {t['ml']}\n{{% endif %}}"
        # The grind is text in the record — a manual brew's can be "medium
        # fine" — so it is shown as written, a trailing ".0" dropped.
        f"{{% if b.get('grind') %}}- **{t['b_grind']}:** {{{{ e(b.grind | string | regex_replace('[.]0$', '')) }}}}\n{{% endif %}}"
        f"{{% if b.get('temperature_c') %}}- **{t['temp']}:** {{{{ {_n('b.temperature_c')} }}}}°\n{{% endif %}}"
        f"{{% if b.get('flow_rate') %}}- **{t['b_flow']}:** {{{{ {_n('b.flow_rate')} }}}} {t['b_ml_s']}\n{{% endif %}}"
        "{% if b.get('duration_s') %}{% set s = b.duration_s | int %}"
        f"- **{t['brew_time']}:** {{{{ s // 60 }}}}:{{{{ '%02d' % (s % 60) }}}}\n{{% endif %}}"
        # The xBloom is the usual brewer; only another one is worth a line.
        f"{{% if b.get('brewer') and b.brewer != '{XBLOOM}' %}}- **{t['b_brewer']}:** {{{{ e(b.brewer) }}}}\n{{% endif %}}"
        + "{% set ts = b.get('tasting') or {} %}" + tasting
        + f"{{% if b.get('next_change') %}}- **{t['b_next']}:** {{{{ e(b.next_change) }}}}\n{{% endif %}}"
        + f"{{% if b.get('needs_review') %}}- **{t['b_review']}**\n{{% endif %}}"
    )
    return (
        ESCAPE
        + f"{{% for b in state_attr('{recent}', 'brews') or [] %}}"
        + "<details><summary>" + summary + "</summary>\n\n" + rows + "\n</details>\n"
        + "{% endfor %}"
    )


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


def water_card(t: dict) -> str:
    """The water left and the shortfall, exactly, while a brew's switch has tripped."""
    return (
        f"{{% set a = states['sensor.{E}_machine_status'].attributes "
        f"if states['sensor.{E}_machine_status'] else {{}} %}}"
        "{% set left = a.get('water_left_ml') %}"
        "{% if left is number %}"
        "{% set short = [a.get('water_needed_ml', 0) - left, 0] | max %}"
        + t["w_water"] + "{% endif %}"
    )


def opened_ago(t: dict) -> str:
    """How long ago bag `b` was opened, counted the language's way, from `days`."""
    n = "{{ days }}"
    if t is TEXT["ar"]:
        # Arabic counted-noun agreement: today, yesterday, two, three to ten, eleven and up.
        return (
            f"{{% if days == 0 %}}{t['opened_0']}{{% elif days == 1 %}}{t['opened_1']}"
            f"{{% elif days == 2 %}}{t['opened_2']}{{% elif days <= 10 %}}{t['opened_few'].replace('{n}', n)}"
            f"{{% else %}}{t['opened_n'].replace('{n}', n)}{{% endif %}}"
        )
    return (
        f"{{% if days == 0 %}}{t['opened_0']}{{% elif days == 1 %}}{t['opened_1']}"
        f"{{% else %}}{t['opened_n'].replace('{n}', n)}{{% endif %}}"
    )


def counted(t: dict, unit: str, n: str) -> str:
    """`n` of a unit, counted the language's way: "1 day", "5 days"; in
    Arabic one, two, three to ten, and eleven and up each have their form."""
    forms = t[f"u_{unit}"]
    if isinstance(forms, str):
        return forms.replace("{n}", "{{ " + n + " }}")
    if len(forms) == 2:
        one, many = forms
        return ("{% if " + n + " == 1 %}" + one.replace("{n}", "1") + "{% else %}"
                + many.replace("{n}", "{{ " + n + " }}") + "{% endif %}")
    one, two, few, many = forms
    return ("{% if " + n + " == 1 %}" + one + "{% elif " + n + " == 2 %}" + two
            + "{% elif 3 <= " + n + " <= 10 %}" + few.replace("{n}", "{{ " + n + " }}")
            + "{% else %}" + many.replace("{n}", "{{ " + n + " }}") + "{% endif %}")


def stock_amount(t: dict, kind: str) -> str:
    """What is left of a kind in its chosen measure, as words: "about 67
    days", "640 g", "at least 12 days" while some of it is not counted.

    Days and cups are reckoned from the pace of brewing, so they are said as
    "about"; grams, bags, pods and boxes are counted, so they are not.
    """
    q = f"sensor.{E}_{kind}_stock"
    measures = ("days", "pods", "boxes") if kind == "xpod" else ("days", "grams", "cups", "bags")
    parts = []
    for i, m in enumerate(measures):
        # Tea in tins and pouches: packs, never "bags" taken for tea bags.
        unit = "packs" if (kind, m) == ("tea", "bags") else m
        words = counted(t, unit, "n")
        if m in ("days", "cups"):
            words = ("{% if least is not none %}" + t["stock_at_least"].replace("{n}", words)
                     + "{% else %}" + t["stock_about"].replace("{n}", words) + "{% endif %}")
        else:
            words = ("{% if least is not none %}" + t["stock_at_least"].replace("{n}", words)
                     + "{% else %}" + words + "{% endif %}")
        parts.append(("{% if" if i == 0 else "{% elif") + f" m == '{m}' %}}" + words)
    return "".join(parts) + "{% endif %}"


def stock_vars(kind: str) -> str:
    """The measure, the floor while some of it is not counted, and the figure
    as a whole number, for stock_amount and the lines around it."""
    q = f"sensor.{E}_{kind}_stock"
    return (f"{{% set m = state_attr('{q}', 'measure') %}}"
            f"{{% set least = state_attr('{q}', 'at_least') %}}"
            f"{{% set n = ((least if least is not none else states('{q}')) | float(0) | round(0) | int) %}}")


def stock_out(t: dict, kind: str) -> str:
    return t["stock_out"].replace("{kind}", t[f"kind_{kind}"]).replace("{Kind}", t[f"Kind_{kind}"])


def stock_line(t: dict, kind: str) -> str:
    """What is left of a kind, always: the Bags tab's line, with a word while
    it is running low, or why there is no figure yet."""
    q = f"sensor.{E}_{kind}_stock"
    not_yet = t["stock_not_yet"].replace("{kind}", t[f"kind_{kind}"])
    return (ESCAPE
            # Too few brews for days or cups: said in words, never "unknown".
            + f"{{% if states('{q}') in ['unknown', 'unavailable'] and state_attr('{q}', 'at_least') is none %}}" + not_yet
            + "{% else %}" + stock_vars(kind)
            # Nothing left is said as such, never "about 0 days".
            + "{% if n == 0 and least is none %}" + stock_out(t, kind)
            + "{% else %}" + t["stock_left"].replace("{Kind}", t[f"Kind_{kind}"]).replace("{n}", stock_amount(t, kind))
            + "{% endif %}{% endif %}"
            + f"{{% if (state_attr('{q}', 'unknown') or 0) > 0 %}} " + t["stock_weigh"] + "{% endif %}"
            + f"{{% if is_state('binary_sensor.{E}_{kind}_stock_low', 'on') %}} " + t["stock_low"]
            + "{% endif %}")


def stock_low_line(t: dict, kind: str) -> str:
    """The Brew tab's line, shown only while the kind is running low."""
    return (stock_vars(kind) + "{% if n == 0 and least is none %}" + stock_out(t, kind) + "{% else %}"
            + t["stock_low_left"].replace("{kind}", t[f"kind_{kind}"]).replace("{Kind}", t[f"Kind_{kind}"])
            .replace("{n}", stock_amount(t, kind)) + "{% endif %}")


def stock_card(t: dict, kind: str, **extra) -> dict:
    return {"type": "markdown", "text_only": True, "content": stock_line(t, kind), **extra}


def stock_low_card(t: dict, kind: str, **extra) -> dict:
    return {"type": "markdown", "text_only": True, "content": stock_low_line(t, kind), **extra}


def bags_view(t: dict) -> dict:
    """What is on hand: the open bags, how much is left and how long each has
    been open, then the unopened ones, each with its size. Each bag opens to
    where and how its coffee was made, as far as the bag says.

    Choosing the bag to brew with is the Brew tab's; this tab only lists.
    """
    bags = f"sensor.{E}_coffee_bags"
    bag = f"select.{E}_coffee_bag"
    left = t["g_of"].replace("{left}", "' ~ (b.get('remaining_g') | round(0) | int) ~ '").replace("{size}", "' ~ (b.get('bag_size_g') | round(0) | int) ~ '")
    pods = t["pods_left"].replace("{n}", "' ~ b.get('pods_left') ~ '")
    size = t["g_size"].replace("{n}", "' ~ (b.get('bag_size_g') | round(0) | int) ~ '")
    in_use = f"{{{{ ' ({t['in_use']})' if b.id in current }}}}"
    name = (
        ISO + "{{ b.name }}" + PDI
        + f"{{% if b.get('kind') == 'xpod' %}} ({t['k_xpod']}){{% elif b.get('kind') == 'tea' %}} ({t['k_tea']}){{% endif %}}"
        + in_use
        # Where it is from; "Other" says nothing about the process.
        + "{% for x in [b.get('country'), b.get('process')] if x and x != 'Other' %} · {{ x }}{% endfor %}"
    )
    amount = (
        " · {% if b.get('kind') == 'xpod' %}{{ ('" + pods + "') if b.get('pods_left') is not none else '" + t["not_tracked"] + "' }}"
        "{% elif b.get('remaining_g') is none %}" + t["not_tracked"]
        + "{% elif b.get('bag_size_g') %}{{ '" + left + "' }}"
        + "{% else %}{{ b.get('remaining_g') | round(0) | int }} " + t["g_left"] + "{% endif %}"
    )
    open_text = (
        name + amount
        + "{% if b.get('opened_on') %}{% set days = (now().date() - as_datetime(b.get('opened_on')).date()).days %} · "
        + opened_ago(t) + "{% endif %}"
        + f"{{% if b.id in (state_attr('{bags}', 'fading') or []) %}} · {t['past_best']}{{% endif %}}"
    )
    # An unopened bag holds what it was sold as, unless it was weighed.
    unopened_text = (
        name + " · {% if b.get('kind') == 'xpod' and b.get('pods_left') is not none %}{{ '" + pods + "' }}"
        "{% elif b.get('remaining_g') is not none %}{{ b.get('remaining_g') | round(0) | int }} " + t["g_left"]
        + "{% elif b.get('bag_size_g') %}{{ '" + size + "' }}"
        + "{% else %}" + t["not_tracked"] + "{% endif %}"
    )
    altitude = (
        "{% set lo = b.get('altitude_m') %}{% set hi = b.get('altitude_max_m') %}"
        "{% if lo %}- **" + t["d_altitude"] + ":** "
        + t["d_m"].replace("{n}", "{{ lo | round(0) | int }}{% if hi and hi != lo %}–{{ hi | round(0) | int }}{% endif %}")
        + "\n{% endif %}"
    )
    details = "".join(
        f"{{% if b.get('{key}') %}}- **{t['d_' + key]}:** {{{{ e(b.get('{key}')) }}}}\n{{% endif %}}"
        for key in ("roaster", "region", "producer", "varietal", "roast", "roast_date")
    ) + altitude + f"{{% if b.get('roaster_notes') %}}- **{t['d_notes']}:** {{{{ e(b.get('roaster_notes')) }}}}\n{{% endif %}}" + (
        # Only a web link, and one with nothing that would end the markdown
        # link early.
        "{% set url = b.get('product_url') or '' %}"
        "{% if url is match('https?://[^\\\\s()<>]+$') %}"
        f"- [{t['d_link']}]({{{{ url }}}})\n{{% endif %}}"
    )

    def entry(text: str) -> str:
        """A bag's line that opens to its details; a plain line when it has none.

        Inside the summary's HTML markdown is not read, so the line is
        escaped as HTML there and as markdown in the plain line.
        """
        return (
            "{% set line %}" + text + "{% endset %}{% set more %}" + details + "{% endset %}"
            # The blank line after </details> ends the HTML block, so a plain
            # line after it is read as markdown again.
            "{% if more | trim %}<details><summary>{{ line | escape }}</summary>\n\n{{ more }}\n</details>\n\n"
            "{% else %}- {{ e(line) }}\n{% endif %}"
        )
    open_line, unopened_line = entry(open_text), entry(unopened_text)
    setup = (
        f"{{% set current = [state_attr('{bag}','id'), state_attr('select.{E}_xpod_box','id'), state_attr('select.{E}_tea','id')] %}}"
        f"{{% set all = state_attr('{bags}','bags') or [] %}}"
    )
    open_card = (
        ESCAPE + setup
        + "{% set opened = all | rejectattr('status', 'eq', 'unopened') | list %}"
        # The bag in use first, then the rest from least left; untracked last.
        "{% set in_use = opened | selectattr('id', 'in', current) | list %}"
        "{% set rest = opened | rejectattr('id', 'in', current) | list %}"
        "{% set counted = rest | selectattr('remaining_g', 'defined') | rejectattr('remaining_g', 'none') | sort(attribute='remaining_g') | list %}"
        "{% set ordered = in_use + counted + (rest | reject('in', counted) | list) %}"
        # The heading is part of the card, so neither shows with nothing open.
        f"{{% if ordered %}}## {t['h_open_bags']}\n\n{{% for b in ordered %}}" + open_line + "{% endfor %}{% endif %}"
    )
    unopened_card = (
        ESCAPE + setup
        # Oldest roast first: the one to open next.
        + "{% set sealed = all | selectattr('status', 'eq', 'unopened') | list %}"
        "{% set dated = sealed | selectattr('roast_date', 'defined') | selectattr('roast_date') | sort(attribute='roast_date') | list %}"
        "{% set ordered = dated + (sealed | reject('in', dated) | list) %}"
        # The one to open now, only when it is time.
        + f"{{% set nxt = all | selectattr('id', 'eq', state_attr('{bags}', 'open_next')) | list %}}"
        f"{{% if ordered %}}## {t['h_unopened_bags']}\n\n"
        + "{% if nxt %}" + t["open_next"].replace("{bag}", "**" + ISO + "{{ e(nxt[0].name) }}" + PDI + "**") + "\n\n{% endif %}"
        "{% for b in ordered %}" + unopened_line + "{% endfor %}{% endif %}"
    )
    bag_list = lambda content: {"type": "markdown", "text_only": True, "show_empty": False, "content": content}  # noqa: E731
    return {"title": t["view_bags"], "path": "bags", "icon": "mdi:shopping", "type": "sections", "max_columns": 2, "sections": [
        {"type": "grid", "cards": [
            bag_list(open_card),
            bag_list(unopened_card),
            {"type": "markdown", "text_only": True,
             "content": f"{{% if not (state_attr('{bags}','bags') or []) %}}{t['no_bags']}{{% endif %}}",
             "show_empty": False},
            press(f"button.{E}_refresh_coffee_bags", visibility=[
                {"condition": "state", "entity": f"button.{E}_refresh_coffee_bags", "state_not": "unavailable"},
            ]),
            {"type": "markdown", "text_only": True, "content": f"[{t['add_bags']}]({INTEGRATION})"},
        ], "visibility": present(bags)[:1]},
        # Any open bag finishing allows: a spill, a bag given away, a leftover.
        section(t["h_finish_a_bag"], [
            select(f"select.{E}_bag_to_finish"),
            {"type": "markdown", "text_only": True, "show_empty": False, "content": (
                ESCAPE + f"{{% set p = 'select.{E}_bag_to_finish' %}}{{% set chosen = states(p) %}}"
                "{% if chosen not in ('unknown', 'unavailable', '') %}"
                "{% set bag = '" + ISO + "' ~ e(chosen) ~ '" + PDI + "' %}"
                "{% set g = state_attr(p, 'remaining_g') %}"
                "{% if g is not none %}"
                + t["f_chosen"].replace("{bag}", "{{ bag }}").replace("{grams}", "{{ g | float | round(1) | string | replace('.0', '') }}")
                + "{% else %}" + t["f_chosen_unknown"].replace("{bag}", "{{ bag }}") + "{% endif %}{% endif %}"
            )},
            press(f"button.{E}_finish_chosen_bag", t["f_confirm"], visibility=available(f"button.{E}_finish_chosen_bag")),
        ], available(f"select.{E}_bag_to_finish")),
        section(t["h_opening"], [
            tile(f"number.{E}_{n}", features=[{"type": "numeric-input", "style": "buttons"}])
            for n in ("open_bags_at_once", "rest_after_roasting", "open_bag_fades_after")
        ], available(f"number.{E}_open_bags_at_once")),
        # Per kind the home has had: what is left, what it is counted in,
        # and the level below which it is running low.
        *(section(t["h_stock"] + f" · {t[f'kind_{kind}']}", [
            stock_card(t, kind),
            select(f"select.{E}_{kind}_stock_measure"),
            tile(f"number.{E}_{kind}_stock_level",
                 features=[{"type": "numeric-input", "style": "buttons"}]),
        ], available(f"sensor.{E}_{kind}_stock")) for kind in ("coffee", "tea", "xpod")),
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
    manage = f"select.{E}_recipe_to_manage"
    updates = [f"update.{E}_update", f"update.{E}_firmware"]
    signed_in = is_not(f"button.{E}_refresh_recipes", "unavailable")
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
        # Its own picker: choosing a recipe here never prepares it on the
        # machine. Each action shows once a recipe is picked, and none while
        # the machine grinds or brews.
        section(t["h_library"], [
            select(manage),
            press(f"button.{E}_archive_recipe", t["confirm_archive"], visibility=present(manage)),
            press(f"button.{E}_archive_and_remove_from_xbloom_cloud", t["confirm_archive_remove"],
                  visibility=[*present(manage), signed_in]),
            press(f"button.{E}_delete_selected_recipe", t["confirm_delete"], visibility=present(manage)),
            press(f"button.{E}_refresh_recipes", visibility=[signed_in]),
            {"type": "markdown", "text_only": True, "content": f"[{t['add_recipes']}]({INTEGRATION})"},
            # The archive is a page of its own, reached from here, so what is
            # archived stays out of the library; the link shows only while
            # there is something in it.
            {"type": "markdown", "text_only": True, "content": f"[{t['h_archive']}](archive)",
             "visibility": present(f"select.{E}_archived_recipe")},
        ], not_busy()),
        # Settings the machine holds: changed only while connected.
        section(t["h_settings"], [
            select(f"select.{E}_mode"),
            select(f"select.{E}_temperature_unit"),
            select(f"select.{E}_weight_unit"),
        ], [live]),
        # Kept in Home Assistant, not the machine: shown whether connected or not.
        section(t["h_stories"], [
            select(f"select.{E}_brew_stories"),
            select(f"select.{E}_story_language", visibility=[is_not(f"select.{E}_brew_stories", "off")]),
            # Read by the story announcement blueprint.
            select(f"select.{E}_spoken_story_parts", visibility=[
                is_not(f"select.{E}_brew_stories", "off"), *present(f"select.{E}_spoken_story_parts")]),
        ], present(f"select.{E}_brew_stories")),
        section(t["h_voice"], [
            toggle(entity, name=name, visibility=[
                {"condition": "state", "entity": entity, "state_not": "unavailable"}]) for entity, name in voice
        ], [{"condition": "or", "conditions": [
            {"condition": "state", "entity": entity, "state_not": "unavailable"} for entity, _ in voice]}]),
        # Only while there is an update to act on: "Up-to-date" with two
        # disabled buttons is nothing to do.
        section(t["h_updates"], [
            tile(update, features=[{"type": "update-actions"}], visibility=[is_(update, "on")])
            for update in updates
        ], [{"condition": "or", "conditions": [is_(update, "on") for update in updates]}]),
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
        + dose_line(t)
    )


def picked_details(t: dict, picker: str) -> dict:
    return folded(t, f"state_attr('{picker}', 'picked') or {{}}",
                  "{% if a.get('description') %}{{ e(a.get('description')) }}\n\n{% endif %}" + pour_table(t))


def recipe_lines(t: dict) -> str:
    """A recipe's dose, ratio, grind and pours, read from `a`."""
    return dose_line(t) + pour_table(t)


def dose_line(t: dict) -> str:
    """A recipe's dose, ratio and grind, read from `a`."""
    return (
        # Tea is weighed as tea and not ground.
        "{% set tea = (a.get('cup') or '') | lower == 'tea' %}"
        + f"{{% if a.get('dose_g') %}}**{{% if tea %}}{t['a_tea']}{{% else %}}{t['coffee']}{{% endif %}}:** {_num("a.get('dose_g')")} {t['g']}"
        + f"{{% if a.get('ratio') %}} · **{t['ratio']}:** 1:{_num("a.get('ratio')")}{{% endif %}}"
        + f"{{% if a.get('grind_size') and not tea %}} · {t['c_grind']} {{{{ a.get('grind_size') | round(0) | int }}}} {t['c_at']} {{{{ a.get('rpm') }}}} {t['c_rpm']}{{% endif %}}\n\n{{% endif %}}"
    )


def pour_table(t: dict) -> str:
    """A recipe's pours as a table, read from `a`."""
    return (
        f"{{% set pours = a.get('pours') or [] %}}{{% if pours %}}"
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
        + "{% set tea = (a.get('cup') or '') | lower == 'tea' %}"
        # The app fills an empty field with the word NONE; it is left out.
        + "{% set c = a.get('coffee') or {} %}{% if c.get('name') %}"
        + f"**{{% if tea %}}{t['a_tea']}{{% else %}}{t['a_pod']}{{% endif %}}:** {{{{ e(c.get('name')) }}}}"
        + "{% for x in [c.get('origin'), c.get('process'), c.get('varietal')] if x and (x | upper) != 'NONE' %} · {{ e(x) }}{% endfor %}\n\n"
        + "{% set notes = c.get('flavor') or '' %}{% if notes and (notes | upper) != 'NONE' %}"
        + f"**{t['c_notes']}:** {{{{ e(notes | regex_replace('\\s*·\\s*', '{t['sep']}')) }}}}\n\n{{% endif %}}{{% endif %}}"
        + dose_line(t)
    )


def folded(t: dict, attrs: str, body: str) -> dict:
    """A recipe's pours, and a hub recipe's description, folded until opened.

    A disclosure: announced as collapsed or expanded, opened in place, so the
    recipe's name and its Add button stay a short swipe apart.
    """
    return {"type": "markdown", "content": (
        ESCAPE + "{% set a = " + attrs + " %}"
        + "{% if a.get('pours') or a.get('description') %}"
        # Named after what it holds: a hub recipe can carry a description.
        + "<details><summary>{% if a.get('description') %}" + t["c_desc_pours"]
        + "{% else %}" + t["c_pours"] + "{% endif %}</summary>\n\n" + body + "\n\n</details>{% endif %}"
    )}


def account_details(t: dict, entity: str) -> dict:
    return folded(t, f"states['{entity}'].attributes if states['{entity}'] is defined else {{}}", pour_table(t))


def _num(expr: str) -> str:
    return "{{ (" + expr + " | float) | round(1) | string | replace('.0', '') }}"


def version_words(t: dict, var: str) -> str:
    """One version in a few words: "grind 52, 1:15", only what it has.

    A version is its grind and ratio; the dose is how much was made.
    """
    parts = []
    for key, text in (("grind", "k_grind"), ("ratio", "k_ratio")):
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
    num = "{{ (v | float) | round(1) | string | replace('.0', '') }}"
    # The settings in the dashboard's language when they were read from the
    # note; the note as written otherwise.
    said = (
        f"{{% set s = state_attr('{n}', 'settings') or {{}} %}}"
        "{% if s %}{% for k, v in s.items() %}"
        "{% if k == 'grind' %}" + t["n_grind"] + "{% elif k == 'ratio' %}" + t["n_ratio"]
        + "{% else %}" + t["n_dose"] + "{% endif %}"
        "{% if not loop.last %}" + t["sep"] + "{% endif %}{% endfor %}"
        f"{{% else %}}{{{{ e(states('{n}')) }}}}{{% endif %}}"
    ).replace("{value}", num)
    return ESCAPE + t["v_wanted"].replace("{text}", f"**{said}**")


def rating_card(t: dict) -> str:
    """The question: which recipe with which bag, what was changed, and what
    was to be noticed in it, as said when it was ready."""
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
    ).replace("{changes}", changes) + (
        f"{{% set f = state_attr('{q}', 'focus') %}}{{% if f %}}\n\n{{{{ e(f) }}}}{{% endif %}}"
    )


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
        + "{% endif %}"
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
    browse = f"select.{E}_browse"
    signed_in = is_not(f"button.{E}_refresh_recipes", "unavailable")
    showing = lambda name: is_(browse, name)  # noqa: E731
    return {"title": t["view_community"], "path": "community", "icon": "mdi:account-group",
            "type": "sections", "max_columns": 2, "sections": [
        # One list at a time, chosen here; the menu names it, so no heading
        # repeats it. Signed out only the search is offered, and the menu,
        # with nothing to choose, is hidden.
        {"type": "grid", "cards": [select(browse)], "visibility": [signed_in]},
        # In each list: what the recipe is, then Add, then its pours folded,
        # so Add is a swipe or two away, not past a table.
        {"type": "grid", "cards": [
            {"type": "markdown", "content": account_card(t, for_you, with_name=True)},
            press(f"button.{E}_add_for_you_recipe", t["c_confirm_add"], name=t["c_add"]),
            press(f"button.{E}_another_for_you", name=t["a_another"]),
            account_details(t, for_you),
        ], "visibility": [showing("for_you"), *present(for_you)]},
        {"type": "grid", "cards": [
            select(trending, name=t["c_recipe"], visibility=present(trending)),
            press(f"button.{E}_add_trending_recipe", t["c_confirm_add"], name=t["c_add"],
                  visibility=present(trending)),
            {"type": "markdown", "content": account_card(t, trending), "visibility": present(trending)},
            {**account_details(t, trending), "visibility": present(trending)},
            # Kept outside the list's own condition: with every trending
            # recipe an xPod and this off, the list is empty and this must
            # still be reachable.
            toggle(f"switch.{E}_show_xpod_recipes"),
        ], "visibility": [showing("trending")]},
        {"type": "grid", "cards": [
            select(tea, name=t["c_recipe"]),
            press(f"button.{E}_add_tea_recipe", t["c_confirm_add"], name=t["c_add"]),
            {"type": "markdown", "content": account_card(t, tea)},
            account_details(t, tea),
        ], "visibility": [showing("tea"), *present(tea)]},
        {"type": "grid", "cards": [
            # First: one press, a recipe to try with the bag in use, for the
            # drink chosen — here too, since without Coffee Lab the Brew
            # tab's bag section, where Drink also is, is not shown.
            select(f"select.{E}_drink"),
            press(f"button.{E}_suggest_community_recipe", name=t["c_suggest_hub"]),
            tile(f"text.{E}_community_search", name=t["c_words"]),
            select(f"select.{E}_community_origin", name=t["c_origin"]),
            select(f"select.{E}_community_sort", name=t["c_sort"]),
            press(f"button.{E}_search_community", name=t["c_search"]),
            {"type": "markdown", "text_only": True, "content": matches_sentence(t, sensor, picker),
             "visibility": present(sensor)},
        ], "visibility": [showing("search")]},
        section(t["h_results"], [
            select(picker, name=t["c_recipe"]),
            press(f"button.{E}_add_community_recipe", t["c_confirm_add"], name=t["c_add"],
                  visibility=present(picker)),
            {"type": "markdown", "content": picked_card(t, picker), "visibility": present(picker)},
            {**picked_details(t, picker), "visibility": present(picker)},
        ], [showing("search"), {"condition": "numeric_state", "entity": sensor, "above": 0}]),
    ]}


def dashboard(lang: str) -> dict:
    t = TEXT[lang]
    return {"views": [brew_view(t), stats_view(t), bags_view(t), community_view(t), xbloom_view(t), archive_view(t)]}


def spoken_separators(node, sep: str):
    """Every " · " between words becomes the language's comma.

    Spoken, a comma keeps a pause between the words; a middle dot is spoken
    as "dot", or not at all and the words run together.
    """
    if isinstance(node, str):
        return node.replace(" · ", sep)
    if isinstance(node, list):
        return [spoken_separators(x, sep) for x in node]
    if isinstance(node, dict):
        return {k: spoken_separators(v, sep) for k, v in node.items()}
    return node


def main() -> None:
    assert TEXT["en"].keys() == TEXT["ar"].keys(), "every language carries every string"
    for lang in TEXT:
        name = "dashboard-xbloom-studio.yaml" if lang == "en" else f"dashboard-xbloom-studio.{lang}.yaml"
        body = yaml.safe_dump(spoken_separators(dashboard(lang), TEXT[lang]["sep"]),
                              allow_unicode=True, sort_keys=False, width=100)
        (HERE / name).write_text(
            "# Built by dashboard/build.py — edit that, not this file.\n" + body, encoding="utf-8"
        )


if __name__ == "__main__":
    main()

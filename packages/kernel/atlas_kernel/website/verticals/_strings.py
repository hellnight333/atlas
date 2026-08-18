"""Interface copy in English and Arabic.

Arabic is the largest confirmed gap across the twenty audited clinics — eleven
of them have no Arabic at all — and in Dubai a large share of patients read it
first. That makes it the clearest thing a demo can win on.

**Only the interface is translated, never the clinic's own name.** A practice
called "Dr. Joy Dental Clinic" is called that in both languages; transliterating
it would put a name on their page that they do not use and did not choose.

Service names are Modern Standard Arabic and deliberately plain — the words a
patient would search for, not a marketing register. Anything that would be a
claim rather than a label is absent from both languages, so the two versions
assert exactly the same things.
"""

from __future__ import annotations

from typing import NamedTuple


class Strings(NamedTuple):
    """Every piece of interface text on the page."""

    lang: str
    direction: str
    services_heading: str
    services_sub: str
    why_heading: str
    why_sub: str
    visit_heading: str
    visit_sub: str
    book_heading: str
    book_sub_with_phone: str
    book_sub_without_phone: str
    call: str
    whatsapp: str
    directions: str
    address: str
    phone_label: str
    area: str
    hours_heading: str
    nav_services: str
    nav_visit: str
    nav_contact: str
    clinic_label: str
    other_language: str
    headline_template: str
    headline_plain: str
    lead_template: str
    lead_plain: str
    description_template: str
    contact_tbc: str


EN = Strings(
    lang="en",
    direction="ltr",
    services_heading="Our services",
    services_sub="Comprehensive dental care for adults and children.",
    why_heading="Why patients choose us",
    why_sub="Careful, unhurried treatment with the details explained.",
    visit_heading="Visit us",
    visit_sub="Find us, call us, or message us.",
    book_heading="Book an appointment",
    book_sub_with_phone="Call us and we will find a time that suits you.",
    book_sub_without_phone="Get in touch and we will find a time that suits you.",
    call="Call",
    whatsapp="WhatsApp",
    directions="Directions",
    address="Address",
    phone_label="Phone",
    area="Area",
    hours_heading="Opening hours",
    nav_services="Services",
    nav_visit="Visit us",
    nav_contact="Contact",
    clinic_label="Dental clinic",
    other_language="العربية",
    headline_template="Gentle, modern dentistry in {area}",
    headline_plain="Gentle, modern dentistry",
    lead_template=(
        "{name} provides routine and specialist dental care in {area}. "
        "Same-day appointments available for urgent problems."
    ),
    lead_plain=(
        "{name} provides routine and specialist dental care. "
        "Same-day appointments available for urgent problems."
    ),
    description_template=(
        "{name} — dental clinic{area_clause}. Check-ups, cleaning, whitening, "
        "braces, implants and emergency care."
    ),
    contact_tbc="Details to be confirmed",
)

AR = Strings(
    lang="ar",
    direction="rtl",
    services_heading="خدماتنا",
    services_sub="رعاية أسنان شاملة للكبار والأطفال.",
    why_heading="لماذا يختارنا المرضى",
    why_sub="علاج دقيق ومتأنٍ مع شرح كل التفاصيل.",
    visit_heading="زورونا",
    visit_sub="تجدوننا هنا، أو اتصلوا بنا، أو راسلونا.",
    book_heading="احجز موعداً",
    book_sub_with_phone="اتصل بنا وسنجد لك الوقت المناسب.",
    book_sub_without_phone="تواصل معنا وسنجد لك الوقت المناسب.",
    call="اتصل",
    whatsapp="واتساب",
    directions="الاتجاهات",
    address="العنوان",
    phone_label="الهاتف",
    area="المنطقة",
    hours_heading="ساعات العمل",
    nav_services="الخدمات",
    nav_visit="زورونا",
    nav_contact="اتصل بنا",
    clinic_label="عيادة أسنان",
    other_language="English",
    headline_template="طب أسنان حديث ولطيف في {area}",
    headline_plain="طب أسنان حديث ولطيف",
    lead_template=(
        "تقدم {name} رعاية الأسنان العامة والتخصصية في {area}. "
        "تتوفر مواعيد في نفس اليوم للحالات العاجلة."
    ),
    lead_plain=(
        "تقدم {name} رعاية الأسنان العامة والتخصصية. تتوفر مواعيد في نفس اليوم للحالات العاجلة."
    ),
    description_template=(
        "{name} — عيادة أسنان{area_clause}. فحص وتنظيف وتبييض وتقويم وزراعة الأسنان ورعاية الطوارئ."
    ),
    contact_tbc="سيتم تأكيد التفاصيل",
)

#: Service labels per language. Same six services, same order, so the two pages
#: are the same page — a patient switching language must not find different
#: treatments offered.
SERVICES_EN: tuple[tuple[str, str, str], ...] = (
    (
        "Check-ups & Cleaning",
        "tooth",
        "Routine examinations and professional hygiene appointments.",
    ),
    ("Fillings & Restorations", "shield", "Tooth-coloured fillings and repair of damaged teeth."),
    ("Teeth Whitening", "sparkle", "In-clinic and take-home whitening options."),
    ("Braces & Aligners", "align", "Orthodontic assessment and treatment planning."),
    ("Implants & Crowns", "crown", "Replacement and restoration of missing teeth."),
    ("Emergency Dental Care", "clock", "Same-day appointments for pain and urgent problems."),
)

SERVICES_AR: tuple[tuple[str, str, str], ...] = (
    ("الفحص والتنظيف", "tooth", "فحوصات دورية وجلسات تنظيف وتلميع الأسنان."),
    ("الحشوات والترميم", "shield", "حشوات بلون الأسنان وإصلاح الأسنان المتضررة."),
    ("تبييض الأسنان", "sparkle", "تبييض داخل العيادة وخيارات للاستخدام المنزلي."),
    ("التقويم والمصففات", "align", "تقييم تقويم الأسنان ووضع خطة العلاج."),
    ("الزراعة والتيجان", "crown", "تعويض وترميم الأسنان المفقودة."),
    ("طوارئ الأسنان", "clock", "مواعيد في نفس اليوم للألم والحالات العاجلة."),
)

ASSURANCES_EN: tuple[tuple[str, str], ...] = (
    ("Modern equipment", "Digital imaging and up-to-date clinical technique."),
    ("Comfortable care", "Gentle treatment, with anxious patients in mind."),
    ("Clear pricing", "Costs explained before treatment begins."),
    ("Family friendly", "Appointments for adults and children alike."),
)

ASSURANCES_AR: tuple[tuple[str, str], ...] = (
    ("أجهزة حديثة", "تصوير رقمي وتقنيات علاجية محدّثة."),
    ("راحة أثناء العلاج", "علاج لطيف يراعي المرضى القلقين."),
    ("أسعار واضحة", "توضيح التكلفة قبل بدء العلاج."),
    ("مناسب للعائلة", "مواعيد للكبار والأطفال على حد سواء."),
)

#: Day names for a translated opening-hours table. Applied only to hours that
#: came from the clinic's own listing — a translated guess is still a guess.
DAYS_AR: dict[str, str] = {
    "monday": "الاثنين",
    "tuesday": "الثلاثاء",
    "wednesday": "الأربعاء",
    "thursday": "الخميس",
    "friday": "الجمعة",
    "saturday": "السبت",
    "sunday": "الأحد",
    "closed": "مغلق",
    "open 24 hours": "مفتوح ٢٤ ساعة",
}

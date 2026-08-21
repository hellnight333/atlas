"""Every string on the concept, in both languages.

The Arabic is authored rather than translated. Where their English marketing
runs long, the Arabic says the same thing the way it would be said in Arabic —
Ramadan and iftar catering is sold in this market in Arabic, and a mechanical
translation of "culinary mastery" reads as exactly what it is.

Nothing here states a fact that `source.py` does not carry. Section headings and
connective prose are ours; claims are theirs.
"""

from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "en": {
        "dir": "ltr", "lang": "en", "other": "ar", "other_name": "العربية",
        "brand": "AHS", "tagline": "Beyond Catering",
        "nav_work": "The work", "nav_services": "What we cater", "nav_eatlux": "EATLUX",
        "nav_journal": "Journal", "nav_about": "About", "nav_contact": "Enquire",
        "call": "Call us", "whatsapp": "WhatsApp", "email": "Email",

        "home_eyebrow": "Dubai · Event catering",
        "home_title": "Your dream event,",
        "home_title_em": "our signature cuisine.",
        "home_cta": "Plan your event", "home_cta2": "See the work",

        "proof_eyebrow": "The work",
        "proof_title": "Thirty-two events, on the record.",
        "proof_lead": "Filter to the kind of event you are planning. Every entry below is one "
                      "AHS publishes; where a detail is not published, it says so rather than "
                      "guessing.",
        "proof_all": "All", "proof_sector": "Sector", "proof_kind": "Event",
        "proof_count": "events", "proof_photos": "photographs",
        "proof_empty": "Nothing published in that combination.",
        "proof_open": "Open the record",

        "case_published": "What AHS publishes", "case_unpublished": "Not published",
        "case_client": "Client", "case_kind": "Event", "case_venue": "Venue",
        "case_sector": "Sector", "case_photos": "Photographs",
        "case_back": "All work", "case_related": "Comparable work",
        "case_note": "About their page",

        "svc_eyebrow": "What we cater", "svc_title": "Six ways an event is fed.",
        "svc_lead": "Each of these is a service AHS already publishes in full. The headings "
                    "under them are theirs.",
        "svc_includes": "They publish", "svc_source": "On their site",
        "svc_words": "words", "svc_photos": "photographs",

        "journal_eyebrow": "Journal", "journal_title": "What they have written.",
        "journal_lead": "AHS published four pieces on one day in November 2025, none of them "
                        "carrying a picture. The subjects were theirs and they were the right "
                        "ones. This is the same four, presented as a reader would want them.",
        "journal_read": "Read", "journal_source": "Published by AHS",
        "journal_facts": "From their piece", "journal_back": "All writing",

        "about_eyebrow": "About", "about_title": "Twenty years, then a belt that moves.",
        "about_founder": "The founder", "about_clients": "Who they have fed",
        "about_clients_note": "AHS's own client list, as published on their About page and in "
                              "their Formula 1 announcement.",
        "about_team": "The team",

        "brief_eyebrow": "Your brief", "brief_title": "Your brief, already written.",
        "brief_lead": "Everything you chose while reading is below. Add how to reach you and "
                      "AHS will come back with a bespoke offer — they price every event "
                      "individually, so nothing here quotes a figure.",
        "brief_q": "What are you planning?",
        "brief_sub": "Set these as you read. The page answers, and your enquiry writes itself.",
        "brief_send": "Get a custom offer", "brief_wa": "WhatsApp AHS",
        "brief_or": "Or reach AHS directly — these are their own published details",
        "brief_unset": "not set yet — choose in the brief",
        "brief_start": "Tap to start", "brief_your": "Your event brief",
        "occasion": "Occasion", "guests": "Guests", "date": "Date", "style": "Style",
        "name": "Name", "org": "Company or occasion", "phone": "Phone",
        "notes": "Anything else about the event",

        "privacy_title": "Privacy", "privacy_eyebrow": "Concept",
        "footer_do": "What we do", "footer_reach": "Get in touch",
        "wa_aria": "Message AHS on WhatsApp",
        "sent": "Nothing was sent. This is a demonstration interaction on a concept page.",
        "disclaim": "This is a demonstration interaction. Nothing is sent, no enquiry is "
                    "created, and no event is booked or held. The call, WhatsApp and email "
                    "links go to AHS's own published contact details and are not routed "
                    "through Qevik.",
    },
    "ar": {
        "dir": "rtl", "lang": "ar", "other": "en", "other_name": "English",
        "brand": "AHS", "tagline": "ما وراء الضيافة",
        "nav_work": "أعمالنا", "nav_services": "خدماتنا", "nav_eatlux": "EATLUX",
        "nav_journal": "المدوّنة", "nav_about": "من نحن", "nav_contact": "اطلب عرضًا",
        "call": "اتصل بنا", "whatsapp": "واتساب", "email": "البريد",

        "home_eyebrow": "دبي · ضيافة المناسبات",
        "home_title": "مناسبتكم كما تتخيلونها،",
        "home_title_em": "ومطبخنا كما عهدتموه.",
        "home_cta": "خطّط لمناسبتك", "home_cta2": "شاهد أعمالنا",

        "proof_eyebrow": "أعمالنا",
        "proof_title": "٣٢ مناسبة موثّقة.",
        "proof_lead": "اختر نوع المناسبة التي تخطّط لها. كل ما يلي منشور على موقع AHS، وحين "
                      "لا تكون التفاصيل منشورة نذكر ذلك بدل تخمينها.",
        "proof_all": "الكل", "proof_sector": "القطاع", "proof_kind": "نوع المناسبة",
        "proof_count": "مناسبة", "proof_photos": "صورة",
        "proof_empty": "لا يوجد ما هو منشور بهذا التصنيف.",
        "proof_open": "افتح السجل",

        "case_published": "ما تنشره AHS", "case_unpublished": "غير منشور",
        "case_client": "العميل", "case_kind": "نوع المناسبة", "case_venue": "المكان",
        "case_sector": "القطاع", "case_photos": "الصور",
        "case_back": "كل الأعمال", "case_related": "أعمال مشابهة",
        "case_note": "ملاحظة على صفحتهم",

        "svc_eyebrow": "خدماتنا", "svc_title": "ست طرق لإطعام مناسبة.",
        "svc_lead": "كل خدمة أدناه منشورة بالكامل على موقع AHS، والعناوين الفرعية عناوينهم.",
        "svc_includes": "ينشرون", "svc_source": "على موقعهم",
        "svc_words": "كلمة", "svc_photos": "صورة",

        "journal_eyebrow": "المدوّنة", "journal_title": "ما كتبوه.",
        "journal_lead": "نشرت AHS أربع مقالات في يوم واحد من نوفمبر ٢٠٢٥، بلا صورة واحدة. "
                        "المواضيع مواضيعهم وكانت صائبة. هذه المقالات الأربع نفسها، معروضة "
                        "كما يريدها القارئ.",
        "journal_read": "اقرأ", "journal_source": "منشور على موقع AHS",
        "journal_facts": "من مقالهم", "journal_back": "كل المقالات",

        "about_eyebrow": "من نحن", "about_title": "عشرون عامًا، ثم حزام يتحرك.",
        "about_founder": "المؤسّس", "about_clients": "من قدّمنا لهم",
        "about_clients_note": "قائمة عملاء AHS كما نشروها في صفحة «من نحن» وفي إعلان فورمولا ١.",
        "about_team": "الفريق",

        "brief_eyebrow": "طلبك", "brief_title": "طلبك، مكتوب سلفًا.",
        "brief_lead": "كل ما اخترته أثناء التصفّح مُدرج أدناه. أضف وسيلة للتواصل معك وسيعود "
                      "إليك فريق AHS بعرض مخصّص — فهم يسعّرون كل مناسبة على حدة، ولذلك لا "
                      "يرد هنا أي رقم.",
        "brief_q": "ما الذي تخطّط له؟",
        "brief_sub": "اختر أثناء القراءة، وستُكتب رسالتك تلقائيًا.",
        "brief_send": "اطلب عرضًا مخصّصًا", "brief_wa": "راسلنا على واتساب",
        "brief_or": "أو تواصل مع AHS مباشرة — هذه بياناتهم المنشورة",
        "brief_unset": "لم يُحدَّد بعد — اختر من الطلب",
        "brief_start": "اضغط للبدء", "brief_your": "طلبك",
        "occasion": "المناسبة", "guests": "عدد الضيوف", "date": "التاريخ", "style": "الأسلوب",
        "name": "الاسم", "org": "الشركة أو المناسبة", "phone": "الهاتف",
        "notes": "تفاصيل أخرى عن المناسبة",

        "privacy_title": "الخصوصية", "privacy_eyebrow": "نموذج",
        "footer_do": "ما نقدّمه", "footer_reach": "تواصل معنا",
        "wa_aria": "راسل AHS على واتساب",
        "sent": "لم يُرسل شيء. هذا تفاعل توضيحي على صفحة نموذجية.",
        "disclaim": "هذا تفاعل توضيحي. لا يُرسل شيء، ولا يُنشأ طلب، ولا تُحجز أي مناسبة. "
                    "روابط الاتصال والواتساب والبريد تعود إلى بيانات AHS المنشورة ولا تمر "
                    "عبر Qevik.",
    },
}

#: The brief's options. Values are stable keys; labels are per language.
STEPS = (
    ("occasion", (("wedding", "Wedding", "زفاف"), ("gala", "Gala", "حفل تكريم"),
                  ("corporate", "Corporate", "مناسبة مؤسسية"), ("private", "Private", "مناسبة خاصة"),
                  ("ramadan", "Ramadan", "رمضان"), ("canape", "Canapé & dessert", "كانابيه وحلويات"))),
    ("guests", (("40", "Up to 50", "حتى ٥٠"), ("120", "50–150", "٥٠–١٥٠"),
                ("300", "150–400", "١٥٠–٤٠٠"), ("500", "400+", "أكثر من ٤٠٠"))),
    ("month", (("jan", "January", "يناير"), ("mar", "March", "مارس"), ("jun", "June", "يونيو"),
               ("sep", "September", "سبتمبر"), ("nov", "November", "نوفمبر"),
               ("open", "Not fixed", "غير محدد"))),
    ("style", (("seated", "Seated", "جلوس"), ("standing", "Standing", "وقوف"),
               ("live", "Live stations", "محطات حيّة"), ("canape", "Canapé", "كانابيه"))),
)

#: Service names in Arabic. Keyed on the slug in source.SERVICES.
SERVICE_AR = {
    "corporate": "ضيافة الشركات", "private": "الضيافة الخاصة",
    "live-stations": "المحطات الحيّة", "canape-dessert": "الكانابيه والحلويات",
    "wedding": "ضيافة الأعراس", "gala": "حفلات التكريم",
    "ramadan": "رمضان ٢٠٢٦", "eatlux": "EATLUX",
}

SECTOR_AR = {
    "fmcg": "سلع استهلاكية", "automotive": "سيارات", "luxury": "أزياء وسلع فاخرة",
    "media": "إعلام", "finance": "تمويل", "beauty": "تجميل", "tech": "تقنية",
    "energy": "طاقة", "logistics": "خدمات لوجستية", "professional": "خدمات مهنية",
    "real-estate": "عقارات", "corporate": "مؤسسي", "hospitality": "ضيافة",
    "seasonal": "موسمي", "private": "خاص",
}

ARTICLE_AR = {
    "formula-1-abu-dhabi": ("AHS في فورمولا ١ أبوظبي ٢٠٢٥",
                            "حين يلتقي الترف بالسرعة."),
    "show-belt-dining": ("EATLUX — حين يصبح الطعام عرضًا",
                         "أول تجربة «حزام العرض» في الإمارات."),
    "behind-the-scenes": ("خلف الكواليس — كيف تُصنع تجربة ضيافة فاخرة",
                          "كل قائمة تبدأ بسؤال واحد: بماذا تريد أن يشعر ضيوفك؟"),
    "sustainable-luxury": ("الاستدامة والفخامة — نعم، يجتمعان",
                           "مصادر محلية، ولا هدر، وأدوات تُعاد."),
}


#: Event types in Arabic. Their page *titles* stay as AHS published them —
#: "Nestle", "ROGER VIVIER DUBAI MALL" — because those are their words and a
#: translated title would misquote them. The event type is our classification,
#: so it is translated; leaving it English is how an "Arabic version" ends up
#: being an English page laid out backwards.
KIND_AR = {
    "Ramadan iftar": "إفطار رمضاني", "Board meeting": "اجتماع مجلس إدارة",
    "Academy": "أكاديمية", "Breakfast": "إفطار صباحي", "Office opening": "افتتاح مكتب",
    "Office brunch": "برانش مكتبي", "Auction event": "مزاد", "Iftar": "إفطار",
    "Company opening": "افتتاح شركة", "Showroom opening": "افتتاح صالة عرض",
    "Corporate lunch": "غداء مؤسسي", "Staff party": "حفل موظفين",
    "Theme dinner": "عشاء بطابع خاص", "Seated dinner": "عشاء جلوس",
    "Birthday": "عيد ميلاد", "Birthday, seated": "عيد ميلاد بجلوس",
    "Brunch": "برانش", "Seated lunch": "غداء جلوس", "Dinner": "عشاء",
}

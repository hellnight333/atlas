#!/usr/bin/env python3
"""Qevik's own sample sites, one per industry. Not clients, and labelled as such.

These exist because the public site cannot show the twenty clinic demos: those
were built unsolicited from public listings, none of those businesses are
customers, and presenting them as portfolio would be exactly the invented client
relationship the whole project refuses.

So these are ours. Every one carries Qevik's real phone number, which means the
call and WhatsApp buttons genuinely work, and every one is flagged on the page as
a sample rather than a real business. Nothing about them is a claim about
somebody else.

The Arabic is written, not generated at render time. Where a phrase has no
natural Arabic form it is rewritten rather than transliterated.

    samples.py            # report what would be built
    samples.py --deploy
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.website.verticals.business import (  # noqa: E402
    Business,
    Group,
    Item,
    Question,
    Text,
    render_site,
)

SITES_ROOT = Path(os.environ.get("QEVIK_SITES_ROOT", "/srv/sites"))
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "https://sites.qevik.ai")

#: Qevik's own number. Using it means every button on a sample works, and no
#: fictional number is published that might belong to a real person.
PHONE = "050 102 9104"
ADDRESS = "Office 301, Al Othman Building, Deiram, Dubai"


def restaurant() -> Business:
    return Business(
        name="Sample Grill House",
        schema_type="Restaurant",
        area="Business Bay, Dubai",
        phone=PHONE,
        address=ADDRESS,
        tagline=Text("Charcoal grill, Levantine plates", "مشاوي على الفحم وأطباق شامية"),
        intro=Text(
            "A neighbourhood grill in Business Bay. Everything is cooked to order "
            "over charcoal, and the mezze is made fresh each morning.",
            "مطعم مشاوي في الخليج التجاري. كل طبق يُحضّر عند الطلب على الفحم، "
            "والمقبلات تُعدّ طازجة كل صباح.",
        ),
        offering_heading=Text("Menu", "قائمة الطعام"),
        offering_note=Text(
            "A sample of the menu. Prices are illustrative.",
            "نموذج من القائمة. الأسعار توضيحية.",
        ),
        groups=(
            Group(
                Text("Mezze", "المقبلات"),
                (
                    Item(Text("Hummus", "حمص"),
                         Text("Chickpea, tahini, olive oil", "حمص وطحينة وزيت زيتون"), "AED 22"),
                    Item(Text("Moutabal", "متبل"),
                         Text("Smoked aubergine, yoghurt, garlic", "باذنجان مدخّن ولبن وثوم"), "AED 24"),
                    Item(Text("Fattoush", "فتوش"),
                         Text("Garden salad, sumac, toasted bread", "سلطة خضار مع السماق والخبز المحمّص"), "AED 26"),
                ),
            ),
            Group(
                Text("From the grill", "من على الفحم"),
                (
                    Item(Text("Mixed grill", "مشاوي مشكلة"),
                         Text("Lamb, chicken and kofta, served with rice", "لحم ودجاج وكفتة مع الأرز"), "AED 89"),
                    Item(Text("Shish taouk", "شيش طاووق"),
                         Text("Marinated chicken skewers, garlic sauce", "أسياخ دجاج متبّلة مع صلصة الثوم"), "AED 58"),
                    Item(Text("Lamb chops", "ريش غنم"),
                         Text("Four chops, grilled over charcoal", "أربع قطع مشوية على الفحم"), "AED 96"),
                ),
            ),
            Group(
                Text("Sweets", "الحلويات"),
                (
                    Item(Text("Kunafa", "كنافة"),
                         Text("Cheese kunafa, pistachio, syrup", "كنافة بالجبن والفستق والقطر"), "AED 32"),
                    Item(Text("Rice pudding", "رز بحليب"),
                         Text("Cardamom, rose water", "بالهيل وماء الورد"), "AED 24"),
                ),
            ),
        ),
        highlights=(
            Item(Text("Cooked to order", "يُحضّر عند الطلب"),
                 Text("Nothing sits under a lamp. Grilling starts when you order.",
                      "لا شيء ينتظر تحت المصابيح. الشوي يبدأ عند طلبك.")),
            Item(Text("Family tables", "طاولات عائلية"),
                 Text("Large tables for groups, and a quiet section at the back.",
                      "طاولات كبيرة للمجموعات وقسم هادئ في الخلف.")),
            Item(Text("Takeaway in 20 minutes", "طلبات خارجية خلال ٢٠ دقيقة"),
                 Text("Call ahead and collect. No delivery app markup.",
                      "اتصل مسبقاً واستلم طلبك. بدون رسوم تطبيقات التوصيل.")),
        ),
        request_heading=Text("Request a table", "اطلب حجز طاولة"),
        cta_label=Text("Send request", "إرسال الطلب"),
        request_note=Text(
            "This is a request form, not a confirmed reservation — and it is a "
            "demonstration that is not connected. A table is only held once the "
            "restaurant confirms by phone.",
            "هذا نموذج طلب وليس نظام حجز — وهو عرض توضيحي غير متصل. "
            "لا يتم تثبيت الطاولة إلا بعد تأكيد المطعم هاتفياً.",
        ),
        hours=(
            (Text("Monday – Thursday", "الاثنين – الخميس"), Text("12:00 PM – 12:00 AM", "12:00 PM – 12:00 AM")),
            (Text("Friday", "الجمعة"), Text("1:00 PM – 1:00 AM", "1:00 PM – 1:00 AM")),
            (Text("Saturday – Sunday", "السبت – الأحد"), Text("12:00 PM – 1:00 AM", "12:00 PM – 1:00 AM")),
        ),
    )


def cafe() -> Business:
    return Business(
        name="Sample Coffee Roasters",
        schema_type="CafeOrCoffeeShop",
        area="Al Quoz, Dubai",
        phone=PHONE,
        address=ADDRESS,
        tagline=Text("Roasted here, poured here", "نحمّص هنا ونقدّم هنا"),
        intro=Text(
            "A small roastery and café in Al Quoz. We roast twice a week and "
            "serve what came out of the drum that morning.",
            "محمصة ومقهى صغير في القوز. نحمّص مرتين أسبوعياً ونقدّم ما خرج من "
            "المحمصة في الصباح نفسه.",
        ),
        offering_heading=Text("What we pour", "ما نقدمه"),
        groups=(
            Group(
                Text("Espresso bar", "الإسبريسو"),
                (
                    Item(Text("Flat white", "فلات وايت"),
                         Text("Double shot, steamed milk", "جرعتان مع حليب مبخّر"), "AED 20"),
                    Item(Text("Cortado", "كورتادو"),
                         Text("Equal parts espresso and milk", "إسبريسو وحليب بنسب متساوية"), "AED 18"),
                    Item(Text("Spanish latte", "لاتيه إسباني"),
                         Text("Condensed milk, cinnamon", "حليب مكثّف مع القرفة"), "AED 24"),
                ),
            ),
            Group(
                Text("Filter and cold", "الفلتر والبارد"),
                (
                    Item(Text("V60 pour over", "في٦٠ تقطير"),
                         Text("Single origin, changes weekly", "أصل واحد، يتغيّر أسبوعياً"), "AED 26"),
                    Item(Text("Cold brew", "كولد برو"),
                         Text("Steeped 16 hours, served over ice", "منقوع ١٦ ساعة ويُقدّم مع الثلج"), "AED 25"),
                ),
            ),
            Group(
                Text("Beans to take home", "حبوب للمنزل"),
                (
                    Item(Text("Ethiopia — Guji", "إثيوبيا — قوجي"),
                         Text("250g whole bean, floral and bright", "٢٥٠ غم حبوب كاملة، نكهة زهرية"), "AED 68"),
                    Item(Text("Brazil — Cerrado", "البرازيل — سيرادو"),
                         Text("250g whole bean, chocolate and nuts", "٢٥٠ غم حبوب كاملة، شوكولاتة ومكسرات"), "AED 58"),
                ),
            ),
        ),
        highlights=(
            Item(Text("Roasted twice a week", "نحمّص مرتين أسبوعياً"),
                 Text("The roast date is on every bag. Nothing older than two weeks.",
                      "تاريخ التحميص على كل كيس. لا شيء أقدم من أسبوعين.")),
            Item(Text("Somewhere to work", "مكان للعمل"),
                 Text("Power at most tables and unmetered wifi.",
                      "كهرباء عند معظم الطاولات وإنترنت بلا حدود.")),
        ),
        request_heading=Text("Ask us anything", "اسألنا"),
        cta_label=Text("Send message", "إرسال الرسالة"),
        hours=(
            (Text("Every day", "كل يوم"), Text("7:00 AM – 10:00 PM", "7:00 AM – 10:00 PM")),
        ),
    )


def service_business() -> Business:
    return Business(
        name="Sample Auto Detailing",
        schema_type="AutoWash",
        area="Al Quoz Industrial, Dubai",
        phone=PHONE,
        address=ADDRESS,
        tagline=Text("Detailing that comes to you", "خدمة تلميع تأتي إليك"),
        intro=Text(
            "Mobile car detailing across Dubai. We arrive with our own water and "
            "power, work in your parking space, and are usually done in two hours.",
            "خدمة تلميع سيارات متنقلة في دبي. نصل بالماء والكهرباء الخاصة بنا، "
            "ونعمل في موقف سيارتك، وننتهي عادةً خلال ساعتين.",
        ),
        offering_heading=Text("Services", "خدماتنا"),
        offering_note=Text(
            "Prices vary by vehicle size. Ask for a quote.",
            "تختلف الأسعار حسب حجم السيارة. اطلب عرض سعر.",
        ),
        groups=(
            Group(
                Text("Exterior", "الخارج"),
                (
                    Item(Text("Wash and wax", "غسيل وتلميع"),
                         Text("Hand wash, clay bar, spray wax", "غسيل يدوي وتنظيف عميق وشمع")),
                    Item(Text("Paint correction", "تصحيح الطلاء"),
                         Text("Machine polish to remove swirl marks", "تلميع آلي لإزالة الخدوش السطحية")),
                    Item(Text("Ceramic coating", "طلاء سيراميك"),
                         Text("Applied after correction, cures overnight", "يُطبّق بعد التصحيح ويجف خلال ليلة")),
                ),
            ),
            Group(
                Text("Interior", "الداخل"),
                (
                    Item(Text("Deep clean", "تنظيف عميق"),
                         Text("Vacuum, steam, trim and glass", "شفط وبخار وتنظيف الزجاج والتفاصيل")),
                    Item(Text("Leather care", "العناية بالجلد"),
                         Text("Clean and condition seats and trim", "تنظيف وترطيب المقاعد والتفاصيل")),
                ),
            ),
        ),
        highlights=(
            Item(Text("We come to you", "نأتي إليك"),
                 Text("Home, office or building parking. No drop-off.",
                      "المنزل أو المكتب أو موقف المبنى. بدون توصيل السيارة.")),
            Item(Text("Own water and power", "ماء وكهرباء خاصة"),
                 Text("Nothing needed from your building.",
                      "لا نحتاج شيئاً من مبناك.")),
            Item(Text("Fixed quote first", "عرض سعر ثابت مسبقاً"),
                 Text("You get the price before we start, not after.",
                      "تعرف السعر قبل البدء وليس بعده.")),
        ),
        faq=(
            Question(
                Text("How long does it take?", "كم تستغرق الخدمة؟"),
                Text("A wash and interior clean is about two hours. Paint correction "
                     "and coating take most of a day.",
                     "الغسيل وتنظيف الداخل نحو ساعتين. تصحيح الطلاء والطلاء السيراميكي "
                     "يستغرقان معظم اليوم."),
            ),
            Question(
                Text("Which areas do you cover?", "ما المناطق التي تغطونها؟"),
                Text("Anywhere in Dubai. Sharjah by arrangement.",
                     "أي مكان في دبي. الشارقة بالاتفاق المسبق."),
            ),
            Question(
                Text("Do I need to be there?", "هل يجب أن أكون موجوداً؟"),
                Text("Only to hand over the keys. Many customers leave them at "
                     "reception and collect the car later.",
                     "فقط لتسليم المفاتيح. كثير من العملاء يتركونها في الاستقبال "
                     "ويستلمون السيارة لاحقاً."),
            ),
        ),
        request_heading=Text("Request a quote", "اطلب عرض سعر"),
        cta_label=Text("Send request", "إرسال الطلب"),
        hours=(
            (Text("Saturday – Thursday", "السبت – الخميس"), Text("8:00 AM – 8:00 PM", "8:00 AM – 8:00 PM")),
            (Text("Friday", "الجمعة"), Text("2:00 PM – 8:00 PM", "2:00 PM – 8:00 PM")),
        ),
    )


def professional() -> Business:
    return Business(
        name="Sample Property Consultants",
        schema_type="RealEstateAgent",
        area="Dubai Marina, Dubai",
        phone=PHONE,
        address=ADDRESS,
        tagline=Text("Buying, selling and leasing in Dubai", "بيع وشراء وتأجير في دبي"),
        intro=Text(
            "A small property consultancy working across Dubai Marina, JLT and "
            "Business Bay. We handle the paperwork, the viewings and the "
            "negotiation, and tell you when a deal is not worth doing.",
            "شركة استشارات عقارية صغيرة تعمل في مرسى دبي وأبراج بحيرات جميرا "
            "والخليج التجاري. نتولى المعاملات والمعاينات والتفاوض، ونخبرك متى "
            "لا تستحق الصفقة المتابعة.",
        ),
        offering_heading=Text("How we help", "كيف نساعدك"),
        groups=(
            Group(
                Text("For owners", "لأصحاب العقارات"),
                (
                    Item(Text("Selling", "البيع"),
                         Text("Valuation, listing, viewings, and the transfer at the DLD",
                              "التقييم والإدراج والمعاينات ونقل الملكية في دائرة الأراضي")),
                    Item(Text("Leasing", "التأجير"),
                         Text("Tenant screening, Ejari, and renewal handling",
                              "فحص المستأجرين وتسجيل إيجاري وإدارة التجديد")),
                ),
            ),
            Group(
                Text("For buyers and tenants", "للمشترين والمستأجرين"),
                (
                    Item(Text("Finding a property", "البحث عن عقار"),
                         Text("A shortlist based on your budget and how you actually live",
                              "قائمة مختصرة حسب ميزانيتك وأسلوب حياتك الفعلي")),
                    Item(Text("Negotiation", "التفاوض"),
                         Text("We negotiate on price, payment terms and handover date",
                              "نتفاوض على السعر وشروط الدفع وموعد التسليم")),
                ),
            ),
        ),
        highlights=(
            Item(Text("We will tell you not to buy", "قد ننصحك بعدم الشراء"),
                 Text("If the numbers do not work, that is the advice you get.",
                      "إذا لم تكن الأرقام مناسبة، فهذه هي النصيحة التي ستسمعها.")),
            Item(Text("One person handles your file", "شخص واحد يتابع ملفك"),
                 Text("You are not passed between agents.",
                      "لن يتم تحويلك بين عدة وكلاء.")),
        ),
        faq=(
            Question(
                Text("What are your fees?", "ما هي أتعابكم؟"),
                Text("Standard Dubai brokerage terms, agreed in writing before we "
                     "start. Nothing is deducted without your signature.",
                     "شروط الوساطة المعتادة في دبي، تُتفق عليها كتابةً قبل البدء. "
                     "لا يُخصم شيء دون توقيعك."),
            ),
            Question(
                Text("Which areas do you cover?", "ما المناطق التي تغطونها؟"),
                Text("Dubai Marina, JLT and Business Bay. Elsewhere in Dubai on request.",
                     "مرسى دبي وأبراج بحيرات جميرا والخليج التجاري. مناطق أخرى عند الطلب."),
            ),
        ),
        request_heading=Text("Request a call back", "اطلب مكالمة"),
        cta_label=Text("Send request", "إرسال الطلب"),
        hours=(
            (Text("Sunday – Thursday", "الأحد – الخميس"), Text("9:00 AM – 7:00 PM", "9:00 AM – 7:00 PM")),
            (Text("Saturday", "السبت"), Text("10:00 AM – 4:00 PM", "10:00 AM – 4:00 PM")),
        ),
    )


def salon() -> Business:
    return Business(
        name="Sample Beauty Studio",
        schema_type="BeautySalon",
        area="Jumeirah, Dubai",
        phone=PHONE,
        address=ADDRESS,
        tagline=Text("Hair, skin and nails in Jumeirah", "شعر وبشرة وأظافر في جميرا"),
        intro=Text(
            "A small studio with four chairs. Appointments only, so nobody waits, "
            "and the same stylist looks after you each visit.",
            "استوديو صغير بأربعة كراسي. بالمواعيد فقط، فلا انتظار، "
            "ونفس المصفف يعتني بك في كل زيارة.",
        ),
        offering_heading=Text("Treatments", "الخدمات"),
        offering_note=Text(
            "Times are indicative. Longer or thicker hair takes longer.",
            "الأوقات تقريبية. الشعر الطويل أو الكثيف يحتاج وقتاً أطول.",
        ),
        groups=(
            Group(
                Text("Hair", "الشعر"),
                (
                    Item(Text("Cut and finish", "قص وتصفيف"),
                         Text("Consultation, wash, cut and blow dry — about 60 minutes",
                              "استشارة وغسيل وقص وتجفيف — نحو ٦٠ دقيقة"), "AED 180"),
                    Item(Text("Colour", "صبغة"),
                         Text("Full colour or highlights — 2 to 3 hours",
                              "صبغة كاملة أو هاي لايت — من ساعتين إلى ٣ ساعات"), "from AED 450"),
                    Item(Text("Treatment", "علاج"),
                         Text("Deep conditioning or keratin", "ترطيب عميق أو كيراتين"), "from AED 300"),
                ),
            ),
            Group(
                Text("Skin and nails", "البشرة والأظافر"),
                (
                    Item(Text("Facial", "تنظيف بشرة"),
                         Text("Cleanse, exfoliate, mask — 45 minutes",
                              "تنظيف وتقشير وماسك — ٤٥ دقيقة"), "AED 250"),
                    Item(Text("Manicure and pedicure", "مانيكير وبديكير"),
                         Text("Classic or gel", "كلاسيكي أو جل"), "from AED 150"),
                ),
            ),
        ),
        highlights=(
            Item(Text("Appointments only", "بالمواعيد فقط"),
                 Text("You are seen at the time you booked, not when a chair frees up.",
                      "نستقبلك في الوقت المحدد، لا عندما يتوفر كرسي.")),
            Item(Text("The same stylist", "نفس المصفف"),
                 Text("You keep the person who knows your hair.",
                      "تبقى مع من يعرف شعرك.")),
        ),
        request_heading=Text("Request an appointment", "اطلب موعداً"),
        cta_label=Text("Send request", "إرسال الطلب"),
        request_note=Text(
            "This is a request, not a confirmed booking — and this form is a "
            "demonstration that is not connected. Your time is only held once "
            "the studio confirms.",
            "هذا طلب وليس حجزاً مؤكداً — وهذا النموذج توضيحي غير متصل. "
            "لا يُحجز موعدك إلا بعد تأكيد الاستوديو.",
        ),
        hours=(
            (Text("Saturday – Thursday", "السبت – الخميس"), Text("10:00 AM – 8:00 PM", "10:00 AM – 8:00 PM")),
            (Text("Friday", "الجمعة"), Text("2:00 PM – 8:00 PM", "2:00 PM – 8:00 PM")),
        ),
    )


SAMPLES: dict[str, tuple[Business, dict[str, str]]] = {
    "sample-restaurant": (restaurant(), {"brand": "#8C2F1F", "brand_deep": "#6B2317", "accent": "#E9B44C"}),
    "sample-cafe": (cafe(), {"brand": "#6B4B2A", "brand_deep": "#523920", "accent": "#D9A05B"}),
    "sample-detailing": (service_business(), {"brand": "#1F3A5F", "brand_deep": "#152A46", "accent": "#4FA3D1"}),
    "sample-property": (professional(), {"brand": "#1F4D3D", "brand_deep": "#16382C", "accent": "#C9A227"}),
    "sample-salon": (salon(), {"brand": "#7A2E5C", "brand_deep": "#5C2246", "accent": "#E0A3C4"}),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)

    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE) if args.deploy else None
    try:
        for slug, (biz, palette) in SAMPLES.items():
            if args.only and args.only != slug:
                continue
            files = render_site(biz, base_url=f"{PUBLIC_BASE}/{slug}", **palette)
            if target is None:
                print(f"  {slug:<22} {biz.schema_type:<18} "
                      f"{sum(len(v) for v in files.values()) // 1024} KB, {len(files)} files")
                continue
            version = target.publish(slug, files)
            print(f"  {slug:<22} -> {target.promote(slug, version.id)}")
    finally:
        if target is not None:
            target.close()

    if target is None:
        print("\ndry run — nothing published. Re-run with --deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

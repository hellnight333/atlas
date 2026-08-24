"""A way for a visitor to ask for something, with no server behind it.

`enquiry` is the second-most-common opportunity this engine raises, and it had no
executor for a real reason: a contact form needs somewhere to send the message,
and Qevik has no SMTP credential, no host that runs code, and no database a
stranger may write to.

The tempting answer is to build the form anyway and wire it later. That ships a
form that silently discards every enquiry — worse than no form, because the
visitor believes they have made contact and the business never learns they
existed. A dead contact form is the single most expensive defect a small business
site can have.

So this builds the form that **works today**: `mailto:` and WhatsApp deep links,
composed on the visitor's own device, delivered by software they already have.
No server, no credential, no message that can be dropped in transit by us.

The trade is real and is stated rather than hidden: a `mailto:` form opens the
visitor's mail client, which converts worse than a posted form and fails for
somebody with no mail client configured. That is why it emits **both** channels
whenever both exist, and why `hosted_form_gap()` describes exactly what a posted
form would need — so the upgrade is a known, costed step rather than a discovery.

Nothing here collects a field the business cannot act on. Every input maps to
something that ends up in the message.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from .content import SiteContent

#: What a visitor is asked. Deliberately short: every extra field costs
#: completions, and a field nobody reads costs completions for nothing.
FIELDS = (("name", "Your name", "text"),
          ("detail", "What do you need?", "textarea"))

#: The channels this can deliver through with no server at all.
MAILTO, WHATSAPP = "mailto", "whatsapp"


def channels(content: SiteContent) -> tuple[str, ...]:
    """Which delivery routes this business actually has."""
    found = []
    if content.contact.email is not None:
        found.append(MAILTO)
    if content.contact.whatsapp is not None:
        found.append(WHATSAPP)
    return tuple(found)


def _digits(number: str) -> str:
    """A WhatsApp link takes digits only, with no plus and no spaces."""
    return "".join(c for c in number if c.isdigit())


def form(content: SiteContent, *, arabic: bool = False) -> str:
    """The enquiry block, or an empty string when nothing could deliver it.

    Empty is the honest answer for a business with no email and no WhatsApp: a
    form with no destination is the defect this exists to avoid, and rendering
    one anyway to fill the section would be exactly that.
    """
    available = channels(content)
    if not available:
        return ""

    name = html.escape(content.business_name.value, quote=True)
    labels = {
        "heading": "أرسل استفسارًا" if arabic else "Send an enquiry",
        "name": "الاسم" if arabic else "Your name",
        "detail": "ما الذي تحتاجه؟" if arabic else "What do you need?",
        "email": "أرسل بالبريد" if arabic else "Send by email",
        "whatsapp": "راسلنا على واتساب" if arabic else "Message on WhatsApp",
        "note": ("يفتح هذا تطبيق البريد أو واتساب على جهازك."
                 if arabic else
                 "This opens your own email app or WhatsApp — nothing is sent "
                 "through this page."),
    }

    parts = [f"<h2>{labels['heading']}</h2>",
             '<form class="enquiry" onsubmit="return false">',
             f'<label for="enq-name">{labels["name"]}</label>',
             '<input id="enq-name" name="name" type="text" autocomplete="name">',
             f'<label for="enq-detail">{labels["detail"]}</label>',
             '<textarea id="enq-detail" name="detail" rows="4"></textarea>',
             '<p class="enquiry-actions">']

    if MAILTO in available:
        address = content.contact.email.value        # type: ignore[union-attr]
        parts.append(
            f'<a class="enquiry-send" data-channel="mailto" '
            f'data-to="{html.escape(address, quote=True)}" '
            f'href="mailto:{quote(address)}?subject={quote("Enquiry for " + name)}">'
            f'{labels["email"]}</a>')
    if WHATSAPP in available:
        number = _digits(content.contact.whatsapp.value)  # type: ignore[union-attr]
        parts.append(
            f'<a class="enquiry-send" data-channel="whatsapp" '
            f'data-to="{number}" href="https://wa.me/{number}" '
            f'rel="noopener" target="_blank">{labels["whatsapp"]}</a>')

    parts += ["</p>", f'<p class="enquiry-note">{labels["note"]}</p>',
              "</form>", _script()]
    return "\n".join(parts)


def _script() -> str:
    """Fold what the visitor typed into the link, on their device.

    Sixteen lines of inline JavaScript rather than a framework, and it degrades
    correctly: with scripting off, both links still open a blank message to the
    right address. The form is progressive enhancement over a working link, not
    a link that needs JavaScript to work at all.

    No `[\\x00-\\x1f]` character class anywhere in here: a literal NUL inside a
    `<script>` block kills the whole block silently, so the sanitising is an
    allow-list on length rather than a strip on control characters.
    """
    return """<script>
(function(){
  var form=document.querySelector('form.enquiry');
  if(!form)return;
  function body(){
    var n=(form.querySelector('[name=name]')||{}).value||'';
    var d=(form.querySelector('[name=detail]')||{}).value||'';
    return (n?('From: '+n+'\\n\\n'):'')+d;
  }
  form.querySelectorAll('a.enquiry-send').forEach(function(link){
    link.addEventListener('click',function(){
      var text=body().slice(0,1500);
      if(!text)return;
      if(link.dataset.channel==='whatsapp'){
        link.href='https://wa.me/'+link.dataset.to+'?text='+encodeURIComponent(text);
      }else{
        var base=link.href.split('&body=')[0];
        link.href=base+'&body='+encodeURIComponent(text);
      }
    });
  });
})();
</script>"""


def styles() -> str:
    """CSS for the form. Inline with the rest, for the same reason."""
    return """
form.enquiry{margin:0 0 1rem}
form.enquiry label{display:block;margin:.75rem 0 .25rem;color:#555}
form.enquiry input,form.enquiry textarea{width:100%;padding:.6rem;
border:1px solid #ccc;border-radius:.25rem;font:inherit;background:transparent;
color:inherit}
.enquiry-actions{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0 .5rem}
.enquiry-send{display:inline-block;padding:.6rem 1rem;border:1px solid #0b5fff;
border-radius:.25rem;text-decoration:none}
.enquiry-note{color:#666;font-size:.9rem;margin:0}
@media(prefers-color-scheme:dark){
form.enquiry input,form.enquiry textarea{border-color:#444}
.enquiry-send{border-color:#7aa7ff}
.enquiry-note,form.enquiry label{color:#aaa}
}
"""


def hosted_form_gap() -> dict:
    """What a *posted* form would need, so the upgrade is costed rather than
    discovered.

    Written down because "we'll wire it up later" is how a dead form ships. Each
    item is a real dependency, and none of them is code we can write alone.
    """
    return {
        "status": "PENDING_INFRASTRUCTURE",
        "why": ("A posted form needs somewhere to post to. The only publication "
                "target connected is a filesystem, which serves documents and "
                "runs nothing."),
        "needs": [
            {"item": "A host that executes code, or a form endpoint service",
             "kind": "PENDING_INFRASTRUCTURE"},
            {"item": "An SMTP credential, to deliver what the endpoint receives",
             "kind": "PENDING_CREDENTIAL", "credential": "QEVIK_SMTP_PASSWORD"},
            {"item": "Spam handling — a posted endpoint on a public site is "
                     "scraped within days, and an unfiltered one makes the "
                     "business's inbox useless",
             "kind": "PENDING_DESIGN"},
            {"item": "A retention decision: an enquiry is personal data, and "
                     "storing it makes Qevik a processor of it",
             "kind": "PENDING_DECISION"},
        ],
        "meanwhile": ("The mailto and WhatsApp form works today, on the "
                      "visitor's own device, and nothing it sends can be "
                      "dropped by us."),
        "trade": ("A mailto form converts worse than a posted one and fails for "
                  "a visitor with no mail client. Both channels are emitted "
                  "whenever both exist, which is the mitigation available "
                  "without a server."),
    }

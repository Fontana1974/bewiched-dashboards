#!/usr/bin/env python3
# One-time + reusable: ensure the "Documented coaching" block lives ONLY on the
# Op's Excellence (tab-f1) tab, and sickness/RTW stay on Sentiment. Idempotent.
import re, sys

def relocate_coaching(h):
    sidx = h.find('id="tab-sentiment"')
    cidx = h.find('Documented coaching')
    if cidx < 0:
        return h, "no coaching block"
    if 0 <= cidx < sidx:
        return h, "already on Op's Excellence (no-op)"
    # Block = from the coaching section-title up to (not incl) the Sentiment footer.
    m = re.search(r'(\s*<div class="section-title"[^>]*>📋 Documented coaching[\s\S]*?)(\n\s*<footer style="margin-top:18px">Customer:)', h)
    if not m:
        return h, "BOUNDARY NOT FOUND"
    block = m.group(1)
    # remove from sentiment (footer in group2 stays put)
    h = h[:m.start(1)] + h[m.end(1):]
    # insert before the </section> that closes tab-f1 (the one right before <section id="tab-sentiment">)
    h2, n = re.subn(r'(\n\s*</section>)(\s*(?:<!--[^>]*-->\s*)?<section class="tab-panel" id="tab-sentiment">)',
                    lambda mm: "\n" + block.rstrip() + "\n" + mm.group(1) + mm.group(2), h, count=1)
    if not n:
        return h, "F1 ANCHOR NOT FOUND (reverted)"
    return h2, "moved coaching Sentiment -> Op's Excellence"

if __name__ == "__main__":
    files = ["Olney_Forecast.html","Attleborough_Forecast.html","Billing_DriveThru_Forecast.html",
             "Northampton_DriveThru_Forecast.html","Glenvale_Forecast.html"]
    for f in files:
        h = open(f, encoding="utf-8").read()
        h2, msg = relocate_coaching(h)
        if h2 != h:
            open(f, "w", encoding="utf-8").write(h2)
        print(f"{f}: {msg}")

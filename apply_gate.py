#!/usr/bin/env python3
# Client-side password gate injector — stamps each served dashboard with its OWN
# SHA-256 password hash. Run as the FINAL step of run_weekly build() so it is
# re-applied on every scheduled rebuild (survives regeneration). Idempotent via the
# <!--BWGATE--> marker. Templates/partials are excluded.
#
# SECURITY NOTE: a client-side gate is OBFUSCATION, not real access control. The full
# page (data included) is delivered to the browser; a determined person can bypass it
# via view-source / DevTools. Passwords are stored ONLY as SHA-256 hashes (never plain).
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))
SNIPPET = open(os.path.join(HERE, "gate_snippet.html"), encoding="utf-8").read()
MARK = "<!--BWGATE-->"

# filename -> SHA-256(password). One unique password per served dashboard.
GATE = {
    "Company_Dashboard.html": "6b059f3dfd366e57d7229df6efbaa927660811ae5eb7b8c61d4ae8e584b30dc9",
    "EOS_Scorecard.html": "0801def6f2b71e0cc97f115b1a9d0c72c9081e3ce01cb25327fd6659c349d76a",
    "Maintenance_Dashboard.html": "5c2088419f90a915b8e78f62b4bc2f3ed94ca30f6aaa66ee6489340383dd6564",
    "Jon_Area_Dashboard.html": "f18df8d36331ba73c33cb028867944ed8dff6d32b5ee39059863870d404c9691",
    "Rich_Area_Dashboard.html": "bb874bed0535270a8303653c0255f021e2b88ceb049ac9ffda867ffa73348065",
    "Ian_Area_Dashboard.html": "7828cc4ce24fdba087251a8ab951579630d79aaa1ded8353b3c2c9ad7f2ef984",
    "Claire_Engagement_Dashboard.html": "77aaa7545efbe3b11718826143c4694e9c4f79094dc1c826d521ea9af016d808",
    "Kel_Engagement_Dashboard.html": "8b73eb76d060431a63960d56bb61b4e510ac7003e3b17077022a9c8c9975a08e",
    "App_Dashboard.html": "bad3937f1f18b1c04284001fb07031cb8251093a7cb79b396b3afb489f6b8756",
    "Area_Coach_F1_Playbook.html": "95f5b67c25bcfdf68673ba24178c339d96cbdcb415a2ad550df53beeb42bc35f",
    "Rewards_Concept.html": "5a11cf64c70b54ea5ba00b75eb79e9f3cbc7d08962efa966172e5eb69e59678e",
    "Attleborough_Forecast.html": "34eeff71de008f0deccf9d1439dc53cd74adec5dc9c21e315f22f0c64a657c09",
    "Billing_DriveThru_Forecast.html": "2022a78e3e770ec47d081bb2aee16b0f01a5809752519e1c0af015d5a2fb414b",
    "Glenvale_Forecast.html": "8cf7800034243e1c0eb6e00efffbbaeba8b0e1195eb68f91f88ae5036d44ddcf",
    "Leamington_Parade_Forecast.html": "184e5b970397e3cbc01a8c6d0b1e202a4b3b1e3734972fe818cddfbec2c3b5ee",
    "Northampton_DriveThru_Forecast.html": "cd89b36c8f9920d0bd130b75ce15b840b5d141c5323e5ced33093786a3d7a3ac",
    "Olney_Forecast.html": "73cf6ce5e618f175805a41e3f2151275fbcb696883da58e91d34eeb726756cb9",
    "index.html": "574fb459b05c8e53a242035f9c2cc6d057b05352cfe1bff5e43d86d6332ae7b6",
    "select-catering-june.html": "37ef84c9f609b9181e49579bbb3ae6a450b628c84cc839926e01c6af373a42e2",
}
# Fallback for any served page not explicitly listed (e.g. a brand-new NSO forecast),
# so a new dashboard is never accidentally published ungated.
DEFAULT_HASH = "bd71fba3ed5bdcc067903cb7a53c2d8522653d150e2e10de7b1c5370d5dac578"

def is_served(fn):
    if not fn.endswith(".html"): return False
    if fn.startswith("TEMPLATE_"): return False
    if fn.endswith("_template.html") or fn.endswith("_tmpl.html"): return False
    return True

def inject(fn):
    path = os.path.join(HERE, fn)
    s = open(path, encoding="utf-8").read()
    if MARK in s: return "skip(already gated)"
    if not re.search(r"<body[^>]*>", s, re.I): return "skip(no body)"
    h = GATE.get(fn, DEFAULT_HASH)
    snip = MARK + SNIPPET.replace("__GATE_HASH__", h)
    s = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + snip, s, count=1, flags=re.I)
    open(path, "w", encoding="utf-8").write(s)
    return "gated(%s)" % ("map" if fn in GATE else "DEFAULT")

def main():
    done = 0
    for fn in sorted(os.listdir(HERE)):
        if is_served(fn):
            r = inject(fn); print("[gate] %-38s %s" % (fn, r))
            if r.startswith("gated"): done += 1
    print("[gate] %d pages gated" % done)

if __name__ == "__main__":
    main()

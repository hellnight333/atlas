# Caddyfile reconciliation — live host vs repository vs the target artifact

WS-3 / B-2. Produced 2026-09-03 by comparing three files, and deciding each
difference in writing rather than letting one side silently overwrite the other.

| | file | lines | sha256 |
|---|---|---|---|
| A | live `/etc/caddy/Caddyfile` on `qevik-core-01` (read-only copy) | 225 | `38df2a4a71297d716afb1913e45c46e0151a9d3652e33e4534948e2baae98894` |
| B | repository `infra/qevik-production.Caddyfile` before this change | 290 | `8d879127ca53fd9975b5084ebea238f88d00333199a70e73242677ebfa4da482` |
| C | **the target artifact** — B with the `:8443` block removed | 260 | `b787b6cc5cad02ede1bd8bb71d1cdd6351433b4d075c6d9c76626b0a4260ca5c` |

## Every difference, and who wins

| # | Difference | Which side is newer | Decision |
|---|---|---|---|
| 1 | `qevik.ai` block: the live file has `try_files {path} /index.html`; the repository does not | **repository** — the fallback was measured serving the homepage (HTTP 200, 25,331 bytes) for `/services/`, `/about/`, every case study and the whole Arabic site on 2026-09-01 | Repository wins. The live file is *older*: this fix was committed and never deployed. Copying the live file to the target, as the data inventory's P1 row used to say, would have re-introduced the defect. |
| 2 | `handle_errors` with `/ar/404.html` and `/404.html`, both `status 404` | **repository** (absent from the live file) | Repository wins. Needs Caddy ≥ 2.7 — the reason `install_caddy.sh` refuses Ubuntu's 2.6.2. |
| 3 | ~22 lines of comment explaining 1 and 2 | repository | Repository wins (it is the same change). |
| 4 | `https://2.28.62.83:8443` site block, `tls internal`, 42 lines | present in **both** A and B | **Removed** (D-D). It never worked — the host firewall dropped 8443 — and it carries one host's IP in the configuration of another. Break-glass is the Hetzner console plus SSH. `infra/secure_8443.sh`, the never-applied lockdown proposal for this block, is removed with it. |
| 5 | Everything else — global options (`admin off`, ACME contact, Cloudflare `trusted_proxies`), the `(security)` and `(le)` snippets, `www` redirect, `app.qevik.ai` routing (`/api/*`,`/auth/*`,`/health` → :8081, `/control/*` → :8080), `sites.qevik.ai` with its `current` rewrites and `X-Qevik-Host`, and the `:80` bare-IP origin | identical | No decision needed. |

## What this changes when it reaches a host

- The target serves **real 404s** for unknown URLs, in the right language, where the live host today answers HTTP 200 with the homepage. That is the fix landing, and it belongs on the cutover checklist as an expected behaviour change rather than a surprise.
- The `:8443` door disappears from any host this configuration is deployed to. Nothing may be deployed to the old host before cutover (AR-4), so the old host is unaffected in practice.
- No host was modified in producing this record: the live file was read with `cat` over SSH under the AR-4 read-only carve-out.

## Verification

- `caddy validate --config infra/qevik-production.Caddyfile` — runs on a host with Caddy ≥ 2.7 (`infra/install_caddy.sh` gates both the version and this validation).
- `packages/kernel/tests/test_public_serving.py` asserts the `qevik.ai` block has no `try_files`, that every `handle_errors` rewrite target exists in the build, and (new) that the file contains no bare-IP site address.

## Appendix — the raw diff (live A → repository B, before the `:8443` removal)

```diff
--- /private/tmp/claude-501/-Users-salmansheraf/cedd70e3-ce10-46ad-bd33-f2592cb8e8a0/scratchpad/live-caddyfile.txt	2026-09-03 20:13:25
+++ -	2026-09-03 21:36:43
@@ -56,12 +56,77 @@
 }
 
 # --- public marketing site --------------------------------------------------
+#
+# This site is NOT a single-page application and must never be served as one.
+# `apps/public/build.py` writes one directory per page — services/index.html,
+# work/apex/index.html, ar/contact/index.html — plus a sitemap listing every
+# one of them.
+#
+# It was served as one. `try_files {path} /index.html` is the SPA fallback, and
+# `try_files` tests for a *file*: a request for `/services/` is a directory, so
+# it missed every candidate and was rewritten to the homepage. Measured on the
+# live site 2026-09-01 — `/services/` returned 25,331 bytes titled "Qevik —
+# digital products built around your business" while
+# `/srv/qevik-public/services/index.html` was a real 7,362-byte page titled
+# "Services — Qevik". The same for /about/, /contact/, /work/, all seven case
+# studies and the entire Arabic site, and `/nonsense-does-not-exist/` answered
+# HTTP 200 with the homepage. Every navigation link on the site was broken,
+# ~60 KB of written content was unreachable, and the sitemap advertised a dozen
+# URLs that served identical bytes.
+#
+# The fix is to stop rewriting rather than to write a cleverer rewrite:
+# `file_server` resolves a directory to its own `index.html` unaided, and
+# returns a real 404 for what is not there. The `sites.qevik.ai` block below has
+# always relied on exactly that — it is how `/slug/ar/` resolves there.
 qevik.ai {
 	import le
 	import security
 	root * /srv/qevik-public
-	try_files {path} /index.html
 	file_server
+
+	# A URL that is not a page here is a 404, not a 200 carrying the homepage.
+	# The page served is built by the same builder as every other page, so it
+	# arrives with the site's header, navigation, phone number and
+	# operating-entity footer instead of as a bare server error.
+	handle_errors {
+		# The Arabic site is a whole second site under /ar/. Someone who
+		# mistypes a URL there must not be answered in English, left-to-right.
+		#
+		# The expressions are backtick-quoted so each is a single Caddyfile
+		# argument. Unquoted they are three, which older `expression` matchers
+		# reject outright — and a config that fails to parse takes the whole
+		# server down, not just this block.
+		@ar_404 {
+			expression `{err.status_code} == 404`
+			path /ar/*
+		}
+		@404 expression `{err.status_code} == 404`
+
+		handle @ar_404 {
+			rewrite * /ar/404.html
+			# `status` is not optional here. Without it `file_server` answers
+			# 200 and the error page is indexed as a real page — the same lie
+			# the SPA fallback was telling. Needs Caddy >= 2.7; the deploy runs
+			# `caddy validate` before restarting, so an older binary refuses
+			# loudly rather than serving a soft 404.
+			file_server {
+				status 404
+			}
+		}
+		handle @404 {
+			rewrite * /404.html
+			file_server {
+				status 404
+			}
+		}
+		handle {
+			# Anything other than a missing page is unexpected on a directory
+			# of static files. Answer plainly rather than dressing an unknown
+			# failure up as a page somebody designed.
+			respond "{err.status_code} {err.status_text}" {err.status_code}
+		}
+	}
+
 	log {
 		format console
 	}
```

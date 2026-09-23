"""Checks run INSIDE the confined container by the CI smoke test.

    docker exec -i <container> python3 - < ha_docs/tests/container_smoke.py

Not a unittest module (the name keeps discovery away from it): it needs the
image's nginx, busybox and AppArmor profile, none of which exist on a
workstation. Exits non-zero with a reason on the first failure.
"""

import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8099"
SECURITY = ("X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy")


def fail(message):
    print(f"container smoke: {message}", file=sys.stderr)
    sys.exit(1)


def headers(path):
    try:
        response = urllib.request.urlopen(BASE + path, timeout=5)
    except urllib.error.HTTPError as error:  # 404 still carries `always` headers
        response = error
    return response.headers


# run.sh and entity_watch.py share /data/.checkout.lock (Plan 021). The base
# image's busybox has to provide flock, and the profile has to allow `k` on
# /data - the AppArmor grants nothing it does not list.
try:
    subprocess.run(["flock", "-x", "-n", "/data/.checkout.lock", "true"], check=True, timeout=10)
except FileNotFoundError:
    fail("flock is not in the image")
except subprocess.CalledProcessError as error:
    fail(f"flock on /data/.checkout.lock failed: exit {error.returncode}")

site = headers("/")
if site.get("Cache-Control") != "no-cache":
    fail(f"site Cache-Control is {site.get('Cache-Control')!r}, want 'no-cache'")
for name in SECURITY:
    if not site.get(name):
        fail(f"site response lost {name} (add_header inheritance)")

# Content-addressed assets are immutable, so a page change paints from cache
# instead of revalidating every stylesheet through ingress (1.17.1). The files
# need not exist: add_header ... always applies to the 404 too.
IMMUTABLE = "public, max-age=31536000, immutable"
for path, want in (
    ("/assets/stylesheets/main.ec1eaa64.min.css", IMMUTABLE),
    ("/assets/javascripts/bundle.d7400e89.min.js", IMMUTABLE),
    ("/assets/annotate.css?v=0123456789ab", IMMUTABLE),
    ("/assets/mermaid.min.js?v=0123456789ab", IMMUTABLE),
    ("/assets/annotate.css", "no-cache"),
    ("/docs/some-page.html", "no-cache"),
):
    got = headers(path).get("Cache-Control")
    if got != want:
        fail(f"{path} Cache-Control is {got!r}, want {want!r}")

anno = headers("/anno/health")
cache = anno.get_all("Cache-Control") or []
if cache != ["no-store"]:
    fail(f"/anno/ Cache-Control is {cache!r}, want exactly ['no-store']")
for name in SECURITY:
    if not anno.get(name):
        fail(f"/anno/ response lost {name}")

print("container smoke: flock and response headers OK")

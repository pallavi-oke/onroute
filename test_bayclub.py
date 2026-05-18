"""
test_bayclub.py — Fetch Bay Club Pleasanton class schedule via their public API.

Bay Club's public schedule page is JavaScript-rendered, BUT the underlying data
comes from a public Azure-hosted JSON API. We hit it directly — no Playwright,
no headless browser, no auth, no credentials, no member portal involvement.

Endpoint:
  https://bayclubs-classes-czdrbdfgdef2h5ef.westus-01.azurewebsites.net/
    api/getClasses?club=pleasanton&dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD

Stability caveat: the Azure subdomain looks auto-generated; if Bay Club ever
redeploys their backend, this URL could change. In that case, repeat the
DevTools-Network-tab investigation to find the new endpoint. Worth wrapping
in a try/except + clear error message so we know when it breaks.

Filter: only return classes matching Pallavi's 7 class types, only active
(skip cancelled). Today and tomorrow.

Run: python test_bayclub.py
"""

import sys
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

# Pallavi's class type filter. Substring match against `title`, case-insensitive.
CLASS_TYPES = [
    "Group Power",
    "ChoreoBarre",
    "Zumba",
    "Bollywood Jam",
    "Balance Sculpt",
    "Mat Pilates",
    "Rhythm Ride",
]

API_BASE = (
    "https://bayclubs-classes-czdrbdfgdef2h5ef.westus-01.azurewebsites.net"
    "/api/getClasses"
)
CLUB = "pleasanton"


def minutes_to_time(minutes: int) -> str:
    """Convert minutes-from-midnight (e.g., 615) to readable 12-hour time (10:15 AM)."""
    h, m = divmod(minutes, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h if h <= 12 else h - 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {period}"


def fetch_classes(date_str: str) -> list:
    """Fetch the day's class list from Bay Club's API."""
    params = {"club": CLUB, "dateFrom": date_str, "dateTo": date_str}
    resp = requests.get(API_BASE, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])


def filter_matches(items: list) -> list:
    """Filter to active classes whose title matches Pallavi's class types."""
    matches = []
    for item in items:
        if item.get("status") != "active":
            continue
        title_lower = item.get("title", "").lower()
        for class_type in CLASS_TYPES:
            if class_type.lower() in title_lower:
                matches.append(item)
                break
    return matches


# Fetch today and tomorrow
today = datetime.now().date()
tomorrow = today + timedelta(days=1)

for date_obj, label in [(today, "Today"), (tomorrow, "Tomorrow")]:
    date_str = date_obj.strftime("%Y-%m-%d")
    print(f"\n{'=' * 60}")
    print(f"{label}: {date_obj.strftime('%A, %B %d, %Y')}")
    print("=" * 60)

    try:
        items = fetch_classes(date_str)
    except requests.exceptions.RequestException as e:
        print(f"ERROR fetching {date_str}: {e}")
        continue

    matches = filter_matches(items)
    print(f"Total active classes at Pleasanton: {len(items)}")
    print(f"Matching your filter ({', '.join(CLASS_TYPES)}): {len(matches)}")

    if not matches:
        print("\n  (No classes matching your filter on this day.)")
        continue

    # Sort by start time for readability
    matches.sort(key=lambda x: x.get("timeFromInMinutes", 0))

    # Short, readable day-date label that we'll repeat on every class line
    # so each match is self-contained (e.g., "Sun May 17").
    day_date_label = date_obj.strftime("%a %b %d")

    print()
    for item in matches:
        start = minutes_to_time(item["timeFromInMinutes"])
        end = minutes_to_time(item["timeToInMinutes"])
        title = item.get("title", "").strip()
        instructor = item.get("instructor", "").strip() or "TBD"
        location = item.get("location", "").strip() or "(location TBD)"
        substitute = " (sub)" if item.get("substitute") else ""

        print(f"  {title}")
        print(f"    {day_date_label}, {start} - {end} | {instructor}{substitute} | {location}")

print()
print("Next: BriefingPlanner will surface relevant classes per the day's")
print("time budget and mode (e.g., 'Mat Pilates at 10am' as a 1-line callout).")

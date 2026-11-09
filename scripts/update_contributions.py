"""Render public GitHub contribution data as a blue-gray SVG; stdlib only."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}
        self.tooltip = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-date" in attrs and "data-level" in attrs:
            self.days[attrs["id"]] = {
                "date": date.fromisoformat(attrs["data-date"]),
                "level": int(attrs["data-level"]),
                "count": None,
            }
        if tag == "tool-tip":
            self.tooltip = attrs.get("for")
            self.parts = []

    def handle_data(self, text):
        if self.tooltip is not None:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.tooltip is not None:
            if self.tooltip in self.days:
                text = " ".join("".join(self.parts).split())
                match = re.match(r"([\d,]+) contributions?\b", text)
                if match:
                    self.days[self.tooltip]["count"] = int(match[1].replace(",", ""))
                elif text.startswith("No contributions"):
                    self.days[self.tooltip]["count"] = 0
            self.tooltip = None
            self.parts = []


def render(html, username):
    parser = CalendarParser()
    parser.feed(html)
    days = sorted(parser.days.values(), key=lambda d: d["date"])
    if not 350 <= len(days) <= 380:
        raise ValueError(f"Unexpected calendar length: {len(days)}; existing image kept.")
    if any(d["count"] is None or d["level"] not in range(5) for d in days):
        raise ValueError("Incomplete calendar data; existing image kept.")
    if len({d["date"] for d in days}) != len(days):
        raise ValueError("Duplicate dates; existing image kept.")

    total = sum(d["count"] for d in days)
    start, end = days[0]["date"], days[-1]["date"]
    anchor = start - timedelta(days=(start.weekday() + 1) % 7)
    colors = ["#edf3f7", "#d5e4ef", "#b9d1e3", "#96b7cf", "#759bb8"]
    pitch, cell = 17.2, 13.5
    left, top = 57, 40
    week_count = (end - anchor).days // 7 + 1
    width = max(1000, int(left + week_count * pitch + 22))
    title = f"{total:,} contributions in {start.year}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="195" viewBox="0 0 {width} 195" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(username)} — {title}</title>',
        f'<desc id="desc">Public contribution calendar, {start} to {end}. Source: https://github.com/users/{escape(username)}/contributions</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#7f8e9b}</style>',
    ]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    labels = [(start, 0)]
    labels.extend((d["date"], (d["date"] - anchor).days // 7) for d in days if d["date"].day == 1 and d["date"] != start)
    for day, col in labels:
        parts.append(f'<text x="{left + col * pitch:.1f}" y="23" font-size="12">{months[day.month-1]}</text>')
    for label, row in [("Mon", 1), ("Wed", 3), ("Fri", 5)]:
        parts.append(f'<text x="12" y="{top + row*pitch + 10:.1f}" font-size="12">{label}</text>')
    for day in days:
        row = (day["date"].weekday() + 1) % 7
        col = (day["date"] - anchor).days // 7
        x, y = left + col * pitch, top + row * pitch
        caption = f'{day["date"]}: {day["count"]} contributions'
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="2.7" fill="{colors[day["level"]]}"><title>{caption}</title></rect>')
    legend_x = width - 175
    parts.append(f'<text x="{legend_x-34}" y="183" font-size="10.5">Less</text>')
    for level, color in enumerate(colors):
        parts.append(f'<rect x="{legend_x + level*17}" y="172" width="13" height="13" rx="2.5" fill="{color}"/>')
    parts.append(f'<text x="{legend_x+91}" y="183" font-size="10.5">More</text>')
    parts.append('</svg>\n')
    return "\n".join(parts), total, start, end


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--username", default="saltseven77")
    cli.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    cli.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "assets" / "contributions.svg")
    cli.add_argument("--source-html", type=Path, help="Optional previously fetched calendar for local preview.")
    args = cli.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", args.username):
        cli.error("Invalid GitHub username")
    if not 2008 <= args.year <= 9999:
        cli.error("Invalid contribution year")
    if args.source_html:
        html = args.source_html.read_text(encoding="utf-8")
    else:
        query = urlencode({"from": f"{args.year}-01-01", "to": f"{args.year}-12-31"})
        request = Request(f"https://github.com/users/{args.username}/contributions?{query}", headers={"User-Agent": "profile-contribution-calendar", "Accept": "text/html"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=40) as response:
                    html = response.read().decode("utf-8")
                break
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(2 * (attempt + 1))
    svg, total, start, end = render(html, args.username)
    if start != date(args.year, 1, 1) or end != date(args.year, 12, 31):
        raise ValueError("Unexpected date range; existing contribution image kept.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"{args.username}: {total} publicly visible contributions, {start} to {end}. Saved {args.output}")


if __name__ == "__main__":
    main()

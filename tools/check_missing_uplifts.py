#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Report Thunderbird port commits that have not been uplifted to a branch.

Given a range of Firefox revisions, find the Firefox bugs landed in that range,
find the Thunderbird commits porting those bugs ("Bug N - Port bug M: ..."),
and check whether each port commit is present on the target comm branch.

Example:
    check_missing_uplifts.py beta FIREFOX_158_0b1_RELEASE FIREFOX_158_0b2_RELEASE
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COMM_REPO = os.path.dirname(SCRIPT_DIR)
DEFAULT_FIREFOX_REPO = os.path.dirname(DEFAULT_COMM_REPO)

BUGZILLA_URL = "https://bugzilla.mozilla.org/rest"
THUNDERBIRD_PRODUCTS = {"Thunderbird", "MailNews Core", "Calendar", "Chat Core"}

SUBJECT_BUG_RE = re.compile(r"^\s*bug\s*(\d+)", re.I)
PORT_RE = re.compile(
    r"\bport(?:ed)?\s+(?:of\s+)?bugs?\s+"
    r"((?:bug\s*)?\d+(?:\s*(?:,|and|&|\+|/)\s*(?:bug\s*)?\d+)*)",
    re.I,
)
DIFF_REV_RE = re.compile(r"^Differential Revision:\s*(\S+)", re.M)
TRAILER_RE = re.compile(r"\s+(?:[ar]\s*[=?+]|r\+a=|DONTBUILD).*$", re.I)
BACKOUT_RE = re.compile(r"^(?:back(?:ed|ing)?\s*out|revert)", re.I)
REVERTS_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
SEE_ALSO_BUG_RE = re.compile(r"bugzilla\.mozilla\.org/show_bug\.cgi\?id=(\d+)")


@dataclass
class Commit:
    sha: str
    subject: str
    body: str

    @property
    def bug(self):
        m = SUBJECT_BUG_RE.match(self.subject)
        return int(m.group(1)) if m else None

    @property
    def ported_bugs(self):
        m = PORT_RE.search(self.subject)
        return {int(n) for n in re.findall(r"\d+", m.group(1))} if m else set()

    @property
    def diff_rev(self):
        m = DIFF_REV_RE.search(self.body)
        return m.group(1).rstrip("/") if m else None

    @property
    def normalized_subject(self):
        return TRAILER_RE.sub("", self.subject).strip().lower()


@dataclass
class PortStatus:
    commit: Commit
    status: str
    match: str = ""


@dataclass
class FirefoxBug:
    bug: int
    subjects: list = field(default_factory=list)
    linked_tb_bugs: dict = field(default_factory=dict)
    ports: list = field(default_factory=list)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def log(repo, *args):
    out = git(repo, "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", *args)
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body = record.split("\x1f", 2)
        commits.append(Commit(sha, subject, body))
    return commits


def rev_list(repo, *args):
    return set(git(repo, "rev-list", *args).split())


def bugzilla_get(path, params, api_key):
    url = f"{BUGZILLA_URL}/{path}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "check_missing_uplifts.py"}
    if api_key:
        headers["X-BUGZILLA-API-KEY"] = api_key
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
        return json.load(r)


def fetch_bugs(ids, fields, api_key):
    bugs = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        data = bugzilla_get(
            "bug",
            {
                "id": ",".join(map(str, chunk)),
                "include_fields": ",".join(fields),
                "permissive": 1,
            },
            api_key,
        )
        for bug in data.get("bugs", []):
            bugs[bug["id"]] = bug
    return bugs


def find_linked_tb_bugs(ff_bugs, api_key):
    """Return {firefox bug: {thunderbird bug: bug data}} using Bugzilla links."""
    link_fields = ["id", "see_also", "depends_on", "blocks", "regressions"]
    ff_data = fetch_bugs(ff_bugs, link_fields, api_key)
    links = defaultdict(set)
    for ff_id, bug in ff_data.items():
        for key in ("depends_on", "blocks", "regressions"):
            links[ff_id].update(bug.get(key, []))
        for url in bug.get("see_also", []):
            m = SEE_ALSO_BUG_RE.search(url)
            if m:
                links[ff_id].add(int(m.group(1)))

    all_linked = set().union(*links.values()) if links else set()
    linked_data = fetch_bugs(
        all_linked, ["id", "product", "summary", "status", "resolution"], api_key
    )
    result = defaultdict(dict)
    for ff_id, linked in links.items():
        for tb_id in linked:
            data = linked_data.get(tb_id)
            if data and data["product"] in THUNDERBIRD_PRODUCTS:
                result[ff_id][tb_id] = data
    return result


def classify(commit, not_on_target, uplifts):
    if commit.sha not in not_on_target:
        return PortStatus(commit, "included", "reachable from target")
    if commit.diff_rev and commit.diff_rev in uplifts["diff_rev"]:
        other = uplifts["diff_rev"][commit.diff_rev]
        return PortStatus(commit, "uplifted", f"same revision as {other.sha[:12]}")
    if commit.normalized_subject in uplifts["subject"]:
        other = uplifts["subject"][commit.normalized_subject]
        return PortStatus(commit, "uplifted", f"same subject as {other.sha[:12]}")
    if commit.bug in uplifts["bug"]:
        shas = ", ".join(c.sha[:12] for c in uplifts["bug"][commit.bug])
        return PortStatus(commit, "partial", f"bug {commit.bug} has uplifts: {shas}")
    return PortStatus(commit, "missing")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", help="comm branch to check, e.g. beta or esr153")
    parser.add_argument("start", help="start of the Firefox range (exclusive)")
    parser.add_argument("end", help="end of the Firefox range (inclusive)")
    parser.add_argument(
        "--source",
        default="origin/main",
        help="comm branch where ports land first (default: %(default)s)",
    )
    parser.add_argument("--firefox-repo", default=DEFAULT_FIREFOX_REPO)
    parser.add_argument("--comm-repo", default=DEFAULT_COMM_REPO)
    parser.add_argument(
        "--since",
        help="only look at comm commits on the source branch after this date",
    )
    parser.add_argument(
        "--bugzilla",
        action="store_true",
        help="also use Bugzilla links to find Thunderbird bugs for Firefox bugs "
        "(uses BUGZILLA_API_KEY from the environment if set)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="also list uplifted ports")
    args = parser.parse_args()

    ff_commits = log(args.firefox_repo, f"{args.start}..{args.end}")
    ff_bugs = {}
    # print("Bugs on firefox:beta")
    for c in ff_commits:
        # print(c.bug)
        if c.bug and not BACKOUT_RE.match(c.subject):
            ff_bugs.setdefault(c.bug, FirefoxBug(c.bug)).subjects.append(c.subject)

    # print("-------------------\n")
    source_args = [args.source] + ([f"--since={args.since}"] if args.since else [])
    port_commits = defaultdict(list)
    reverted = set()

    m = log(args.comm_repo, "-i", "-E", "--grep=port(ed)? ", *source_args)
    # print(f"{len(m)} matches")
    for c in m:
        # print(c)
        if BACKOUT_RE.match(c.subject):
            reverted.update(REVERTS_RE.findall(c.body))
            continue
        if any(c.sha.startswith(r) for r in reverted):
            continue
        for ff_bug in c.ported_bugs & ff_bugs.keys():
            port_commits[ff_bug].append(c)
            # print(f"{ff_bug} <> {c}")

    if args.bugzilla and ff_bugs:
        linked = find_linked_tb_bugs(ff_bugs.keys(), os.environ.get("BUGZILLA_API_KEY"))
        tb_bugs = {tb for tbs in linked.values() for tb in tbs}
        by_tb_bug = defaultdict(list)
        for c in log(args.comm_repo, *source_args):
            if c.bug in tb_bugs:
                by_tb_bug[c.bug].append(c)
        for ff_bug, tbs in linked.items():
            ff_bugs[ff_bug].linked_tb_bugs = tbs
            known = {c.sha for c in port_commits[ff_bug]}
            for tb in tbs:
                port_commits[ff_bug].extend(c for c in by_tb_bug.get(tb, []) if c.sha not in known)

    not_on_target = rev_list(args.comm_repo, f"{args.target}..{args.source}")
    uplifts = {"diff_rev": {}, "subject": {}, "bug": defaultdict(list)}
    for c in log(args.comm_repo, f"{args.source}..{args.target}"):
        if c.diff_rev:
            uplifts["diff_rev"][c.diff_rev] = c
        uplifts["subject"][c.normalized_subject] = c
        if c.bug:
            uplifts["bug"][c.bug].append(c)

    for ff_bug, commits in port_commits.items():
        ff_bugs[ff_bug].ports = [classify(c, not_on_target, uplifts) for c in reversed(commits)]

    print(f"Firefox {args.start}..{args.end}: {len(ff_commits)} commits, {len(ff_bugs)} bugs")
    print(f"Thunderbird: ports on {args.source}, checking {args.target}\n")

    sections = [
        ("missing", "MISSING: port landed but not on target"),
        ("partial", "CHECK: Thunderbird bug has uplifts, but not this commit"),
    ]
    if args.verbose:
        sections += [
            ("uplifted", "UPLIFTED"),
            ("included", "INCLUDED: already reachable from target"),
        ]

    missing = False
    for status, title in sections:
        rows = [
            (b, p)
            for b in sorted(ff_bugs.values(), key=lambda b: b.bug)
            for p in b.ports
            if p.status == status
        ]
        if not rows:
            continue
        missing |= status in ("missing", "partial")
        print(f"{title} ({len(rows)})")
        last = None
        for ff, port in rows:
            if ff.bug != last:
                print(f"  Firefox {ff.subjects[0]}")
                last = ff.bug
            print(f"    {port.commit.sha[:12]} {port.commit.subject}")
            if port.match:
                print(f"      ({port.match})")
        print()

    if args.bugzilla:
        unlanded = [
            (ff, tb, data)
            for ff in sorted(ff_bugs.values(), key=lambda b: b.bug)
            for tb, data in sorted(ff.linked_tb_bugs.items())
            if not any(p.commit.bug == tb for p in ff.ports)
        ]
        if unlanded:
            print(f"LINKED: Thunderbird bugs with no commit on {args.source}")
            last = None
            for ff, tb, data in unlanded:
                if ff.bug != last:
                    print(f"  Firefox {ff.subjects[0]}")
                    last = ff.bug
                status = " ".join(filter(None, (data["status"], data["resolution"])))
                print(f"    Bug {tb} [{data['product']}, {status}] {data['summary']}")
            print()

    if not missing:
        print("No missing uplifts found.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

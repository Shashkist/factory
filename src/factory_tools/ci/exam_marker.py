"""Pick the recorded exam commits from a PR's comments (DECISIONS D43). Stdlib only.

Usage: python exam_marker.py < comments.jsonl
Each input line is a JSON object: id, author_association, created_at, updated_at, first
(the first line of the comment body, which starts with `exam-commit:`), in comment order.

Lines are split on "\n" only (a commenter can put U+0085 or U+2028 in a body).
A marker counts only when its first line fully matches `exam-commit: <40 hex>`, its author is
an OWNER, MEMBER or COLLABORATOR, and it was not edited. Other markers are ignored with a log
line on stderr. An edited marker by a trusted author fails the run (it could have re-pointed
the record). Prints the counted SHAs, one per line, oldest first (D43 amendment 2: the judge
accepts a later one only when the exam is identical); prints nothing when there is no marker.
"""

import json
import re
import sys

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
FORMAT = re.compile(r"exam-commit: ([0-9a-f]{40})")


def pick(comments: list[dict[str, object]]) -> list[str]:
    """The counted marker SHAs in order; ValueError when one must be refused."""
    chain: list[str] = []
    for c in comments:
        cid = c.get("id")
        m = FORMAT.fullmatch(str(c.get("first", "")).removesuffix("\r"))
        if c.get("author_association") not in TRUSTED:
            print(f"ignoring exam-commit marker comment {cid}: author not trusted", file=sys.stderr)
        elif m is None:
            print(f"ignoring exam-commit comment {cid}: not `exam-commit: <sha>`", file=sys.stderr)
        elif c.get("updated_at") != c.get("created_at"):
            raise ValueError(f"exam-commit marker (comment {cid}) was edited")
        else:
            chain.append(m.group(1))
    return chain


def main(text: str) -> int:
    try:
        comments = [json.loads(line) for line in text.split("\n") if line.strip()]
        chain = pick(comments)
    except (ValueError, AttributeError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    for sha in chain:
        print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))

"""Pick the recorded exam commit from a PR's comments (DECISIONS D43). Stdlib only.

Usage: python exam_marker.py < comments.jsonl
Each input line is a JSON object: id, author_association, created_at, updated_at, first
(the first line of the comment body, which starts with `exam-commit:`), in comment order.

Only the first marker by an OWNER, MEMBER or COLLABORATOR counts. Other markers are ignored
with a log line on stderr. When the first counted marker was edited (updated_at differs from
created_at) the run fails: it could have re-pointed the record. Prints the value after
`exam-commit:` (the judge validates it) or nothing when there is no marker.
"""

import json
import sys

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


def pick(comments: list[dict[str, object]]) -> str | None:
    """The marker value, None when there is none; ValueError when it must be refused."""
    chosen: str | None = None
    for c in comments:
        cid = c.get("id")
        if c.get("author_association") not in TRUSTED:
            print(f"ignoring exam-commit marker comment {cid}: author not trusted", file=sys.stderr)
        elif chosen is not None:
            print(f"ignoring later exam-commit marker comment {cid}", file=sys.stderr)
        elif c.get("updated_at") != c.get("created_at"):
            raise ValueError(f"the first exam-commit marker (comment {cid}) was edited")
        else:
            chosen = str(c.get("first", "")).removeprefix("exam-commit:").strip()
    return chosen


def main(text: str) -> int:
    try:
        comments = [json.loads(line) for line in text.splitlines() if line.strip()]
        sha = pick(comments)
    except (ValueError, AttributeError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    if sha is not None:
        print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))

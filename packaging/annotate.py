"""
Prints the end of a text file as a GitHub Actions notice, so CI diagnostics show up in the run's annotations.

Usage: python packaging/annotate.py TITLE FILE [LINES]
"""
import os
import sys


def escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    title, path = sys.argv[1], sys.argv[2]
    lines = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    if not os.path.isfile(path):
        body = "(missing: %s)" % path
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            body = "".join(f.readlines()[-lines:]).strip() or "(empty)"
    print("::notice title=%s::%s" % (escape(title).replace(",", "%2C").replace(":", "%3A"), escape(body)))


if __name__ == "__main__":
    main()

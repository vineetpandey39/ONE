"""Command-line entry point for managing per-channel social publishing accounts.

Kept as a real module (not an inline ``python -c`` string) so the PowerShell
helpers can call it without hitting native-argument quoting problems, and so it
can be driven directly:

    python -m openjarvis.scripts.social_account_cli list --verify
    python -m openjarvis.scripts.social_account_cli verify --channel ImagineIndia --platform instagram
    # 'set' reads KEY<TAB>VALUE lines from stdin so secrets stay off argv:
    printf 'INSTAGRAM_ACCESS_TOKEN\\t<tok>\\nINSTAGRAM_BUSINESS_ACCOUNT_ID\\t<id>\\n' | \\
        python -m openjarvis.scripts.social_account_cli set --channel ImagineIndia --platform instagram
"""

from __future__ import annotations

import argparse
import sys

from openjarvis.core import social_accounts as sa


def _cmd_list(args: argparse.Namespace) -> int:
    slugs = sa.list_channel_slugs()
    if not slugs:
        print("No channels registered yet. Add one with:")
        print('  set-social-account.ps1 -Channel "ImagineIndia" -Platform instagram')
        return 0
    for slug in slugs:
        name = sa.channel_name(slug)
        print(f"\n== {name}  ({slug}) ==")
        for platform in sa.PLATFORMS:
            st = sa.account_status(slug, platform)
            spec = sa.PLATFORMS[platform]
            ready = bool(st[spec["token_key"]] and st[spec["id_key"]])
            marks = " ".join(("[x]" if v else "[ ]") + k for k, v in st.items())
            print(f"  {spec['label']:16} {'ready' if ready else 'incomplete':10} {marks}")
            if args.verify and ready:
                ok, detail = sa.verify_account(slug, platform)
                print(f"                   {'OK  ' if ok else 'FAIL '} {detail}")
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    count = 0
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            print(f"Skipping malformed line (no tab): {line[:20]}...", file=sys.stderr)
            continue
        key, value = line.split("\t", 1)
        if value.strip():
            sa.set_account_field(args.channel, args.platform, key.strip(), value)
            count += 1
    print(f"Stored {count} field(s) for {args.platform} on channel: {args.channel}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    ok, detail = sa.verify_account(args.channel, args.platform)
    print(("OK  " if ok else "FAIL ") + detail)
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="social_account_cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show masked status for every channel")
    p_list.add_argument("--verify", action="store_true", help="also live-check each configured token")
    p_list.set_defaults(func=_cmd_list)

    p_set = sub.add_parser("set", help="store fields (read from stdin as KEY<TAB>VALUE)")
    p_set.add_argument("--channel", required=True)
    p_set.add_argument("--platform", required=True, choices=list(sa.PLATFORMS))
    p_set.set_defaults(func=_cmd_set)

    p_ver = sub.add_parser("verify", help="live-verify one channel's account identity")
    p_ver.add_argument("--channel", required=True)
    p_ver.add_argument("--platform", required=True, choices=list(sa.PLATFORMS))
    p_ver.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

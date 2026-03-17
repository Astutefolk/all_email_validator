#!/usr/bin/env python3
from __future__ import annotations
"""
All Email Validator – CLI  (hacker edition)
===========================================
Reads emails from a text file, validates each through multiple methods,
and streams every result live in a Matrix-style terminal UI.

  ✅ Green = valid       ❌ Red = invalid

Optimised for 100k+ emails with domain-level DNS/MX caching.
"""

import argparse
import sys
import time
import os
import random
import threading
import shutil
from concurrent.futures import ThreadPoolExecutor

import colorama
from colorama import Fore, Style, Back

from validator import validate_email, ValidationResult, DomainCache, reset_cache

# Enable ANSI escape sequences on Windows CMD/PowerShell
colorama.init(autoreset=True, strip=False)

# Detect if running on Windows
IS_WINDOWS = sys.platform == "win32"

# Enable virtual terminal processing on Windows 10+
if IS_WINDOWS:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ── ANSI helpers ────────────────────────────────────────────────────────────

DIM = "\033[2m"
RESET = "\033[0m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"

G = Fore.GREEN          # hacker green
GD = f"{DIM}{Fore.GREEN}"  # dim green
R = Fore.RED
RB = f"{Fore.RED}{Style.BRIGHT}"
Y = Fore.YELLOW
C = Fore.CYAN
W = Fore.WHITE
B = Style.BRIGHT
RS = Style.RESET_ALL

# ── constants ───────────────────────────────────────────────────────────────

SMTP_AUTO_THRESHOLD = 500
TERM_WIDTH = shutil.get_terminal_size((80, 24)).columns

# ── hacker banner ───────────────────────────────────────────────────────────

BANNER = f"""
{G}{B}
    ██████╗ ███████╗████████╗██╗   ██╗████████╗███████╗
    ██╔══██╗██╔════╝╚══██╔══╝██║   ██║╚══██╔══╝██╔════╝
    ███████║███████╗   ██║   ██║   ██║   ██║   █████╗  
    ██╔══██║╚════██║   ██║   ██║   ██║   ██║   ██╔══╝  
    ██║  ██║███████║   ██║   ╚██████╔╝   ██║   ███████╗
    ╚═╝  ╚═╝╚══════╝   ╚═╝    ╚═════╝    ╚═╝   ╚══════╝
{RS}{GD}       ┌──────────────────────────────────────────┐
       │  EMAIL VALIDATOR v2.0  ·  MULTI-METHOD   │
       │  Syntax · DNS · MX · Disposable · SMTP   │
       └──────────────────────────────────────────┘{RS}
"""

# matrix-style random chars for decoration
GLITCH_CHARS = "ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ012345789Z:・.\"=*+-<>¦╌"


def glitch_string(length: int = 20) -> str:
    return "".join(random.choice(GLITCH_CHARS) for _ in range(length))


# ── live line printer ───────────────────────────────────────────────────────

class LivePrinter:
    """Thread-safe printer that streams each email result + a sticky status
    bar at the bottom. Works with any terminal that supports ANSI."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0
        self.valid_count = 0
        self.invalid_count = 0
        self.disposable_count = 0
        self.domains = 0
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()

    # called from worker threads
    def feed(self, r: ValidationResult, cache: DomainCache) -> None:
        with self._lock:
            self.done += 1
            self.domains = cache.unique_domains
            if r.is_valid:
                self.valid_count += 1
            else:
                self.invalid_count += 1
            if r.is_disposable:
                self.disposable_count += 1

            self._print_email_line(r)
            self._print_status_bar()

    def _print_email_line(self, r: ValidationResult) -> None:
        """Print a single line for this email — green or red."""
        idx_str = f"{self.done:>7,}"
        elapsed = time.perf_counter() - self._t0

        if r.is_valid:
            tag = f"{G}{B}  VALID {RS}"
            color = G
        else:
            # pick specific reason
            if not r.syntax_valid:
                tag = f"{R}{B} SYNTAX {RS}"
            elif not r.domain_exists:
                tag = f"{R}{B} NO-DNS {RS}"
            elif not r.has_mx_record:
                tag = f"{R}{B}  NO-MX {RS}"
            elif r.is_disposable:
                tag = f"{Y}{B}  DISPS {RS}"
            else:
                tag = f"{R}{B} FAILED {RS}"
            color = R

        # truncate email if too long
        max_email = TERM_WIDTH - 42
        email_display = r.email if len(r.email) <= max_email else r.email[:max_email - 2] + ".."

        # random matrix glitch decoration at the end
        glitch_len = max(0, TERM_WIDTH - 40 - len(email_display))
        glitch = f"{GD}{glitch_string(min(glitch_len, 8))}{RS}" if glitch_len > 4 else ""

        sys.stdout.write(
            f"  {GD}{idx_str}{RS} │{tag}│ {color}{email_display}{RS} {glitch}\n"
        )

    def _print_status_bar(self) -> None:
        """Overwrite the bottom line with a live status bar."""
        elapsed = time.perf_counter() - self._t0
        pct = self.done / self.total * 100 if self.total else 0
        rate = self.done / elapsed if elapsed > 0 else 0
        eta = (self.total - self.done) / rate if rate > 0 else 0

        bar_width = 20
        filled = int(bar_width * self.done // self.total) if self.total else 0
        bar = f"{G}{'█' * filled}{GD}{'░' * (bar_width - filled)}{RS}"

        status = (
            f"  {bar} {W}{B}{pct:5.1f}%{RS} "
            f"│ {G}{self.valid_count:,}✓{RS} "
            f"{R}{self.invalid_count:,}✗{RS} "
            f"│ {C}{self.domains:,} dom{RS} "
            f"│ {W}{rate:,.0f}/s{RS} "
            f"│ {Y}ETA {eta:,.0f}s{RS}"
        )

        # write bar, then move cursor back up so next email prints above it
        sys.stdout.write(f"{CLEAR_LINE}{status}\r\033[A")
        sys.stdout.flush()

    def finish(self) -> None:
        """Print final status bar (no cursor tricks)."""
        sys.stdout.write("\n\n")
        sys.stdout.flush()


# ── summary ─────────────────────────────────────────────────────────────────

def print_summary(results: list, elapsed: float, cache: DomainCache) -> None:
    total = len(results)
    valid = sum(1 for r in results if r.is_valid)
    high = sum(1 for r in results if r.confidence == "HIGH")
    medium = sum(1 for r in results if r.confidence == "MEDIUM")
    invalid = total - valid
    disposable = sum(1 for r in results if r.is_disposable)
    syntax_fail = sum(1 for r in results if not r.syntax_valid)
    no_domain = sum(1 for r in results if r.syntax_valid and not r.domain_exists)
    no_mx = sum(1 for r in results if r.syntax_valid and r.domain_exists and not r.has_mx_record)

    w = 58
    line = f"{G}{'─' * w}{RS}"
    print(f"\n{line}")
    print(f"  {G}{B}▓▓ SCAN COMPLETE ▓▓{RS}")
    print(line)
    print(f"  {GD}Target scanned    :{RS} {W}{B}{total:,}{RS} emails")
    print(f"  {GD}Unique domains    :{RS} {W}{B}{cache.unique_domains:,}{RS}")
    print(f"  {GD}Elapsed           :{RS} {W}{B}{elapsed:.2f}s{RS}  ({G}{total / elapsed:,.0f} emails/s{RS})" if elapsed > 0 else "")
    print(line)
    print(f"  {G}{B}  ✔ VALID         : {valid:,}{RS}")
    print(f"  {GD}    ├─ High conf.  : {high:,}{RS}")
    print(f"  {GD}    └─ Medium conf.: {medium:,}{RS}")
    print(f"  {R}{B}  ✘ INVALID       : {invalid:,}{RS}")
    print(f"  {GD}    ├─ Bad syntax  : {syntax_fail:,}{RS}")
    print(f"  {GD}    ├─ No DNS      : {no_domain:,}{RS}")
    print(f"  {GD}    └─ No MX       : {no_mx:,}{RS}")
    if disposable:
        print(f"  {Y}{B}  ⚠ DISPOSABLE    : {disposable:,}{RS}")
    print(line)


def write_output_file(path: str, results: list) -> None:
    valid = [r.email for r in results if r.is_valid]
    invalid = [r.email for r in results if not r.is_valid]
    disposable = [r.email for r in results if r.is_disposable]

    with open(path, "w") as fh:
        fh.write("=" * 50 + "\n")
        fh.write("  Email Validation Results\n")
        fh.write("=" * 50 + "\n\n")

        fh.write(f"--- VALID EMAILS ({len(valid):,}) ---\n")
        for e in valid:
            fh.write(f"  {e}\n")

        fh.write(f"\n--- INVALID EMAILS ({len(invalid):,}) ---\n")
        for e in invalid:
            fh.write(f"  {e}\n")

        fh.write(f"\n--- DISPOSABLE EMAILS ({len(disposable):,}) ---\n")
        for e in disposable:
            fh.write(f"  {e}\n")

    # Also write a clean valid-only file
    valid_path = path.rsplit(".", 1)
    if len(valid_path) == 2:
        valid_file = f"{valid_path[0]}_valid.{valid_path[1]}"
    else:
        valid_file = f"{path}_valid"

    with open(valid_file, "w") as fh:
        for e in valid:
            fh.write(f"{e}\n")

    print(f"  {G}[+] Full results  → {B}{path}{RS}")
    print(f"  {G}[+] Valid only    → {B}{valid_file}{RS} ({G}{len(valid):,} emails{RS})")
    print(f"  {GD}[i] Contact       → @astute_support on TG{RS}")


# ── main logic ──────────────────────────────────────────────────────────────

def load_emails(path: str) -> list:
    if not os.path.isfile(path):
        print(f"  {R}[!] Error: file '{path}' not found.{RS}")
        sys.exit(1)

    with open(path) as fh:
        emails = [
            line.strip()
            for line in fh
            if line.strip() and not line.strip().startswith("#")
        ]

    if not emails:
        print(f"  {R}[!] Error: no emails found in '{path}'.{RS}")
        sys.exit(1)

    return emails


def run(
    emails: list,
    *,
    do_smtp: bool = True,
    workers: int = 20,
) -> tuple:
    """Validate all emails with live streaming output. Returns (results, cache)."""
    cache = reset_cache()
    results: list = [None] * len(emails)
    printer = LivePrinter(len(emails))

    print(f"  {G}[*] Initiating scan...{RS}\n")
    sys.stdout.write(HIDE_CURSOR)

    def _validate_one(idx: int, email: str) -> None:
        r = validate_email(email, do_smtp=do_smtp, cache=cache)
        results[idx] = r
        printer.feed(r, cache)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_validate_one, i, email)
                for i, email in enumerate(emails)
            ]
            for f in futures:
                f.result()
    finally:
        sys.stdout.write(SHOW_CURSOR)

    printer.finish()
    return results, cache


def interactive_mode() -> None:
    """Called when user double-clicks the .exe with no arguments."""
    print(f"  {G}{B}[INTERACTIVE MODE]{RS}")
    print(f"  {GD}Drag & drop your email file here, or type the path:{RS}")
    print()

    # Get file path
    file_path = input(f"  {G}>{RS} Email file path: ").strip().strip('"').strip("'")
    if not file_path:
        print(f"  {R}[!] No file provided.{RS}")
        return

    # Get output file
    out_name = os.path.splitext(os.path.basename(file_path))[0]
    default_output = f"{out_name}_results.txt"
    output_input = input(f"  {G}>{RS} Output file [{default_output}]: ").strip().strip('"').strip("'")
    output_path = output_input if output_input else default_output

    # SMTP?
    smtp_input = input(f"  {G}>{RS} Enable SMTP check? (y/N): ").strip().lower()
    do_smtp = smtp_input in ("y", "yes")

    print()
    run_scan(file_path, output_path, do_smtp=do_smtp, workers=20)


def run_scan(
    file_path: str,
    output_path: str = "",
    *,
    do_smtp: bool = False,
    workers: int = 20,
) -> None:
    """Core scan logic shared by CLI and interactive mode."""
    emails = load_emails(file_path)
    count = len(emails)

    if not do_smtp and count > SMTP_AUTO_THRESHOLD:
        print(f"  {Y}[!] {count:,} targets — SMTP auto-disabled for speed.{RS}")
        print(f"  {GD}    Use --smtp to force it on.{RS}\n")

    print(f"  {GD}[i] Target file   :{RS} {C}{B}{file_path}{RS}")
    print(f"  {GD}[i] Emails loaded :{RS} {W}{B}{count:,}{RS}")
    methods = f"{G}Syntax{RS} . {G}DNS{RS} . {G}MX{RS} . {G}Disposable{RS}"
    if do_smtp:
        methods += f" . {G}SMTP{RS}"
    else:
        methods += f" . {GD}SMTP off{RS}"
    print(f"  {GD}[i] Methods       :{RS} {methods}")
    print(f"  {GD}[i] Threads       :{RS} {W}{B}{workers}{RS}")
    print(f"  {G}{'─' * 58}{RS}")

    t0 = time.perf_counter()
    results, cache = run(emails, do_smtp=do_smtp, workers=workers)
    elapsed = time.perf_counter() - t0

    print_summary(results, elapsed, cache)

    if output_path:
        write_output_file(output_path, results)
    else:
        print(f"  {Y}[i] Tip: use -o results.txt to save results.{RS}")

    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Validate emails from a text file using multiple methods.",
    )
    parser.add_argument("file", nargs="?", default=None,
                        help="Text file with one email per line.")
    smtp_group = parser.add_mutually_exclusive_group()
    smtp_group.add_argument(
        "--no-smtp", action="store_true",
        help="Skip SMTP mailbox verification.",
    )
    smtp_group.add_argument(
        "--smtp", action="store_true",
        help="Force SMTP verification even for large files.",
    )
    parser.add_argument(
        "-o", "--output", metavar="FILE",
        help="Write results to a text file.",
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=20,
        help="Number of parallel threads (default: 20).",
    )
    args = parser.parse_args()

    print(BANNER)

    # No file argument → interactive mode (double-clicked .exe)
    if args.file is None:
        interactive_mode()
        return

    # Decide SMTP mode
    if args.no_smtp:
        do_smtp = False
    elif args.smtp:
        do_smtp = True
    else:
        do_smtp = False  # auto-decide inside run_scan based on count

    run_scan(
        args.file,
        args.output or "",
        do_smtp=do_smtp,
        workers=args.workers,
    )


def main() -> None:
    """Entry point with full error handling for .exe builds."""
    try:
        cli()
    except KeyboardInterrupt:
        print(f"\n  {Y}[!] Interrupted by user.{RS}")
    except Exception as exc:
        print(f"\n  {R}[!] Fatal error: {exc}{RS}")
        import traceback
        traceback.print_exc()
    finally:
        # Keep the window open when double-clicked on Windows
        if IS_WINDOWS and len(sys.argv) <= 1:
            print()
            input(f"  {GD}Press Enter to exit...{RS}")


if __name__ == "__main__":
    main()

"""
Email Validator Module
=====================
Validates email addresses using multiple methods:
  1. Regex syntax check
  2. Domain existence (DNS A / AAAA records)
  3. MX record lookup
  4. Disposable / temporary email detection
  5. SMTP mailbox verification (RCPT TO)

Designed to handle files with 100k+ emails efficiently via domain-level
caching — DNS and MX lookups are done once per unique domain, not per email.
"""
from __future__ import annotations

import re
import dns.resolver
import smtplib
import socket
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known disposable / temporary email domains
# ---------------------------------------------------------------------------
DISPOSABLE_DOMAINS: set = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "yopmail.com", "sharklasers.com", "guerrillamailblock.com", "grr.la",
    "dispostable.com", "trashmail.com", "fakeinbox.com", "tempail.com",
    "temp-mail.org", "getnada.com", "mohmal.com", "maildrop.cc",
    "10minutemail.com", "minutemail.com", "emailondeck.com", "33mail.com",
    "mytemp.email", "burnermail.io", "temp-mail.io", "tmail.ws",
    "tmpmail.net", "tmpmail.org", "harakirimail.com", "crazymailing.com",
    "mailnesia.com", "guerrillamail.info", "guerrillamail.net",
    "guerrillamail.org", "guerrillamail.de", "spam4.me", "trash-mail.com",
    "filzmail.com", "jetable.org", "discard.email", "mailcatch.com",
}


# ---------------------------------------------------------------------------
# Thread-safe domain cache
# ---------------------------------------------------------------------------
class DomainCache:
    """Caches DNS-A, MX, and disposable results per domain so each domain is
    resolved at most once regardless of how many emails share it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._domain_exists: Dict[str, bool] = {}
        self._mx_host: Dict[str, Optional[str]] = {}

    def get_domain_exists(self, domain: str, timeout: float = 5.0) -> bool:
        with self._lock:
            if domain in self._domain_exists:
                return self._domain_exists[domain]
        result = _check_domain_exists(domain, timeout)
        with self._lock:
            self._domain_exists[domain] = result
        return result

    def get_mx_host(self, domain: str, timeout: float = 5.0) -> Optional[str]:
        with self._lock:
            if domain in self._mx_host:
                return self._mx_host[domain]
        result = _check_mx_records(domain, timeout)
        with self._lock:
            self._mx_host[domain] = result
        return result

    @property
    def unique_domains(self) -> int:
        with self._lock:
            return len(self._domain_exists)


# Module-level default cache
_default_cache = DomainCache()


def reset_cache() -> DomainCache:
    """Create and return a fresh cache."""
    global _default_cache
    _default_cache = DomainCache()
    return _default_cache


@dataclass
class ValidationResult:
    """Holds the outcome of every validation step for a single email."""

    email: str
    syntax_valid: bool = False
    domain_exists: bool = False
    has_mx_record: bool = False
    is_disposable: bool = False
    smtp_verified: bool = False
    smtp_message: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            self.syntax_valid
            and self.domain_exists
            and self.has_mx_record
            and not self.is_disposable
        )

    @property
    def confidence(self) -> str:
        if not self.is_valid:
            return "INVALID"
        if self.smtp_verified:
            return "HIGH"
        return "MEDIUM"

    @property
    def status_emoji(self) -> str:
        return {"HIGH": "✅", "MEDIUM": "⚠️", "INVALID": "❌"}.get(
            self.confidence, "❓"
        )


# ---------------------------------------------------------------------------
# Individual validation steps
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r"\.[a-zA-Z]{2,}$"
)


def check_syntax(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def _make_resolver(timeout: float = 5.0) -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["8.8.8.8", "1.1.1.1"] + resolver.nameservers
    resolver.timeout = timeout
    resolver.lifetime = timeout
    return resolver


def _check_domain_exists(domain: str, timeout: float = 5.0) -> bool:
    resolver = _make_resolver(timeout)
    for rdtype in ("A", "AAAA"):
        try:
            resolver.resolve(domain, rdtype)
            return True
        except Exception:
            continue
    return False


def _check_mx_records(domain: str, timeout: float = 5.0) -> Optional[str]:
    resolver = _make_resolver(timeout)
    try:
        answers = resolver.resolve(domain, "MX")
        best = sorted(answers, key=lambda r: r.preference)[0]
        return str(best.exchange).rstrip(".")
    except Exception:
        return None


def check_disposable(domain: str) -> bool:
    return domain.lower() in DISPOSABLE_DOMAINS


def check_smtp(
    email: str,
    mx_host: str,
    timeout: float = 10.0,
    helo_domain: str = "verify.local",
) -> Tuple[bool, str]:
    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
            smtp.ehlo(helo_domain)
            smtp.mail(f"verify@{helo_domain}")
            code, msg = smtp.rcpt(email)
            smtp.quit()
            if code == 250:
                return True, "Mailbox exists (250 OK)"
            return False, f"Server responded {code}: {msg.decode(errors='replace')}"
    except smtplib.SMTPServerDisconnected:
        return False, "Server disconnected (may block verification)"
    except smtplib.SMTPConnectError as exc:
        return False, f"Connection refused: {exc}"
    except socket.timeout:
        return False, "Connection timed out"
    except OSError as exc:
        return False, f"Network error: {exc}"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def validate_email(
    email: str,
    *,
    do_smtp: bool = True,
    dns_timeout: float = 5.0,
    smtp_timeout: float = 10.0,
    cache: Optional[DomainCache] = None,
) -> ValidationResult:
    """Validate a single email. Uses *cache* so repeated domains are only
    resolved once."""
    if cache is None:
        cache = _default_cache

    result = ValidationResult(email=email.strip())
    email_clean = email.strip()

    # 1  Syntax
    result.syntax_valid = check_syntax(email_clean)
    if not result.syntax_valid:
        result.errors.append("Failed syntax check")
        return result

    domain = email_clean.rsplit("@", 1)[1].lower()

    # 2  Domain existence  (cached)
    result.domain_exists = cache.get_domain_exists(domain, dns_timeout)
    if not result.domain_exists:
        result.errors.append(f"Domain '{domain}' has no DNS records")

    # 3  MX records  (cached)
    mx_host = cache.get_mx_host(domain, dns_timeout)
    result.has_mx_record = mx_host is not None
    if not result.has_mx_record:
        result.errors.append(f"No MX record for '{domain}'")

    # 4  Disposable check
    result.is_disposable = check_disposable(domain)
    if result.is_disposable:
        result.errors.append(f"'{domain}' is a disposable email provider")

    # 5  SMTP verification
    if do_smtp and mx_host:
        result.smtp_verified, result.smtp_message = check_smtp(
            email_clean, mx_host, timeout=smtp_timeout
        )
        if not result.smtp_verified:
            result.errors.append(f"SMTP check failed: {result.smtp_message}")
    elif not mx_host:
        result.smtp_message = "Skipped (no MX host)"
    else:
        result.smtp_message = "Skipped by user"

    return result

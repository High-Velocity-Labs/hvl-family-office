"""
Passphrase rules for a portable `.fovault` backup (format v2).

The embedded household FEK is wrapped with the shared scrypt + AES-256-GCM envelope
(`hvl_common.security.passphrase_wrap`); this module holds only what is particular to an export:
the stronger passphrase an export asks for and the messages for refused old-format files.
"""

from __future__ import annotations

from typing import Any

from hvl_common.security import MAX_PASSPHRASE_LEN, PassphraseError, PassphraseRequired

MIN_EXPORT_PASSPHRASE_LEN = 12
BACKUP_PASSPHRASE_REQUIRED_MESSAGE = "This backup is protected. Enter the passphrase chosen when it was exported."


class WeakPassphrase(PassphraseError):
    pass


class LegacyFovaultFormat(ValueError):
    """The file uses the pre-v2 unprotected key wrapping and the caller did not opt in to legacy import."""


LEGACY_FORMAT_MESSAGE = (
    "This .fovault file uses the old unprotected format (its key is not protected by a passphrase). "
    "It is refused by default. To import it anyway, tick 'Import an old-format backup' and try again."
)


def validate_export_passphrase(passphrase: Any, confirm: Any = None) -> str:
    """Returns the passphrase if acceptable for a new export; raises a user-facing error otherwise."""
    if not isinstance(passphrase, str) or passphrase == "":
        raise PassphraseRequired("A passphrase is required to export a vault backup.")
    if len(passphrase) < MIN_EXPORT_PASSPHRASE_LEN:
        raise WeakPassphrase(f"Choose a passphrase of at least {MIN_EXPORT_PASSPHRASE_LEN} characters.")
    if len(passphrase) > MAX_PASSPHRASE_LEN:
        raise WeakPassphrase(f"Passphrase must be at most {MAX_PASSPHRASE_LEN} characters.")
    if len(set(passphrase)) < 4:
        raise WeakPassphrase("Choose a passphrase with more variety than a few repeated characters.")
    if confirm is not None and confirm != passphrase:
        raise PassphraseRequired("The passphrase and its confirmation do not match.")
    return passphrase

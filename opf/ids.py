"""Identifier validation, GS1 GTIN check-digit math, ULID/track helpers, and repo/API routing."""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

GTIN_ID_RE = re.compile(r"^gtin:([0-9]{14})$")
OPF_ID_RE = re.compile(
    r"^opf:([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*)$"
)
RAW_DIGITS_RE = re.compile(r"^[0-9]{8,14}$")

CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
MARKET_RE = re.compile(r"^[A-Z]{2}$")
TRACK_AXIS_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TRACK_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
POSITIVE_INT_RE = re.compile(r"^[1-9][0-9]*$")


def compute_gs1_check_digit(body_digits: str) -> str:
    """Compute the GS1 Mod-10 check digit for the preceding digits (length 7..13)."""
    if not body_digits.isdigit() or not (7 <= len(body_digits) <= 13):
        raise ValueError(f"Expected 7..13 numeric digits, got {body_digits!r}")
    total = 0
    # From rightmost digit of body_digits moving left: weights alternate 3, 1, 3, 1...
    for idx, ch in enumerate(reversed(body_digits)):
        weight = 3 if (idx % 2 == 0) else 1
        total += int(ch) * weight
    remainder = total % 10
    return "0" if remainder == 0 else str(10 - remainder)


def verify_gs1_gtin(gtin: str) -> bool:
    """Return True if a numeric string of length 8, 12, 13, or 14 has a valid GS1 check digit."""
    if not gtin.isdigit() or len(gtin) not in (8, 12, 13, 14):
        return False
    expected = compute_gs1_check_digit(gtin[:-1])
    return gtin[-1] == expected


def normalize_gtin_to_14(barcode: str) -> str:
    """Normalize a GTIN-8/12/13/14 barcode string into a 14-digit GTIN-14."""
    cleaned = barcode.strip()
    if cleaned.startswith("gtin:"):
        cleaned = cleaned[5:]
    if not cleaned.isdigit() or len(cleaned) not in (8, 12, 13, 14):
        raise ValueError(f"GTIN must be 8, 12, 13, or 14 digits, got {barcode!r}")
    if not verify_gs1_gtin(cleaned):
        expected = compute_gs1_check_digit(cleaned[:-1])
        raise ValueError(
            f"Invalid GS1 check digit for {barcode!r}: expected {expected}, got {cleaned[-1]}"
        )
    return cleaned.zfill(14)


def is_restricted_instore_gtin(gtin14: str) -> bool:
    """Check whether a GTIN-14 represents a GS1 restricted circulation / variable-weight code.

    GS1 prefixes 020-029 and 200-299 in EAN-13 (which become 0020..0029 or 0200..0299 in GTIN-14)
    are reserved for internal retailer / variable-weight use and are not globally unique.
    """
    if len(gtin14) != 14 or not gtin14.isdigit():
        return False
    ean13_prefix = gtin14[1:4]
    if "020" <= ean13_prefix <= "029" or "200" <= ean13_prefix <= "299":
        return True
    return False


def validate_product_id(product_id: str) -> list[str]:
    """Validate a canonical product ID ('gtin:...' or 'opf:...'). Returns a list of error strings."""
    errors: list[str] = []
    if product_id.startswith("gtin:"):
        m = GTIN_ID_RE.match(product_id)
        if not m:
            errors.append(
                f"Invalid GTIN ID format {product_id!r}: must be 'gtin:' followed by 14 digits"
            )
            return errors
        gtin14 = m.group(1)
        if gtin14 == "00000000000000":
            errors.append("Invalid GTIN ID: all zeros")
            return errors
        if not verify_gs1_gtin(gtin14):
            expected = compute_gs1_check_digit(gtin14[:-1])
            errors.append(
                f"Invalid GS1 check digit in {product_id!r}: expected final digit {expected}"
            )
        if is_restricted_instore_gtin(gtin14):
            errors.append(
                f"Restricted in-store/variable-weight barcode {product_id!r} (EAN-13 prefix {gtin14[1:4]}) "
                "cannot be used as a global GTIN; use 'opf:<brand>/<product>/<spec>' instead"
            )
    elif product_id.startswith("opf:"):
        if not OPF_ID_RE.match(product_id):
            errors.append(
                f"Invalid OPF ID format {product_id!r}: must match 'opf:<brand-slug>/<product-slug>/<spec-slug>' "
                "using lowercase alphanumeric kebab-case segments"
            )
    else:
        errors.append(
            f"Product ID {product_id!r} must start with 'gtin:' or 'opf:'"
        )
    return errors


def is_valid_ulid(val: str) -> bool:
    """Return True if val is a canonical 26-character uppercase Crockford Base32 ULID."""
    return isinstance(val, str) and bool(ULID_RE.match(val))


def generate_ulid(timestamp_ms: int | None = None) -> str:
    """Generate a 26-character uppercase Crockford Base32 ULID using stdlib time + secrets."""
    if timestamp_ms is None:
        timestamp_ms = time.time_ns() // 1_000_000
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or not (0 <= timestamp_ms <= 0xFFFFFFFFFFFF):
        raise ValueError(f"ULID timestamp_ms must fit in 48 unsigned bits, got {timestamp_ms!r}")
    time_chars = [CROCKFORD_BASE32[(timestamp_ms >> (45 - 5 * i)) & 0x1F] for i in range(10)]
    rand_bits = secrets.randbits(80)
    rand_chars = [CROCKFORD_BASE32[(rand_bits >> (75 - 5 * i)) & 0x1F] for i in range(16)]
    return "".join(time_chars + rand_chars)


def validate_track_key(track: str, allow_default: bool = True) -> list[str]:
    """Validate an OPF v0.2 track key (<market>/default or <market>/<axis>:<val_or_set>(+...)*).

    Enforces strict lexicographical ordering and uniqueness on compound axis names and set-valued members.
    """
    errors: list[str] = []
    if not isinstance(track, str) or not track:
        return ["Track key must be a non-empty string"]
    if "/" not in track:
        return [f"Invalid track key {track!r}: missing '/' separating market and track body"]
    market, rest = track.split("/", 1)
    if "/" in rest:
        return [f"Invalid track key {track!r}: unexpected extra '/'"]
    if not MARKET_RE.match(market):
        errors.append(f"Invalid market prefix {market!r} in track {track!r}: expected 2 uppercase letters")

    if rest == "default":
        if not allow_default:
            errors.append(f"Track {track!r} is a default track, which is not allowed here")
        return errors

    if not rest:
        errors.append(f"Invalid track key {track!r}: empty track specification after '/'")
        return errors

    clauses = rest.split("+")
    axes: list[str] = []
    for clause in clauses:
        if ":" not in clause:
            errors.append(f"Invalid track clause {clause!r} in {track!r}: expected '<axis>:<value>'")
            continue
        axis, val_part = clause.split(":", 1)
        if not TRACK_AXIS_RE.match(axis):
            errors.append(
                f"Invalid track axis {axis!r} in {track!r}: must match ^[a-z][a-z0-9_]*$"
            )
        axes.append(axis)

        if val_part.startswith("{") or val_part.endswith("}"):
            if not (val_part.startswith("{") and val_part.endswith("}")):
                errors.append(f"Malformed set-valued track discriminator {val_part!r} in {track!r}")
                continue
            inner = val_part[1:-1]
            if not inner:
                errors.append(f"Empty set in track {track!r}")
                continue
            members = inner.split(",")
            if len(members) < 2:
                errors.append(
                    f"Set-valued track {track!r} must contain at least 2 members; single value must use scalar '{axis}:{members[0]}'"
                )
            for member in members:
                if not TRACK_VALUE_RE.match(member):
                    errors.append(
                        f"Invalid set member {member!r} in track {track!r}: must match ^[A-Za-z0-9._-]+$"
                    )
            if len(set(members)) != len(members):
                errors.append(f"Duplicate members in set-valued track {track!r}")
            elif members != sorted(members):
                errors.append(
                    f"Set members in track {track!r} must be sorted lexicographically: expected {{{','.join(sorted(members))}}}"
                )
        else:
            if not TRACK_VALUE_RE.match(val_part):
                errors.append(
                    f"Invalid track value {val_part!r} in {track!r}: must match ^[A-Za-z0-9._-]+$"
                )

    if len(set(axes)) != len(axes):
        errors.append(f"Duplicate track axis names in compound track {track!r}")
    elif axes != sorted(axes):
        errors.append(
            f"Compound track axes in {track!r} must be sorted lexicographically by axis name"
        )
    return errors


def product_dir_for_id(products_root: Path, product_id: str) -> Path:
    """Return the v0.2 product directory under products_root for a canonical product ID."""
    errs = validate_product_id(product_id)
    if errs:
        raise ValueError("; ".join(errs))
    root = Path(products_root)
    if product_id.startswith("gtin:"):
        gtin14 = product_id[5:]
        p1 = gtin14[1:4]
        p2 = gtin14[4:7]
        return root / "gtin" / p1 / p2 / gtin14
    rest = product_id[4:]
    brand, product, spec = rest.split("/")
    return root / "opf" / brand / product / spec


def product_json_path(products_root: Path, product_id: str) -> Path:
    """Return path to v0.2 product.json for a canonical product ID."""
    return product_dir_for_id(products_root, product_id) / "product.json"


def edition_json_path(products_root: Path, product_id: str, edition_id: str) -> Path:
    """Return path to v0.2 editions/<edition_id>.json for a canonical product ID and ULID."""
    if not is_valid_ulid(edition_id):
        raise ValueError(f"Invalid ULID edition_id: {edition_id!r}")
    return product_dir_for_id(products_root, product_id) / "editions" / f"{edition_id}.json"


def parse_edition_ref(ref: str) -> tuple[str, int | None]:
    """Parse '<ulid>' or '<ulid>@<rev>' into (ulid, rev_or_none)."""
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"Invalid edition reference: {ref!r}")
    if "@" in ref:
        ulid_part, rev_part = ref.split("@", 1)
        if not is_valid_ulid(ulid_part):
            raise ValueError(f"Invalid ULID in edition reference: {ref!r}")
        if not POSITIVE_INT_RE.match(rev_part):
            raise ValueError(f"Invalid revision number in edition reference: {ref!r}")
        return ulid_part, int(rev_part)
    if not is_valid_ulid(ref):
        raise ValueError(f"Invalid ULID edition reference: {ref!r}")
    return ref, None


def api_paths_for_id(product_id: str) -> tuple[str, str]:
    """Return relative API paths (compact_path, full_path) under /v1/ for a canonical product ID."""
    if product_id.startswith("gtin:"):
        gtin14 = product_id[5:]
        p1 = gtin14[1:4]
        p2 = gtin14[4:7]
        base = f"v1/gtin/{p1}/{p2}/{gtin14}"
        return f"{base}.json", f"{base}.full.json"
    if product_id.startswith("opf:"):
        rest = product_id[4:]
        base = f"v1/opf/{rest}"
        return f"{base}.json", f"{base}.full.json"
    raise ValueError(f"Unsupported product_id: {product_id!r}")

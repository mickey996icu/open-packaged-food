"""Image sanitization, WebP cropped-label transcoding, content-addressed media validation, and URL resolution."""

from __future__ import annotations

import hashlib
import io
import re
import struct
from pathlib import Path
from typing import Any

_OPF_MEDIA_RE = re.compile(r"^opf-media://sha256/([a-f0-9]{64})$")
_MEDIA_SHARD_PATH_RE = re.compile(r"^([a-f0-9]{2})/([a-f0-9]{2})/([a-f0-9]{64})\.webp$")

CANONICAL_EVIDENCE_REGIONS: tuple[str, ...] = (
    "nutrition_table",
    "ingredients_box",
    "allergen_statement",
    "manufacturer_block",
    "barcode_net_content",
    "full_back_label",
    "other",
)
LABEL_PHOTO_REGIONS: tuple[str, ...] = CANONICAL_EVIDENCE_REGIONS

LEGACY_REGION_ALIASES: dict[str, str] = {
    "nutrition_panel": "nutrition_table",
    "ingredients_panel": "ingredients_box",
    "origin_manufacturer_panel": "manufacturer_block",
    "manufacturer_panel": "manufacturer_block",
    "barcode_panel": "barcode_net_content",
    "full_back": "full_back_label",
    "full_label": "full_back_label",
    "lot_code": "other",
}

FORBIDDEN_FRONT_REGIONS: frozenset[str] = frozenset({"front_of_pack", "front_thumb"})

FRONT_COVER_ERROR_MESSAGE = (
    "Front-of-pack cover photos ('front_of_pack' / 'front_thumb') are prohibited "
    "to avoid packaging copyright issues; crop functional label regions only "
    "(nutrition_table, ingredients_box, allergen_statement, manufacturer_block, "
    "barcode_net_content, full_back_label, other)."
)


def normalize_evidence_region(region: str) -> str:
    """Normalize a functional evidence region name and reject front-of-pack cover art."""
    raw = str(region).strip()
    if raw in FORBIDDEN_FRONT_REGIONS:
        raise ValueError(FRONT_COVER_ERROR_MESSAGE)
    mapped = LEGACY_REGION_ALIASES.get(raw, raw)
    if mapped not in CANONICAL_EVIDENCE_REGIONS:
        raise ValueError(
            f"Unsupported evidence region {region!r}; expected one of: "
            + ", ".join(CANONICAL_EVIDENCE_REGIONS)
        )
    return mapped

JPEG_STRIP_MARKERS = {
    0xE1,  # APP1 (EXIF / XMP)
    0xE2,  # APP2 (ICC / FlashPix)
    0xEC,  # APP12 (Picture Info)
    0xED,  # APP13 (Photoshop IPTC)
    0xFE,  # COM (Comment)
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_STRIP_CHUNKS = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def strip_jpeg_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Strip EXIF/XMP/IPTC/Comment segments from a JPEG byte stream losslessly."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Not a valid JPEG file (missing SOI marker)")

    out = bytearray(b"\xff\xd8")
    removed: list[str] = []
    i = 2
    n = len(data)

    while i < n:
        if data[i] != 0xFF:
            out.extend(data[i:])
            break
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1

        # Standalone markers without length payload
        if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            out.extend(b"\xff" + bytes([marker]))
            if marker == 0xD9:
                break
            continue

        if i + 2 > n:
            out.extend(b"\xff" + bytes([marker]) + data[i:])
            break

        seg_len = struct.unpack(">H", data[i : i + 2])[0]
        if seg_len < 2 or i + seg_len > n:
            out.extend(b"\xff" + bytes([marker]) + data[i:])
            break

        if marker == 0xDA:  # SOS (Start of Scan): copy segment + remaining entropy-coded data
            out.extend(b"\xff\xda")
            out.extend(data[i:])
            break

        if marker in JPEG_STRIP_MARKERS:
            removed.append(f"JPEG:0xFF{marker:02X}")
        else:
            out.extend(b"\xff" + bytes([marker]))
            out.extend(data[i : i + seg_len])

        i += seg_len

    return bytes(out), removed


def strip_png_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Strip eXIf, tEXt, zTXt, iTXt, and tIME chunks from a PNG byte stream."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a valid PNG file (missing signature)")

    out = bytearray(PNG_SIGNATURE)
    removed: list[str] = []
    i = len(PNG_SIGNATURE)
    n = len(data)

    while i + 8 <= n:
        length = struct.unpack(">I", data[i : i + 4])[0]
        chunk_type = data[i + 4 : i + 8]
        chunk_end = i + 8 + length + 4
        if chunk_end > n:
            out.extend(data[i:])
            break
        if chunk_type in PNG_STRIP_CHUNKS:
            removed.append(f"PNG:{chunk_type.decode('ascii', errors='replace')}")
        else:
            out.extend(data[i:chunk_end])
        i = chunk_end
        if chunk_type == b"IEND":
            break

    return bytes(out), removed


def strip_webp_metadata(data: bytes) -> tuple[bytes, list[str]]:
    """Strip EXIF and XMP chunks from a RIFF/WebP byte stream."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Not a valid WebP file")

    chunks = bytearray()
    removed: list[str] = []
    i = 12
    n = len(data)

    while i + 8 <= n:
        fourcc = data[i : i + 4]
        chunk_size = struct.unpack("<I", data[i + 4 : i + 8])[0]
        padded_size = chunk_size + (chunk_size & 1)
        chunk_end = i + 8 + padded_size
        if chunk_end > n:
            chunks.extend(data[i:])
            break
        if fourcc in (b"EXIF", b"XMP "):
            removed.append(f"WEBP:{fourcc.decode('ascii', errors='replace').strip()}")
        else:
            chunks.extend(data[i:chunk_end])
        i = chunk_end

    riff_size = 4 + len(chunks)
    out = b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + bytes(chunks)
    return out, removed


def sanitize_image_bytes(data: bytes) -> tuple[bytes, list[str]]:
    """Detect JPEG, PNG, or WebP and strip privacy-sensitive metadata chunks."""
    if data.startswith(b"\xff\xd8"):
        return strip_jpeg_metadata(data)
    if data.startswith(PNG_SIGNATURE):
        return strip_png_metadata(data)
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return strip_webp_metadata(data)
    return data, []


def sanitize_and_hash_image(in_path: Path, out_path: Path | None = None) -> dict[str, object]:
    """Read an image file, strip metadata, optionally write cleaned file, and return SHA-256 report."""
    raw = in_path.read_bytes()
    cleaned, removed = sanitize_image_bytes(raw)
    target = out_path or in_path
    if out_path is not None or removed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cleaned)
    sha256_hex = hashlib.sha256(cleaned).hexdigest()
    return {
        "input": str(in_path),
        "output": str(target),
        "original_bytes": len(raw),
        "cleaned_bytes": len(cleaned),
        "removed_metadata": removed,
        "sha256": sha256_hex,
    }


def inspect_webp_bytes(data: bytes) -> dict[str, Any]:
    """Inspect a RIFF/WebP container using pure stdlib struct parsing (no Pillow required).

    Returns `{"width": int, "height": int, "metadata_chunks": list[str]}` or raises ValueError.
    """
    n = len(data)
    if n < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Not a valid RIFF/WEBP container")
    riff_size = struct.unpack("<I", data[4:8])[0]
    if riff_size + 8 > n or riff_size < 4:
        raise ValueError(f"Truncated or invalid RIFF size {riff_size} for {n}-byte payload")

    end = riff_size + 8
    i = 12
    vp8x_dims: tuple[int, int] | None = None
    bitstream_dims: tuple[int, int] | None = None
    metadata_chunks: list[str] = []

    while i + 8 <= end:
        fourcc = data[i : i + 4]
        chunk_size = struct.unpack("<I", data[i + 4 : i + 8])[0]
        payload_start = i + 8
        payload_end = payload_start + chunk_size
        if payload_end > end:
            raise ValueError(f"Truncated WebP chunk {fourcc!r}")
        payload = data[payload_start:payload_end]

        if fourcc in (b"EXIF", b"XMP "):
            metadata_chunks.append(fourcc.decode("ascii", errors="replace").strip())
        elif fourcc == b"VP8X" and chunk_size >= 10:
            w = 1 + int.from_bytes(payload[4:7], "little")
            h = 1 + int.from_bytes(payload[7:10], "little")
            vp8x_dims = (w, h)
        elif fourcc == b"VP8 " and chunk_size >= 10:
            if (payload[0] & 1) == 0 and payload[3:6] == b"\x9d\x01\x2a":
                w_raw, h_raw = struct.unpack("<HH", payload[6:10])
                bitstream_dims = (w_raw & 0x3FFF, h_raw & 0x3FFF)
        elif fourcc == b"VP8L" and chunk_size >= 5:
            if payload[0] == 0x2F:
                bits = struct.unpack("<I", payload[1:5])[0]
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                bitstream_dims = (w, h)

        i = payload_end + (chunk_size & 1)

    dims = vp8x_dims or bitstream_dims
    if dims is None or dims[0] <= 0 or dims[1] <= 0:
        raise ValueError("WebP container missing valid canvas dimensions (VP8X/VP8/VP8L)")

    return {
        "width": dims[0],
        "height": dims[1],
        "metadata_chunks": metadata_chunks,
    }


def process_cropped_label_to_webp(
    in_path: Path,
    media_root: Path | None = None,
    out_path: Path | None = None,
    max_edge: int = 1000,
    quality: int = 80,
) -> dict[str, Any]:
    """EXIF-transpose, proportionally downscale (<= max_edge), strip metadata, and encode to WebP.

    Uses a lazy Pillow import so validation/normalization/build commands stay pure Python stdlib.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for WebP label transcoding (install `Pillow>=10.0` or use `uvx`)."
        ) from exc

    raw_bytes = in_path.read_bytes()
    with Image.open(io.BytesIO(raw_bytes)) as opened:
        img = ImageOps.exif_transpose(opened)
        w, h = img.size
        if max(w, h) > max_edge:
            scale = max_edge / float(max(w, h))
            new_w = max(1, min(max_edge, int(round(w * scale))))
            new_h = max(1, min(max_edge, int(round(h * scale))))
            if max(new_w, new_h) > max_edge:
                if w >= h:
                    new_w = max_edge
                    new_h = max(1, int(h * max_edge / w))
                else:
                    new_h = max_edge
                    new_w = max(1, int(w * max_edge / h))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        w, h = img.size

        has_alpha = "A" in img.getbands() or (img.mode == "P" and "transparency" in img.info)
        target_mode = "RGBA" if has_alpha else "RGB"
        if img.mode != target_mode:
            img = img.convert(target_mode)

        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=6)

    webp_bytes, _ = strip_webp_metadata(buf.getvalue())
    sha256_hex = hashlib.sha256(webp_bytes).hexdigest()
    rel_path = f"media/{sha256_hex[0:2]}/{sha256_hex[2:4]}/{sha256_hex}.webp"
    media_ref = f"opf-media://sha256/{sha256_hex}"

    written_path: Path | None = None
    if media_root is not None:
        dest = Path(media_root) / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(webp_bytes)
        written_path = dest
    if out_path is not None:
        dest_out = Path(out_path)
        dest_out.parent.mkdir(parents=True, exist_ok=True)
        dest_out.write_bytes(webp_bytes)
        written_path = dest_out

    return {
        "input": str(in_path),
        "output": str(written_path) if written_path is not None else None,
        "rel_path": rel_path,
        "media_ref": media_ref,
        "sha256": sha256_hex,
        "original_bytes": len(raw_bytes),
        "webp_bytes": len(webp_bytes),
        "width": w,
        "height": h,
    }


def validate_media_repo(
    media_root: Path,
    max_edge: int = 1000,
    max_bytes: int = 512_000,
) -> list[str]:
    """Validate content-addressed `media/<h0:2>/<h2:4>/<sha256>.webp` store without Pillow."""
    root = Path(media_root)
    if (root / "media").is_dir():
        store_dir = root / "media"
    elif root.name == "media" and root.is_dir():
        store_dir = root
    else:
        return [f"Media store directory not found under {root}"]

    errors: list[str] = []
    for path in sorted(store_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(store_dir).as_posix()
        if rel == ".gitkeep":
            continue
        m = _MEDIA_SHARD_PATH_RE.match(rel)
        if not m:
            errors.append(
                f"Invalid media path media/{rel}: must match media/<h0:2>/<h2:4>/<64-hex>.webp"
            )
            continue
        p1, p2, expected_hex = m.groups()
        if p1 != expected_hex[0:2] or p2 != expected_hex[2:4]:
            errors.append(
                f"Shard directory mismatch for media/{rel}: expected {expected_hex[0:2]}/{expected_hex[2:4]}"
            )
            continue

        data = path.read_bytes()
        if len(data) > max_bytes:
            errors.append(
                f"media/{rel} size {len(data)} bytes exceeds limit {max_bytes} bytes"
            )
        actual_hex = hashlib.sha256(data).hexdigest()
        if actual_hex != expected_hex:
            errors.append(
                f"SHA-256 mismatch for media/{rel}: file hashes to {actual_hex}, expected {expected_hex}"
            )
            continue

        try:
            info = inspect_webp_bytes(data)
        except ValueError as exc:
            errors.append(f"Corrupt or non-WebP file media/{rel}: {exc}")
            continue

        if info["metadata_chunks"]:
            errors.append(
                f"media/{rel} contains forbidden metadata chunks: {info['metadata_chunks']}"
            )
        if info["width"] > max_edge or info["height"] > max_edge:
            errors.append(
                f"media/{rel} dimensions {info['width']}x{info['height']} exceed max edge {max_edge}px"
            )

    return errors


def resolve_media_ref(media_ref: str, media_base_url: str) -> str | None:
    """Resolve a location-independent `opf-media://sha256/<hex>` reference to a public URL.

    Layout: `{media_base_url}/media/<hex[0:2]>/<hex[2:4]>/<hex>.webp`.
    Plain http(s) URLs and relative `media/` paths are returned unchanged.
    Returns None for an opf-media reference when no base URL is configured.
    """
    if media_ref.startswith(("http://", "https://", "media/")):
        return media_ref
    m = _OPF_MEDIA_RE.match(media_ref)
    if not m or not media_base_url:
        return None
    h = m.group(1)
    return f"{media_base_url.rstrip('/')}/media/{h[0:2]}/{h[2:4]}/{h}.webp"

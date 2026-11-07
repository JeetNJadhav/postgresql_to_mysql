import re
import uuid

NAMESPACE = uuid.UUID("7fa9ec06-bfa1-5f14-9f36-72a445dcf2aa")

def uuid_bytes(value: str) -> bytes:
    """Convert canonical UUID text to MySQL BINARY(16), preserving UUID byte order."""
    return uuid.UUID(str(value)).bytes

def category_id(name: str) -> bytes:
    return uuid.uuid5(NAMESPACE, "category:" + name.strip().casefold()).bytes

def related_id(source_id: str, kind: str, index: int) -> bytes:
    return uuid.uuid5(NAMESPACE, f"{source_id}:{kind}:{index}").bytes

def product_slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.casefold())).strip("-")[:255] or "product"

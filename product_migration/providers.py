import logging
from typing import Any
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from .config import settings
from .models import SourceProduct

log = logging.getLogger(__name__)

class CatalogProvider:
    name = "catalog"
    base_url = ""

    def __init__(self):
        self.client = httpx.Client(timeout=settings.provider_timeout, headers={"User-Agent": settings.user_agent})

    @retry(retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)), stop=stop_after_attempt(3), wait=wait_exponential(multiplier=.5, max=4), reraise=True)
    def search(self, product: SourceProduct) -> list[dict[str, Any]]:
        query = " ".join(x for x in (product.brand, product.name) if x)
        try:
            response = self.client.get(self.base_url, params={"search_terms": query, "search_simple": 1, "action": "process", "json": 1, "page_size": 5})
            if response.status_code == 429:
                log.warning("%s rate limited", self.name)
                return []
            response.raise_for_status()
            payload = response.json()
            return payload.get("products", []) if isinstance(payload, dict) else []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s lookup failed for %s: %s", self.name, product.id, exc)
            return []

    def close(self):
        self.client.close()

class OpenFoodFactsProvider(CatalogProvider):
    name = "Open Food Facts"
    base_url = "https://world.openfoodfacts.org/cgi/search.pl"

class OpenBeautyFactsProvider(CatalogProvider):
    name = "Open Beauty Facts"
    base_url = "https://world.openbeautyfacts.org/cgi/search.pl"

def exact_match(product: SourceProduct, candidate: dict[str, Any]) -> bool:
    name = str(candidate.get("product_name", "")).strip().casefold()
    brand = str(candidate.get("brands", "")).split(",")[0].strip().casefold()
    wanted_name = product.name.strip().casefold()
    wanted_brand = (product.brand or "").strip().casefold()
    return bool(name and name == wanted_name and (not wanted_brand or brand == wanted_brand))

def provider_facts(product: SourceProduct, providers: list[CatalogProvider]) -> dict[str, Any]:
    """Only accept exact name+brand catalog results; never promote approximate search hits."""
    facts: dict[str, Any] = {"sources": [], "specifications": [], "images": []}
    for provider in providers:
        try:
            matches = [item for item in provider.search(product) if exact_match(product, item)]
        except Exception as exc:  # one source must not stop the migration
            log.warning("%s failed for %s: %s", provider.name, product.id, exc)
            continue
        if not matches:
            continue
        item = matches[0]
        facts["sources"].append(provider.name)
        # These fields originate in the provider record; absent/unknown values remain empty.
        if item.get("generic_name") and not facts.get("description"):
            facts["description"] = str(item["generic_name"])[:255]
        image = item.get("image_url")
        if isinstance(image, str) and image.startswith("https://"):
            facts["images"].append(image)
        for key, label in (("quantity", "Pack size"), ("categories", "Catalog category"), ("countries", "Market")):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                facts["specifications"].append({"group_name": "Catalog", "name": label, "value": val.strip()[:255]})
        # OFF nutritional/ingredient facts may be useful but are never inferred. Keep only explicit values.
        nutriments = item.get("nutriments") or {}
        for key, label in (("energy-kcal_100g", "Energy (kcal/100g)"), ("proteins_100g", "Protein (g/100g)"), ("fat_100g", "Fat (g/100g)")):
            if nutriments.get(key) is not None:
                facts["specifications"].append({"group_name": "Nutrition", "name": label, "value": str(nutriments[key])})
    return facts

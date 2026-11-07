import logging
import json
import click
from sqlalchemy import text
from .config import settings
from .database import postgres_engine, mysql_engine, test_connection, fetch_products, insert_product, already_migrated
from .workflow import enrich, enrich_with_trace
from .utils import uuid_bytes, category_id, related_id, product_slug

def setup_logging():
    logging.basicConfig(level=getattr(logging, __import__("os").getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")

@click.group()
def cli():
    """Enrich and migrate PostgreSQL products into an existing MySQL catalog."""
    setup_logging()

@cli.command("test-postgres")
def test_postgres():
    """Test PostgreSQL connectivity."""
    test_connection(postgres_engine())
    click.echo("PostgreSQL connection OK")

@cli.command("test-mysql")
def test_mysql():
    """Test MySQL connectivity."""
    test_connection(mysql_engine())
    click.echo("MySQL connection OK")

@cli.command("preview")
@click.option("--limit", default=10, type=click.IntRange(min=1))
def preview(limit):
    """Show source products without modifying either database."""
    for product in fetch_products(postgres_engine(), limit=limit):
        click.echo(f"{product.id}\t{product.name}\t{product.brand or ''}\t{product.category or ''}")

@cli.command("inspect")
@click.option("--limit", default=3, type=click.IntRange(min=1), help="Maximum products to inspect (default: 3).")
@click.option("--offset", default=0, type=click.IntRange(min=0), help="Skip this many products ordered by source UUID.")
def inspect_products(limit, offset):
    """Print source input, catalog evidence, enrichment output, and projected MySQL rows; never writes to MySQL."""
    for product in fetch_products(postgres_engine(), limit=limit, offset=offset):
        try:
            facts, enriched = enrich_with_trace(product)
            pid = uuid_bytes(product.id)
            category_name = enriched.category or product.category
            cid = category_id(category_name) if category_name else None
            now = "<migration time>"
            projection = {
                "product": {
                    "id_hex": pid.hex(), "name": product.name[:255],
                    "brand": (enriched.brand or product.brand)[:255] if (enriched.brand or product.brand) else None,
                    "description": ((enriched.description or product.description)[:255] if (enriched.description or product.description) else None),
                    "price": str(enriched.price) if enriched.price is not None else None,
                    "slug": product_slug(product.name), "state": "ACTIVE",
                    "created_at": product.created_at.isoformat() if product.created_at else None,
                    "last_updated_at": product.updated_at.isoformat() if product.updated_at else now,
                },
                "category": ({"id_hex": cid.hex(), "created_at": now, "last_updated_at": now, "state": "ACTIVE", "description": None, "image_url": None, "name": category_name[:255], "slug": product_slug(category_name), "parent_id_hex": None} if cid else None),
                "product_categories": ([{"product_id_hex": pid.hex(), "category_id_hex": cid.hex()}] if cid else []),
                "product_image": [{"id_hex": related_id(product.id, "image", i).hex(), "created_at": now, "last_updated_at": now, "state": "ACTIVE", "alt_text": product.name[:255], "display_order": i, "is_primary": i == 0, "url": str(url)[:255], "product_id_hex": pid.hex()} for i, url in enumerate(enriched.images)],
                "product_specification": [{"id_hex": related_id(product.id, "spec", i).hex(), "created_at": now, "last_updated_at": now, "state": "ACTIVE", "group_name": spec.group_name[:255] if spec.group_name else None, "name": spec.name[:255], "value": spec.value[:255], "display_order": i, "product_id_hex": pid.hex()} for i, spec in enumerate(enriched.specifications)],
            }
            report = {
                "source_input": product.model_dump(mode="json"),
                "verified_catalog_facts": facts,
                "enrichment_output": enriched.model_dump(mode="json"),
                "mysql_projection_not_written": projection,
            }
            click.echo(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            click.echo("=" * 88)
        except Exception as exc:
            logging.getLogger("inspect").exception("Inspection failed for %s: %s", product.id, exc)

@cli.command("stats")
def stats():
    """Show source count and destination migrated count."""
    source = postgres_engine()
    target = mysql_engine()
    with source.connect() as conn:
        total = conn.execute(text('SELECT count(*) FROM "Product"')).scalar_one()
    with target.connect() as conn:
        migrated = conn.execute(text("SELECT count(*) FROM product")).scalar_one()
    click.echo(f"Source products: {total}\nRows in destination product table: {migrated}")

@cli.command("migrate")
@click.option("--dry-run", is_flag=True, help="Enrich and validate without any MySQL writes.")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum number of products to process.")
@click.option("--offset", default=0, type=click.IntRange(min=0), help="Source row offset for selected batches.")
@click.option("--resume/--no-resume", default=True, help="Skip source UUIDs already present in MySQL.")
def migrate(dry_run, limit, offset, resume):
    """Run migration; repeat safely to resume after interruption."""
    log = logging.getLogger("migration")
    pg = postgres_engine()
    target = None if dry_run else mysql_engine()
    if target:
        test_connection(target)
    counts = {"fetched": 0, "migrated": 0, "skipped": 0, "review": 0, "failed": 0}
    for product in fetch_products(pg, limit=limit, offset=offset):
        counts["fetched"] += 1
        try:
            if target and resume:
                with target.connect() as conn:
                    if already_migrated(conn, uuid_bytes(product.id)):
                        counts["skipped"] += 1
                        log.info("SKIP %s already migrated", product.id)
                        continue
            enriched = enrich(product)
            if enriched.review_reason:
                counts["review"] += 1
                log.warning("REVIEW %s: %s", product.id, enriched.review_reason)
            log.info("ENRICHED %s providers=%s confidence=%.2f", product.id, enriched.sources, enriched.confidence)
            if target:
                insert_product(target, product, enriched)
                counts["migrated"] += 1
                log.info("MIGRATED %s", product.id)
            else:
                log.info("DRY-RUN validated %s", product.id)
        except Exception as exc:
            counts["failed"] += 1
            log.exception("FAILED %s: %s", product.id, exc)
    click.echo("\n".join(f"{key}: {value}" for key, value in counts.items()))
    if counts["failed"]:
        raise click.exceptions.Exit(1)

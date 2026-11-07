import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from .config import settings
from .models import SourceProduct, EnrichedProduct

log = logging.getLogger(__name__)

def postgres_engine() -> Engine:
    return create_engine(settings.postgres_url(), pool_pre_ping=True)

def mysql_engine() -> Engine:
    return create_engine(settings.mysql_url(), pool_pre_ping=True)

def fetch_products(engine: Engine, limit: int | None = None, offset: int = 0, batch_size: int | None = None):
    size = batch_size or settings.batch_size
    remaining = limit
    query = text('SELECT "id", "name", "description", "brand", "category", "createdAt", "updatedAt" FROM "Product" ORDER BY "id" LIMIT :lim OFFSET :off')
    with engine.connect() as conn:
        while True:
            if remaining is not None and remaining <= 0:
                break
            rows = conn.execute(query, {"lim": min(size, remaining) if remaining is not None else size, "off": offset}).mappings().all()
            if not rows:
                break
            for row in rows:
                yield SourceProduct(id=row["id"], name=row["name"], description=row["description"], brand=row["brand"], category=row["category"], created_at=row["createdAt"], updated_at=row["updatedAt"])
            offset += len(rows)
            if remaining is not None:
                remaining -= len(rows)

def test_connection(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

def already_migrated(conn, product_id: bytes) -> bool:
    return conn.execute(text("SELECT 1 FROM product WHERE id=:id"), {"id": product_id}).first() is not None

def insert_product(engine: Engine, source: SourceProduct, enriched: EnrichedProduct) -> None:
    """Insert one product and all related records atomically; assumes the supplied schema."""
    from .utils import category_id, product_slug, uuid_bytes, related_id
    import datetime
    pid = uuid_bytes(source.id)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    def mysql_datetime(value):
        if value is None:
            return None
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    category_name = enriched.category or source.category
    with engine.begin() as conn:
        if already_migrated(conn, pid):
            log.info("Product %s already exists; skipping", source.id)
            return
        cid = category_id(category_name) if category_name else None
        if cid:
            slug = product_slug(category_name)
            conn.execute(text("INSERT INTO category (id,name,slug,state,created_at,last_updated_at) VALUES (:id,:name,:slug,'ACTIVE',:now,:now) ON DUPLICATE KEY UPDATE id=id"), {"id":cid,"name":category_name[:255],"slug":slug,"now":now})
        conn.execute(text("INSERT INTO product (id,name,brand,description,price,slug,state,created_at,last_updated_at) VALUES (:id,:name,:brand,:description,:price,:slug,'ACTIVE',:created,:updated)"), {
            "id":pid,"name":source.name[:255],"brand":((enriched.brand or source.brand)[:255] if (enriched.brand or source.brand) else None),"description":((enriched.description or source.description)[:255] if (enriched.description or source.description) else None),"price":enriched.price,"slug":product_slug(source.name),"created":mysql_datetime(source.created_at),"updated":mysql_datetime(source.updated_at) or now})
        if cid:
            conn.execute(text("INSERT INTO product_categories (product_id,category_id) VALUES (:pid,:cid)"), {"pid":pid,"cid":cid})
        for i, url in enumerate(enriched.images):
            conn.execute(text("INSERT INTO product_image (id,product_id,url,alt_text,display_order,is_primary,state,created_at,last_updated_at) VALUES (:id,:pid,:url,:alt,:ord,:primary,'ACTIVE',:now,:now)"), {"id":related_id(source.id,"image",i),"pid":pid,"url":str(url)[:255],"alt":source.name[:255],"ord":i,"primary":i==0,"now":now})
        for i, spec in enumerate(enriched.specifications):
            conn.execute(text("INSERT INTO product_specification (id,product_id,group_name,name,value,display_order,state,created_at,last_updated_at) VALUES (:id,:pid,:group,:name,:value,:ord,'ACTIVE',:now,:now)"), {"id":related_id(source.id,"spec",i),"pid":pid,"group":spec.group_name[:255] if spec.group_name else None,"name":spec.name[:255],"value":spec.value[:255],"ord":i,"now":now})

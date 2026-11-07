# Product enrichment and PostgreSQL → MySQL migration

Python 3.11+ CLI that reads the existing PostgreSQL `"Product"` table, optionally enriches records from Open Food Facts and Open Beauty Facts, and writes product/category/image/specification rows into an existing MySQL catalog. It never creates or alters destination tables.

## Architecture

- `database.py`: SQLAlchemy connectivity, batched PostgreSQL extraction, and per-product MySQL transactions.
- `providers.py`: HTTP catalog adapters with timeout/retry handling and strict exact product-name/brand matching.
- `workflow.py`: LangGraph retrieval and structured normalization workflow. OpenAI, Anthropic, and Groq-compatible LLMs are optional.
- `models.py`: Pydantic validation for source/enriched products.
- `utils.py`: canonical UUID-to-16-byte conversion and deterministic category/child IDs.
- `cli.py`: connection checks, source preview, detailed read-only inspection, migration, and statistics.

## Requirements and setup

Install Python 3.11+, PostgreSQL connectivity, and access to the already provisioned MySQL schema. From this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `.env` with PostgreSQL and MySQL host, port, database, user, and password. Credentials are read only from environment variables; do not commit `.env`.

## Catalog and LLM configuration

The enabled providers use the public Open Food Facts and Open Beauty Facts search endpoints and their documented `search.pl` JSON response. Queries use brand plus name, but results are accepted only when the returned product name matches exactly and (when supplied) the brand matches exactly. Provider failures, no exact match, and rate limiting do not block migration. A configurable User-Agent and timeout are in `.env.example`.

Optionally set `LLM_PROVIDER` to `openai`, `anthropic`, or `groq`, plus `LLM_API_KEY` and `LLM_MODEL`. For Groq, the default OpenAI-compatible base URL is used; override with `LLM_BASE_URL` if needed. The LLM is only called when a provider found an exact match and may normalize verified description text. Its invented price, specification, image, category, or identity output is never mapped. With no LLM configuration, source transfer and provider extraction still work.

No MRP is mapped to `product.price`: the source schema has no price field and the target field does not state whether it means MRP or selling price. Unverified optional data remains null/empty. Low-confidence catalog misses are flagged for review; original source product data can still migrate.

## Commands

```powershell
python main.py test-postgres
python main.py test-mysql
python main.py preview --limit 10
python main.py inspect --limit 3
python main.py stats
```

`inspect` is the pre-migration review command. For each product it prints the exact source fields, provider facts accepted by the exact-match rule, the validated enrichment result, and a projected set of MySQL rows with binary UUIDs shown as hex. It uses PostgreSQL and configured catalog/LLM services, but does not connect to MySQL or write anything. Use `--offset` to inspect a different small source slice.

Dry-run performs extraction, catalog requests, and validation but opens no MySQL connection and makes no destination writes:

```powershell
python main.py migrate --dry-run
```

Migrate all products, or a selected 50-row batch beginning at offset 100:

```powershell
python main.py migrate
python main.py migrate --offset 100 --limit 50
```

Rerunning `migrate` is the resume mechanism: existing source UUIDs are detected in `product` and skipped. Each new product plus category, link, images, and specifications is committed in one transaction. A failed product rolls back as a unit and is eligible on the next run. Per-product failures are logged and make the command exit nonzero.

## Destination mapping and idempotency

The supplied `product_catalog_schemas.csv` is followed exactly: product/category and child IDs are binary UUIDs; state values use `ACTIVE`; `product.name`, `product_image.display_order`, `product_image.is_primary`, and `product_specification.display_order` are populated as required. Categories get deterministic UUIDv5 IDs from normalized category names, and child rows use deterministic UUIDv5 IDs. Product source UUIDs are retained as their canonical 16-byte representation. Category insertion uses MySQL `ON DUPLICATE KEY UPDATE` so reruns do not duplicate categories. All related writes are inside a SQLAlchemy transaction.

The CSV lists column metadata but not foreign-key definitions or indexes. This application assumes the existing database has the relationships required by the brief and a unique/primary key on `category.id`; it does not alter schema. The CSV also does not list a primary key for `product_categories`; duplicate prevention is achieved by checking the product first, in the same transaction. Run one migration process at a time for a given source set.

## Verify in MySQL

```sql
SELECT COUNT(*) FROM product;
SELECT p.name, p.brand, c.name AS category
FROM product p
LEFT JOIN product_categories pc ON pc.product_id = p.id
LEFT JOIN category c ON c.id = pc.category_id
ORDER BY p.name LIMIT 20;
SELECT COUNT(*) FROM product_image;
SELECT COUNT(*) FROM product_specification;
```

## Testing and live checks

Run unit tests with `python -m pytest`. They verify UUID byte order, deterministic identifiers, slug normalization, and invalid UUID handling. Live database checks require credentials and network access to the configured PostgreSQL and MySQL servers; provider enrichment needs internet access, and LLM normalization requires the selected provider credentials. Dry-run and `preview` do not write to MySQL.

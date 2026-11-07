import logging
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from .config import settings
from .models import SourceProduct, EnrichedProduct, Specification
from .providers import OpenFoodFactsProvider, OpenBeautyFactsProvider, provider_facts

log = logging.getLogger(__name__)

class State(TypedDict, total=False):
    source: SourceProduct
    facts: dict[str, Any]
    result: EnrichedProduct

def _llm():
    if not settings.llm_provider:
        return None
    if not settings.llm_api_key or not settings.llm_model:
        raise ValueError("LLM_PROVIDER requires LLM_API_KEY and LLM_MODEL")
    if settings.llm_provider in ("openai", "groq"):
        from langchain_openai import ChatOpenAI
        args = {"model": settings.llm_model, "api_key": settings.llm_api_key, "temperature": 0}
        if settings.llm_provider == "groq":
            args["base_url"] = settings.llm_base_url or "https://api.groq.com/openai/v1"
        elif settings.llm_base_url:
            args["base_url"] = settings.llm_base_url
        return ChatOpenAI(**args)
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.llm_model, api_key=settings.llm_api_key, temperature=0)
    raise ValueError("LLM_PROVIDER must be openai, anthropic, groq, or empty")

def build_graph(providers=None):
    if providers is None:
        providers = ([OpenFoodFactsProvider()] if settings.enable_off else []) + ([OpenBeautyFactsProvider()] if settings.enable_obf else [])
    llm = _llm()

    def retrieve(state: State):
        product = state["source"]
        facts = provider_facts(product, providers)
        log.info("Product %s catalog sources: %s", product.id, facts["sources"] or "none")
        return {"facts": facts}

    def structure(state: State):
        source, facts = state["source"], state.get("facts", {})
        # No LLM is required for lossless transfer; it is used only to normalize verified text.
        desc = facts.get("description") or source.description
        specs = [Specification.model_validate(s) for s in facts.get("specifications", [])]
        confidence = 1.0 if facts.get("sources") else 0.0
        review = None if confidence >= settings.confidence_threshold else "No exact name and brand catalog match; review optional enrichment manually."
        if llm and facts.get("sources"):
            structured = llm.with_structured_output(EnrichedProduct)
            prompt = ("Normalize the product description using only facts explicitly present in the source record below. "
                      "Do not add, infer, or guess specifications, price, category, or images. Preserve missing values as null/empty. "
                      "Return the same exact product identity and confidence no higher than 0.95.\n" +
                      f"Source product: {source.model_dump_json()}\nVerified catalog record: {facts}")
            try:
                candidate = structured.invoke(prompt)
                # Accept only text normalization; all factual fields and URLs remain provider/source derived.
                if candidate.description and facts.get("description"):
                    desc = candidate.description[:255]
            except Exception as exc:
                log.warning("LLM processing failed for %s; preserving verified source data: %s", source.id, exc)
        result = EnrichedProduct(name=source.name, brand=source.brand, description=desc,
            category=source.category, price=None, images=facts.get("images", []), specifications=specs,
            confidence=confidence, sources=facts.get("sources", []), review_reason=review)
        return {"result": result}

    graph = StateGraph(State)
    graph.add_node("retrieve", retrieve)
    graph.add_node("structure", structure)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "structure")
    graph.add_edge("structure", END)
    return graph.compile(), providers

def enrich_with_trace(product: SourceProduct):
    """Run enrichment and return the provider facts as well as the validated result."""
    graph, providers = build_graph()
    try:
        state = graph.invoke({"source": product})
        return state.get("facts", {}), state["result"]
    finally:
        for provider in providers:
            provider.close()

def enrich(product: SourceProduct, graph=None):
    if graph is not None:
        return graph.invoke({"source": product})["result"]
    _, result = enrich_with_trace(product)
    return result

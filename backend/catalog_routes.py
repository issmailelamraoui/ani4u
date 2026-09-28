"""Additive catalog API; intentionally independent of all legacy source routes."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from anilist_provider import AnimeNotFound, ProviderError
from catalog_models import DetailResponse, HomeResponse, PageResponse


router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def service(request: Request):
    catalog = getattr(request.app.state, "catalog", None)
    if catalog is None:
        raise HTTPException(503, "Catalog is not initialized")
    return catalog


async def result(operation, response):
    # SQLite owns freshness; do not let a second HTTP cache hide mapping edits or stale status.
    response.headers["Cache-Control"] = "no-store"
    try:
        return await operation
    except AnimeNotFound:
        raise HTTPException(404, "Anime not found in catalog") from None
    except ProviderError:
        raise HTTPException(503, "Catalog metadata is temporarily unavailable", headers={"Retry-After": "60"}) from None


@router.get("/home", response_model=HomeResponse)
async def home(response: Response, catalog=Depends(service)):
    return await result(catalog.home(), response)


@router.get("/search", response_model=PageResponse)
async def search(response: Response, q: str = Query(min_length=2, max_length=100), page: int = Query(1, ge=1, le=100), per_page: int = Query(24, ge=1, le=30), catalog=Depends(service)):
    query = " ".join(q.split())
    if len(query) < 2:
        raise HTTPException(422, "Search query must contain at least two characters")
    return await result(catalog.page(page, per_page, query), response)


@router.get("/discover", response_model=PageResponse)
async def discover(response: Response, page: int = Query(1, ge=1, le=100), per_page: int = Query(24, ge=1, le=30), catalog=Depends(service)):
    return await result(catalog.page(page, per_page), response)


@router.get("/anime", response_model=DetailResponse)
async def detail_by_slug(response: Response, slug: str = Query(min_length=1, max_length=220, pattern=r"^[a-z0-9-]+$"), catalog=Depends(service)):
    return await result(catalog.detail_by_slug(slug), response)


@router.get("/anime/{anilist_id}", response_model=DetailResponse)
async def detail(response: Response, anilist_id: int = Path(ge=1, le=2147483647), catalog=Depends(service)):
    return await result(catalog.detail(anilist_id), response)

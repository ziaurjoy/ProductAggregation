import math
import httpx
import datetime
from typing import Optional, List, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Query, BackgroundTasks

from config import settings
from database import db_helper, get_db
from models import ItemListResponse, ItemDetailResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Establish connection to MongoDB on startup
    db_helper.connect()
    yield
    # Clean up connection on shutdown
    db_helper.disconnect()

app = FastAPI(
    title="Product Aggregation API",
    description="A proxy API for 1688 products with MongoDB caching.",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {
        "message": "Welcome to the Product Aggregation API!",
        "endpoints": {
            "query_items": "/items?q=nikon&page=1&lang=en",
            "item_details": "/items/{num_iid}"
        },
        "docs": "/docs"
    }


def get_mongo_sort(sort: Optional[str]):
    """Map sort parameter to MongoDB sort directive."""
    mapping = {
        "sale":      [("sales", 1)],
        "_sale":     [("sales", -1)],
        "bid":       [("price", 1)],
        "_bid":      [("price", -1)],
        "credit":    [("tag_percent", 1)],
        "_credit":   [("tag_percent", -1)],
        "cached_at": [("cached_at", 1)],
        "_cached_at":[("cached_at", -1)],
    }
    return mapping.get(sort) if sort else None


def build_cache_filter(
    search_key: str,
    start_price: Optional[float] = None,
    end_price: Optional[float] = None,
) -> dict:
    """
    Build a MongoDB filter that:
    - Matches documents whose search_tags array contains the search_key (q or imgid)
    - Optionally filters by price range
    search_tags only stores the query key (q / imgid), not page_size / sort / start_price etc.
    """
    query: dict = {
        "$or": [
            {"search_tag": search_key},   # legacy single-string field
            {"search_tags": search_key},  # current array field
        ]
    }
    price_filter: dict = {}
    if start_price is not None:
        price_filter["$gte"] = start_price
    if end_price is not None:
        price_filter["$lte"] = end_price
    if price_filter:
        query["price"] = price_filter
    return query


def extract_items_and_meta(data: Any, default_page: int, default_limit: int):
    """
    Safely extract items list and pagination metadata from upstream API response,
    supporting both dictionary and list formats.
    """
    items = []
    meta = {
        "page": str(default_page),
        "real_total_results": 0,
        "total_results": 0,
        "page_size": default_limit,
        "page_count": 1
    }

    if isinstance(data, list):
        items = data
        meta["real_total_results"] = len(data)
        meta["total_results"] = len(data)
    elif isinstance(data, dict):
        items_data = data.get("items")
        if isinstance(items_data, dict):
            items = items_data.get("item", [])
            meta["page"] = str(items_data.get("page", default_page))
            meta["real_total_results"] = items_data.get("real_total_results", 0)
            meta["total_results"] = items_data.get("total_results", 0)
            meta["page_size"] = items_data.get("page_size", default_limit)
            meta["page_count"] = items_data.get("page_count", 1)
        elif isinstance(items_data, list):
            items = items_data
            meta["real_total_results"] = len(items_data)
            meta["total_results"] = len(items_data)
        else:
            item_list = data.get("item")
            if isinstance(item_list, list):
                items = item_list
                meta["real_total_results"] = len(item_list)
                meta["total_results"] = len(item_list)

    if not isinstance(items, list):
        items = []

    return items, meta


def build_3rd_party_url(
    base_url_type: str,  # "item_search" or "item_search_img"
    api_key: str,
    q: Optional[str] = None,
    imgid: Optional[str] = None,
    page: int = 1,
    lang: str = "en",
    start_price: Optional[float] = None,
    end_price: Optional[float] = None,
    cat: Optional[int] = None,
    sort: Optional[str] = None,
    page_size: Optional[int] = None,
    filter_val: Optional[str] = None
) -> str:
    url = f"https://api.icom.la/1688/api/call.php?api_key={api_key}&{base_url_type}"
    if q is not None:
        url += f"&q={q}"
    if imgid is not None:
        url += f"&imgid={imgid}"
    url += f"&page={page}&lang={lang}"
    if start_price is not None:
        url += f"&start_price={start_price}"
    if end_price is not None:
        url += f"&end_price={end_price}"
    if cat is not None:
        url += f"&cat={cat}"
    # cached_at / _cached_at are local-only sorts; don't send to upstream API
    if sort is not None and sort not in ("cached_at", "_cached_at"):
        url += f"&sort={sort}"
    if page_size is not None:
        url += f"&page_size={page_size}"
    if filter_val is not None:
        url += f"&filter={filter_val}"
    return url


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------

async def fetch_all_pages(
    q: str, page: int, max_pages: int, lang: str,
    start_price: Optional[float] = None,
    end_price: Optional[float] = None,
    cat: Optional[int] = None,
    sort: Optional[str] = None,
    page_size: Optional[int] = None,
    filter_val: Optional[str] = None
):
    """Recursively fetch and cache all remaining pages for a text search."""
    if page > max_pages:
        return

    url = build_3rd_party_url(
        "item_search", settings.api_key, q=q, page=page, lang=lang,
        start_price=start_price, end_price=end_price, cat=cat, sort=sort,
        page_size=page_size, filter_val=filter_val
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "error" in data:
                    print(f"Upstream error on page {page}: {data['error']}")
                    return
                items, _ = extract_items_and_meta(data, page, page_size if page_size is not None else 20)
                db = get_db()
                # Save only the query term (q) as search_tags — not price/sort/page_size
                search_key = q.lower()
                for _item in items:
                    num_iid = _item.get("num_iid")
                    if num_iid and db is not None:
                        try:
                            await db["products_cache"].update_one(
                                {"num_iid": num_iid},
                                {
                                    "$set": {
                                        "num_iid": num_iid,
                                        "title": _item.get("title"),
                                        "price": _item.get("price"),
                                        "pic_url": _item.get("pic_url"),
                                        "detail_url": _item.get("detail_url"),
                                        "promotion_price": _item.get("promotion_price"),
                                        "sales": _item.get("sales", 0),
                                        "tag_percent": _item.get("tag_percent", "0%"),
                                        "cached_at": datetime.datetime.utcnow().isoformat()
                                    },
                                    "$addToSet": {
                                        "search_tags": search_key
                                    }
                                },
                                upsert=True
                            )
                        except Exception as db_err:
                            print(f"DB write error on page {page}: {db_err}")
    except httpx.TimeoutException:
        print(f"Timeout on page {page}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error on page {page}: {e}")
    except Exception as e:
        print(f"Unexpected error on page {page}: {e}")

    # Fetch next page
    await fetch_all_pages(
        q, page + 1, max_pages, lang, start_price, end_price, cat, sort, page_size, filter_val
    )


async def fetch_all_pages_img(
    imgid: str, page: int, max_pages: int, lang: str,
    start_price: Optional[float] = None,
    end_price: Optional[float] = None,
    cat: Optional[int] = None,
    sort: Optional[str] = None,
    page_size: Optional[int] = None,
    filter_val: Optional[str] = None
):
    """Recursively fetch and cache all remaining pages for an image search."""
    if page > max_pages:
        print(f"Finished fetching all image pages (max: {max_pages})")
        return

    url = build_3rd_party_url(
        "item_search_img", settings.api_key, imgid=imgid, page=page, lang=lang,
        start_price=start_price, end_price=end_price, cat=cat, sort=sort,
        page_size=page_size, filter_val=filter_val
    )
    print('===url', url)
    print(f"Fetching image page {page}/{max_pages} --- {url}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "error" in data:
                    print(f"Upstream error on image page {page}: {data['error']}")
                    return
                items, _ = extract_items_and_meta(data, page, page_size if page_size is not None else 20)
                db = get_db()
                # Save only the imgid as search_tags — not price/sort/page_size
                search_key = imgid.lower()
                for _item in items:
                    num_iid = _item.get("num_iid")
                    if num_iid and db is not None:
                        try:
                            await db["products_cache"].update_one(
                                {"num_iid": num_iid},
                                {
                                    "$set": {
                                        "num_iid": num_iid,
                                        "title": _item.get("title"),
                                        "price": _item.get("price"),
                                        "pic_url": _item.get("pic_url"),
                                        "detail_url": _item.get("detail_url"),
                                        "promotion_price": _item.get("promotion_price"),
                                        "sales": _item.get("sales", 0),
                                        "tag_percent": _item.get("tag_percent", "0%"),
                                        "cached_at": datetime.datetime.utcnow().isoformat()
                                    },
                                    "$addToSet": {
                                        "search_tags": search_key
                                    }
                                },
                                upsert=True
                            )
                        except Exception as db_err:
                            print(f"DB write error on image page {page}: {db_err}")
    except httpx.TimeoutException:
        print(f"Timeout on image page {page}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error on image page {page}: {e}")
    except Exception as e:
        print(f"Unexpected error on image page {page}: {e}")

    # Fetch next page
    await fetch_all_pages_img(
        imgid, page + 1, max_pages, lang, start_price, end_price, cat, sort, page_size, filter_val
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/items", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
async def query_items(
    background_tasks: BackgroundTasks,
    q: str = Query("nikon", description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    lang: str = Query("en", description="Language of result"),
    start_price: Optional[float] = Query(None, description="Start price filter"),
    end_price: Optional[float] = Query(None, description="End price filter"),
    cat: Optional[int] = Query(None, description="Category ID filter"),
    sort: Optional[str] = Query(None, description="Sort option: [bid, _bid, sale, _sale, credit, _credit, cached_at, _cached_at]"),
    page_size: Optional[int] = Query(40, ge=1, description="Number of items per page"),
    filter: Optional[str] = Query(None, description="Additional filter parameters e.g. filtId:1,2,3;city:Tianjin")
):
    db = get_db()
    # search_key = only the query term; price/sort/page_size are applied at query time
    search_key = q.lower()
    limit_val = page_size if page_size is not None else 20

    # 1. Check MongoDB cache first
    cached_items = []
    total_cached = 0
    if db is not None:
        try:
            cache_filter = build_cache_filter(search_key, start_price, end_price)

            total_cached = await db["products_cache"].count_documents(cache_filter)
            query_cursor = db["products_cache"].find(cache_filter)
            # print('cache_filter===', cache_filter)
            mongo_sort = get_mongo_sort(sort)
            if mongo_sort:
                query_cursor = query_cursor.sort(mongo_sort)
            cursor = query_cursor.skip((page - 1) * limit_val).limit(limit_val)
            async for doc in cursor:
                cached_items.append({
                    "title": doc.get("title"),
                    "pic_url": doc.get("pic_url"),
                    "price": doc.get("price"),
                    "promotion_price": doc.get("promotion_price", doc.get("price")),
                    "sales": doc.get("sales", 0),
                    "num_iid": doc.get("num_iid"),
                    "tag_percent": doc.get("tag_percent", "0%"),
                    "detail_url": doc.get("detail_url")
                })
        except Exception as db_err:
            print(f"MongoDB cache lookup failed: {db_err}")
            cached_items = []
            total_cached = 0
    # print('cached_items===', cached_items)
    if cached_items:
        page_count = math.ceil(total_cached / limit_val) if limit_val > 0 else 1
        return {
            "items": {
                "page": str(page),
                "real_total_results": total_cached,
                "total_results": total_cached,
                "page_size": limit_val,
                "page_count": page_count,
                "item": cached_items
            },
        }

    # 2. Cache miss — call 3rd party API
    print(f"[CACHE MISS] query='{q}' search_key='{search_key}' — calling upstream API")
    final_response = {
        "items": {
            "page": str(page),
            "real_total_results": 0,
            "total_results": 0,
            "page_size": limit_val,
            "page_count": 1,
            "item": []
        },
    }

    if settings.api_key:
        url = build_3rd_party_url(
            "item_search", settings.api_key, q=q, page=page, lang=lang,
            start_price=start_price, end_price=end_price, cat=cat, sort=sort,
            page_size=page_size, filter_val=filter
        )
        print(f"Calling upstream: {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                data = res.json()

                # Surface upstream errors clearly
                if isinstance(data, dict) and "error" in data:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Upstream API error: {data['error']}"
                    )

                if res.status_code == 200:
                    items, items_meta = extract_items_and_meta(data, page, limit_val)
                    # print('===data', data)
                    # Cache results — only store q as search_tags
                    if db is not None:
                        for _item in items:
                            num_iid = _item.get("num_iid")
                            if num_iid:
                                try:
                                    await db["products_cache"].update_one(
                                        {"num_iid": num_iid},
                                        {
                                            "$set": {
                                                "num_iid": num_iid,
                                                "title": _item.get("title"),
                                                "price": _item.get("price"),
                                                "pic_url": _item.get("pic_url"),
                                                "detail_url": _item.get("detail_url"),
                                                "promotion_price": _item.get("promotion_price"),
                                                "sales": _item.get("sales", 0),
                                                "tag_percent": _item.get("tag_percent", "0%"),
                                                "cached_at": datetime.datetime.utcnow().isoformat()
                                            },
                                            "$addToSet": {
                                                "search_tags": search_key
                                            }
                                        },
                                        upsert=True
                                    )
                                except Exception as db_err:
                                    print(f"DB write error: {db_err}")

                    final_response["items"] = {
                        "page": str(items_meta.get("page", page)),
                        "real_total_results": items_meta.get("real_total_results", 0),
                        "total_results": items_meta.get("total_results", 0),
                        "page_size": limit_val,
                        "page_count": items_meta.get("page_count", 1),
                        "item": items[:limit_val]
                    }

                    max_pages = items_meta.get("page_count", 1)
                    if max_pages > page:
                        background_tasks.add_task(
                            fetch_all_pages, q, page + 1, max_pages, lang,
                            start_price, end_price, cat, sort, page_size, filter
                        )

                    return final_response

        except HTTPException:
            raise
        except Exception as e:
            print(f"Error querying upstream API: {e}")

    return final_response


@app.get("/items/search-by-image", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
@app.get("/item_search_img", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
async def search_by_image(
    background_tasks: BackgroundTasks,
    imgid: str = Query(..., description="Image URL to search"),
    page: int = Query(1, ge=1, description="Page number"),
    lang: str = Query("zh-CN", description="Language of result"),
    start_price: Optional[float] = Query(None, description="Start price filter"),
    end_price: Optional[float] = Query(None, description="End price filter"),
    cat: Optional[int] = Query(None, description="Category ID filter"),
    sort: Optional[str] = Query(None, description="Sort option: [bid, _bid, sale, _sale, credit, _credit, cached_at, _cached_at]"),
    page_size: Optional[int] = Query(40, ge=1, description="Number of items per page"),
    filter: Optional[str] = Query(None, description="Additional filter parameters e.g. filtId:1,2,3;city:Tianjin")
):
    db = get_db()
    # search_key = only the imgid; price/sort/page_size are applied at query time
    search_key = imgid.lower()
    limit_val = page_size if page_size is not None else 20

    # 1. Check MongoDB cache first
    cached_items = []
    total_cached = 0
    if db is not None:
        try:
            cache_filter = build_cache_filter(search_key, start_price, end_price)
            total_cached = await db["products_cache"].count_documents(cache_filter)
            query_cursor = db["products_cache"].find(cache_filter)
            mongo_sort = get_mongo_sort(sort)
            if mongo_sort:
                query_cursor = query_cursor.sort(mongo_sort)
            cursor = query_cursor.skip((page - 1) * limit_val).limit(limit_val)
            async for doc in cursor:
                cached_items.append({
                    "title": doc.get("title"),
                    "pic_url": doc.get("pic_url"),
                    "price": doc.get("price"),
                    "promotion_price": doc.get("promotion_price", doc.get("price")),
                    "sales": doc.get("sales", 0),
                    "num_iid": doc.get("num_iid"),
                    "tag_percent": doc.get("tag_percent", "0%"),
                    "detail_url": doc.get("detail_url")
                })
        except Exception as db_err:
            print(f"MongoDB cache lookup failed: {db_err}")
            cached_items = []
            total_cached = 0

    if cached_items:
        page_count = math.ceil(total_cached / limit_val) if limit_val > 0 else 1
        return {
            "items": {
                "page": str(page),
                "real_total_results": total_cached,
                "total_results": total_cached,
                "page_size": limit_val,
                "page_count": page_count,
                "item": cached_items
            }
        }

    # 2. Cache miss — call 3rd party API
    print(f"[CACHE MISS] imgid='{imgid}' — calling upstream API")
    final_response = {
        "items": {
            "page": str(page),
            "real_total_results": 0,
            "total_results": 0,
            "page_size": limit_val,
            "page_count": 1,
            "item": []
        }
    }


    if settings.api_key:
        url = build_3rd_party_url(
            "item_search_img", settings.api_key, imgid=imgid, page=page, lang=lang,
            start_price=start_price, end_price=end_price, cat=cat, sort=sort,
            page_size=page_size, filter_val=filter
        )
        print(f"Calling upstream: {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                data = res.json()

                # Surface upstream errors clearly
                if isinstance(data, dict) and "error" in data:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Upstream API error: {data['error']}"
                    )

                if res.status_code == 200:
                    items, items_meta = extract_items_and_meta(data, page, limit_val)

                    # Cache results — only store imgid as search_tags
                    if db is not None:
                        for _item in items:
                            num_iid = _item.get("num_iid")
                            if num_iid:
                                try:
                                    await db["products_cache"].update_one(
                                        {"num_iid": num_iid},
                                        {
                                            "$set": {
                                                "num_iid": num_iid,
                                                "title": _item.get("title"),
                                                "price": _item.get("price"),
                                                "pic_url": _item.get("pic_url"),
                                                "detail_url": _item.get("detail_url"),
                                                "promotion_price": _item.get("promotion_price"),
                                                "sales": _item.get("sales", 0),
                                                "tag_percent": _item.get("tag_percent", "0%"),
                                                "cached_at": datetime.datetime.utcnow().isoformat()
                                            },
                                            "$addToSet": {
                                                "search_tags": search_key
                                            }
                                        },
                                        upsert=True
                                    )
                                except Exception as db_err:
                                    print(f"DB write error: {db_err}")

                    final_response["items"] = {
                        "page": str(items_meta.get("page", page)),
                        "real_total_results": items_meta.get("real_total_results", 0),
                        "total_results": items_meta.get("total_results", 0),
                        "page_size": limit_val,
                        "page_count": items_meta.get("page_count", 1),
                        "item": items[:limit_val]
                    }

                    max_pages = items_meta.get("page_count", 1)
                    if max_pages > page:
                        # background_tasks.add_task(
                        #     fetch_all_pages_img, imgid, page + 1, max_pages, lang,
                        #     start_price, end_price, cat, sort, page_size, filter
                        # )
                        pass

                    return final_response

        except HTTPException:
            raise
        except Exception as e:
            print(f"Error querying upstream image search API: {e}")

    return final_response


@app.get("/items/{num_iid}", response_model=ItemDetailResponse, status_code=status.HTTP_200_OK)
async def get_item_detail(
    num_iid: int,
    lang: str = Query("en", description="Language of result")
):
    db = get_db()

    # 1. Check MongoDB cache first
    if db is not None:
        try:
            cached_doc = await db["product_details"].find_one({"num_iid": num_iid})
            if cached_doc:
                return cached_doc.get("raw_details")
        except Exception as db_err:
            print(f"MongoDB detail cache lookup failed: {db_err}")

    # 2. Cache miss — call 3rd party API
    if settings.api_key:
        url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_get&num_iid={num_iid}&lang={lang}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                data = res.json()

                if "error" in data:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Upstream API error: {data['error']}"
                    )

                if res.status_code == 200:
                    item_detail = data.get("item", {})
                    if item_detail:
                        final_detail_response = {"item": item_detail}
                        if db is not None:
                            try:
                                await db["product_details"].update_one(
                                    {"num_iid": num_iid},
                                    {
                                        "$set": {
                                            "num_iid": num_iid,
                                            "title": item_detail.get("title"),
                                            "price": item_detail.get("price"),
                                            "pic_url": item_detail.get("pic_url"),
                                            "cached_at": datetime.datetime.utcnow().isoformat(),
                                            "raw_details": final_detail_response
                                        }
                                    },
                                    upsert=True
                                )
                            except Exception as db_err:
                                print(f"MongoDB detail cache write failed: {db_err}")
                        return final_detail_response

        except HTTPException:
            raise
        except Exception as e:
            print(f"Error querying detail API: {e}")




























# import httpx
# import datetime
# from typing import Optional, List
# from contextlib import asynccontextmanager
# from fastapi import FastAPI, status, Query, BackgroundTasks

# from config import settings
# from database import db_helper, get_db
# from models import ItemListResponse, ItemDetailResponse


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Establish connection to MongoDB on startup
#     db_helper.connect()
#     yield
#     # Clean up connection on shutdown
#     db_helper.disconnect()

# app = FastAPI(
#     title="Product Aggregation API",
#     description="A proxy API for 1688 products with MongoDB caching.",
#     version="2.0.0",
#     lifespan=lifespan
# )

# @app.get("/", status_code=status.HTTP_200_OK)
# async def root():
#     return {
#         "message": "Welcome to the Product Aggregation API!",
#         "endpoints": {
#             "query_items": "/items?q=nikon&page=1&lang=en",
#             "item_details": "/items/{num_iid}"
#         },
#         "docs": "/docs"
#     }

# def get_search_tag(
#     base_tag: str,
#     start_price: Optional[float] = None,
#     end_price: Optional[float] = None,
#     cat: Optional[int] = None,
#     sort: Optional[str] = None,
#     page_size: Optional[int] = None,
#     filter_val: Optional[str] = None
# ) -> str:
#     parts = [base_tag.lower()]
#     if start_price is not None:
#         parts.append(f"sp:{start_price}")
#     if end_price is not None:
#         parts.append(f"ep:{end_price}")
#     if cat is not None:
#         parts.append(f"cat:{cat}")
#     if sort is not None:
#         parts.append(f"sort:{sort}")
#     if page_size is not None:
#         parts.append(f"ps:{page_size}")
#     if filter_val is not None:
#         parts.append(f"f:{filter_val}")
#     return "|".join(parts)


# def get_mongo_sort(sort: Optional[str]):
#     mongo_sort = []
#     if sort:
#         if sort == "sale":
#             mongo_sort.append(("sales", 1))
#         elif sort == "_sale":
#             mongo_sort.append(("sales", -1))
#         elif sort == "bid":
#             mongo_sort.append(("price", 1))
#         elif sort == "_bid":
#             mongo_sort.append(("price", -1))
#         elif sort == "credit":
#             mongo_sort.append(("tag_percent", 1))
#         elif sort == "_credit":
#             mongo_sort.append(("tag_percent", -1))
#         elif sort == "cached_at":
#             mongo_sort.append(("cached_at", 1))
#         elif sort == "_cached_at":
#             mongo_sort.append(("cached_at", -1))
#     return mongo_sort if mongo_sort else None


# def build_3rd_party_url(
#     base_url_type: str, # "item_search" or "item_search_img"
#     api_key: str,
#     q: Optional[str] = None,
#     imgid: Optional[str] = None,
#     page: int = 1,
#     lang: str = "en",
#     start_price: Optional[float] = None,
#     end_price: Optional[float] = None,
#     cat: Optional[int] = None,
#     sort: Optional[str] = None,
#     page_size: Optional[int] = None,
#     filter_val: Optional[str] = None
# ) -> str:
#     url = f"https://api.icom.la/1688/api/call.php?api_key={api_key}&{base_url_type}"
#     if q is not None:
#         url += f"&q={q}"
#     if imgid is not None:
#         url += f"&imgid={imgid}"
#     url += f"&page={page}&lang={lang}"

#     if start_price is not None:
#         url += f"&start_price={start_price}"
#     if end_price is not None:
#         url += f"&end_price={end_price}"
#     if cat is not None:
#         url += f"&cat={cat}"
#     if sort is not None and sort not in ("cached_at", "_cached_at"):
#         url += f"&sort={sort}"
#     if page_size is not None:
#         url += f"&page_size={page_size}"
#     if filter_val is not None:
#         url += f"&filter={filter_val}"
#     return url


# async def fetch_all_pages(
#     q: str, page: int, max_pages: int, lang: str,
#     start_price: Optional[float] = None,
#     end_price: Optional[float] = None,
#     cat: Optional[int] = None,
#     sort: Optional[str] = None,
#     page_size: Optional[int] = None,
#     filter_val: Optional[str] = None
# ):
#     if page > max_pages:
#         return

#     url = build_3rd_party_url(
#         "item_search", settings.api_key, q=q, page=page, lang=lang,
#         start_price=start_price, end_price=end_price, cat=cat, sort=sort,
#         page_size=page_size, filter_val=filter_val
#     )

#     try:
#         async with httpx.AsyncClient(timeout=30.0) as client:
#             response = await client.get(url)
#             if response.status_code == 200:
#                 data = response.json()
#                 items = data.get("items", {}).get("item", [])
#                 db = get_db()
#                 search_tag = get_search_tag(
#                     q, start_price, end_price, cat, sort, page_size, filter_val
#                 )
#                 for _item in items:

#                     num_iid = _item.get("num_iid")
#                     if num_iid and db is not None:
#                         await db["products_cache"].update_one(
#                             {"num_iid": num_iid},
#                             {
#                                 "$set": {
#                                     "num_iid": num_iid,
#                                     "title": _item.get("title"),
#                                     "price": _item.get("price"),
#                                     "pic_url": _item.get("pic_url"),
#                                     "detail_url": _item.get("detail_url"),
#                                     "promotion_price": _item.get("promotion_price"),
#                                     "sales": _item.get("sales", 0),
#                                     "tag_percent": _item.get("tag_percent", "0%"),
#                                     "cached_at": datetime.datetime.utcnow().isoformat()
#                                 },
#                                 "$addToSet": {
#                                     "search_tags": search_tag
#                                 }
#                             },
#                             upsert=True
#                         )
#     except httpx.TimeoutException:
#         print(f"Timeout on page {page}")
#     except httpx.HTTPStatusError as e:
#         print(f"HTTP error on page {page}: {e}")
#     except Exception as e:
#         print(f"Unexpected error on page {page}: {e}")

#     # Recursive case
#     await fetch_all_pages(
#         q, page + 1, max_pages, lang, start_price, end_price, cat, sort, page_size, filter_val
#     )


# async def fetch_all_pages_img(
#     img_url: str, page: int, max_pages: int, lang: str,
#     start_price: Optional[float] = None,
#     end_price: Optional[float] = None,
#     cat: Optional[int] = None,
#     sort: Optional[str] = None,
#     page_size: Optional[int] = None,
#     filter_val: Optional[str] = None
# ):
#     if page > max_pages:
#         print(f"Finished fetching all image pages (max: {max_pages})")
#         return

#     url = build_3rd_party_url(
#         "item_search_img", settings.api_key, imgid=img_url, page=page, lang=lang,
#         start_price=start_price, end_price=end_price, cat=cat, sort=sort,
#         page_size=page_size, filter_val=filter_val
#     )
#     print(f"Fetching image page {page}/{max_pages} --- {url}")

#     try:
#         async with httpx.AsyncClient(timeout=30.0) as client:
#             response = await client.get(url)
#             if response.status_code == 200:
#                 data = response.json()
#                 items = data.get("items", {}).get("item", [])
#                 db = get_db()
#                 search_tag = get_search_tag(
#                     img_url, start_price, end_price, cat, sort, page_size, filter_val
#                 )
#                 for _item in items:

#                     num_iid = _item.get("num_iid")
#                     if num_iid and db is not None:
#                         await db["products_cache"].update_one(
#                             {"num_iid": num_iid},
#                             {
#                                 "$set": {
#                                     "num_iid": num_iid,
#                                     "title": _item.get("title"),
#                                     "price": _item.get("price"),
#                                     "pic_url": _item.get("pic_url"),
#                                     "detail_url": _item.get("detail_url"),
#                                     "promotion_price": _item.get("promotion_price"),
#                                     "sales": _item.get("sales", 0),
#                                     "tag_percent": _item.get("tag_percent", "0%"),
#                                     "cached_at": datetime.datetime.utcnow().isoformat()
#                                 },
#                                 "$addToSet": {
#                                     "search_tags": search_tag
#                                 }
#                             },
#                             upsert=True
#                         )
#     except httpx.TimeoutException:
#         print(f"Timeout on image page {page}")
#     except httpx.HTTPStatusError as e:
#         print(f"HTTP error on image page {page}: {e}")
#     except Exception as e:
#         print(f"Unexpected error on image page {page}: {e}")

#     # Recursive case
#     await fetch_all_pages_img(
#         img_url, page + 1, max_pages, lang, start_price, end_price, cat, sort, page_size, filter_val
#     )


# @app.get("/items", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
# async def query_items(
#     background_tasks: BackgroundTasks,
#     q: str = Query("nikon", description="Search query"),
#     page: int = Query(1, ge=1, description="Page number"),
#     lang: str = Query("en", description="Language of result"),
#     start_price: Optional[float] = Query(None, description="Start price filter"),
#     end_price: Optional[float] = Query(None, description="End price filter"),
#     cat: Optional[int] = Query(None, description="Category ID filter"),
#     sort: Optional[str] = Query(None, description="Sort option: [bid, _bid, sale, _sale, credit, _credit, cached_at, _cached_at]"),
#     page_size: Optional[int] = Query(40, ge=1, description="Number of items per page"),
#     filter: Optional[str] = Query(None, description="Additional filter parameters e.g. filtId:1,2,3;city:Tianjin")
# ):
#     db = get_db()
#     search_tag = get_search_tag(
#         q, start_price, end_price, cat, sort, page_size, filter
#     )

#     limit_val = page_size if page_size is not None else 20
#     # 1. First, check if matching query data exists in MongoDB cache
#     cached_items = []
#     total_cached = 0
#     if db is not None:
#         total_cached = await db["products_cache"].count_documents({
#             "$or": [
#                 {"search_tag": search_tag},
#                 {"search_tags": search_tag}
#             ]
#         })
#         query_cursor = db["products_cache"].find({
#             "$or": [
#                 {"search_tag": search_tag},
#                 {"search_tags": search_tag}
#             ]
#         })
#         mongo_sort = get_mongo_sort(sort)
#         if mongo_sort:
#             query_cursor = query_cursor.sort(mongo_sort)
#         cursor = query_cursor.skip((page - 1) * limit_val).limit(limit_val)
#         async for doc in cursor:
#             cached_items.append({
#                 "title": doc.get("title"),
#                 "pic_url": doc.get("pic_url"),
#                 "price": doc.get("price"),
#                 "promotion_price": doc.get("promotion_price", doc.get("price")),
#                 "sales": doc.get("sales", 0),
#                 "num_iid": doc.get("num_iid"),
#                 "tag_percent": doc.get("tag_percent", "0%"),
#                 "detail_url": doc.get("detail_url")
#             })

#     if cached_items:
#         import math
#         page_count = math.ceil(total_cached / limit_val) if limit_val > 0 else 1
#         print(f"Returning cached search results for query '{q}' with tag '{search_tag}' from DB")
#         return {
#             "items": {
#                 "page": str(page),
#                 "real_total_results": total_cached,
#                 "total_results": total_cached,
#                 "page_size": limit_val,
#                 "page_count": page_count,
#                 "item": cached_items
#             },
#         }

#     # 2. If no data exists in DB, call the 3rd party URL
#     final_response = {
#         "items": {
#             "page": str(page),
#             "real_total_results": 0,
#             "total_results": 0,
#             "page_size": page_size,
#             "page_count": 1,
#             "item": []
#         },
#     }

#     if settings.api_key:
#         url = build_3rd_party_url(
#             "item_search", settings.api_key, q=q, page=page, lang=lang,
#             start_price=start_price, end_price=end_price, cat=cat, sort=sort,
#             page_size=page_size, filter_val=filter
#         )
#         print(f"Calling first page: {url}")

#         try:
#             async with httpx.AsyncClient(timeout=30.0) as client:
#                 res = await client.get(url)
#                 if res.status_code == 200:
#                     data = res.json()

#                     # Safely handle data elements
#                     items_data = data.get("items", {})
#                     items = items_data.get("item", [])

#                     for _item in items:

#                         # Save to MongoDB without raw_data key
#                         num_iid = _item.get("num_iid")
#                         if num_iid and db is not None:
#                             await db["products_cache"].update_one(
#                                 {"num_iid": num_iid},
#                                 {
#                                     "$set": {
#                                         "num_iid": num_iid,
#                                         "title": _item.get("title"),
#                                         "price": _item.get("price"),
#                                         "pic_url": _item.get("pic_url"),
#                                         "detail_url": _item.get("detail_url"),
#                                         "promotion_price": _item.get("promotion_price"),
#                                         "sales": _item.get("sales", 0),
#                                         "tag_percent": _item.get("tag_percent", "0%"),
#                                         "cached_at": datetime.datetime.utcnow().isoformat()
#                                     },
#                                     "$addToSet": {
#                                         "search_tags": search_tag
#                                     }
#                                 },
#                                 upsert=True
#                             )

#                     # Update final response
#                     if "items" in data:
#                         final_response["items"] = {
#                             "page": str(items_data.get("page", page)),
#                             "real_total_results": items_data.get("real_total_results", 0),
#                             "total_results": items_data.get("total_results", 0),
#                             "page_size": limit_val,
#                             "page_count": items_data.get("page_count", 1),
#                             "item": items[:limit_val]
#                         }

#                     max_pages = items_data.get("page_count", 1)
#                     if max_pages > page:
#                         background_tasks.add_task(
#                             fetch_all_pages, q, page + 1, max_pages, lang,
#                             start_price, end_price, cat, sort, page_size, filter
#                         )

#                     return final_response
#         except Exception as e:
#             print(f"Error querying 3rd party API: {e}")
#             pass

#     return final_response


# @app.get("/items/search-by-image", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
# @app.get("/item_search_img", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
# async def search_by_image(
#     background_tasks: BackgroundTasks,
#     imgid: str = Query(..., description="Image URL to search"),
#     page: int = Query(1, ge=1, description="Page number"),
#     lang: str = Query("zh-CN", description="Language of result"),
#     start_price: Optional[float] = Query(None, description="Start price filter"),
#     end_price: Optional[float] = Query(None, description="End price filter"),
#     cat: Optional[int] = Query(None, description="Category ID filter"),
#     sort: Optional[str] = Query(None, description="Sort option: [bid, _bid, sale, _sale, credit, _credit, cached_at, _cached_at]"),
#     page_size: Optional[int] = Query(40, ge=1, description="Number of items per page"),
#     filter: Optional[str] = Query(None, description="Additional filter parameters e.g. filtId:1,2,3;city:Tianjin")
# ):
#     db = get_db()
#     search_tag = get_search_tag(
#         imgid, start_price, end_price, cat, sort, page_size, filter
#     )

#     limit_val = page_size if page_size is not None else 20
#     # 1. First, check if matching query data exists in MongoDB cache
#     cached_items = []
#     total_cached = 0
#     if db is not None:
#         total_cached = await db["products_cache"].count_documents({
#             "$or": [
#                 {"search_tag": search_tag},
#                 {"search_tags": search_tag}
#             ]
#         })
#         query_cursor = db["products_cache"].find({
#             "$or": [
#                 {"search_tag": search_tag},
#                 {"search_tags": search_tag}
#             ]
#         })
#         mongo_sort = get_mongo_sort(sort)
#         if mongo_sort:
#             query_cursor = query_cursor.sort(mongo_sort)
#         cursor = query_cursor.skip((page - 1) * limit_val).limit(limit_val)
#         async for doc in cursor:
#             cached_items.append({
#                 "title": doc.get("title"),
#                 "pic_url": doc.get("pic_url"),
#                 "price": doc.get("price"),
#                 "promotion_price": doc.get("promotion_price", doc.get("price")),
#                 "sales": doc.get("sales", 0),
#                 "num_iid": doc.get("num_iid"),
#                 "tag_percent": doc.get("tag_percent", "0%"),
#                 "detail_url": doc.get("detail_url")
#             })

#     if cached_items:
#         import math
#         page_count = math.ceil(total_cached / limit_val) if limit_val > 0 else 1
#         print(f"Returning cached search results for image '{imgid}' with tag '{search_tag}' from DB")
#         return {
#             "items": {
#                 "page": str(page),
#                 "real_total_results": total_cached,
#                 "total_results": total_cached,
#                 "page_size": limit_val,
#                 "page_count": page_count,
#                 "item": cached_items
#             }
#         }

#     # 2. If no data exists in DB, call the 3rd party URL
#     final_response = {
#         "items": {
#             "page": str(page),
#             "real_total_results": 0,
#             "total_results": 0,
#             "page_size": page_size,
#             "page_count": 1,
#             "item": []
#         }
#     }

#     if settings.api_key:
#         url = build_3rd_party_url(
#             "item_search_img", settings.api_key, imgid=imgid, page=page, lang=lang,
#             start_price=start_price, end_price=end_price, cat=cat, sort=sort,
#             page_size=page_size, filter_val=filter
#         )
#         print(f"Calling image search first page: {url}")

#         try:
#             async with httpx.AsyncClient(timeout=30.0) as client:
#                 res = await client.get(url)
#                 if res.status_code == 200:
#                     data = res.json()

#                     # Safely handle data elements
#                     items_data = data.get("items", {})
#                     items = items_data.get("item", [])

#                     for _item in items:

#                         # Save to MongoDB without raw_data key
#                         num_iid = _item.get("num_iid")
#                         if num_iid and db is not None:
#                             await db["products_cache"].update_one(
#                                 {"num_iid": num_iid},
#                                 {
#                                     "$set": {
#                                         "num_iid": num_iid,
#                                         "title": _item.get("title"),
#                                         "price": _item.get("price"),
#                                         "pic_url": _item.get("pic_url"),
#                                         "detail_url": _item.get("detail_url"),
#                                         "promotion_price": _item.get("promotion_price"),
#                                         "sales": _item.get("sales", 0),
#                                         "tag_percent": _item.get("tag_percent", "0%"),
#                                         "cached_at": datetime.datetime.utcnow().isoformat()
#                                     },
#                                     "$addToSet": {
#                                         "search_tags": search_tag
#                                     }
#                                 },
#                                 upsert=True
#                             )

#                     # Update final response
#                     if "items" in data:
#                         final_response["items"] = {
#                             "page": str(items_data.get("page", page)),
#                             "real_total_results": items_data.get("real_total_results", 0),
#                             "total_results": items_data.get("total_results", 0),
#                             "page_size": limit_val,
#                             "page_count": items_data.get("page_count", 1),
#                             "item": items[:limit_val]
#                         }

#                     max_pages = items_data.get("page_count", 1)
#                     if max_pages > page:
#                         background_tasks.add_task(
#                             fetch_all_pages_img, imgid, page + 1, max_pages, lang,
#                             start_price, end_price, cat, sort, page_size, filter
#                         )

#                     return final_response
#         except Exception as e:
#             print(f"Error querying 3rd party image search API: {e}")
#             pass

#     return final_response


# @app.get("/items/{num_iid}", response_model=ItemDetailResponse, status_code=status.HTTP_200_OK)
# async def get_item_detail(
#     num_iid: int,
#     lang: str = Query("en", description="Language of result")
# ):
#     db = get_db()

#     # 1. First, check if product details exist in MongoDB cache
#     if db is not None:
#         cached_doc = await db["product_details"].find_one({"num_iid": num_iid})
#         if cached_doc:
#             print(f"Returning cached item details for num_iid={num_iid} from DB")
#             return cached_doc.get("raw_details")

#     # 2. If not found in cache, query 3rd party API
#     if settings.api_key:
#         url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_get&num_iid={num_iid}&lang={lang}"

#         try:
#             async with httpx.AsyncClient(timeout=30.0) as client:
#                 res = await client.get(url)
#                 if res.status_code == 200:
#                     data = res.json()
#                     item_detail = data.get("item", {})

#                     if item_detail:
#                         final_detail_response = {
#                             "item": item_detail
#                         }

#                         if db is not None:
#                             await db["product_details"].update_one(
#                                 {"num_iid": num_iid},
#                                 {
#                                     "$set": {
#                                         "num_iid": num_iid,
#                                         "title": item_detail.get("title"),
#                                         "price": item_detail.get("price"),
#                                         "pic_url": item_detail.get("pic_url"),
#                                         "cached_at": datetime.datetime.utcnow().isoformat(),
#                                         "raw_details": final_detail_response
#                                     }
#                                 },
#                                 upsert=True
#                             )
#                         return final_detail_response
#         except Exception as e:
#             print(f"Error querying detail API: {e}")
#             pass

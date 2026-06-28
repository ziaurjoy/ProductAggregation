import httpx
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, status, Query, BackgroundTasks

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

async def fetch_all_pages(q: str, page: int, max_pages: int, lang: str):
    if page > max_pages:
        print(f"Finished fetching all pages (max: {max_pages})")
        return

    url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_search&q={q}&page={page}&lang={lang}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", {}).get("item", [])
                db = get_db()
                for _item in items:
                    num_iid = _item.get("num_iid")
                    if num_iid and db is not None:
                        await db["products_cache"].update_one(
                            {"num_iid": num_iid},
                            {"$set": {
                                "num_iid": num_iid,
                                "title": _item.get("title"),
                                "price": _item.get("price"),
                                "pic_url": _item.get("pic_url"),
                                "detail_url": _item.get("detail_url"),
                                "promotion_price": _item.get("promotion_price"),
                                "sales": _item.get("sales", 0),
                                "tag_percent": _item.get("tag_percent", "0%"),
                                "cached_at": datetime.datetime.utcnow().isoformat(),
                                "search_tag": q.lower()
                            }},
                            upsert=True
                        )
    except httpx.TimeoutException:
        print(f"Timeout on page {page}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error on page {page}: {e}")
    except Exception as e:
        print(f"Unexpected error on page {page}: {e}")

    # Recursive case
    await fetch_all_pages(q, page + 1, max_pages, lang)


@app.get("/items", response_model=ItemListResponse, status_code=status.HTTP_200_OK)
async def query_items(
    background_tasks: BackgroundTasks,
    q: str = Query("nikon", description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    lang: str = Query("en", description="Language of result")
):
    db = get_db()

    # 1. First, check if matching query data exists in MongoDB cache
    cached_items = []
    if db is not None:
        cursor = db["products_cache"].find({"search_tag": q.lower()}).skip((page - 1) * 40).limit(40)
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

    if cached_items:
        return {
            "items": {
                "page": str(page),
                "real_total_results": len(cached_items),
                "total_results": len(cached_items),
                "page_size": 40,
                "page_count": 1,
                "item": cached_items
            },
        }

    # 2. If no data exists in DB, call the 3rd party URL
    final_response = {
        "items": {
            "page": str(page),
            "real_total_results": 0,
            "total_results": 0,
            "page_size": 40,
            "page_count": 1,
            "item": []
        },
    }

    if settings.api_key:
        url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_search&q={q}&page={page}&lang={lang}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()

                    # Safely handle data elements
                    items_data = data.get("items", {})
                    items = items_data.get("item", [])

                    for _item in items:
                        # Save to MongoDB without raw_data key
                        num_iid = _item.get("num_iid")
                        if num_iid and db is not None:
                            await db["products_cache"].update_one(
                                {"num_iid": num_iid},
                                {"$set": {
                                    "num_iid": num_iid,
                                    "title": _item.get("title"),
                                    "price": _item.get("price"),
                                    "pic_url": _item.get("pic_url"),
                                    "detail_url": _item.get("detail_url"),
                                    "promotion_price": _item.get("promotion_price"),
                                    "sales": _item.get("sales", 0),
                                    "tag_percent": _item.get("tag_percent", "0%"),
                                    "cached_at": datetime.datetime.utcnow().isoformat(),
                                    "search_tag": q.lower()
                                }},
                                upsert=True
                            )

                    # Update final response
                    if "items" in data:
                        final_response["items"] = {
                            "page": str(items_data.get("page", page)),
                            "real_total_results": items_data.get("real_total_results", 0),
                            "total_results": items_data.get("total_results", 0),
                            "page_size": items_data.get("page_size", 40),
                            "page_count": items_data.get("page_count", 1),
                            "item": items
                        }


                    max_pages = items_data.get("page_count", 1)
                    if max_pages > page:
                        background_tasks.add_task(fetch_all_pages, q, page + 1, max_pages, lang)

                    return final_response
        except Exception as e:
            print(f"Error querying 3rd party API: {e}")
            pass


@app.get("/items/{num_iid}", response_model=ItemDetailResponse, status_code=status.HTTP_200_OK)
async def get_item_detail(
    num_iid: int,
    lang: str = Query("en", description="Language of result")
):
    db = get_db()

    # 1. First, check if product details exist in MongoDB cache
    if db is not None:
        cached_doc = await db["product_details"].find_one({"num_iid": num_iid})
        if cached_doc:
            return cached_doc.get("raw_details")

    # 2. If not found in cache, query 3rd party API
    if settings.api_key:
        url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_get&num_iid={num_iid}&lang={lang}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                # if True:
                    data = res.json()
                    item_detail = data.get("item", {})

                    if item_detail:

                        final_detail_response = {
                            "item": item_detail
                        }

                        if db is not None:
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
                        return final_detail_response
        except Exception as e:
            print(f"Error querying detail API: {e}")
            pass






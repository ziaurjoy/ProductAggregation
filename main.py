import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Query
import httpx
from typing import List, Optional
from fastapi import BackgroundTasks
from config import settings
from database import db_helper, get_db
from models import ItemListResponse, ItemDetailResponse

# --- Mock/Fallback Data in case 3rd party API call fails ---
MOCK_ITEMS_RESPONSE = {
  "items": {
    "page": "1",
    "real_total_results": 2000,
    "total_results": 2000,
    "page_size": 40,
    "page_count": 51,
    "item": [
      {
        "title": "Chinese Version Digital Camera Coolpix P1100 with Dual Vr Shock Stabilization and 125X Zoom Telephoto Camera for Bird Photography",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01cGmO5W1ey7AJl1dqd_!!1877763939-0-cib.jpg",
        "price": 6990.0,
        "promotion_price": 6990.0,
        "sales": 1,
        "num_iid": 1040419053367,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/1040419053367.html"
      },
      {
        "title": "Chinese Version D7500 Kit 18-200 Vr Ii High-Definition Digital Camera for Live Streaming and Professional Travel Photography",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01v5vCs21ey72znIiAu_!!1877763939-0-cib.jpg",
        "price": 5180.0,
        "promotion_price": 5180.0,
        "sales": 0,
        "num_iid": 1038868103579,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/1038868103579.html"
      },
      {
        "title": "420-800mm F8.3 Telephoto Lens Manual Focus Telephoto Mirrorless Full-Frame Slr Telephoto Lens",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01hULXzB1zFKPZzhZrm_!!2220367276684-0-cib.jpg",
        "price": 246.28,
        "promotion_price": 246.28,
        "sales": 0,
        "num_iid": 999526505291,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/999526505291.html"
      },
      {
        "title": "9 Viltrox 35Mmf1.8 Z-Mount Lens Full-Frame Z5 Z6 Zfc Camera Lens Autofocus",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01cK8WHi1d4PQ3sbxm9_!!2212791833682-0-cib.jpg",
        "price": 1799.0,
        "promotion_price": 1799.0,
        "sales": 0,
        "num_iid": 995877748672,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/995877748672.html"
      },
      {
        "title": "Cheka 25mmF1.8 half frame fixed focus micro single lens for Sony Canon Fuji Nikon Panasonic camera",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN014bbreE1pzRyW0KUDl_!!2216621885431-0-cib.jpg",
        "price": 378.0,
        "promotion_price": 378.0,
        "sales": 0,
        "num_iid": 779976064683,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/779976064683.html"
      },
      {
        "title": "Spot genuine D7200 D7500 SLR camera 18-140 18-200 anti-shake lens",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01KRV4BS1VLnKUYhxMm_!!2211931562637-0-cib.jpg",
        "price": 4399.0,
        "promotion_price": 4399.0,
        "sales": 0,
        "num_iid": 647164141078,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/647164141078.html"
      },
      {
        "title": "Camera Pan-Focus Lens Nikon Z Oral Suitable for Nikon All Z Port Micro Semi-Full-Frame Universal Leo",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN017CUO0v1b2ulIm6y6B_!!2218171243408-0-cib.jpg",
        "price": 68.0,
        "promotion_price": 68.0,
        "sales": 74,
        "num_iid": 811344271032,
        "tag_percent": "40%",
        "detail_url": "https://detail.1688.com/offer/811344271032.html"
      },
      {
        "title": "Yongnuo YN 35mm F2 suitable for Nikon F-Port full-frame SLR camera automatic fixed focus lens",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01ZhhOO81Bs2uvcaeRh_!!0-0-cib.jpg",
        "price": 556.0,
        "promotion_price": 556.0,
        "sales": 1,
        "num_iid": 670708148135,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/670708148135.html"
      },
      {
        "title": "55MM 2X distance increasing lens additional lens suitable for Pentax Nikon Sony 18-55 lens",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01tUhAFQ1Bs2uupBBO0_!!0-0-cib.jpg",
        "price": 35.0,
        "promotion_price": 35.0,
        "sales": 3,
        "num_iid": 557254146279,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/557254146279.html"
      },
      {
        "title": "Viltrox Af 85mm F1.8Ii Xf Automatic Lens Is Compatible with Fujifilm Xf Mount",
        "pic_url": "https://cbu01.alicdn.com/img/ibank/O1CN01doZMFj2Cp8PAuStds_!!2222264578522-0-cib.jpg",
        "price": 1699.0,
        "promotion_price": 1699.0,
        "sales": 0,
        "num_iid": 1041663700490,
        "tag_percent": "0%",
        "detail_url": "https://detail.1688.com/offer/1041663700490.html"
      }
    ]
  },
}

MOCK_DETAILS_RESPONSE = {
  "item": {
    "num_iid": 582896733162,
    "title": "FOR Nikon Nikon D7500 SLR Camera Silicone Case d7500 D7000 Silicone Protective Case Camera Bag",
    "desc_short": "FOR Nikon Nikon D7500 SLR Camera Silicone Case d7500 D7000 Silicone Protective Case Camera Bag",
    "price": 35.0,
    "total_price": 0.0,
    "suggestive_price": 0.0,
    "orginal_price": 35.0,
    "nick": "_sopid@BBBZN7gpraGZX_6szb3-TE5tA",
    "num": 7288,
    "min_num": 3,
    "detail_url": "https://detail.1688.com/offer/582896733162.html",
    "pic_url": "https://img.dev.1buyo.com/img/ibank/9844043716_529504497.jpg",
    "brand": "",
    "brandId": "",
    "rootCatId": 0,
    "cid": 1036596,
    "crumbs": [],
    "created_time": "",
    "modified_time": "",
    "delist_time": "",
    "desc": "<div id=\"offer-template-0\"></div><p><strong><span style=\"font-size: 22.0pt;\">适用型号：尼康D7500相机（任何镜头）</span></strong></p>\r\n<p><strong><span style=\"font-size: 22.0pt;\">颜 &nbsp; &nbsp; &nbsp;色：黑色，迷彩，红色，黄色（如图）</span></strong></p>",
    "desc_img": [
      "https://img.dev.1buyo.com/img/ibank/2018/617/340/9844043716_529504497.jpg"
    ],
    "item_imgs": [
      {"url": "https://img.dev.1buyo.com/img/ibank/9844043716_529504497.jpg"}
    ],
    "item_weight": "1000",
    "item_size": "",
    "location": "广东省深圳市",
    "post_fee": "",
    "express_fee": 0.0,
    "ems_fee": "",
    "shipping_to": "",
    "has_discount": "",
    "video": None,
    "is_virtual": "",
    "sample_id": "",
    "is_promotion": "",
    "props_name": "0:0:Color:D7500 camouflage/camouflage",
    "prop_imgs": {
      "prop_img": [
        {"properties": "0:0", "url": "https://img.dev.1buyo.com/img/ibank/9820705794_529504497.jpg"}
      ]
    },
    "property_alias": "0:0:Color:D7500 camouflage/camouflage",
    "props": [
      {"name": "Item No.", "value": "D7500"},
      {"name": "Material", "value": "Silicone"}
    ],
    "total_sold": 7288,
    "skus": {
      "sku": [
        {"price": 35, "total_price": 35, "batch_price": 35, "orginal_price": 35, "onepiece_price": "35", "properties": "0:0", "properties_name": "0:0:Color:D7500 camouflage/camouflage", "quantity": 866, "sku_id": 4531173224811, "spec_id": "bcf7d2c191158d1758f93407952c94e1"}
      ]
    },
    "seller_id": None,
    "sales": 0,
    "shop_id": None,
    "props_list": {
      "0:0": "Color:D7500 camouflage/camouflage"
    },
    "seller_info": {
      "nick": "_sopid@BBBZN7gpraGZX_6szb3-TE5tA",
      "user_num_id": "",
      "sid": "",
      "title": "",
      "shop_name": "",
      "item_score": "3.6",
      "score_p": "3.6",
      "consult_score": "4.0",
      "delivery_score": "4.0",
      "composite_score": "4.5",
      "zhuy": "https://detail.1688.com/offer/582896733162.html?kjSource=pc"
    },
    "tmall": "false",
    "warning": "",
    "url_log": [],
    "batch_price": "35.0",
    "unit": "个",
    "is_support_mix": None,
    "mix_amount": None,
    "mix_begin": None,
    "mix_number": None,
    "scale": 1,
    "priceRange": [[3, 35], [50, 30], [1000, 25]],
    "priceRangeOriginal": [],
    "cn_source": {
      "item": {
        "cn_props_list": {
          "0:0": "颜色:D7500迷彩/camouflage"
        },
        "cn_title": "FOR尼康Nikon D7500单反相机硅胶套d7500 D7000硅胶保护套相机包",
        "skus": [
          {"price": 35, "total_price": 35, "batch_price": 35, "orginal_price": 35, "onepiece_price": "35", "properties": "0:0", "properties_name": "0:0:颜色:D7500迷彩/camouflage", "quantity": 866, "sku_id": 4531173224811, "spec_id": "bcf7d2c191158d1758f93407952c94e1"}
        ]
      },
      "volume": 0,
      "sales_info": {
        "sku_shipping_list": None,
        "seller_num": "",
        "repeat_rate_purchase": "",
        "per_capita_purchases": "",
        "comment_num": "",
        "comment_url": ""
      },
      "props_img": {
        "0:0": "https://img.dev.1buyo.com/img/ibank/9820705794_529504497.jpg"
      },
      "format_check": "ok",
      "shop_item": [],
      "relate_items": [],
      "cn_title": "FOR Nikon Nikon D7500 SLR Camera Silicone Case d7500 D7000 Silicone Protective Case Camera Bag",
      "cn_props_list": {
        "0:0": "Color:D7500 camouflage/camouflage"
      },
      "cn_skus": {
        "sku": [
          {"price": 35, "total_price": 35, "batch_price": 35, "orginal_price": 35, "onepiece_price": "35", "properties": "0:0", "properties_name": "0:0:Color:D7500 camouflage/camouflage", "quantity": 866, "sku_id": 4531173224811, "spec_id": "bcf7d2c191158d1758f93407952c94e1"}
        ]
      },
      "weight": "1000",
      "goodstype": 0,
      "goods_id": 582896733162
    },
    "weight": "1000",
    "goodstype": 0,
    "goods_id": 582896733162
  },
}

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
    print(f"Fetching page {page}/{max_pages} --- {url}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", {}).get("item", [])
                db = get_db()
                for _item in items:
                    print('===============')
                    print(_item)
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
        cursor = db["products_cache"].find({"title": {"$regex": q.lower(), "$options": "i"}}).skip((page - 1) * 40).limit(40)
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
        print(f"Returning cached search results for query '{q}' from DB")
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
        print(f"Calling first page: {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()

                    # Safely handle data elements
                    items_data = data.get("items", {})
                    items = items_data.get("item", [])

                    for _item in items:
                        print('===============')
                        print(_item)
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

    # If everything fails, use static mock items data
    return MOCK_ITEMS_RESPONSE


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
            print(f"Returning cached item details for num_iid={num_iid} from DB")
            return cached_doc.get("raw_details")

    # 2. If not found in cache, query 3rd party API
    if settings.api_key:
        url = f"https://api.icom.la/1688/api/call.php?api_key={settings.api_key}&item_get&num_iid={num_iid}&lang={lang}"
        print(f"Calling detail URL: {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                # if True:
                    data = res.json()
                    # data = MOCK_DETAILS_RESPONSE
                    item_detail = data.get("item", {})

                    if item_detail:
                        print('===============')
                        print(item_detail)

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






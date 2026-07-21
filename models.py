from typing import Annotated, Any, Dict, List, Optional
from pydantic import BaseModel, Field, BeforeValidator

# Custom type to convert MongoDB ObjectId to string
PyObjectId = Annotated[str, BeforeValidator(str)]

class ApiLimit(BaseModel):
    limit_type: str
    limit_type_label: str
    unlimited: bool
    call_limit: Optional[int] = None
    calls_made: int
    remaining_calls: Optional[int] = None
    status: str

class ItemSummary(BaseModel):
    title: Optional[Any] = None
    pic_url: Optional[Any] = None
    price: Optional[Any] = None
    promotion_price: Optional[Any] = None
    sales: Optional[Any] = 0
    num_iid: Any
    tag_percent: Optional[Any] = "0%"
    detail_url: Optional[Any] = ""

class ItemListContainer(BaseModel):
    page: Optional[Any] = None
    real_total_results: Optional[Any] = None
    total_results: Optional[Any] = None
    page_size: Optional[Any] = None
    page_count: Optional[Any] = None
    item: List[ItemSummary]

class ItemListResponse(BaseModel):
    items: ItemListContainer

class ItemDetail(BaseModel):
    num_iid: Any
    title: Optional[Any] = None
    desc_short: Optional[Any] = None
    price: Optional[Any] = None
    total_price: Optional[Any] = None
    suggestive_price: Optional[Any] = None
    orginal_price: Optional[Any] = None
    nick: Optional[Any] = None
    num: Optional[Any] = None
    min_num: Optional[Any] = None
    detail_url: Optional[Any] = None
    pic_url: Optional[Any] = None
    brand: Optional[Any] = None
    brandId: Optional[Any] = None
    rootCatId: Optional[Any] = None
    cid: Optional[Any] = None
    crumbs: Optional[Any] = None
    created_time: Optional[Any] = None
    modified_time: Optional[Any] = None
    delist_time: Optional[Any] = None
    desc: Optional[Any] = None
    desc_img: Optional[Any] = None
    item_imgs: Optional[Any] = None
    item_weight: Optional[Any] = None
    item_size: Optional[Any] = None
    location: Optional[Any] = None
    post_fee: Optional[Any] = None
    express_fee: Optional[Any] = None
    ems_fee: Optional[Any] = None
    shipping_to: Optional[Any] = None
    has_discount: Optional[Any] = None
    video: Optional[Any] = None
    is_virtual: Optional[Any] = None
    sample_id: Optional[Any] = None
    is_promotion: Optional[Any] = None
    props_name: Optional[Any] = None
    prop_imgs: Optional[Any] = None
    property_alias: Optional[Any] = None
    props: Optional[Any] = None
    total_sold: Optional[Any] = None
    skus: Optional[Any] = None
    seller_id: Optional[Any] = None
    sales: Optional[Any] = None
    shop_id: Optional[Any] = None
    props_list: Optional[Any] = None
    seller_info: Optional[Any] = None
    tmall: Optional[Any] = None
    warning: Optional[Any] = None
    url_log: Optional[Any] = None
    batch_price: Optional[Any] = None
    unit: Optional[Any] = None
    is_support_mix: Optional[Any] = None
    mix_amount: Optional[Any] = None
    mix_begin: Optional[Any] = None
    mix_number: Optional[Any] = None
    scale: Optional[Any] = None
    priceRange: Optional[Any] = None
    priceRangeOriginal: Optional[Any] = None
    cn_source: Optional[Any] = None
    weight: Optional[Any] = None
    goodstype: Optional[Any] = None
    goods_id: Optional[Any] = None

class ItemDetailResponse(BaseModel):
    item: ItemDetail

class Seller(BaseModel):
    title: Optional[str] = None
    desc: Optional[str] = None
    detail: Optional[List[Dict[str, List[Dict[str, str]]]]] = None

class SellerResponse(BaseModel):
    seller: Seller

# MongoDB schema representation for product logs/cache
class ProductCacheDB(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    num_iid: Any
    title: Optional[Any] = None
    price: Optional[Any] = None
    pic_url: Optional[Any] = None
    detail_url: Optional[Any] = None
    cached_at: Optional[Any] = None
    search_tag: Optional[Any] = None
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


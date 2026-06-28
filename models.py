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
    title: str
    pic_url: str
    price: float
    promotion_price: float
    sales: int
    num_iid: int
    tag_percent: str
    detail_url: str

class ItemListContainer(BaseModel):
    page: str
    real_total_results: int
    total_results: int
    page_size: int
    page_count: int
    item: List[ItemSummary]

class ItemListResponse(BaseModel):
    items: ItemListContainer

class ItemDetail(BaseModel):
    num_iid: int
    title: str
    desc_short: Optional[str] = None
    price: float
    total_price: Optional[float] = 0.0
    suggestive_price: Optional[float] = 0.0
    orginal_price: Optional[float] = 0.0
    nick: Optional[str] = None
    num: Optional[int] = 0
    min_num: Optional[int] = 1
    detail_url: str
    pic_url: str
    brand: Optional[Any] = ""
    brandId: Optional[Any] = ""
    rootCatId: Optional[int] = 0
    cid: Optional[int] = 0
    crumbs: Optional[Any] = []
    created_time: Optional[str] = ""
    modified_time: Optional[str] = ""
    delist_time: Optional[str] = ""
    desc: Optional[str] = ""
    desc_img: Optional[Any] = []
    item_imgs: Optional[Any] = []
    item_weight: Optional[str] = ""
    item_size: Optional[str] = ""
    location: Optional[str] = ""
    post_fee: Optional[str] = ""
    express_fee: Optional[float] = 0.0
    ems_fee: Optional[str] = ""
    shipping_to: Optional[str] = ""
    has_discount: Optional[str] = ""
    video: Optional[Any] = None
    is_virtual: Optional[str] = ""
    sample_id: Optional[str] = ""
    is_promotion: Optional[str] = ""
    props_name: Optional[Any] = ""
    prop_imgs: Optional[Any] = {}
    property_alias: Optional[Any] = ""
    props: Optional[Any] = []
    total_sold: Optional[int] = 0
    skus: Optional[Any] = {}
    seller_id: Optional[Any] = None
    sales: Optional[int] = 0
    shop_id: Optional[Any] = None
    props_list: Optional[Any] = {}
    seller_info: Optional[Any] = {}
    tmall: Optional[str] = "false"
    warning: Optional[str] = ""
    url_log: Optional[Any] = []
    batch_price: Optional[str] = ""
    unit: Optional[str] = ""
    is_support_mix: Optional[bool] = None
    mix_amount: Optional[float] = None
    mix_begin: Optional[int] = None
    mix_number: Optional[int] = None
    scale: Optional[int] = 1
    priceRange: Optional[Any] = []
    priceRangeOriginal: Optional[Any] = []
    cn_source: Optional[Any] = {}
    weight: Optional[str] = ""
    goodstype: Optional[int] = 0
    goods_id: Optional[Any] = 0

class ItemDetailResponse(BaseModel):
    item: ItemDetail

# MongoDB schema representation for product logs/cache
class ProductCacheDB(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    num_iid: int
    title: str
    price: float
    pic_url: str
    detail_url: str
    cached_at: Optional[str] = None
    search_tag: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True

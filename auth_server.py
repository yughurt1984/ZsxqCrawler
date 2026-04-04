"""
认证代理网关 - auth_server.py
独立运行在 :8209，将请求转发到 main.py:8208
提供用户注册/登录、权限控制、隔日查看等功能

启动方式: python auth_server.py
"""

import os
import re
import json
import sqlite3
import threading
from datetime import datetime, timedelta, date
from typing import Optional
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field, field_validator
from jose import JWTError, jwt
from passlib.context import CryptContext

from fastapi.staticfiles import StaticFiles
from pathlib import Path

# =========================
# 配置
# =========================

AUTH_PORT = int(os.environ.get("AUTH_PORT", "8209"))
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://localhost:8208").rstrip("/")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-default-secret-key-2026")
TOKEN_EXPIRE_DAYS = int(os.environ.get("TOKEN_EXPIRE_DAYS", "30"))
DB_PATH = os.environ.get("AUTH_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.db"))

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# =========================
# 数据库
# =========================

_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema():
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                access_mode TEXT NOT NULL DEFAULT 'free',   
                expire_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS group_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                granted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(user_id, group_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


_ensure_schema()


# =========================
# 工具函数
# =========================

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(user_id: int, username: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire},
        JWT_SECRET,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None


def is_today(time_str: str) -> bool:
    """判断时间字符串是否是今天（本地时间）"""
    if not time_str:
        return False
    try:
        # 尝试多种时间格式
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                dt = datetime.strptime(time_str, fmt)
                return dt.date() == date.today()
            except ValueError:
                continue
        return False
    except Exception:
        return False

def is_within_days(time_str: str, days: int) -> bool:
    """判断时间字符串是否在指定天数内（本地时间）"""
    if not time_str:
        return False
    try:
        # 去掉时区部分（简单处理）
        if '+' in time_str:
            time_str = time_str.split('+')[0]
        elif time_str.count('-') > 2:  # 检查是否有时区偏移
            time_str = time_str.rsplit('-', 1)[0]
        
        # 尝试多种时间格式
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",        # 带毫秒
            "%Y-%m-%dT%H:%M:%S",           # 标准
            "%Y-%m-%d %H:%M:%S",           # 空格分隔
        ):
            try:
                dt = datetime.strptime(time_str, fmt)
                return (datetime.now() - dt).days < days
            except ValueError:
                continue
        return False
    except Exception:
        return False

def is_expired(expire_at: str | None) -> bool:
    """检查授权是否已过期"""
    if not expire_at:
        return True  # 没有到期日，视为已过期
    try:
        expire_date = datetime.strptime(expire_at, "%Y-%m-%d").date()
        return expire_date < date.today()  # 已过期
    except Exception:
        return True  # 解析失败，视为已过期

def get_user_allowed_groups(user_id: int) -> dict:
    """获取用户有权限的群组及其到期日和加入时间"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT group_id, expire_at, granted_at FROM group_permissions WHERE user_id = ?", 
            (user_id,)
        ).fetchall()
        # 返回 {group_id: {"expiry": expire_at, "joined": granted_at}} 的映射
        return {
            r["group_id"]: {
                "expiry": r["expire_at"],
                "joined": r["granted_at"]
            } 
            for r in rows
        }
    finally:
        conn.close()


def get_user_from_token(token: str) -> Optional[dict]:
    """从 Token 获取用户完整信息"""
    payload = decode_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not row:
            return None
        user = dict(row)
        
        # 附加权限列表
        user["allowed_groups"] = get_user_allowed_groups(user["id"])
        return user
    finally:
        conn.close()


def extract_group_id(path: str) -> Optional[int]:
    """从 URL 路径中提取 group_id"""
    # 匹配 /api/groups/{group_id}/... 或 /api/topics/{topic_id}/{group_id}
    m = re.search(r'/api/groups/(\d+)', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/topics/\d+/(\d+)', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/files/(\d+)', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/cache/images/info/(\d+)', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/cache/images/(\d+)', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/groups/(\d+)/images/', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/groups/(\d+)/videos/', path)
    if m:
        return int(m.group(1))
    m = re.search(r'/api/crawl/scheduled/(\d+)', path)
    if m:
        return int(m.group(1))
    return None


# =========================
# Pydantic 模型
# =========================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., description="邮箱")
    phone: Optional[str] = Field(None, description="手机号")
    password: str = Field(..., min_length=6)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    id: int
    username: str
    email: str
    phone: str
    access_mode: str
    created_at: str
    allowed_groups: dict  # 改为 dict，key 是 group_id，value 是到期日

# =========================
# 群组商品相关模型
# =========================

class GroupProductCreate(BaseModel):
    group_id: int = Field(..., description="群组ID")
    name: str = Field(..., min_length=1, max_length=100)
    price_monthly: float = Field(default=0, ge=0)
    price_quarterly: Optional[float] = Field(None, ge=0)
    price_yearly: Optional[float] = Field(None, ge=0)
    original_price: Optional[float] = Field(None, ge=0)
    is_visible: bool = Field(default=True)
    cover_image: Optional[str] = None


class GroupProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    price_monthly: Optional[float] = Field(None, ge=0)
    price_quarterly: Optional[float] = Field(None, ge=0)
    price_yearly: Optional[float] = Field(None, ge=0)
    original_price: Optional[float] = Field(None, ge=0)
    is_visible: Optional[bool] = None
    cover_image: Optional[str] = None


class GroupProductResponse(BaseModel):
    id: int
    group_id: int
    name: str
    price_monthly: float
    price_quarterly: Optional[float]
    price_yearly: Optional[float]
    original_price: Optional[float]
    is_visible: bool
    cover_image: Optional[str]
    created_at: str


class OrderCreate(BaseModel):
    group_id: int
    subscription_type: str = Field(..., pattern="^(monthly|quarterly|yearly|permanent)$")

# =========================
# FastAPI 应用
# =========================

app = FastAPI(title="认证网关", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建图片目录
IMAGES_DIR = Path(__file__).parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)


# 挂载静态文件目录（让图片可通过URL访问）
app.mount("/static/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

# =========================
# 图片代理 API（解决 CORS 问题）
# =========================

@app.get("/api/image/{filename}")
async def proxy_image(filename: str):
    """图片代理接口，用于解决跨域问题"""
    file_path = IMAGES_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    
    # 安全检查：确保文件在允许的目录内
    try:
        file_path.resolve().relative_to(IMAGES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="禁止访问")
    
    # 根据文件扩展名确定 Content-Type
    ext = file_path.suffix.lower()
    content_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    content_type = content_types.get(ext, 'application/octet-stream')
    
    # 读取文件内容
    with open(file_path, 'rb') as f:
        content = f.read()
    
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "public, max-age=86400"  # 缓存1天
        }
    )


@app.options("/api/image/{filename}")
async def proxy_image_options(filename: str):
    """处理 CORS 预检请求"""
    return Response(
        content="",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*"
        }
    )

# =========================
# 图片管理 API
# =========================

@app.get("/api/admin/images")
async def list_images():
    """获取服务器图片列表（管理员功能）"""
    # TODO: 添加管理员权限检查
    
    try:
        images = []
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        
        for file_path in IMAGES_DIR.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in allowed_extensions:
                stat = file_path.stat()
                images.append({
                    "filename": file_path.name,
                    "url": f"/static/images/{file_path.name}",
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
                })
        
        # 按创建时间倒序排列
        images.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {"images": images, "total": len(images)}
    except Exception as e:
        raise HTTPException(500, f"获取图片列表失败: {str(e)}")



# =========================
# 群组商品管理 API（管理员）
# =========================

@app.post("/api/admin/group-products", response_model=GroupProductResponse)
async def create_group_product(req: GroupProductCreate, request: Request):
    """创建群组商品"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            """INSERT INTO group_products 
               (group_id, name, price_monthly, price_quarterly, price_yearly, 
                original_price, is_visible, cover_image, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (req.group_id, req.name, req.price_monthly, 
             req.price_quarterly, req.price_yearly, req.original_price, 
             req.is_visible, req.cover_image, now)
        )
        conn.commit()
        product_id = cursor.lastrowid
        
        # 返回创建的记录
        row = conn.execute("SELECT * FROM group_products WHERE id = ?", (product_id,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"群组 {req.group_id} 已存在商品记录")
    except Exception as e:
        raise HTTPException(500, f"创建失败: {str(e)}")
    finally:
        conn.close()


@app.get("/api/admin/group-products")
async def list_all_group_products(request: Request):
    """获取所有群组商品（管理用，包含隐藏的）"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM group_products ORDER BY created_at DESC"
        ).fetchall()
        return {"products": [dict(r) for r in rows], "total": len(rows)}
    finally:
        conn.close()


@app.get("/api/admin/group-products/{group_id}", response_model=GroupProductResponse)
async def get_group_product(group_id: int, request: Request):
    """获取单个群组商品详情"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM group_products WHERE group_id = ?", (group_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "群组商品不存在")
        return dict(row)
    finally:
        conn.close()


@app.put("/api/admin/group-products/{group_id}", response_model=GroupProductResponse)
async def update_group_product(group_id: int, req: GroupProductUpdate, request: Request):
    """更新群组商品"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        # 检查是否存在
        existing = conn.execute(
            "SELECT * FROM group_products WHERE group_id = ?", (group_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "群组商品不存在")
        
        # 构建更新语句
        updates = []
        values = []
        for field in ["name", "description", "price_monthly", "price_quarterly", 
                      "price_yearly", "original_price", "is_visible", "cover_image"]:
            value = getattr(req, field, None)
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        
        if not updates:
            return dict(existing)
        
        values.append(group_id)
        
        conn.execute(
            f"UPDATE group_products SET {', '.join(updates)} WHERE group_id = ?",
            values
        )
        conn.commit()
        
        # 返回更新后的记录
        row = conn.execute(
            "SELECT * FROM group_products WHERE group_id = ?", (group_id,)
        ).fetchone()
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"更新失败: {str(e)}")
    finally:
        conn.close()


@app.delete("/api/admin/group-products/{group_id}")
async def delete_group_product(group_id: int, request: Request):
    """删除群组商品"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        result = conn.execute(
            "DELETE FROM group_products WHERE group_id = ?", (group_id,)
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "群组商品不存在")
        return {"success": True, "message": f"已删除群组 {group_id} 的商品记录"}
    finally:
        conn.close()

# =========================
# 用户端群组商品 API
# =========================

@app.get("/api/groups/products")
async def get_visible_group_products(request: Request):
    """获取可购买的群组列表（用户端，只显示 is_visible=1）"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT group_id, name, price_monthly, price_quarterly, 
                      price_yearly, original_price, cover_image
               FROM group_products 
               WHERE is_visible = 1 
               ORDER BY created_at DESC"""
        ).fetchall()
        return {"products": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/groups/products/{group_id}")
async def get_group_product_detail(group_id: int, request: Request):
    """获取群组商品详情（用户端）"""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT group_id, name, price_monthly, price_quarterly, 
                      price_yearly, original_price, cover_image
               FROM group_products 
               WHERE group_id = ? AND is_visible = 1""",
            (group_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "群组商品不存在或已下架")
        return dict(row)
    finally:
        conn.close()


# =========================
# 订单 API
# =========================

class OrderResponse(BaseModel):
    order_id: str
    group_id: int
    group_name: str
    subscription_type: str
    amount: float
    status: str
    created_at: str


@app.post("/api/orders/create", response_model=OrderResponse)
async def create_order(req: OrderCreate, request: Request):
    """创建订单"""
    user = _authenticate(request)
    if not user:
        raise HTTPException(401, "未登录")
    
    conn = _get_conn()
    try:
        # 1. 获取群组价格
        product = conn.execute(
            "SELECT * FROM group_products WHERE group_id = ? AND is_visible = 1",
            (req.group_id,)
        ).fetchone()
        if not product:
            raise HTTPException(404, "群组商品不存在或已下架")
        
        # 2. 计算金额
        price_map = {
            "monthly": product["price_monthly"],
            "quarterly": product["price_quarterly"],
            "yearly": product["price_yearly"],
            "permanent": product["price_yearly"] * 3 if product["price_yearly"] else 0,  # 永久=3年
        }
        amount = price_map.get(req.subscription_type, 0)
        
        if amount <= 0:
            raise HTTPException(400, "无效的订阅类型或价格未设置")
        
        # 3. 生成订单ID
        import uuid
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        
        # 4. 创建订单记录（需要先创建 orders 表）
        # TODO: 实现 orders 表和订单逻辑
        
        return OrderResponse(
            order_id=order_id,
            group_id=req.group_id,
            group_name=product["name"],
            subscription_type=req.subscription_type,
            amount=amount,
            status="pending",
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    finally:
        conn.close()


@app.get("/api/orders/my")
async def get_my_orders(request: Request):
    """获取我的订单列表"""
    user = _authenticate(request)
    if not user:
        raise HTTPException(401, "未登录")
    
    # TODO: 实现
    return {"orders": []}


# =========================
# 管理员 API
# =========================

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """获取所有用户列表"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, username, email, phone, access_mode, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        return {"users": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.put("/api/admin/users/{user_id}/access-mode")
async def admin_update_user_access_mode(user_id: int, data: dict, request: Request):
    """更新用户权限"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET access_mode = ? WHERE id = ?",
            (data.get("access_mode", "free"), user_id)
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@app.get("/api/admin/subscriptions")
async def admin_list_subscriptions(request: Request):
    """获取所有订阅记录"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT gp.user_id, gp.group_id, gp.granted_at, gp.expire_at, 
                   gp.subscription_type, u.username, prod.name as group_name
            FROM group_permissions gp
            LEFT JOIN users u ON gp.user_id = u.id
            LEFT JOIN group_products prod ON gp.group_id = prod.group_id
            ORDER BY gp.granted_at DESC
        """).fetchall()
        return {"subscriptions": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/admin/grant-subscription")
async def admin_grant_subscription(data: dict, request: Request):
    """管理员授权订阅"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        granted_at = data.get("granted_at") or datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            """INSERT OR REPLACE INTO group_permissions 
            (user_id, group_id, expire_at, subscription_type, granted_at)
            VALUES (?, ?, ?, ?, ?)""",
            (data["user_id"], data["group_id"], data["expire_at"], data.get("subscription_type", "monthly"), granted_at)
        )

        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@app.delete("/api/admin/subscriptions/{user_id}/{group_id}")
async def admin_revoke_subscription(user_id: int, group_id: int, request: Request):
    """撤销用户订阅"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM group_permissions WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()





# httpx 异步客户端（复用连接池）
_http_client = httpx.AsyncClient(timeout=60.0)


# =========================
# 认证路由（不需要登录即可访问）
# =========================

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    conn = _get_conn()
    try:
        # 检查用户名
        if conn.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone():
            raise HTTPException(400, "用户名已存在")
        # 检查邮箱
        if conn.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone():
            raise HTTPException(400, "邮箱已被注册")
        # 检查手机号（如果提供了）
        if req.phone and conn.execute("SELECT id FROM users WHERE phone = ?", (req.phone,)).fetchone():
            raise HTTPException(400, "手机号已被注册")

        hashed = hash_password(req.password)
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, phone, access_mode) VALUES (?, ?, ?, ?, ?)",
            (req.username, hashed, req.email, req.phone or '', 'free'),
        )
        conn.commit()
        user_id = cur.lastrowid

        token = create_token(user_id, req.username)
        return TokenResponse(access_token=token, username=req.username)
    finally:
        conn.close()


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (req.username,)).fetchone()
        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(401, "用户名或密码错误")

        token = create_token(row["id"], row["username"])
        return TokenResponse(access_token=token, username=row["username"])
    finally:
        conn.close()

# =========================
# 授权管理 API
# =========================

class GrantPermissionRequest(BaseModel):
    user_id: int
    group_id: int

@app.post("/api/auth/grant-group")
async def grant_group_permission(
    req: GrantPermissionRequest,
    request: Request,
    expire_at: Optional[str] = None  # 新增：到期日，格式 YYYY-MM-DD

):
    """为用户授权群组访问权限（管理员功能）"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        # 检查用户是否存在
        user = conn.execute("SELECT id FROM users WHERE id = ?", (req.user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        
        # 添加授权
        conn.execute(
            "INSERT OR IGNORE INTO group_permissions (user_id, group_id, expire_at) VALUES (?, ?, ?)",
            (req.user_id, req.group_id, req.expire_at)
        )
        conn.commit()
        
        return {"success": True, "message": f"已为用户 {req.user_id} 授权群组 {req.group_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"授权失败: {str(e)}")
    finally:
        conn.close()


@app.delete("/api/auth/revoke-group")
async def revoke_group_permission(
    user_id: int,
    group_id: int,
    request: Request
):
    """撤销用户的群组访问权限（管理员功能）"""
    # TODO: 添加管理员权限检查
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM group_permissions WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        )
        conn.commit()
        
        return {"success": True, "message": f"已撤销用户 {user_id} 对群组 {group_id} 的访问权限"}
    except Exception as e:
        raise HTTPException(500, f"撤销失败: {str(e)}")
    finally:
        conn.close()


@app.get("/api/auth/user-groups/{user_id}")
async def get_user_groups(user_id: int, request: Request):
    """获取用户的授权群组列表"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT group_id, granted_at FROM group_permissions WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        
        return {
            "user_id": user_id,
            "groups": [
                {"group_id": r["group_id"], "granted_at": r["granted_at"]}
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"查询失败: {str(e)}")
    finally:
        conn.close()


@app.get("/api/auth/me", response_model=UserInfo)
async def get_me(request: Request):
    user = _authenticate(request)
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    return UserInfo(**user)


# =========================
# 代理转发（需要认证）
# =========================

def _authenticate(request: Request) -> Optional[dict]:
    """从请求中提取并验证 Token，返回用户信息"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return get_user_from_token(auth[7:])


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str):
    # 0. 公开端点跳过认证（直接转发）
    public_paths = [
        "/api/proxy-image",      # 图片代理（需要cookie认证，不需要用户登录）
        "/api/image",            # 图片代理（解决CORS问题，公开访问）
        "/api/auth/register",     # 用户注册
        "/api/auth/login",        # 用户登录
        "/api/health",            # 健康检查
        "/api/groups/products",   # 商品列表（公开）
    ]
    
    if any(pub_path in f"/{path}" for pub_path in public_paths):
        # 直接转发，不进行用户认证
        upstream_url = f"{UPSTREAM_URL}/{path}"
        if request.url.query:
            upstream_url += f"?{request.url.query}"
        body = await request.body()
        forward_headers = {k: v for k, v in request.headers.items() 
                          if k.lower() not in ("host", "content-length", "transfer-encoding")}
        forward_headers.pop("Authorization", None)
        
        try:
            upstream_resp = await _http_client.request(
                method=request.method, url=upstream_url, headers=forward_headers, content=body
            )
        except httpx.ConnectError:
            return JSONResponse({"detail": "后端服务不可用"}, status_code=502)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "后端服务响应超时"}, status_code=504)
        
        return _build_response(upstream_resp)

    # 1. 认证检查
    user = _authenticate(request)
    if not user:
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
    
    # 2. 管理员权限检查
    if "/api/admin/" in f"/{path}":
        if user["access_mode"] != "admin":
            return JSONResponse({"detail": "需要管理员权限"}, status_code=403)
    
    # 3. Group 权限检查（免费用户可访问所有群组）
    group_id = extract_group_id(f"/{path}")
    if group_id is not None:
        if user["access_mode"] == "vip":
            # VIP用户可以访问所有群组，无需检查
            pass
        elif user["access_mode"] == "admin":
            # 管理员可以访问所有群组，无需检查
            pass
        elif user["access_mode"] == "free":
            # 免费用户可以访问所有群组（但内容会被过滤）
            pass
        elif user["access_mode"] == "client":
            # client用户可以访问所有群组（未授权群组的内容会被过滤）
            pass
        else:
            # 未知权限模式，拒绝访问
            return JSONResponse({"detail": "无效的权限模式"}, status_code=403)

    # 4. 构建转发请求
    upstream_url = f"{UPSTREAM_URL}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # 读取请求体
    body = await request.body()

    # 构建转发 headers（去掉 host，保留其余）
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() in ("host", "content-length", "transfer-encoding"):
            continue
        forward_headers[key] = value
    # 去掉 Authorization，main.py 不需要
    forward_headers.pop("Authorization", None)

    # 5. 转发请求
    try:
        upstream_resp = await _http_client.request(
            method=request.method,
            url=upstream_url,
            headers=forward_headers,
            content=body,
        )
    except httpx.ConnectError:
        return JSONResponse({"detail": "后端服务不可用"}, status_code=502)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "后端服务响应超时"}, status_code=504)
    
    # 6. 内容过滤（根据用户类型）
    # VIP 和 admin 用户不进行内容过滤
    if user["access_mode"] in ("vip", "admin"):
        return _build_response(upstream_resp)
    
    # free 用户：过滤所有群组的 7 天内内容
    if user["access_mode"] == "free":
        print(f"[DEBUG] Free user filtering, path: /{path}")
        filtered_resp = _apply_delayed_filter(f"/{path}", upstream_resp, "free")
        print(f"[DEBUG] Filter result: {filtered_resp is not None}")
        if filtered_resp:
            return filtered_resp
        return _build_response(upstream_resp)
    
    # client 用户：检查是否有群组权限
    if user["access_mode"] == "client":
        allowed_groups = user.get("allowed_groups", {})
        if group_id and group_id in allowed_groups:
            # 有权限的群组，不过滤
            return _build_response(upstream_resp)
        else:
            # 无权限的群组，应用 7 天过滤
            filtered_resp = _apply_delayed_filter(f"/{path}", upstream_resp, "free")
            if filtered_resp:
                return filtered_resp
            return _build_response(upstream_resp)
    
    # 7. 默认返回
    return _build_response(upstream_resp)


def _apply_delayed_filter(path: str, resp: httpx.Response, access_mode: str) -> Optional[JSONResponse]:
    """内容过滤：免费用户过滤7天内，隔日用户过滤当天"""

    topic_list_pattern = re.compile(r"^/api/groups/\d+/topics$")
    topic_detail_pattern = re.compile(r"^/api/topics/\d+/\d+$")
    column_topics_pattern = re.compile(r"^/api/groups/\d+/columns/\d+/topics$")
    column_topic_detail_pattern = re.compile(r"^/api/groups/\d+/columns/topics/\d+$")

    try:
        data = resp.json()
    except Exception:
        return None

    filtered = False

    # 根据访问模式确定提示信息和过滤天数
    if access_mode == "free":
        filter_days = 7
        title_placeholder = "📢 该内容仅对付费用户开放"
        text_placeholder = "免费用户仅可查看 7 天前的内容，升级会员可查看更多。"
    else:  # delayed
        filter_days = 1
        title_placeholder = "📢 该内容将于明日查看"
        text_placeholder = "该内容将在明天自动开放查看，请耐心等待。"

    # 话题列表
    if topic_list_pattern.match(path) and isinstance(data, dict) and "topics" in data:
        for topic in data["topics"]:
            if is_within_days(topic.get("create_time", ""), filter_days):
                topic["title"] = title_placeholder
                topic["_filtered"] = True
        filtered = True

    # 话题详情
    elif topic_detail_pattern.match(path) and isinstance(data, dict):
        if is_within_days(data.get("create_time", ""), filter_days):
            data["title"] = title_placeholder
            data["text"] = text_placeholder
            data["_filtered"] = True
        filtered = True

    # 专栏文章列表
    elif column_topics_pattern.match(path) and isinstance(data, dict) and "topics" in data:
        for topic in data["topics"]:
            if is_within_days(topic.get("create_time", ""), filter_days) or \
               is_within_days(topic.get("attached_to_column_time", ""), filter_days):
                topic["title"] = title_placeholder
                topic["_filtered"] = True
        filtered = True

    # 专栏文章详情
    elif column_topic_detail_pattern.match(path) and isinstance(data, dict):
        if is_within_days(data.get("create_time", ""), filter_days):
            data["title"] = title_placeholder
            data["full_text"] = text_placeholder
            data["_filtered"] = True
        filtered = True

    if filtered:
        return JSONResponse(content=data, status_code=resp.status_code)
    return None



def _apply_group_filter(resp: httpx.Response, allowed_groups: list) -> Optional[JSONResponse]:
    """过滤 /api/groups 返回结果，只返回用户有权限的 group"""
    try:
        data = resp.json()
    except Exception:
        return None

    if isinstance(data, dict) and "groups" in data:
        allowed = set(allowed_groups)
        data["groups"] = [g for g in data["groups"] if g.get("group_id") in allowed]
        return JSONResponse(content=data, status_code=resp.status_code)
    return None


def _build_response(resp: httpx.Response) -> Response:
    """原样构建响应（支持流式、文件下载等）"""
    headers = dict(resp.headers)
    # 去掉可能导致问题的 headers
    for h in ("content-encoding", "content-length", "transfer-encoding"):
        headers.pop(h, None)

    # 流式响应（SSE、文件下载等）
    if "text/event-stream" in headers.get("content-type", ""):
        return StreamingResponse(
            resp.aiter_bytes(),
            status_code=resp.status_code,
            headers=headers,
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=headers,
    )


# =========================
# 启动
# =========================

if __name__ == "__main__":
    print(f"🔐 认证网关启动在 http://0.0.0.0:{AUTH_PORT}")
    print(f"📡 上游服务: {UPSTREAM_URL}")
    print(f"🗄️ 数据库: {DB_PATH}")
    print(f"⏰ Token 有效期: {TOKEN_EXPIRE_DAYS} 天")
    uvicorn.run(app, host="0.0.0.0", port=AUTH_PORT)

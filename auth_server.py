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
    """获取用户有权限的群组及其到期日"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT group_id, expire_at FROM group_permissions WHERE user_id = ?", 
            (user_id,)
        ).fetchall()
        # 返回 {group_id: expire_at} 的映射
        return {r["group_id"]: r["expire_at"] for r in rows}
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
    phone: str = Field(..., description="手机号")
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
        # 检查手机号
        if conn.execute("SELECT id FROM users WHERE phone = ?", (req.phone,)).fetchone():
            raise HTTPException(400, "手机号已被注册")

        hashed = hash_password(req.password)
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, phone) VALUES (?, ?, ?, ?)",
            (req.username, hashed, req.email, req.phone, 'free'),
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
    # 0. 公开端点跳过认证
    if "/api/proxy" in f"/{path}":
        # 直接转发
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

    # 2. Group 权限检查（免费用户可访问所有群组）
    group_id = extract_group_id(f"/{path}")
    if group_id is not None:
        if user["access_mode"] == "vip":
            # VIP用户可以访问所有群组，无需检查
            pass
        elif user["access_mode"] == "free":
            # 免费用户可以访问所有群组（但内容会被过滤）
            pass
        elif user["access_mode"] == "paid":
            # 付费用户可以访问所有群组（未授权群组的内容会被过滤）
            pass
        else:
            # 未知权限模式，拒绝访问
            return JSONResponse({"detail": "无效的权限模式"}, status_code=403)

    # 3. 构建转发请求
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

    # 4. 转发请求
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

    # 5. 内容过滤（免费用户/隔日用户）
    response_content_type = upstream_resp.headers.get("content-type", "")

    if "application/json" in response_content_type:
        should_filter = False
        filter_mode = "free"
        
        # 判断是否需要过滤
        if user["access_mode"] == "free":
            # 免费用户：所有群组都需要过滤（7天限制）
            should_filter = True
            filter_mode = "free"
        elif user["access_mode"] == "vip":
            # VIP用户：不进行任何过滤
            should_filter = False
        elif user["access_mode"] == "paid":
            # 付费用户：检查群组授权状态和有效期
            if group_id is not None:
                # 检查是否在授权列表中
                if group_id in user["allowed_groups"]:
                    expire_at = user["allowed_groups"][group_id]
                    # 检查是否在有效期内
                    if not is_expired(expire_at):
                        # 授权有效期内：不过滤
                        should_filter = False
                    else:
                        # 授权已过期：按免费用户处理
                        should_filter = True
                        filter_mode = "free"
                else:
                    # 未授权的群组：按免费用户处理
                    should_filter = True
                    filter_mode = "free"
            else:
                # 没有群组ID（如群组列表），不进行内容过滤
                should_filter = False
        else:
            # 未知权限模式，拒绝访问
            return JSONResponse({"detail": "无效的权限模式"}, status_code=403)
        
        if should_filter:
            filtered = _apply_delayed_filter(f"/{path}", upstream_resp, filter_mode)
            if filtered is not None:
                return filtered
    
    # 6. 对 /api/groups 接口做 Group 权限过滤（免费用户显示所有群组）
    # 所有用户都可以看到所有群组，不进行过滤
    # 权限区别在于访问群组内容时的过滤



    # 7. 非过滤场景，原样返回响应
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

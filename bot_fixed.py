"""
Reward Farm — Complete backend (single file, hardcoded config)
Telegram Mini App auth + Telegram Admin Bot + Firebase/Firestore + REST API.

Run:
    python bot.py
"""
from __future__ import annotations

import os, json, time, hmac, hashlib, secrets, asyncio, logging, traceback, random, string
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import parse_qsl, unquote

import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# ═══════════════════════════════════════════════════════════════════════════
# 🔧 CONFIGURATION — তোমার সব তথ্য এখানে বসাও
# ═══════════════════════════════════════════════════════════════════════════
BOT_TOKEN          = "8980377845:AAHKfaoEjDtKSkbT1EkPgW64HFRUpbqhaaY"       # ⚠️ REVOKE NOW → paste new
ADMIN_TELEGRAM_ID  = 8765546786
APP_BASE_URL       = "https://talegram-52fd4.web.app"                        # ← REAL HTTPS domain

FIREBASE_PROJECT_ID    = "talegram-52fd4"
FIREBASE_CLIENT_EMAIL  = "mdashekurislam8@gmail.com"   # ← paste
FIREBASE_PRIVATE_KEY   = "AIzaSyCUkHBPIqFMP1wDv1_De1OGGLhKACs7E4k"  # ← paste

WEBAPP_SESSION_SECRET  = "change-this-to-64-random-characters"
MONETAG_ZONE_ID        = "9901775"
MONETAG_REWARD         = 50
# ═══════════════════════════════════════════════════════════════════════════

SESSION_TTL_SEC    = 60 * 60 * 24 * 7
INITDATA_MAX_AGE   = 60 * 60 * 24

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reward-farm")

# ─── Firebase Init ─────────────────────────────────────────────────────────
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": FIREBASE_PROJECT_ID,
        "client_email": FIREBASE_CLIENT_EMAIL,
        "private_key": FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# ─── Collections ───────────────────────────────────────────────────────────
C_USERS            = db.collection("users")
C_TASKS            = db.collection("tasks")
C_TASK_COMPLETIONS = db.collection("task_completions")
C_REFERRALS        = db.collection("referrals")
C_TOKEN_TX         = db.collection("token_transactions")
C_USD_TX           = db.collection("usd_transactions")
C_FARMING          = db.collection("farming_sessions")
C_LEVELS           = db.collection("levels")
C_BOOSTS           = db.collection("boosts")
C_BOOST_USES       = db.collection("boost_uses")
C_WITHDRAWALS      = db.collection("withdrawals")
C_NOTIFICATIONS    = db.collection("notifications")
C_AD_REWARDS       = db.collection("ad_rewards")
C_SETTINGS         = db.collection("settings")
C_ADMIN_LOGS       = db.collection("admin_logs")
C_SESSIONS         = db.collection("sessions")
C_DAILY            = db.collection("daily_actions")

# ─── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "referral":    {"reward_usd": 0.07, "enabled": True, "require_verification": True, "daily_limit": 50},
    "withdrawal":  {"min": 1.00, "fee_pct": 0.0, "methods": ["bkash","nagad","paypal","usdt"], "daily_limit": 3},
    "farming":     {"enabled": True, "duration_hours": 8, "reward_rate": 100, "reward_type": "TOKEN",
                    "daily_limit": 3, "cooldown_minutes": 5, "auto_claim": False},
    "monetag":     {"enabled": True, "zone_id": MONETAG_ZONE_ID, "reward": MONETAG_REWARD,
                    "reward_type": "TOKEN", "daily_limit": 10, "cooldown_seconds": 30},
    "combo":       {"enabled": True, "bonus_token": 500, "bonus_usd": 0.0, "total_steps": 5, "reset_hour_utc": 0},
    "maintenance": {"enabled": False, "message": "🔧 We're currently performing maintenance. Please try again later."},
}

DEFAULT_LEVELS = [
    {"level":1, "xp_required":0,     "tokens_required":0,     "daily_farming":3, "daily_tasks":10, "daily_ads":5,  "farming_rate":1.0, "boost_access":False, "boost_multiplier":1.0},
    {"level":2, "xp_required":1000,  "tokens_required":1000,  "daily_farming":5, "daily_tasks":20, "daily_ads":10, "farming_rate":1.1, "boost_access":True,  "boost_multiplier":1.0},
    {"level":3, "xp_required":5000,  "tokens_required":5000,  "daily_farming":8, "daily_tasks":35, "daily_ads":15, "farming_rate":1.25,"boost_access":True,  "boost_multiplier":1.2},
    {"level":4, "xp_required":20000, "tokens_required":20000, "daily_farming":12,"daily_tasks":50, "daily_ads":20, "farming_rate":1.5, "boost_access":True,  "boost_multiplier":1.5},
    {"level":5, "xp_required":80000, "tokens_required":80000, "daily_farming":20,"daily_tasks":80, "daily_ads":30, "farming_rate":2.0, "boost_access":True,  "boost_multiplier":2.0},
]

DEFAULT_BOOSTS = [
    {"name":"🚀 2X Farming Boost","description":"Double farming reward","multiplier":2.0,"duration_seconds":60,"reward_type":"FARMING","daily_limit":3,"required_level":1,"bypass_limits":False,"active":True},
    {"name":"⚡ 3X Token Boost",  "description":"Triple token gain",    "multiplier":3.0,"duration_seconds":30,"reward_type":"TOKEN",  "daily_limit":2,"required_level":2,"bypass_limits":False,"active":True},
    {"name":"🔥 5X Mega Boost",  "description":"Massive multiplier",   "multiplier":5.0,"duration_seconds":30,"reward_type":"TOKEN",  "daily_limit":1,"required_level":3,"bypass_limits":False,"active":True},
]

# ─── Helpers ───────────────────────────────────────────────────────────────
def now_utc(): return datetime.now(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).isoformat()
def today_key(dt=None): return (dt or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%d")

def get_settings() -> Dict[str, Any]:
    doc = C_SETTINGS.document("global").get()
    if not doc.exists:
        C_SETTINGS.document("global").set(DEFAULT_SETTINGS)
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    data = doc.to_dict() or {}
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged

def save_settings(patch: Dict[str, Any]):
    C_SETTINGS.document("global").set(patch, merge=True)

def ensure_defaults():
    if not list(C_LEVELS.limit(1).stream()):
        for lvl in DEFAULT_LEVELS:
            C_LEVELS.document(f"L{lvl['level']}").set(lvl)
    if not list(C_BOOSTS.limit(1).stream()):
        for i, b in enumerate(DEFAULT_BOOSTS, 1):
            C_BOOSTS.document(f"B{i}").set(b)
    get_settings()

# ─── Telegram initData validation ──────────────────────────────────────────
def validate_init_data(init_data: str) -> Dict[str, Any]:
    if not init_data:
        raise HTTPException(401, "Missing initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(401, "Invalid initData signature")
    auth_date = int(pairs.get("auth_date", "0"))
    if time.time() - auth_date > INITDATA_MAX_AGE:
        raise HTTPException(401, "initData expired")
    user_json = pairs.get("user")
    if not user_json:
        raise HTTPException(401, "Missing user")
    try:
        user = json.loads(unquote(user_json) if user_json.startswith("%7B") else user_json)
    except Exception:
        user = json.loads(user_json)
    return user

# ─── Sessions ──────────────────────────────────────────────────────────────
def issue_session(telegram_user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    C_SESSIONS.document(sid).set({
        "telegram_user_id": telegram_user_id,
        "created_at": iso(now_utc()),
        "expires_at": iso(now_utc() + timedelta(seconds=SESSION_TTL_SEC)),
    })
    return sid

def validate_session(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(401, "Missing session")
    doc = C_SESSIONS.document(token).get()
    if not doc.exists:
        raise HTTPException(401, "Invalid session")
    data = doc.to_dict()
    try:
        exp = datetime.fromisoformat(data["expires_at"])
    except Exception:
        raise HTTPException(401, "Invalid session")
    if exp < now_utc():
        C_SESSIONS.document(token).delete()
        raise HTTPException(401, "Session expired")
    return data

async def current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    sess = validate_session(authorization.split(" ", 1)[1])
    udoc = C_USERS.document(str(sess["telegram_user_id"])).get()
    if not udoc.exists:
        raise HTTPException(401, "User not found")
    user = udoc.to_dict()
    user["_id"] = udoc.id
    if user.get("account_status") == "suspended":
        raise HTTPException(403, "Account suspended")
    return user

# ─── User ──────────────────────────────────────────────────────────────────
def new_referral_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "".join(random.choices(alphabet, k=7))
        if not list(C_USERS.where(filter=FieldFilter("referral_code", "==", code)).limit(1).stream()):
            return code
    return secrets.token_urlsafe(6).upper()

def get_user(uid: str) -> Optional[Dict[str, Any]]:
    d = C_USERS.document(uid).get()
    if not d.exists: return None
    u = d.to_dict(); u["_id"] = d.id; return u

def create_or_load_user(tg_user: Dict[str, Any], referred_by: Optional[str] = None) -> Dict[str, Any]:
    uid = str(tg_user["id"])
    ref = C_USERS.document(uid)
    doc = ref.get()
    if doc.exists:
        u = doc.to_dict()
        ref.update({
            "telegram_username": tg_user.get("username"),
            "display_name": tg_user.get("first_name","") + ((" " + tg_user["last_name"]) if tg_user.get("last_name") else ""),
            "photo_url": tg_user.get("photo_url"),
            "last_login": iso(now_utc()),
        })
        u.update({"telegram_username": tg_user.get("username"), "last_login": iso(now_utc())})
        u["_id"] = uid
        return u
    code = new_referral_code()
    base = {
        "telegram_user_id": tg_user["id"],
        "telegram_username": tg_user.get("username"),
        "display_name": tg_user.get("first_name","") + ((" " + tg_user["last_name"]) if tg_user.get("last_name") else ""),
        "photo_url": tg_user.get("photo_url"),
        "token_balance": 0, "usd_balance": 0.0,
        "level": 1, "xp": 0,
        "referral_code": code,
        "referred_by": referred_by or None,
        "referral_status": "pending",
        "account_status": "active",
        "total_tokens_earned": 0, "total_usd_earned": 0.0, "total_usd_withdrawn": 0.0,
        "created_at": iso(now_utc()), "last_login": iso(now_utc()),
    }
    ref.set(base)
    if referred_by:
        try: link_referral(uid, referred_by)
        except Exception as e: log.warning("referral link failed: %s", e)
    base["_id"] = uid
    return base

def link_referral(new_uid: str, referrer_code: str):
    q = C_USERS.where(filter=FieldFilter("referral_code", "==", referrer_code)).limit(1).stream()
    referrer = None
    for r in q: referrer = r; break
    if not referrer or referrer.id == new_uid: return
    existing = list(C_REFERRALS.where(filter=FieldFilter("referred_user_id", "==", new_uid)).limit(1).stream())
    if existing: return
    C_REFERRALS.document().set({
        "referrer_id": referrer.id,
        "referred_user_id": new_uid,
        "status": "pending", "reward_usd": 0.0,
        "created_at": iso(now_utc()),
    })
    C_USERS.document(new_uid).update({"referred_by": referrer.id})

def verify_referral_for_user(uid: str, reason: str = "task"):
    q = list(C_REFERRALS.where(filter=FieldFilter("referred_user_id", "==", uid)).limit(1).stream())
    if not q: return
    ref_doc = q[0]
    data = ref_doc.to_dict()
    if data.get("status") == "verified": return
    settings = get_settings()
    if not settings["referral"]["enabled"]: return
    referrer_id = data["referrer_id"]
    reward = float(settings["referral"]["reward_usd"])

    def _txn(transaction, ref_ref, user_ref):
        snap = ref_ref.get(transaction=transaction)
        if not snap.exists or snap.to_dict().get("status") == "verified": return
        u_snap = user_ref.get(transaction=transaction)
        if not u_snap.exists: return
        before = float(u_snap.to_dict().get("usd_balance", 0.0))
        after = round(before + reward, 4)
        transaction.update(user_ref, {
            "usd_balance": after,
            "total_usd_earned": float(u_snap.to_dict().get("total_usd_earned", 0.0)) + reward,
        })
        transaction.update(ref_ref, {"status":"verified","reward_usd":reward,"verified_at":iso(now_utc()),"reason":reason})
        tx_ref = C_USD_TX.document()
        transaction.set(tx_ref, {
            "transaction_id": tx_ref.id, "user_id": referrer_id, "type": "referral_reward",
            "amount": reward, "balance_before": before, "balance_after": after,
            "source": "referral", "reference_id": ref_ref.id,
            "status": "completed", "created_at": iso(now_utc()),
        })
    try:
        _txn(db.transaction(), ref_doc.reference, C_USERS.document(referrer_id))
        notify(referrer_id, "💰 Referral Reward", f"You earned ${reward:.2f} from a verified referral!", icon="💰")
    except Exception as e:
        log.warning("verify_referral txn: %s", e)

# ─── Ledgers ───────────────────────────────────────────────────────────────
def credit_token(uid: str, amount: int, source: str, reference_id: str = ""):
    amount = int(amount)
    if amount == 0: return
    user_ref = C_USERS.document(uid)
    tx_ref = C_TOKEN_TX.document()
    def _txn(transaction, uref, tref):
        snap = uref.get(transaction=transaction)
        if not snap.exists: return
        d = snap.to_dict()
        before = int(d.get("token_balance", 0))
        after = before + amount
        transaction.update(uref, {
            "token_balance": after,
            "total_tokens_earned": int(d.get("total_tokens_earned", 0)) + (amount if amount > 0 else 0),
        })
        transaction.set(tref, {
            "transaction_id": tref.id, "user_id": uid,
            "type": "credit" if amount > 0 else "debit",
            "amount": amount, "balance_before": before, "balance_after": after,
            "source": source, "reference_id": reference_id,
            "status": "completed", "created_at": iso(now_utc()),
        })
    _txn(db.transaction(), user_ref, tx_ref)
    add_xp(uid, max(1, abs(amount) // 10))

def credit_usd(uid: str, amount: float, source: str, reference_id: str = ""):
    amount = round(float(amount), 4)
    if amount == 0: return
    user_ref = C_USERS.document(uid)
    tx_ref = C_USD_TX.document()
    def _txn(transaction, uref, tref):
        snap = uref.get(transaction=transaction)
        if not snap.exists: return
        d = snap.to_dict()
        before = float(d.get("usd_balance", 0.0))
        after = round(before + amount, 4)
        upd = {"usd_balance": after}
        if amount > 0:
            upd["total_usd_earned"] = float(d.get("total_usd_earned", 0.0)) + amount
        transaction.update(uref, upd)
        transaction.set(tref, {
            "transaction_id": tref.id, "user_id": uid,
            "type": "credit" if amount > 0 else "debit",
            "amount": amount, "balance_before": before, "balance_after": after,
            "source": source, "reference_id": reference_id,
            "status": "completed", "created_at": iso(now_utc()),
        })
    _txn(db.transaction(), user_ref, tx_ref)

def add_xp(uid: str, xp: int):
    if xp <= 0: return
    user_ref = C_USERS.document(uid)
    def _txn(transaction, uref):
        snap = uref.get(transaction=transaction)
        if not snap.exists: return
        d = snap.to_dict()
        new_xp = int(d.get("xp", 0)) + xp
        cur_level = int(d.get("level", 1))
        new_level = cur_level
        levels = list(C_LEVELS.order_by("level").stream())
        for l in levels:
            ld = l.to_dict()
            if new_xp >= int(ld.get("xp_required", 0)):
                new_level = int(ld["level"])
        upd = {"xp": new_xp}
        if new_level != cur_level: upd["level"] = new_level
        transaction.update(uref, upd)
        if new_level != cur_level:
            notify_in_txn(transaction, uid, "🎉 Level Up!", f"You reached Level {new_level}!", icon="⭐")
    _txn(db.transaction(), user_ref)

# ─── Notifications ─────────────────────────────────────────────────────────
def notify(uid: str, title: str, body: str, icon: str = "🔔"):
    C_NOTIFICATIONS.document().set({
        "user_id": uid, "title": title, "body": body, "icon": icon,
        "read": False, "created_at": iso(now_utc()),
    })

def notify_in_txn(transaction, uid: str, title: str, body: str, icon: str = "🔔"):
    ref = C_NOTIFICATIONS.document()
    transaction.set(ref, {
        "user_id": uid, "title": title, "body": body, "icon": icon,
        "read": False, "created_at": iso(now_utc()),
    })

# ─── Daily counters ────────────────────────────────────────────────────────
def daily_doc_id(uid: str, kind: str) -> str:
    return f"{uid}_{today_key()}_{kind}"

def get_daily_count(uid: str, kind: str) -> int:
    d = C_DAILY.document(daily_doc_id(uid, kind)).get()
    return int((d.to_dict() or {}).get("count", 0)) if d.exists else 0

def bump_daily(uid: str, kind: str, inc: int = 1) -> int:
    doc = C_DAILY.document(daily_doc_id(uid, kind))
    def _txn(transaction, ref):
        snap = ref.get(transaction=transaction)
        cur = int((snap.to_dict() or {}).get("count", 0)) if snap.exists else 0
        new = cur + inc
        transaction.set(ref, {"user_id": uid, "kind": kind, "day": today_key(),
                              "count": new, "updated_at": iso(now_utc())}, merge=True)
        return new
    return _txn(db.transaction(), doc)

# ─── Levels / Boosts ───────────────────────────────────────────────────────
def level_limits(uid: str) -> Dict[str, Any]:
    u = get_user(uid) or {}
    lvl = int(u.get("level", 1))
    ld = C_LEVELS.document(f"L{lvl}").get()
    if not ld.exists:
        for l in C_LEVELS.order_by("level", direction=firestore.Query.DESCENDING).limit(1).stream():
            return l.to_dict()
        return DEFAULT_LEVELS[0]
    return ld.to_dict()

def active_boost(uid: str) -> Optional[Dict[str, Any]]:
    now = now_utc()
    for d in C_BOOST_USES.where(filter=FieldFilter("user_id", "==", uid)).stream():
        data = d.to_dict()
        try: exp = datetime.fromisoformat(data["expires_at"])
        except Exception: continue
        if exp > now and data.get("status") == "active":
            data["_id"] = d.id
            return data
    return None

# ═══════════════════════════════════════════════════════════════════════════
# FastAPI
# ═══════════════════════════════════════════════════════════════════════════
app = FastAPI(title="Reward Farm", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[APP_BASE_URL, "https://web.telegram.org"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

class AuthIn(BaseModel):
    initData: str
    ref: Optional[str] = None

class WithdrawIn(BaseModel):
    amount: float
    method: str
    account: str

def public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "telegram_user_id": u.get("telegram_user_id"),
        "telegram_username": u.get("telegram_username"),
        "display_name": u.get("display_name"),
        "photo_url": u.get("photo_url"),
        "token_balance": u.get("token_balance", 0),
        "usd_balance": u.get("usd_balance", 0.0),
        "level": u.get("level", 1),
        "xp": u.get("xp", 0),
        "referral_code": u.get("referral_code"),
        "account_status": u.get("account_status", "active"),
        "created_at": u.get("created_at"),
    }

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html missing</h1>", status_code=500)

@app.get("/health")
async def health(): return {"ok": True, "ts": iso(now_utc())}

@app.post("/api/auth/telegram")
async def auth_telegram(body: AuthIn):
    tg_user = validate_init_data(body.initData)
    referred_by = body.ref
    if referred_by:
        q = list(C_USERS.where(filter=FieldFilter("referral_code", "==", referred_by.strip().upper())).limit(1).stream())
        referred_by = q[0].id if q else None
    user = create_or_load_user(tg_user, referred_by)
    settings = get_settings()
    token = issue_session(tg_user["id"])
    return {
        "token": token,
        "user": public_user(user),
        "settings": {
            "referral": settings["referral"],
            "withdrawal": settings["withdrawal"],
            "farming": settings["farming"],
            "monetag": settings["monetag"],
        },
    }

@app.get("/api/profile")
async def profile(user=Depends(current_user)):
    return {"user": public_user(user)}

@app.get("/api/dashboard")
async def dashboard(user=Depends(current_user)):
    settings = get_settings()
    if settings["maintenance"]["enabled"]:
        raise HTTPException(503, settings["maintenance"]["message"])
    uid = user["_id"]; today = today_key()
    t_tokens = 0
    for d in C_TOKEN_TX.where(filter=FieldFilter("user_id", "==", uid)).stream():
        data = d.to_dict()
        if data.get("amount", 0) > 0 and (data.get("created_at","") >= today):
            t_tokens += int(data["amount"])
    t_usd = 0.0
    for d in C_USD_TX.where(filter=FieldFilter("user_id", "==", uid)).stream():
        data = d.to_dict()
        if data.get("amount", 0) > 0 and (data.get("created_at","") >= today):
            t_usd += float(data["amount"])
    ref_earn = 0.0
    for d in C_REFERRALS.where(filter=FieldFilter("referrer_id", "==", uid)).stream():
        data = d.to_dict()
        if data.get("status") == "verified":
            ref_earn += float(data.get("reward_usd", 0.0))
    verified_refs = sum(1 for _ in C_REFERRALS.where(filter=FieldFilter("referrer_id", "==", uid)).stream()
                        if _.to_dict().get("status") == "verified")
    lim = level_limits(uid)
    used = get_daily_count(uid, "actions")
    daily_limit = int(lim.get("daily_tasks",10)) + int(lim.get("daily_farming",3)) + int(lim.get("daily_ads",5))
    farm_status = farming_status_payload(uid, user)
    cur_lvl = int(user.get("level", 1))
    nxt = C_LEVELS.document(f"L{cur_lvl + 1}").get()
    next_xp = int(nxt.to_dict()["xp_required"]) if nxt.exists else 0
    return {
        "user": public_user(user),
        "today_tokens": t_tokens,
        "today_usd": round(t_usd, 4),
        "referral_earnings": round(ref_earn, 4),
        "verified_referrals": verified_refs,
        "daily_actions": {"used": used, "limit": daily_limit},
        "level_info": {"level": cur_lvl, "xp": int(user.get("xp", 0)), "next_xp": next_xp},
        "farming": farm_status,
        "combo": combo_status(uid),
    }

def combo_status(uid: str) -> Dict[str, Any]:
    settings = get_settings()
    total = int(settings["combo"]["total_steps"])
    done = 1
    if get_daily_count(uid, "farming") > 0: done += 1
    if get_daily_count(uid, "tasks") >= 3: done += 1
    if get_daily_count(uid, "ads") >= 1: done += 1
    has_ref = any(_.to_dict().get("status") == "verified"
                  for _ in C_REFERRALS.where(filter=FieldFilter("referrer_id", "==", uid)).stream())
    if has_ref: done += 1
    return {"done": min(done, total), "total": total, "completed": done >= total,
            "bonus": settings["combo"]["bonus_token"]}

# ─── Farming ───────────────────────────────────────────────────────────────
def farming_status_payload(uid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    f = settings["farming"]
    lim = level_limits(uid)
    daily_limit = int(lim.get("daily_farming", f["daily_limit"]))
    used = get_daily_count(uid, "farming")
    boost = active_boost(uid)
    q = list(C_FARMING.where(filter=FieldFilter("user_id", "==", uid))
             .order_by("created_at", direction=firestore.Query.DESCENDING).limit(3).stream())
    session = None
    for d in q:
        data = d.to_dict()
        if data.get("status") in ("active", "claimable"):
            session = data; session["_id"] = d.id; break
    if session:
        end_ms = int(datetime.fromisoformat(session["end_time"]).timestamp() * 1000)
        start_ms = int(datetime.fromisoformat(session["start_time"]).timestamp() * 1000)
        claimable = time.time() * 1000 >= end_ms
        status = "claimable" if claimable else "active"
        if status == "claimable" and session.get("status") == "active":
            C_FARMING.document(session["_id"]).update({"status": "claimable"})
        return {
            "status": status, "session_id": session["_id"],
            "start_time": start_ms, "end_time": end_ms,
            "reward_rate": int(session.get("reward_rate", f["reward_rate"])),
            "reward_type": session.get("reward_type", f["reward_type"]),
            "duration_hours": f["duration_hours"],
            "daily_limit": daily_limit, "used_today": used,
            "active_boost": {"name": boost["name"], "multiplier": boost["multiplier"]} if boost else None,
            "can_start": False, "block_reason": "Session in progress",
        }
    can_start = bool(f["enabled"]) and used < daily_limit
    reason = ""
    if not f["enabled"]: reason = "Farming disabled"
    elif used >= daily_limit: reason = "Daily limit reached"
    return {
        "status": "idle", "reward_rate": int(f["reward_rate"]),
        "reward_type": f["reward_type"], "duration_hours": f["duration_hours"],
        "daily_limit": daily_limit, "used_today": used,
        "active_boost": {"name": boost["name"], "multiplier": boost["multiplier"]} if boost else None,
        "can_start": can_start, "block_reason": reason,
    }

@app.get("/api/farming/status")
async def farming_status(user=Depends(current_user)):
    return farming_status_payload(user["_id"], user)

@app.post("/api/farming/start")
async def farming_start(user=Depends(current_user)):
    uid = user["_id"]
    settings = get_settings(); f = settings["farming"]
    if not f["enabled"]: raise HTTPException(400, "Farming disabled")
    lim = level_limits(uid)
    daily_limit = int(lim.get("daily_farming", f["daily_limit"]))
    used = get_daily_count(uid, "farming")
    if used >= daily_limit: raise HTTPException(400, "Daily limit reached")
    for d in C_FARMING.where(filter=FieldFilter("user_id", "==", uid)).stream():
        if d.to_dict().get("status") in ("active", "claimable"):
            raise HTTPException(400, "Session already in progress")
    duration = timedelta(hours=float(f["duration_hours"]))
    start = now_utc(); end = start + duration
    ref = C_FARMING.document()
    ref.set({
        "user_id": uid, "start_time": iso(start), "end_time": iso(end),
        "duration_seconds": int(duration.total_seconds()),
        "reward_rate": int(f["reward_rate"]), "reward_type": f["reward_type"],
        "status": "active", "claim_status": "pending", "created_at": iso(start),
    })
    bump_daily(uid, "farming", 1); bump_daily(uid, "actions", 1)
    return {"ok": True, "session_id": ref.id}

@app.post("/api/farming/claim")
async def farming_claim(user=Depends(current_user)):
    uid = user["_id"]
    session = None
    for d in C_FARMING.where(filter=FieldFilter("user_id", "==", uid)).stream():
        data = d.to_dict()
        if data.get("status") in ("active", "claimable"):
            session = data; session["_id"] = d.id; break
    if not session: raise HTTPException(404, "No session to claim")
    end = datetime.fromisoformat(session["end_time"])
    if now_utc() < end: raise HTTPException(400, "Session not finished")
    ref = C_FARMING.document(session["_id"])
    def _txn(transaction, fref):
        snap = fref.get(transaction=transaction)
        if not snap.exists: raise HTTPException(404, "Session gone")
        data = snap.to_dict()
        if data.get("claim_status") == "claimed": raise HTTPException(409, "Already claimed")
        transaction.update(fref, {"status": "claimed", "claim_status": "claimed", "claimed_at": iso(now_utc())})
    _txn(db.transaction(), ref)
    base_reward = int(session.get("reward_rate", 100))
    boost = active_boost(uid)
    mult = float(boost["multiplier"]) if boost else 1.0
    lim = level_limits(uid)
    mult *= float(lim.get("farming_rate", 1.0))
    final_reward = int(base_reward * mult)
    reward_type = session.get("reward_type", "TOKEN")
    if reward_type == "USD":
        credit_usd(uid, final_reward / 100.0, "farming", session["_id"])
        notify(uid, "🎁 Farming Complete", f"You earned ${final_reward/100.0:.2f}!", icon="🎁")
        return {"amount": final_reward/100.0, "reward_type": "USD"}
    credit_token(uid, final_reward, "farming", session["_id"])
    notify(uid, "🎁 Farming Complete", f"You earned {final_reward} TOKEN!", icon="🎁")
    return {"amount": final_reward, "reward_type": "TOKEN"}

# ─── Tasks ─────────────────────────────────────────────────────────────────
@app.get("/api/tasks")
async def list_tasks(user=Depends(current_user)):
    uid = user["_id"]
    lim = level_limits(uid)
    daily_limit = int(lim.get("daily_tasks", 10))
    used = get_daily_count(uid, "tasks")
    tasks = []
    for d in C_TASKS.stream():
        t = d.to_dict(); t["id"] = d.id
        if t.get("status") == "disabled": continue
        if t.get("daily_limit") and t.get("daily_limit") > 0:
            done_today = sum(1 for x in C_TASK_COMPLETIONS
                             .where(filter=FieldFilter("task_id", "==", d.id))
                             .where(filter=FieldFilter("user_id", "==", uid)).stream()
                             if x.to_dict().get("created_at","") >= today_key())
            t["completed_today"] = done_today >= int(t["daily_limit"])
        else:
            t["completed_today"] = False
        started = False
        for x in C_TASK_COMPLETIONS.where(filter=FieldFilter("task_id", "==", d.id))\
                .where(filter=FieldFilter("user_id", "==", uid)).stream():
            if x.to_dict().get("status") == "started": started = True; break
        t["started"] = started
        tasks.append(t)
    return {"tasks": tasks, "today_completed": used, "daily_limit": daily_limit}

@app.post("/api/tasks/{task_id}/start")
async def task_start(task_id: str, user=Depends(current_user)):
    uid = user["_id"]
    t = C_TASKS.document(task_id).get()
    if not t.exists: raise HTTPException(404, "Task not found")
    td = t.to_dict()
    if td.get("status") == "disabled": raise HTTPException(400, "Task disabled")
    for x in C_TASK_COMPLETIONS.where(filter=FieldFilter("task_id", "==", task_id))\
            .where(filter=FieldFilter("user_id", "==", uid)).stream():
        if x.to_dict().get("status") == "started":
            return {"url": td.get("url",""), "started": True}
    C_TASK_COMPLETIONS.document().set({
        "task_id": task_id, "user_id": uid, "status": "started",
        "reward": int(td.get("reward", 0)), "reward_type": td.get("reward_type", "TOKEN"),
        "created_at": iso(now_utc()),
    })
    return {"url": td.get("url",""), "started": True}

@app.post("/api/tasks/{task_id}/verify")
async def task_verify(task_id: str, user=Depends(current_user)):
    uid = user["_id"]
    t = C_TASKS.document(task_id).get()
    if not t.exists: raise HTTPException(404, "Task not found")
    td = t.to_dict()
    lim = level_limits(uid)
    if get_daily_count(uid, "tasks") >= int(lim.get("daily_tasks", 10)):
        raise HTTPException(400, "Daily task limit reached")
    started = None
    for x in C_TASK_COMPLETIONS.where(filter=FieldFilter("task_id", "==", task_id))\
            .where(filter=FieldFilter("user_id", "==", uid)).stream():
        sd = x.to_dict()
        if sd.get("status") == "started": started = (x, sd); break
        if sd.get("status") == "completed": raise HTTPException(409, "Task already completed")
    if not started: raise HTTPException(400, "Start the task first")
    x_doc, sd = started
    method = td.get("verification", "manual")
    reward = int(sd.get("reward") or td.get("reward", 0))
    reward_type = sd.get("reward_type") or td.get("reward_type", "TOKEN")
    if method == "manual":
        x_doc.reference.update({"status": "pending", "updated_at": iso(now_utc())})
        return {"status": "pending"}
    x_doc.reference.update({"status": "completed", "completed_at": iso(now_utc())})
    bump_daily(uid, "tasks", 1); bump_daily(uid, "actions", 1)
    if reward_type == "USD":
        credit_usd(uid, reward / 100.0, "task", task_id); amount = reward / 100.0
    else:
        credit_token(uid, reward, "task", task_id); amount = reward
    if td.get("qualifies_referral", True):
        try: verify_referral_for_user(uid, reason=f"task:{task_id}")
        except Exception as e: log.warning("referral verify failed: %s", e)
    notify(uid, "🎯 Task Complete", f"You earned +{amount} {reward_type}!", icon="🎯")
    return {"status": "completed", "amount": amount, "reward_type": reward_type}

# ─── Wallet ────────────────────────────────────────────────────────────────
@app.get("/api/wallet")
async def wallet(user=Depends(current_user)):
    uid = user["_id"]
    settings = get_settings()
    tok_hist = []; tok_today = 0
    for d in C_TOKEN_TX.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream():
        data = d.to_dict(); tok_hist.append(data)
        if data.get("amount", 0) > 0 and data.get("created_at","") >= today_key():
            tok_today += int(data["amount"])
    usd_hist = []; pending = 0.0
    for d in C_USD_TX.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream():
        usd_hist.append(d.to_dict())
    for d in C_WITHDRAWALS.where(filter=FieldFilter("user_id", "==", uid)).stream():
        data = d.to_dict()
        if data.get("status") in ("pending","processing"): pending += float(data.get("amount", 0))
    return {
        "token": {"balance": int(user.get("token_balance", 0)),
                  "total_earned": int(user.get("total_tokens_earned", 0)),
                  "today": tok_today, "history": tok_hist},
        "usd":   {"balance": float(user.get("usd_balance", 0.0)),
                  "total_earned": float(user.get("total_usd_earned", 0.0)),
                  "total_withdrawn": float(user.get("total_usd_withdrawn", 0.0)),
                  "min_withdrawal": float(settings["withdrawal"]["min"]),
                  "pending": round(pending, 4), "history": usd_hist},
    }

# ─── Referral ──────────────────────────────────────────────────────────────
@app.get("/api/referral")
async def referral(user=Depends(current_user)):
    uid = user["_id"]
    settings = get_settings()
    code = user["referral_code"]
    link = f"{APP_BASE_URL}/?ref={code}"
    total = verified = pending = 0; earnings = 0.0; recent = []
    for d in C_REFERRALS.where(filter=FieldFilter("referrer_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream():
        data = d.to_dict(); total += 1
        if data.get("status") == "verified": verified += 1; earnings += float(data.get("reward_usd", 0.0))
        elif data.get("status") == "pending": pending += 1
        ru = get_user(data["referred_user_id"]) or {}
        recent.append({"display_name": ru.get("display_name") or "User",
                       "status": data.get("status"), "created_at": data.get("created_at")})
    return {"code": code, "link": link, "reward": float(settings["referral"]["reward_usd"]),
            "total": total, "verified": verified, "pending": pending,
            "earnings": round(earnings, 4), "recent": recent[:20]}

# ─── Withdrawals ───────────────────────────────────────────────────────────
@app.get("/api/withdrawals")
async def get_withdrawals(user=Depends(current_user)):
    uid = user["_id"]; out = []
    for d in C_WITHDRAWALS.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream():
        out.append(d.to_dict())
    return {"withdrawals": out}

@app.post("/api/withdrawals")
async def create_withdrawal(body: WithdrawIn, user=Depends(current_user)):
    uid = user["_id"]
    settings = get_settings(); w = settings["withdrawal"]
    min_amt = float(w["min"])
    if body.amount < min_amt: raise HTTPException(400, f"Minimum withdrawal is ${min_amt:.2f}")
    if body.method.lower() not in [m.lower() for m in w["methods"]]:
        raise HTTPException(400, "Unsupported method")
    if not body.account.strip(): raise HTTPException(400, "Account details required")
    for d in C_WITHDRAWALS.where(filter=FieldFilter("user_id", "==", uid)).stream():
        if d.to_dict().get("status") in ("pending","processing"):
            raise HTTPException(400, "You already have a pending withdrawal")
    bal = float(user.get("usd_balance", 0.0))
    if bal < body.amount: raise HTTPException(400, "Insufficient balance")
    def _txn(transaction, uref):
        snap = uref.get(transaction=transaction)
        d = snap.to_dict()
        before = float(d.get("usd_balance", 0.0))
        if before < body.amount: raise HTTPException(400, "Insufficient balance")
        transaction.update(uref, {"usd_balance": round(before - body.amount, 4)})
    _txn(db.transaction(), C_USERS.document(uid))
    txid = "WD-" + secrets.token_hex(4).upper()
    ref = C_WITHDRAWALS.document()
    ref.set({"transaction_id": txid, "user_id": uid,
             "telegram_username": user.get("telegram_username"),
             "display_name": user.get("display_name"),
             "amount": body.amount, "method": body.method,
             "account": body.account, "status": "pending", "created_at": iso(now_utc())})
    usd_ref = C_USD_TX.document()
    usd_ref.set({"transaction_id": usd_ref.id, "user_id": uid, "type": "debit",
                 "amount": -body.amount, "balance_before": bal, "balance_after": round(bal - body.amount, 4),
                 "source": "withdrawal", "reference_id": ref.id,
                 "status": "pending", "created_at": iso(now_utc())})
    asyncio.create_task(notify_admin_withdrawal(ref.id, uid, body, txid))
    notify(uid, "💸 Withdrawal Submitted", f"Request {txid} for ${body.amount:.2f} is pending review.", icon="💸")
    return {"ok": True, "transaction_id": txid}

# ─── Ads ───────────────────────────────────────────────────────────────────
@app.post("/api/ads/claim")
async def ads_claim(user=Depends(current_user)):
    uid = user["_id"]
    settings = get_settings(); m = settings["monetag"]
    if not m["enabled"]: raise HTTPException(400, "Ads disabled")
    used = get_daily_count(uid, "ads")
    if used >= int(m["daily_limit"]): raise HTTPException(400, "Daily ad limit reached")
    last = None
    for d in C_AD_REWARDS.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).stream():
        last = d.to_dict()
    if last:
        try:
            lt = datetime.fromisoformat(last["created_at"])
            if (now_utc() - lt).total_seconds() < int(m["cooldown_seconds"]):
                raise HTTPException(429, "Please wait before next ad")
        except HTTPException: raise
        except Exception: pass
    ref = C_AD_REWARDS.document()
    ref.set({"user_id": uid, "reward": int(m["reward"]), "reward_type": m["reward_type"],
             "created_at": iso(now_utc()), "status": "credited"})
    bump_daily(uid, "ads", 1); bump_daily(uid, "actions", 1)
    if m["reward_type"] == "USD":
        credit_usd(uid, int(m["reward"]) / 100.0, "ad", ref.id)
        return {"amount": int(m["reward"]) / 100.0, "reward_type": "USD"}
    credit_token(uid, int(m["reward"]), "ad", ref.id)
    return {"amount": int(m["reward"]), "reward_type": "TOKEN"}

# ─── Levels ────────────────────────────────────────────────────────────────
@app.get("/api/levels")
async def get_levels(user=Depends(current_user)):
    out = []; cur = int(user.get("level", 1))
    for d in C_LEVELS.order_by("level").stream():
        data = d.to_dict(); data["current"] = int(data["level"]) == cur
        out.append(data)
    return {"levels": out}

# ─── Boosts ────────────────────────────────────────────────────────────────
@app.get("/api/boosts")
async def get_boosts(user=Depends(current_user)):
    uid = user["_id"]; cur_lvl = int(user.get("level", 1)); out = []
    for d in C_BOOSTS.stream():
        data = d.to_dict()
        if not data.get("active", True): continue
        if int(data.get("required_level", 1)) > cur_lvl: continue
        used_today = sum(1 for x in C_BOOST_USES
                         .where(filter=FieldFilter("boost_id", "==", d.id))
                         .where(filter=FieldFilter("user_id", "==", uid)).stream()
                         if x.to_dict().get("created_at","") >= today_key())
        data["id"] = d.id; data["used_today"] = used_today
        data["available_today"] = used_today < int(data.get("daily_limit", 0))
        out.append(data)
    return {"boosts": out}

@app.post("/api/boosts/{boost_id}/activate")
async def activate_boost(boost_id: str, user=Depends(current_user)):
    uid = user["_id"]
    b = C_BOOSTS.document(boost_id).get()
    if not b.exists: raise HTTPException(404, "Boost not found")
    bd = b.to_dict()
    if not bd.get("active", True): raise HTTPException(400, "Boost disabled")
    if int(bd.get("required_level", 1)) > int(user.get("level", 1)):
        raise HTTPException(403, "Level too low")
    used_today = sum(1 for x in C_BOOST_USES
                     .where(filter=FieldFilter("boost_id", "==", boost_id))
                     .where(filter=FieldFilter("user_id", "==", uid)).stream()
                     if x.to_dict().get("created_at","") >= today_key())
    if used_today >= int(bd.get("daily_limit", 0)):
        raise HTTPException(400, "Daily boost limit reached")
    for d in C_BOOST_USES.where(filter=FieldFilter("user_id", "==", uid)).stream():
        if d.to_dict().get("status") == "active":
            d.reference.update({"status": "expired"})
    dur = int(bd.get("duration_seconds", 60))
    ref = C_BOOST_USES.document()
    ref.set({"user_id": uid, "boost_id": boost_id, "name": bd["name"],
             "multiplier": float(bd.get("multiplier", 2.0)),
             "reward_type": bd.get("reward_type", "TOKEN"),
             "duration_seconds": dur,
             "expires_at": iso(now_utc() + timedelta(seconds=dur)),
             "status": "active", "created_at": iso(now_utc())})
    notify(uid, "🚀 Boost Activated", f"{bd['name']} for {dur}s", icon="🚀")
    return {"ok": True, "boost": {"name": bd["name"], "multiplier": bd["multiplier"], "duration_seconds": dur}}

# ─── History / Notifications ───────────────────────────────────────────────
@app.get("/api/history")
async def history(user=Depends(current_user)):
    uid = user["_id"]
    out = {"tokens": [], "usd": [], "withdrawals": []}
    for d in C_TOKEN_TX.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(100).stream():
        out["tokens"].append(d.to_dict())
    for d in C_USD_TX.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(100).stream():
        out["usd"].append(d.to_dict())
    for d in C_WITHDRAWALS.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(100).stream():
        out["withdrawals"].append(d.to_dict())
    return out

@app.get("/api/notifications")
async def notifications(user=Depends(current_user)):
    uid = user["_id"]; out = []
    for d in C_NOTIFICATIONS.where(filter=FieldFilter("user_id", "==", uid))\
            .order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream():
        out.append(d.to_dict())
    return {"notifications": out}

# ═══════════════════════════════════════════════════════════════════════════
# Telegram Bot (Admin Panel)
# ═══════════════════════════════════════════════════════════════════════════
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
ADMIN_PENDING_INPUT: Dict[int, Dict[str, Any]] = {}

async def tg(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TG_API}/{method}", json=payload)
        try: return r.json()
        except Exception: return {"ok": False}

async def send(chat_id: int, text: str, kb: Optional[Dict] = None, parse_mode: str = "HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if kb: payload["reply_markup"] = kb
    return await tg("sendMessage", payload)

def inline(rows): return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}

def main_menu():
    return inline([
        [("📊 Dashboard","adm:dashboard"),("👥 Users","adm:users")],
        [("🎯 Tasks","adm:tasks"),("🌱 Farming","adm:farming")],
        [("⭐ Levels","adm:levels"),("🚀 Boosts","adm:boosts")],
        [("💸 Withdrawals","adm:wd"),("👥 Referrals","adm:ref")],
        [("📺 Monetag","adm:monetag"),("⚙️ Settings","adm:settings")],
        [("📢 Broadcast","adm:broadcast"),("📜 Logs","adm:logs")],
    ])

async def notify_admin_withdrawal(wid, uid, body, txid):
    mask = body.account
    if len(mask) > 4: mask = mask[:3] + "*" * (len(mask) - 4) + mask[-4:]
    text = (f"🚨 <b>NEW WITHDRAWAL</b>\n\n"
            f"👤 User: <code>{uid}</code>\n"
            f"💵 Amount: <b>${body.amount:.2f}</b>\n"
            f"💳 Method: <b>{body.method}</b>\n"
            f"🏦 Account: <code>{mask}</code>\n"
            f"🧾 TX: <code>{txid}</code>")
    kb = inline([[("✅ APPROVE", f"wd:approve:{wid}"),("❌ REJECT", f"wd:reject:{wid}")],
                 [("🔎 VIEW USER", f"usr:view:{uid}")]])
    await send(ADMIN_TELEGRAM_ID, text, kb)

async def handle_update(update):
    if "message" in update:
        m = update["message"]; chat_id = m["chat"]["id"]; from_id = m.get("from",{}).get("id")
        text = m.get("text","")
        if from_id != ADMIN_TELEGRAM_ID:
            if text.startswith("/start"):
                await send(chat_id, "👋 Open the Mini App from the button below to start earning.",
                           {"inline_keyboard": [[{"text":"🚀 Open App","web_app":{"url": APP_BASE_URL}}]]})
            return
        if text.startswith("/start") or text == "/admin":
            await send(chat_id, "👑 <b>ADMIN PANEL</b>\n\nSelect an option:", main_menu()); return
        if chat_id in ADMIN_PENDING_INPUT:
            await handle_admin_input(chat_id, text); return
        return
    if "callback_query" in update:
        cq = update["callback_query"]; from_id = cq["from"]["id"]
        chat_id = cq["message"]["chat"]["id"]; data = cq.get("data","")
        if from_id != ADMIN_TELEGRAM_ID:
            await tg("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "ACCESS DENIED", "show_alert": True}); return
        try: await tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        except Exception: pass
        await handle_callback(chat_id, cq["message"]["message_id"], data)

async def handle_callback(chat_id, msg_id, data):
    parts = data.split(":"); head = parts[0]
    if head == "adm":
        action = parts[1]
        fn = {"dashboard":adm_dashboard,"users":adm_users,"tasks":adm_tasks,"farming":adm_farming,
              "levels":adm_levels,"boosts":adm_boosts,"wd":adm_wd,"ref":adm_ref,"monetag":adm_monetag,
              "settings":adm_settings,"broadcast":adm_broadcast,"logs":adm_logs}.get(action)
        if fn: return await fn(chat_id, msg_id)
    if head == "wd": return await adm_wd_action(chat_id, msg_id, parts[1], parts[2])
    if head == "edit": return await adm_request_edit(chat_id, msg_id, parts[1])
    if head == "task" and parts[1] == "new": return await adm_task_new_start(chat_id, msg_id)
    await send(chat_id, "👑 <b>ADMIN PANEL</b>", main_menu())

async def adm_dashboard(chat_id, msg_id):
    users_total = len(list(C_USERS.stream()))
    users_active = len(list(C_USERS.where(filter=FieldFilter("account_status","==","active")).stream()))
    today = today_key()
    new_users = sum(1 for u in C_USERS.stream() if u.to_dict().get("created_at","") >= today)
    total_tokens = sum(int(u.to_dict().get("total_tokens_earned",0)) for u in C_USERS.stream())
    total_usd = sum(float(u.to_dict().get("total_usd_earned",0.0)) for u in C_USERS.stream())
    refs = len(list(C_REFERRALS.stream()))
    vrefs = len(list(C_REFERRALS.where(filter=FieldFilter("status","==","verified")).stream()))
    pend_wd = len(list(C_WITHDRAWALS.where(filter=FieldFilter("status","==","pending")).stream()))
    done_wd = len(list(C_WITHDRAWALS.where(filter=FieldFilter("status","==","completed")).stream()))
    text = (f"📊 <b>DASHBOARD</b>\n\n"
            f"👥 Total Users: <b>{users_total}</b>\n"
            f"🟢 Active: <b>{users_active}</b>\n"
            f"🆕 New Today: <b>{new_users}</b>\n\n"
            f"🪙 Tokens: <b>{total_tokens:,}</b>\n"
            f"💵 USD: <b>${total_usd:.2f}</b>\n\n"
            f"👥 Referrals: <b>{refs}</b> ({vrefs} verified)\n"
            f"💸 Withdrawals: <b>{pend_wd}</b> pending · {done_wd} done")
    await send(chat_id, text, inline([[("🔙 Back","adm:back")]]))

async def adm_users(chat_id, msg_id):
    recent = list(C_USERS.order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).stream())
    lines = [f"• <code>{u.id}</code> — {u.to_dict().get('display_name','?')}" for u in recent]
    await send(chat_id, "👥 <b>RECENT USERS</b>\n\n" + ("\n".join(lines) or "None"),
               inline([[("🔙 Back","adm:back")]]))

async def adm_tasks(chat_id, msg_id):
    docs = list(C_TASKS.stream())
    lines = [f"• <code>{d.id}</code> {d.to_dict().get('name')}" for d in docs[:15]]
    await send(chat_id, "🎯 <b>TASKS</b>\n\n" + ("\n".join(lines) or "No tasks"),
               inline([[("➕ Add Task","task:new")],[("🔙 Back","adm:back")]]))

async def adm_task_new_start(chat_id, msg_id):
    ADMIN_PENDING_INPUT[chat_id] = {"action":"task_new_step","step":0,"data":{}}
    await send(chat_id, "Send task <b>name</b>:")

async def adm_farming(chat_id, msg_id):
    s = get_settings()["farming"]
    txt = (f"🌱 <b>FARMING</b>\n\n"
           f"Enabled: {'✅' if s['enabled'] else '❌'}\n"
           f"Session: <b>{s['duration_hours']}h</b>\n"
           f"Reward: <b>{s['reward_rate']} {s['reward_type']}</b>\n"
           f"Daily limit: <b>{s['daily_limit']}</b>")
    await send(chat_id, txt, inline([
        [("🔄 Toggle","farming:toggle")],
        [("💱 Edit Reward","edit:farming.reward_rate"),("⏱ Duration","edit:farming.duration_hours")],
        [("🔙 Back","adm:back")]]))

async def adm_levels(chat_id, msg_id):
    lines = []
    for d in C_LEVELS.order_by("level").stream():
        x = d.to_dict()
        lines.append(f"L{x['level']} · XP {x['xp_required']} · {x['daily_farming']}f/{x['daily_tasks']}t/{x['daily_ads']}a")
    await send(chat_id, "⭐ <b>LEVELS</b>\n\n" + "\n".join(lines), inline([[("🔙 Back","adm:back")]]))

async def adm_boosts(chat_id, msg_id):
    lines = [f"• {d.to_dict()['name']} ({d.to_dict()['multiplier']}x/{d.to_dict()['duration_seconds']}s)" for d in C_BOOSTS.stream()]
    await send(chat_id, "🚀 <b>BOOSTS</b>\n\n" + ("\n".join(lines) or "None"), inline([[("🔙 Back","adm:back")]]))

async def adm_wd(chat_id, msg_id):
    docs = list(C_WITHDRAWALS.where(filter=FieldFilter("status","==","pending")).stream())
    if not docs: return await send(chat_id, "💸 No pending withdrawals", inline([[("🔙 Back","adm:back")]]))
    for d in docs[:5]:
        data = d.to_dict()
        txt = (f"💸 <b>WD {data['transaction_id']}</b>\n"
               f"👤 <code>{data['user_id']}</code>\n"
               f"💵 ${data['amount']:.2f} · {data['method']}\n"
               f"🏦 <code>{data['account']}</code>")
        kb = inline([[("✅ APPROVE", f"wd:approve:{d.id}"),("❌ REJECT", f"wd:reject:{d.id}")],
                     [("🔎 VIEW USER", f"usr:view:{data['user_id']}")]])
        await send(chat_id, txt, kb)
    await send(chat_id, "👑", inline([[("🔙 Back","adm:back")]]))

async def adm_wd_action(chat_id, msg_id, action, wid):
    ref = C_WITHDRAWALS.document(wid); snap = ref.get()
    if not snap.exists: return await send(chat_id, "Not found")
    data = snap.to_dict()
    if data.get("status") != "pending": return await send(chat_id, "Already processed")
    uid = data["user_id"]; amount = float(data["amount"])
    if action == "approve":
        ref.update({"status":"completed","processed_at":iso(now_utc())})
        C_USERS.document(uid).update({"total_usd_withdrawn": firestore.Increment(amount)})
        notify(uid, "✅ Withdrawal Approved", f"Withdrawal {data['transaction_id']} approved.", icon="✅")
        await send(chat_id, f"✅ Approved {data['transaction_id']}")
        await send(int(uid), f"✅ Withdrawal {data['transaction_id']} approved for ${amount:.2f}!")
    elif action == "reject":
        def _txn(transaction, uref, wref):
            s = uref.get(transaction=transaction); d = s.to_dict()
            before = float(d.get("usd_balance", 0.0)); after = round(before + amount, 4)
            transaction.update(uref, {"usd_balance": after})
            transaction.update(wref, {"status":"rejected","processed_at":iso(now_utc())})
            tx = C_USD_TX.document()
            transaction.set(tx, {"transaction_id": tx.id, "user_id": uid, "type": "credit",
                                 "amount": amount, "balance_before": before, "balance_after": after,
                                 "source": "withdrawal_refund", "reference_id": wref.id,
                                 "status": "completed", "created_at": iso(now_utc())})
        _txn(db.transaction(), C_USERS.document(uid), ref)
        notify(uid, "❌ Withdrawal Rejected", f"Withdrawal {data['transaction_id']} rejected. Refunded.", icon="❌")
        await send(chat_id, f"❌ Rejected {data['transaction_id']}")
        await send(int(uid), f"❌ Withdrawal {data['transaction_id']} rejected. Refunded.")

async def adm_ref(chat_id, msg_id):
    s = get_settings()["referral"]
    txt = (f"👥 <b>REFERRALS</b>\n\n"
           f"Reward: <b>${s['reward_usd']:.2f}</b>\n"
           f"Enabled: {'✅' if s['enabled'] else '❌'}\n"
           f"Daily limit: <b>{s['daily_limit']}</b>")
    await send(chat_id, txt, inline([
        [("💱 Edit Reward","edit:referral.reward_usd")],
        [("🔙 Back","adm:back")]]))

async def adm_monetag(chat_id, msg_id):
    s = get_settings()["monetag"]
    txt = (f"📺 <b>MONETAG</b>\n\n"
           f"Enabled: {'✅' if s['enabled'] else '❌'}\n"
           f"Zone: <code>{s['zone_id'] or 'not set'}</code>\n"
           f"Reward: <b>{s['reward']} {s['reward_type']}</b>\n"
           f"Daily limit: <b>{s['daily_limit']}</b>")
    await send(chat_id, txt, inline([
        [("💱 Edit Reward","edit:monetag.reward"),("📊 Edit Limit","edit:monetag.daily_limit")],
        [("🔙 Back","adm:back")]]))

async def adm_settings(chat_id, msg_id):
    s = get_settings()
    txt = (f"⚙️ <b>SETTINGS</b>\n\n"
           f"Min withdrawal: <b>${s['withdrawal']['min']:.2f}</b>\n"
           f"Maintenance: <b>{'ON' if s['maintenance']['enabled'] else 'OFF'}</b>")
    await send(chat_id, txt, inline([
        [("💱 Min Withdrawal","edit:withdrawal.min")],
        [("🔧 Toggle Maintenance","s:maintenance")],
        [("🔙 Back","adm:back")]]))

async def adm_broadcast(chat_id, msg_id):
    ADMIN_PENDING_INPUT[chat_id] = {"action":"broadcast"}
    await send(chat_id, "📢 Send broadcast text now:")

async def adm_logs(chat_id, msg_id):
    docs = list(C_ADMIN_LOGS.order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).stream())
    lines = [f"• {d.to_dict().get('action')} ({d.to_dict().get('created_at','')[:19]})" for d in docs]
    await send(chat_id, "📜 <b>LOGS</b>\n\n" + ("\n".join(lines) or "Empty"),
               inline([[("🔙 Back","adm:back")]]))

async def adm_request_edit(chat_id, msg_id, key):
    ADMIN_PENDING_INPUT[chat_id] = {"action":"edit","key":key}
    await send(chat_id, f"✏️ Send new value for <code>{key}</code>:")

async def handle_admin_input(chat_id, text):
    state = ADMIN_PENDING_INPUT.pop(chat_id)
    action = state.get("action")
    if action == "edit":
        key = state["key"]; grp, field = key.split(".", 1)
        try:
            if field.endswith("_usd") or field in ("min","fee_pct"): val = float(text)
            elif field in ("enabled","require_verification"): val = text.lower() in ("true","1","yes","on")
            else: val = int(text) if text.strip().lstrip("-").isdigit() else float(text)
        except Exception:
            await send(chat_id, "❌ Invalid value"); return
        save_settings({grp: {field: val}})
        await send(chat_id, f"✅ <code>{key}</code> = <b>{val}</b>")
        log_admin(chat_id, "edit_setting", {"key":key,"value":val}); return
    if action == "broadcast":
        sent = failed = 0
        for d in C_USERS.stream():
            try:
                r = await send(int(d.id), text)
                sent += 1 if r.get("ok") else 0
                failed += 0 if r.get("ok") else 1
            except Exception: failed += 1
            await asyncio.sleep(0.05)
        await send(chat_id, f"📢 Broadcast: {sent} sent, {failed} failed"); return
    if action == "task_new_step":
        step = state["step"]; data = state["data"]
        fields = ["name","description","platform","url","reward","reward_type","daily_limit","verification"]
        data[fields[step]] = text.strip(); step += 1
        if step >= len(fields):
            try:
                data["reward"] = int(data["reward"]); data["daily_limit"] = int(data["daily_limit"])
            except Exception:
                await send(chat_id, "❌ Reward/limit must be integers"); return
            data["status"] = "enabled"; data["created_at"] = iso(now_utc())
            ref = C_TASKS.document(); ref.set(data)
            await send(chat_id, f"✅ Task created: <code>{ref.id}</code>")
        else:
            ADMIN_PENDING_INPUT[chat_id] = {"action":"task_new_step","step":step,"data":data}
            await send(chat_id, f"Send <b>{fields[step]}</b>:")

def log_admin(chat_id, action, data):
    C_ADMIN_LOGS.document().set({"admin_id": chat_id, "action": action,
                                 "data": data, "created_at": iso(now_utc())})

async def poll_bot():
    offset = 0
    while True:
        try:
            r = await tg("getUpdates", {"timeout": 25, "offset": offset})
            if r.get("ok"):
                for u in r.get("result", []):
                    offset = u["update_id"] + 1
                    try: await handle_update(u)
                    except Exception as e: log.exception("handle_update: %s", e)
        except Exception as e:
            log.warning("poll_bot: %s", e); await asyncio.sleep(3)

@app.on_event("startup")
async def startup():
    try: ensure_defaults()
    except Exception as e: log.error("ensure_defaults: %s", e)
    asyncio.create_task(poll_bot())

@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("Unhandled: %s\n%s", exc, traceback.format_exc())
    return JSONResponse({"error": "Internal server error"}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, workers=1)
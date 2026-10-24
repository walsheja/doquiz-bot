from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import os
import random
import time
import traceback
import re
import math
import firebase_admin
from firebase_admin import credentials, firestore

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8940346683:AAGaVYxUws6ZNYcP1joO8NGiyWgqsUSBk7A")
BOT_USERNAME = "DoquizGame"
DEFAULT_CHANNEL = "@yashrahly"
ADMIN_IDS = [593866129, 479584086]
WEBHOOK_URL = "https://doquiz-bot.vercel.app/api/index"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "DoquizSecret_9a8f27bc41de8053a")
MAINTENANCE_MODE = False

_db = None

def get_firestore_db():
    global _db
    if _db is not None:
        return _db

    # 1. First priority: Environment variable
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")
    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            _db = firestore.client()
            return _db
        except Exception as e:
            print(f"Error initializing Firebase from FIREBASE_CREDENTIALS env: {e}")

    # 2. Second priority: Local file paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(base_dir, "firebase_credentials.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase_credentials.json"),
        os.path.join(os.getcwd(), "firebase_credentials.json"),
        "firebase_credentials.json"
    ]
    for cred_path in possible_paths:
        if os.path.exists(cred_path):
            try:
                if not firebase_admin._apps:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                _db = firestore.client()
                return _db
            except Exception as e:
                print(f"Error initializing Firebase from {cred_path}: {e}")

    raise RuntimeError("Could not initialize Firebase: credentials not found in env or files.")

def clean_latex(text: str) -> str:
    if not text:
        return ""
    s = text
    s = re.sub(r'\\text\s*\{\s*([^}]*)\s*\}', r' \1 ', s)
    s = s.replace(r'\le', ' ≤ ')
    s = s.replace(r'\ge', ' ≥ ')
    s = s.replace(r'\rightarrow', ' → ')
    s = s.replace(r'\leftarrow', ' ← ')
    s = s.replace(r'\pm', ' ± ')
    s = s.replace(r'\times', ' × ')
    s = s.replace(r'\mu', ' µ')
    s = s.replace(r'\alpha', ' α ')
    s = s.replace(r'\beta', ' β ')
    s = s.replace(r'\gamma', ' γ ')
    s = re.sub(r'Sb\^\{\s*5\+\s*\}', 'Sb⁵⁺', s)
    s = re.sub(r'Fe\^\{\s*2\+\s*\}', 'Fe²⁺', s)
    s = re.sub(r'bc_1', 'bc₁', s)
    s = s.replace('$', '')
    s = s.replace('\\', '')
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s+([,.:;?!])', r'\1', s)
    s = re.sub(r'\(\s+', '(', s)
    s = re.sub(r'\s+\)', ')', s)
    return s.strip()

def get_questions_bank():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(base_dir, "questions.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json"),
        os.path.join(os.getcwd(), "questions.json"),
        "questions.json"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("questions.json not found in any expected location.")

def call_telegram(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"Telegram HTTPError in {method} (code {e.code}): {err_body}")
        try:
            return json.loads(err_body)
        except Exception:
            return {"ok": False, "error": err_body}
    except Exception as e:
        print(f"Error calling telegram {method}: {e}")
        return {"ok": False, "error": str(e)}

def ensure_webhook():
    try:
        info_res = call_telegram("getWebhookInfo", {})
        current_url = info_res.get("result", {}).get("url", "")
        if current_url != WEBHOOK_URL:
            print(f"Webhook was disconnected or incorrect ('{current_url}'). Auto-healing to {WEBHOOK_URL}...")
            call_telegram("setWebhook", {
                "url": WEBHOOK_URL,
                "allowed_updates": ["message", "callback_query", "poll", "poll_answer"],
                "secret_token": WEBHOOK_SECRET,
                "drop_pending_updates": False
            })
            return {"status": "re-healed", "previous": current_url, "current": WEBHOOK_URL}
        return {
            "status": "healthy",
            "url": current_url,
            "pending": info_res.get("result", {}).get("pending_update_count", 0)
        }
    except Exception as e:
        print(f"Error checking/healing webhook: {e}")
        return {"status": "error", "error": str(e)}

def get_blocks_keyboard():
    data = get_questions_bank()
    keyboard = []
    for key, block in data.items():
        # Exclude combined/comprehensive subjects from the total sum to prevent duplication!
        unique_q_ids = set()
        for sk, s in block.get("subjects", {}).items():
            if sk.endswith("_all") or sk == "all" or sk == "para_all":
                continue
            for q in s.get("questions", []):
                qid = q.get("id") if isinstance(q, dict) else str(q)
                unique_q_ids.add(qid)
        total_q = len(unique_q_ids)
        badge = f" ({total_q})" if total_q > 0 else ""
        keyboard.append([{"text": f"{block['title']}{badge}", "callback_data": f"blk:{key}"}])
    return {"inline_keyboard": keyboard}

def get_subjects_keyboard(block_key: str):
    data = get_questions_bank()
    block = data.get(block_key, {})
    subjects = block.get("subjects", {})
    keyboard = []
    for key, subj in subjects.items():
        q_count = len(subj.get("questions", []))
        badge = f" ({q_count})" if q_count > 0 else ""
        keyboard.append([{"text": f"{subj['title']}{badge}", "callback_data": f"subj:{block_key}:{key}"}])
    keyboard.append([{"text": "🔙 رجوع للقائمة الرئيسية", "callback_data": "back_blocks"}])
    return {"inline_keyboard": keyboard}

def get_timer_keyboard(block_key: str, subject_key: str, current_minutes: int):
    next_plus = min(30, current_minutes + 5)
    next_minus = max(0, current_minutes - 5)

    back_text = "🔙 رجوع للموضوعات" if block_key == "parasitology" else "🔙 رجوع للمواد"

    return {
        "inline_keyboard": [
            [
                {"text": "🔼 +5 دقائق", "callback_data": f"time_adj:{block_key}:{subject_key}:{next_plus}"},
                {"text": "🔽 -5 دقائق", "callback_data": f"time_adj:{block_key}:{subject_key}:{next_minus}"}
            ],
            [
                {"text": "♾️ وقت مفتوح (بدون مؤقت)", "callback_data": f"time_adj:{block_key}:{subject_key}:0"}
            ],
            [
                {"text": "🚀 بدء الجولة الآن (20)", "callback_data": f"start_round:{block_key}:{subject_key}:{current_minutes}"}
            ],
            [
                {"text": back_text, "callback_data": f"blk:{block_key}"},
                {"text": "🏠 القائمة الرئيسية", "callback_data": "back_blocks"}
            ]
        ]
    }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        health_info = ensure_webhook() if not MAINTENANCE_MODE else {"maintenance": True, "webhook_active": False}
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "maintenance" if MAINTENANCE_MODE else "ok",
            "service": "Doquiz Medical Telegram Bot on Vercel with Firestore State",
            "bot": f"@{BOT_USERNAME}",
            "maintenance_mode": MAINTENANCE_MODE,
            "webhook_health": health_info
        }, ensure_ascii=False, indent=2).encode("utf-8"))

    def do_POST(self):
        # 1. التحقق الصارم من التوكن السري القادم من خوادم تيليجرام فقط
        secret_header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Forbidden: Invalid secret token"}')
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            update = json.loads(post_data.decode("utf-8"))
            self.process_update(update)
        except Exception as e:
            print(f"Error processing update in do_POST: {e}")
            traceback.print_exc()
        finally:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

    def process_update(self, update: dict):
        # وضع الصيانة العام (إيقاف البوت عن المستخدمين العاديين)
        if MAINTENANCE_MODE:
            chat_id = None
            if "message" in update and "chat" in update["message"]:
                chat_id = update["message"]["chat"]["id"]
            elif "callback_query" in update and "message" in update["callback_query"] and "chat" in update["callback_query"]["message"]:
                chat_id = update["callback_query"]["message"]["chat"]["id"]
            
            if chat_id not in ADMIN_IDS:
                if "message" in update and chat_id:
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": "🛠 **البوت متوقف حالياً لأعمال الصيانة والتحديثات الدورية.**\nسنعود قريباً بإذن الله! 🩺✨",
                        "parse_mode": "Markdown"
                    })
                elif "callback_query" in update:
                    call_telegram("answerCallbackQuery", {
                        "callback_query_id": update["callback_query"]["id"],
                        "text": "🛠 البوت في وضع الصيانة حالياً.",
                        "show_alert": True
                    })
                return

        # 1. الرسائل النصية
        if "message" in update:
            msg = update["message"]
            text = msg.get("text", "")
            chat_id = msg["chat"]["id"]
            first_name = msg.get("from", {}).get("first_name", "دكتور")
            username = msg.get("from", {}).get("username", "")

            # حفظ وتحديث المشترك في قاعدة البيانات السحابية
            try:
                db = get_firestore_db()
                db.collection("doquiz_subscribers").document(str(chat_id)).set({
                    "chat_id": chat_id,
                    "first_name": first_name,
                    "username": username,
                    "last_active": time.time()
                }, merge=True)
            except Exception as e:
                pass

            if text.startswith("/start"):
                welcome = (
                    f"مرحباً بك يا **{first_name}** في بوت **Doquiz** 🧠✨\n\n"
                    "👇 اختر ما ترغب في اختباره:"
                )
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })

            elif text.startswith("/stop") or text.startswith("/cancel"):
                try:
                    db = get_firestore_db()
                    session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
                    if session_doc.exists:
                        session = session_doc.to_dict()
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": "🛑 **تم إيقاف الاختبار بناءً على طلبك.**\nجاري احتساب نتيجتك لما تم حله حتى الآن...",
                            "parse_mode": "Markdown"
                        })
                        self.finish_round(chat_id, session)
                    else:
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": "لا يوجد اختبار نشط حالياً لإيقافه. يمكنك بدء اختبار جديد عبر القائمة أدناه 🩺",
                            "reply_markup": get_blocks_keyboard()
                        })
                except Exception as e:
                    print(f"Stop command error: {e}")
                    traceback.print_exc()

            elif text.startswith("/resume") or text.startswith("/continue"):
                try:
                    db = get_firestore_db()
                    session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
                    if session_doc.exists:
                        session = session_doc.to_dict()
                        cur_idx = session.get("current_index", 0)
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"🔄 **جاري استئناف الجولة من السؤال ({cur_idx + 1}/{session.get('total', 20)})...**",
                            "parse_mode": "Markdown"
                        })
                        self.send_question(chat_id, cur_idx)
                    else:
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": "لا يوجد اختبار نشط حالياً لاستئنافه. يمكنك بدء اختبار جديد عبر القائمة أدناه 🩺",
                            "reply_markup": get_blocks_keyboard()
                        })
                except Exception as e:
                    print(f"Resume command error: {e}")
                    traceback.print_exc()

            elif text.startswith("/admin") or text.startswith("/stats") or text.startswith("/count") or text.startswith("/users") or text.startswith("/subscribers") or text in ["إحصائيات", "المشتركين", "لوحة التحكم"]:
                if chat_id in ADMIN_IDS:
                    self.render_admin_dashboard(chat_id)

            elif text.startswith("/broadcast"):
                if chat_id not in ADMIN_IDS:
                    return
                broadcast_content = text.replace("/broadcast", "").strip()
                if not broadcast_content:
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": "⚠️ **يرجى كتابة نص الرسالة بعد الأمر، مثال:**\n`/broadcast تحديث جديد: تم إضافة أسئلة...`",
                        "parse_mode": "Markdown"
                    })
                else:
                    try:
                        db = get_firestore_db()
                        subs = list(db.collection("doquiz_subscribers").stream())
                        sent_count = 0
                        for s in subs:
                            u_chat_id = s.to_dict().get("chat_id") or s.id
                            res = call_telegram("sendMessage", {
                                "chat_id": u_chat_id,
                                "text": broadcast_content,
                                "reply_markup": {
                                    "inline_keyboard": [
                                        [{"text": "🚀 ابدأ جولة الاختبار الآن", "url": f"https://t.me/{BOT_USERNAME}?start=broadcast"}]
                                    ]
                                }
                            })
                            if res.get("ok"):
                                sent_count += 1
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"✅ **تم إرسال الإشعار والتحديث بنجاح إلى {sent_count} من مستخدمي البوت.**",
                            "parse_mode": "Markdown"
                        })
                    except Exception as e:
                        print(f"Broadcast error: {e}")

            elif text.startswith("/post"):
                if chat_id not in ADMIN_IDS:
                    return
                parts = text.split()
                target = parts[1] if len(parts) > 1 else DEFAULT_CHANNEL
                announcement = (
                    "🩺 **بوت نماذج واختبارات الطب البشري (Doquiz)** 🧠✨\n\n"
                    "نقدّم لطلابنا الأعزاء تجربة اختبارات تفاعلية بنظام الجولات السريرية الذكية (20 سؤالاً):\n\n"
                    "🩸 **بلوك Blood & Lymph** (مكتمل بالكامل: باثولوجي 174 | فارماكولوجي 123 | ميكروبيولوجي 120)\n"
                    "🧬 **بلوك Introduction 1** (باثولوجي 453 | تشريح 204 | أجنة 117)\n"
                    "🔹 نظام تكيفي ذكي يركز على نقاط الضعف ويثبت المعلومات الطبية\n"
                    "🔹 مؤقت زمني اختياري وشرح سريري تفصيلي لكل سؤال\n\n"
                    "👇 اضغط على الزر أدناه لبدء اختبارك مباشرة في البوت:"
                )
                res = call_telegram("sendMessage", {
                    "chat_id": target,
                    "text": announcement,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🚀 ابدأ جولة الاختبار الآن", "url": f"https://t.me/{BOT_USERNAME}?start=channel"}]
                        ]
                    }
                })
                if res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"✅ تم نشر إعلان الاختبار بنجاح في القناة: {target}"
                    })
                else:
                    err_desc = res.get("description") or res.get("error") or "خطأ غير معروف"
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": (
                            f"⚠️ **تعذر النشر في القناة ({target}):**\n`{err_desc}`\n\n"
                            f"💡 **تأكد من:**\n"
                            f"1. إضافة البوت **@{BOT_USERNAME}** كمشرف (Admin) في القناة.\n"
                            f"2. منحه صلاحية **نشر الرسائل (Post Messages)**."
                        ),
                        "parse_mode": "Markdown"
                    })

        # 2. ضغطات الأزرار (Callback Queries)
        elif "callback_query" in update:
            cb = update["callback_query"]
            data = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]

            call_telegram("answerCallbackQuery", {
                "callback_query_id": cb["id"],
                "text": "تم الاختيار 🩺"
            })

            if data == "admin_noop":
                return

            elif data.startswith("admin_"):
                if chat_id not in ADMIN_IDS:
                    return
                if data == "admin_refresh" or data == "admin_back":
                    self.render_admin_dashboard(chat_id, msg_id)
                elif data.startswith("admin_users:"):
                    page = int(data.split(":")[1])
                    self.render_admin_users_page(chat_id, page, msg_id)
                elif data == "admin_clean_sessions":
                    self.clean_old_sessions(chat_id, msg_id)
                elif data == "admin_help_bc":
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": (
                            "📢 <b>طريقة إرسال برودكاست لجميع المشتركين:</b>\n\n"
                            "أرسل رسالة تبدأ بـ <code>/broadcast</code> متبوعة بنص رسالتك، مثال:\n\n"
                            "<code>/broadcast دكاترتنا الأعزاء، تم إضافة أسئلة جديدة! 🩺✨</code>\n\n"
                            "وسيقوم البوت بإرسالها فوراً إلى جميع المشتركين مع زر دخول للاختبار."
                        ),
                        "parse_mode": "HTML",
                        "reply_markup": {
                            "inline_keyboard": [
                                [{"text": "🔙 العودة للوحة التحكم", "callback_data": "admin_back"}],
                                [{"text": "🏠 قائمة الاختبارات", "callback_data": "back_blocks"}]
                            ]
                        }
                    })
                elif data == "admin_post_ch":
                    self.post_announcement_to_channel(chat_id)

            elif data == "back_blocks":
                welcome = "👇 **الخطوة 1:** اختر ما ترغب في اختباره:"
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": welcome,
                        "parse_mode": "Markdown",
                        "reply_markup": get_blocks_keyboard()
                    })

            elif data.startswith("blk:"):
                block_key = data.split(":")[1]
                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                
                if block_key == "parasitology":
                    header_label = "المادة المختارة"
                    step_text = "👇 **الخطوة 2:** اختر الموضوع الذي ترغب باختباره:"
                else:
                    header_label = "البلوك المختار"
                    step_text = "👇 **الخطوة 2:** اختر المادة التي ترغب باختبارها:"

                desc_line = f"ℹ️ {block.get('description')}\n\n" if block.get("description") else ""
                text = (
                    f"🩸 **{header_label}:** {block.get('title', '')}\n"
                    f"{desc_line}"
                    f"{step_text}"
                )
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_subjects_keyboard(block_key)
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_subjects_keyboard(block_key)
                    })

            elif data.startswith("subj:"):
                _, block_key, subject_key = data.split(":")
                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                questions = subj.get("questions", [])
                total_bank = len(questions)

                if total_bank == 0:
                    text = (
                        f"🩺 **{block.get('title', '')}** ➔ **{subj.get('title', '')}**\n\n"
                        "⚠️ **بنك أسئلة هذا القسم قيد الإعداد والتجهيز!**\n"
                        "سيتم إتاحته قريباً بإذن الله عند اكتمال ملفات الأسئلة. 🩺\n\n"
                        "👈 يرجى اختيار قسم مفعل حالياً."
                    )
                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": "🔙 رجوع", "callback_data": f"blk:{block_key}"}],
                            [{"text": "🏠 القائمة الرئيسية", "callback_data": "back_blocks"}]
                        ]
                    }
                    res = call_telegram("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    })
                    if not res.get("ok"):
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                            "reply_markup": reply_markup
                        })
                    return

                if block_key == "parasitology":
                    sec_info = f"🦠 **المادة:** {block.get('title', '')}\n📂 **الموضوع:** {subj.get('title', '')}"
                else:
                    sec_info = f"🩸 **البلوك:** {block.get('title', '')}\n📚 **المادة:** {subj.get('title', '')}"

                text = (
                    f"{sec_info}\n"
                    f"📊 إجمالي بنك الأسئلة المتاح: ({total_bank})\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** (20) في كل مرحلة.\n"
                    "💡 يتم تقديم الأسئلة غير المختبرة سابقاً أولاً، ثم الأسئلة التي تحتاج إلى تثبيت.\n\n"
                    "⏱️ **الوقت المحدد للجولة:** **[ مفتوح ♾️ (بدون مؤقت) ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
                )
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, 0)
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_timer_keyboard(block_key, subject_key, 0)
                    })

            elif data.startswith("time_adj:"):
                parts = data.split(":")
                block_key = parts[1]
                subject_key = parts[2]
                new_minutes = int(parts[3])

                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                total_bank = len(subj.get("questions", []))

                time_display = "مفتوح ♾️ (بدون مؤقت)" if new_minutes == 0 else f"{new_minutes} دقيقة ⏱️"

                if block_key == "parasitology":
                    sec_info = f"🦠 **المادة:** {block.get('title', '')}\n📂 **الموضوع:** {subj.get('title', '')}"
                else:
                    sec_info = f"🩸 **البلوك:** {block.get('title', '')}\n📚 **المادة:** {subj.get('title', '')}"

                text = (
                    f"{sec_info}\n"
                    f"📊 إجمالي بنك الأسئلة المتاح: ({total_bank})\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** (20) في كل مرحلة.\n"
                    "💡 يتم تقديم الأسئلة غير المختبرة سابقاً أولاً، ثم الأسئلة التي تحتاج إلى تثبيت.\n\n"
                    f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, new_minutes)
                })

            elif data.startswith("start_round:"):
                _, block_key, subject_key, mins_str = data.split(":")
                self.launch_round(chat_id, block_key, subject_key, int(mins_str), msg_id)

            elif data.startswith("new_round:"):
                _, block_key, subject_key = data.split(":")
                self.clean_previous_round(chat_id)
                self.launch_round(chat_id, block_key, subject_key, 0)

        # 3. حل السؤال (Poll Answer)
        elif "poll_answer" in update:
            ans = update["poll_answer"]
            user_id = ans.get("user", {}).get("id")
            poll_id = str(ans.get("poll_id"))
            selected_option = ans["option_ids"][0] if ans.get("option_ids") else None

            print(f"Update poll_answer received for user {user_id}, poll {poll_id}, option {selected_option}")
            self.handle_poll_answer(user_id, poll_id, selected_option)

    def render_admin_dashboard(self, chat_id: int, msg_id: int = None):
        try:
            db = get_firestore_db()
            subs = list(db.collection("doquiz_subscribers").stream())
            total_subs = len(subs)

            users = list(db.collection("doquiz_users").stream())
            total_users = len(users)

            sessions = list(db.collection("doquiz_sessions").stream())
            active_sessions = len(sessions)

            hook_info = ensure_webhook()
            hook_status = "متصل وسليم بنجاح ✅" if hook_info.get("status") in ["healthy", "re-healed"] else "⚠️ به مشكلة"

            text = (
                "🎛️ <b>لوحة تحكم مشرف البوت (Admin Dashboard)</b> 🧠✨\n\n"
                f"👥 <b>إجمالي المشتركين الكلي:</b> <code>{total_subs}</code> مشترك\n"
                f"🎯 <b>الطلاب المتفاعلون بالاختبارات:</b> <code>{total_users}</code> طالب\n"
                f"⚡ <b>الجلسات المفتوحة في السيرفر:</b> <code>{active_sessions}</code> جلسة\n"
                f"🔗 <b>اتصال تيليجرام (Webhook):</b> {hook_status}\n\n"
                "💡 <i>الجلسات المفتوحة هي وثائق ساكنة ومحفوظة؛ لا تستهلك أي قراءات أو معالجة أثناء خمول الطالب.</i>\n\n"
                "👇 <b>اختر الإجراء المطلوب:</b>"
            )

            keyboard = {
                "inline_keyboard": [
                    [{"text": f"👥 تفاصيل المشتركين ({total_subs}) - 20 بالصفحة", "callback_data": "admin_users:1"}],
                    [
                        {"text": "📢 إرسال برودكاست", "callback_data": "admin_help_bc"},
                        {"text": "📣 نشر بالقناة", "callback_data": "admin_post_ch"}
                    ],
                    [
                        {"text": "🧹 تنظيف الجلسات القديمة", "callback_data": "admin_clean_sessions"},
                        {"text": "🔄 تحديث الإحصائيات", "callback_data": "admin_refresh"}
                    ],
                    [
                        {"text": "🏠 قائمة الاختبارات الرئيسية", "callback_data": "back_blocks"}
                    ]
                ]
            }

            if msg_id:
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard
                    })
            else:
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                })
        except Exception as e:
            print(f"Error rendering admin dashboard: {e}")
            traceback.print_exc()

    def render_admin_users_page(self, chat_id: int, page: int = 1, msg_id: int = None):
        try:
            db = get_firestore_db()
            subs = list(db.collection("doquiz_subscribers").stream())

            def get_la(doc):
                return doc.to_dict().get("last_active", 0)
            subs_sorted = sorted(subs, key=get_la, reverse=True)

            per_page = 20
            total_items = len(subs_sorted)
            total_pages = max(1, math.ceil(total_items / per_page))
            page = max(1, min(page, total_pages))

            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            current_slice = subs_sorted[start_idx:end_idx]

            lines = []
            for i, s in enumerate(current_slice, start=start_idx + 1):
                sd = s.to_dict()
                name = str(sd.get("first_name", "طبيب")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                un = sd.get("username")
                user_str = f"@{un}" if un else f"ID: {s.id}"
                user_str = user_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                la = sd.get("last_active")
                t_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(la)) if la else "غير مسجل"
                lines.append(f"<b>{i}. {name}</b> ({user_str})\n   └ آخر نشاط: <code>{t_str}</code>")

            content = "\n".join(lines) if lines else "لا يوجد مشتركون مسجلون."

            text = (
                f"👥 <b>قائمة المشتركين بالتفصيل</b>\n"
                f"📊 الإجمالي: <code>{total_items}</code> مشترك | صفحة <b>{page}</b> من <b>{total_pages}</b>\n"
                "──────────────────\n"
                f"{content}\n"
                "──────────────────\n"
                f"💡 <i>المعروض 20 مشتركاً في الصفحة منعاً للإزعاج.</i>"
            )

            nav_row = []
            if page > 1:
                nav_row.append({"text": "⬅️ السابقة", "callback_data": f"admin_users:{page - 1}"})
            nav_row.append({"text": f"صفحة {page} / {total_pages}", "callback_data": "admin_noop"})
            if page < total_pages:
                nav_row.append({"text": "التالية ➡️", "callback_data": f"admin_users:{page + 1}"})

            keyboard = {
                "inline_keyboard": [
                    nav_row,
                    [
                        {"text": "🔙 العودة للوحة التحكم", "callback_data": "admin_back"},
                        {"text": "🏠 قائمة الاختبارات", "callback_data": "back_blocks"}
                    ]
                ]
            }

            if msg_id:
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard
                    })
            else:
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                })
        except Exception as e:
            print(f"Error rendering admin users page: {e}")
            traceback.print_exc()

    def clean_old_sessions(self, chat_id: int, msg_id: int = None):
        try:
            db = get_firestore_db()
            sessions = list(db.collection("doquiz_sessions").stream())
            now = time.time()
            cleaned_count = 0
            for s in sessions:
                sd = s.to_dict()
                started_at = sd.get("started_at", 0)
                if (now - started_at) > (24 * 3600):
                    db.collection("doquiz_sessions").document(s.id).delete()
                    cleaned_count += 1

            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ <b>تم تنظيف <code>{cleaned_count}</code> جلسة معلقة غير نشطة (أقدم من 24 ساعة).</b>",
                "parse_mode": "HTML"
            })
            self.render_admin_dashboard(chat_id, msg_id)
        except Exception as e:
            print(f"Error cleaning sessions: {e}")

    def post_announcement_to_channel(self, chat_id: int):
        announcement = (
            "🩺 **بوت نماذج واختبارات الطب البشري (Doquiz)** 🧠✨\n\n"
            "نقدّم لطلابنا الأعزاء تجربة اختبارات تفاعلية بنظام الجولات السريرية الذكية (20 سؤالاً):\n\n"
            "🩸 **بلوك Blood & Lymph** (مكتمل بالكامل: باثولوجي 174 | فارماكولوجي 123 | ميكروبيولوجي 120)\n"
            "🧬 **بلوك Introduction 1** (باثولوجي 453 | تشريح 204 | أجنة 117)\n"
            "🔹 نظام تكيفي ذكي يركز على نقاط الضعف ويثبت المعلومات الطبية\n"
            "🔹 مؤقت زمني اختياري وشرح سريري تفصيلي لكل سؤال\n\n"
            "👇 اضغط على الزر أدناه لبدء اختبارك مباشرة في البوت:"
        )
        res = call_telegram("sendMessage", {
            "chat_id": DEFAULT_CHANNEL,
            "text": announcement,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "🚀 ابدأ جولة الاختبار الآن", "url": f"https://t.me/{BOT_USERNAME}?start=channel"}]
                ]
            }
        })
        if res.get("ok"):
            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ تم نشر الإعلان بنجاح في القناة {DEFAULT_CHANNEL} 🩺"
            })
        else:
            err = res.get("description") or res.get("error") or "خطأ غير معروف"
            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": f"⚠️ تعذر النشر في القناة ({DEFAULT_CHANNEL}):\n`{err}`",
                "parse_mode": "Markdown"
            })

    def clean_previous_round(self, chat_id: int):
        try:
            db = get_firestore_db()
            session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
            if session_doc.exists:
                session = session_doc.to_dict()
                for m_id in session.get("poll_msg_ids", []):
                    call_telegram("deleteMessage", {"chat_id": chat_id, "message_id": m_id})
                db.collection("doquiz_sessions").document(str(chat_id)).update({"poll_msg_ids": []})
        except Exception as e:
            print(f"Clean round error: {e}")

    def select_round_questions(self, chat_id: int, questions: list) -> list:
        try:
            db = get_firestore_db()
            user_doc = db.collection("doquiz_users").document(str(chat_id)).get()
            history = {}
            if user_doc.exists:
                history = user_doc.to_dict().get("history", {})

            unseen = [q for q in questions if q.get("id") not in history]
            failed = [q for q in questions if history.get(q.get("id")) is False]
            mastered = [q for q in questions if history.get(q.get("id")) is True]

            random.shuffle(unseen)
            random.shuffle(failed)
            random.shuffle(mastered)

            selected = (unseen + failed)[:20]
            if len(selected) < 20 and mastered:
                selected.extend(mastered[:(20 - len(selected))])

            if len(selected) < 20:
                remaining = [q for q in questions if q not in selected]
                random.shuffle(remaining)
                selected.extend(remaining[:(20 - len(selected))])

            random.shuffle(selected)
            return selected[:min(len(questions), 20)]
        except Exception as e:
            print(f"Error in select_round_questions: {e}")
            return random.sample(questions, min(len(questions), 20))

    def shuffle_question_options(self, q: dict) -> dict:
        q_copy = dict(q)
        opts = list(q_copy.get("options", []))
        cid = q_copy.get("correct_id") if q_copy.get("correct_id") is not None else q_copy.get("correct_index")
        if cid is None or cid >= len(opts) or len(opts) < 2:
            return q_copy
        correct_opt = opts[cid]

        last_is_special = any(k in opts[-1].lower() for k in [
            'none of above', 'none of the above', 'all of above', 'all of the above',
            'all of the above are correct', 'none of the above are correct'
        ])

        if last_is_special and len(opts) > 2:
            sub = opts[:-1]
            random.shuffle(sub)
            new_opts = sub + [opts[-1]]
        else:
            new_opts = list(opts)
            random.shuffle(new_opts)

        new_cid = new_opts.index(correct_opt)
        q_copy["options"] = new_opts
        q_copy["correct_id"] = new_cid
        q_copy["correct_index"] = new_cid
        return q_copy

    def launch_round(self, chat_id: int, block_key: str, subject_key: str, minutes: int, edit_msg_id: int = None):
        data_bank = get_questions_bank()
        block = data_bank.get(block_key, {})
        subj = block.get("subjects", {}).get(subject_key, {})
        questions = subj.get("questions", [])

        if not questions:
            call_telegram("sendMessage", {"chat_id": chat_id, "text": "لا توجد أسئلة متوفرة حالياً في هذه المادة."})
            return

        selected = self.select_round_questions(chat_id, questions)
        shuffled_round_questions = [self.shuffle_question_options(q) for q in selected]

        session_data = {
            "block_key": block_key,
            "subject_key": subject_key,
            "block_title": block.get("title", ""),
            "subject_title": subj.get("title", ""),
            "questions": shuffled_round_questions,
            "current_index": 0,
            "score": 0,
            "total": len(selected),
            "minutes": minutes,
            "started_at": time.time(),
            "poll_msg_ids": [],
            "status": "active"
        }

        db = get_firestore_db()
        db.collection("doquiz_sessions").document(str(chat_id)).set(session_data)

        time_info = "مفتوح ♾️ (بدون ضغط وقت)" if minutes == 0 else f"{minutes} دقيقة للجولة بالكامل ⏱️"

        start_text = (
            f"🚀 **بدء جولة جديدة ({len(selected)}):**\n"
            f"📂 {block.get('title', '')} ➔ {subj.get('title', '')}\n"
            f"⏱️ {time_info}\n\n"
            "بالتوفيق يا دكتور! 🩺✨"
        )

        if edit_msg_id:
            call_telegram("editMessageText", {
                "chat_id": chat_id,
                "message_id": edit_msg_id,
                "text": start_text,
                "parse_mode": "Markdown"
            })
        else:
            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": start_text,
                "parse_mode": "Markdown"
            })

        # إرسال السؤال الأول
        self.send_question(chat_id, 0)

    def send_question(self, chat_id: int, index: int):
        db = get_firestore_db()
        session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
        if not session_doc.exists:
            print(f"Session not found for chat_id {chat_id}")
            return
        session = session_doc.to_dict()

        if index >= session.get("total", 0):
            self.finish_round(chat_id, session)
            return

        questions = session.get("questions", [])
        if index >= len(questions):
            self.finish_round(chat_id, session)
            return

        q = questions[index]
        
        header = f"({index + 1}/{session['total']}) "
        raw_q_text = clean_latex(q.get("question", "").strip())
        full_q = header + raw_q_text
        if len(full_q) <= 300:
            q_text = full_q
        else:
            # إذا كان نص السؤال كبيراً أو حالة سريرية تتجاوز 300 حرف
            # يتم إرسال السيناريو كاملاً دون اقتطاع في رسالة نصية تمهيدية
            case_msg = call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": f"📋 **حالة سريرية للسؤال ({index + 1}/{session['total']}):**\n\n{raw_q_text}",
                "parse_mode": "Markdown"
            })
            if case_msg.get("ok"):
                session.get("poll_msg_ids", []).append(case_msg["result"]["message_id"])
            q_text = f"({index + 1}/{session['total']}) بناءً على الحالة السريرية أعلاه، ما هو الخيار الصحيح؟"

        raw_expl = clean_latex(q.get("explanation") or "").strip()

        cleaned_options = []
        for opt in q.get("options", []):
            s_opt = clean_latex(str(opt).strip())
            if len(s_opt) > 100:
                s_opt = s_opt[:97] + "..."
            cleaned_options.append(s_opt)

        correct_opt_id = q.get("correct_id") if q.get("correct_id") is not None else q.get("correct_index", 0)
        poll_payload = {
            "chat_id": chat_id,
            "question": q_text,
            "options": cleaned_options,
            "type": "quiz",
            "correct_option_id": int(correct_opt_id),
            "is_anonymous": False
        }
        # Only attach explanation if a genuine explanation exists (never default to placeholders)
        if raw_expl and raw_expl not in ["إجابة صحيحة!", "إجابة سريرية صحيحة!", "إجابة صحيحة", "إجابة سريرية صحيحة"]:
            poll_payload["explanation"] = raw_expl[:200]

        res = call_telegram("sendPoll", poll_payload)
        if res.get("ok") and "poll" in res.get("result", {}):
            poll_id = str(res["result"]["poll"]["id"])
            msg_id = res["result"]["message_id"]

            db.collection("doquiz_polls").document(poll_id).set({
                "user_id": chat_id,
                "q_idx": index
            })

            poll_msg_ids = session.get("poll_msg_ids", [])
            poll_msg_ids.append(msg_id)

            db.collection("doquiz_sessions").document(str(chat_id)).update({
                "current_index": index,
                "poll_msg_ids": poll_msg_ids
            })
            print(f"Successfully dispatched question {index+1} (poll_id: {poll_id}) to {chat_id}")
        else:
            print(f"Failed to send poll to {chat_id}: {res}")
            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": f"⚠️ **ملاحظة:** تعذر إرسال السؤال رقم {index+1} كاستطلاع بسبب قيود تيليجرام. جاري تخطيه للسؤال التالي...",
                "parse_mode": "Markdown"
            })
            time.sleep(1)
            self.send_question(chat_id, index + 1)

    def handle_poll_answer(self, user_id: int, poll_id: str, selected_option: int):
        print(f"Handling poll_answer: user={user_id}, poll={poll_id}, option={selected_option}")
        db = get_firestore_db()
        poll_doc = db.collection("doquiz_polls").document(str(poll_id)).get()

        if poll_doc.exists:
            p_data = poll_doc.to_dict()
            cur_idx = p_data.get("q_idx", 0)
            target_user_id = p_data.get("user_id", user_id)
        else:
            print(f"Poll {poll_id} not found in doquiz_polls, falling back to user_id")
            target_user_id = user_id
            cur_idx = None

        session_doc = db.collection("doquiz_sessions").document(str(target_user_id)).get()
        if not session_doc.exists:
            print(f"No active session found for user {target_user_id}")
            return

        session = session_doc.to_dict()
        session_idx = session.get("current_index", 0)
        if cur_idx is None:
            cur_idx = session_idx

        # Guard against duplicate updates
        if cur_idx != session_idx:
            print(f"Duplicate answer ignored: poll idx {cur_idx} != session idx {session_idx}")
            return

        questions = session.get("questions", [])
        is_correct = False
        if cur_idx < len(questions):
            q = questions[cur_idx]
            new_score = session.get("score", 0)
            cid = q.get("correct_id") if q.get("correct_id") is not None else q.get("correct_index")
            is_correct = (selected_option is not None and selected_option == cid)
            if is_correct:
                new_score += 1
                
            # Track history for smart adaptive rounds
            try:
                q_id = q.get("id")
                if q_id:
                    db.collection("doquiz_users").document(str(target_user_id)).set({
                        f"history.{q_id}": is_correct
                    }, merge=True)
            except Exception as e:
                print(f"Error saving question history: {e}")
        else:
            new_score = session.get("score", 0)

        next_idx = cur_idx + 1

        db.collection("doquiz_sessions").document(str(target_user_id)).update({
            "score": new_score,
            "current_index": next_idx
        })

        db.collection("doquiz_polls").document(str(poll_id)).delete()

        # انتظار ثانية ونصف ليرى الطالب التفسير والإجابة الصحيحة
        time.sleep(1.5)
        self.send_question(target_user_id, next_idx)

    def finish_round(self, chat_id: int, session: dict):
        db = get_firestore_db()
        fresh_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
        if fresh_doc.exists:
            session = fresh_doc.to_dict()

        score = session.get("score", 0)
        total = session.get("total", len(session.get("questions", [])))
        block = session.get("block_title", "البلوك الطبي")
        subject = session.get("subject_title", "المادة")
        block_key = session.get("block_key", "")
        subject_key = session.get("subject_key", "")
        percentage = int((score / total) * 100) if total > 0 else 0

        if percentage == 100:
            grade = "طبيب متميز! إجابات مثالية 100% 🏆🩺"
        elif percentage >= 80:
            grade = "ممتاز جداً! استيعاب قوي للمادة السريرية 🌟👏"
        elif percentage >= 60:
            grade = "جيد جداً! استمر في المراجعة لتعزيز معلوماتك 💪"
        else:
            grade = "محاولة طيبة! راجع الشروحات والأخطاء وكرر الجولة 📖🩺"

        is_para = block_key == "parasitology"
        if is_para:
            scope_info = f"🦠 **المادة:** {block}\n📂 **الموضوع:** {subject}"
            back_choice_text = "🔙 اختيار موضوع آخر"
        else:
            scope_info = f"🩸 **البلوك:** {block}\n📚 **المادة:** {subject}"
            back_choice_text = "🔙 اختيار مادة أخرى"

        result_text = (
            "🏁 **اكتملت الجولة بنجاح!**\n\n"
            f"{scope_info}\n"
            f"🎯 **الدرجة:** ({score} / {total})\n"
            f"📊 **النسبة المئوية:** {percentage}%\n"
            f"💬 **التقييم:** {grade}\n\n"
            "💡 عند الضغط على **(بدء جولة جديدة)** سيتم اختيار (20) جديدة أو بحاجة لتثبيت! 👇"
        )

        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=حققت%20({score}%20/%20{total})%20في%20جولة%20{subject}%20({block})!%20تحداني%20وجرب%20نفسك%20الآن%20🩺🧠"

        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 بدء جولة جديدة (20)", "callback_data": f"new_round:{block_key}:{subject_key}"}],
                [{"text": back_choice_text, "callback_data": f"blk:{block_key}"}],
                [{"text": "🏠 القائمة الرئيسية", "callback_data": "back_blocks"}],
                [{"text": "📢 شارك نتيجتك مع زملائك", "url": share_url}]
            ]
        }

        call_telegram("sendMessage", {
            "chat_id": chat_id,
            "text": result_text,
            "parse_mode": "Markdown",
            "reply_markup": keyboard
        })

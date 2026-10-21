import asyncio
import json
import logging
import os
import random
import sys
import time
from typing import Dict, Any, List

# ضبط تشفير الطرفية في ويندوز لدعم العربية والإيموجي بدون أخطاء
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from aiohttp import web
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Poll,
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ContextTypes,
)

import config
import database

# إعداد السجلات (Logging)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# تحميل بنك الأسئلة من ملف JSON
def load_questions() -> Dict[str, Any]:
    with open("questions.json", "r", encoding="utf-8") as f:
        return json.load(f)

# جلسات المستخدمين النشطة في الذاكرة
# user_id -> {
#   block_key, subject_key, block_title, subject_title,
#   questions, index, score, total,
#   timer_minutes, timer_task,
#   poll_msg_ids: [int],
#   last_poll_id: str
# }
user_sessions: Dict[int, Dict[str, Any]] = {}
# poll_id -> user_id
poll_to_user: Dict[str, int] = {}
# user_id -> current selected timer in menu
user_timer_selection: Dict[int, int] = {}


def get_blocks_keyboard() -> InlineKeyboardMarkup:
    """توليد أزرار اختيار البلوك أولاً (Blood & Lymph, etc.)"""
    data = load_questions()
    keyboard = []
    for block_key, block_info in data.items():
        btn = InlineKeyboardButton(block_info["title"], callback_data=f"blk:{block_key}")
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)


def get_subjects_keyboard(block_key: str) -> InlineKeyboardMarkup:
    """توليد أزرار اختيار المادة داخل البلوك المحدد (Pathology, Pharmacology, etc.)"""
    data = load_questions()
    block_data = data.get(block_key, {})
    subjects = block_data.get("subjects", {})

    keyboard = []
    for subj_key, subj_info in subjects.items():
        btn = InlineKeyboardButton(subj_info["title"], callback_data=f"subj:{block_key}:{subj_key}")
        keyboard.append([btn])

    keyboard.append([InlineKeyboardButton("🔙 رجوع للبلوكات", callback_data="back_blocks")])
    return InlineKeyboardMarkup(keyboard)


def get_timer_keyboard(block_key: str, subject_key: str, current_minutes: int) -> InlineKeyboardMarkup:
    """توليد لوحة تحكم ضبط الوقت بالأزرار 🔼 و 🔽 مع زر البدء"""
    keyboard = [
        [
            InlineKeyboardButton("🔼 +5 د", callback_data=f"time_adj:{block_key}:{subject_key}:5"),
            InlineKeyboardButton("🔼 +1 د", callback_data=f"time_adj:{block_key}:{subject_key}:1"),
        ],
        [
            InlineKeyboardButton("🔽 -5 د", callback_data=f"time_adj:{block_key}:{subject_key}:-5"),
            InlineKeyboardButton("🔽 -1 د", callback_data=f"time_adj:{block_key}:{subject_key}:-1"),
        ],
        [
            InlineKeyboardButton("♾️ وقت مفتوح (بدون مؤقت)", callback_data=f"time_set:{block_key}:{subject_key}:0")
        ],
        [
            InlineKeyboardButton("🚀 بدء الجولة الآن (20 سؤال)", callback_data=f"start_round:{block_key}:{subject_key}:{current_minutes}")
        ],
        [
            InlineKeyboardButton("🔙 رجوع للمواد", callback_data=f"blk:{block_key}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر البدء /start"""
    user = update.effective_user
    welcome_text = (
        f"مرحباً بك يا **{user.first_name}** في بوت الاختبارات **Doquiz** 🧠✨\n\n"
        "هنا يمكنك خوض تجربة اختبارات تفاعلية مميزة\n\n"
        "👇 **الخطوة 1:** اختر البلوك الدراسي الذي ترغب في اختباره:"
    )
    reply_markup = get_blocks_keyboard()

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text=welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """التعامل مع ضغطات الأزرار الشفافة (Inline Buttons)"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "back_blocks":
        await start_command(update, context)
        return

    # المستوى 1: اختيار البلوك -> عرض المواد التابعة له
    if data.startswith("blk:"):
        block_key = data.split(":")[1]
        all_data = load_questions()
        block_data = all_data.get(block_key)

        if not block_data:
            await query.edit_message_text("عذراً، هذا البلوك غير متوفر حالياً.")
            return

        text = (
            f"🩸 **البلوك المختار:** {block_data['title']}\n"
            f"ℹ️ {block_data.get('description', '')}\n\n"
            "👇 **الخطوة 2:** اختر المادة التي ترغب باختبارها في هذا البلوك:"
        )
        reply_markup = get_subjects_keyboard(block_key)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # المستوى 2: اختيار المادة -> عرض شاشة ضبط الوقت وبدء الجولة
    elif data.startswith("subj:"):
        _, block_key, subject_key = data.split(":")
        all_data = load_questions()
        block_data = all_data.get(block_key, {})
        subject_data = block_data.get("subjects", {}).get(subject_key, {})

        if not subject_data:
            await query.edit_message_text("عذراً، هذه المادة غير متوفرة.")
            return

        # الافتراضي 0 دقائق (وقت مفتوح)
        current_time = user_timer_selection.get(user_id, 0)
        user_timer_selection[user_id] = current_time

        time_display = "مفتوح ♾️ (بدون مؤقت)" if current_time == 0 else f"{current_time} دقيقة ⏱️"
        total_bank = len(subject_data.get("questions", []))

        text = (
            f"🩸 **البلوك:** {block_data['title']}\n"
            f"📚 **المادة:** {subject_data['title']}\n"
            f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
            "───────────────\n"
            "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
            "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
            f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
            "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
        )
        reply_markup = get_timer_keyboard(block_key, subject_key, current_time)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # تعديل الوقت (زيادة أو نقصان)
    elif data.startswith("time_adj:"):
        _, block_key, subject_key, delta_str = data.split(":")
        delta = int(delta_str)
        current = user_timer_selection.get(user_id, 0)
        new_time = max(0, min(120, current + delta))
        user_timer_selection[user_id] = new_time

        all_data = load_questions()
        block_data = all_data.get(block_key, {})
        subject_data = block_data.get("subjects", {}).get(subject_key, {})

        time_display = "مفتوح ♾️ (بدون مؤقت)" if new_time == 0 else f"{new_time} دقيقة ⏱️"
        total_bank = len(subject_data.get("questions", []))

        text = (
            f"🩸 **البلوك:** {block_data['title']}\n"
            f"📚 **المادة:** {subject_data['title']}\n"
            f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
            "───────────────\n"
            "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
            "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
            f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
            "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
        )
        reply_markup = get_timer_keyboard(block_key, subject_key, new_time)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ضبط الوقت إلى قيمة محددة مباشرة (مثلاً 0)
    elif data.startswith("time_set:"):
        _, block_key, subject_key, val_str = data.split(":")
        val = int(val_str)
        user_timer_selection[user_id] = val

        all_data = load_questions()
        block_data = all_data.get(block_key, {})
        subject_data = block_data.get("subjects", {}).get(subject_key, {})

        time_display = "مفتوح ♾️ (بدون مؤقت)" if val == 0 else f"{val} دقيقة ⏱️"
        total_bank = len(subject_data.get("questions", []))

        text = (
            f"🩸 **البلوك:** {block_data['title']}\n"
            f"📚 **المادة:** {subject_data['title']}\n"
            f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
            "───────────────\n"
            "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
            "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
            f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
            "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
        )
        reply_markup = get_timer_keyboard(block_key, subject_key, val)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # بدء الجولة (20 سؤال)
    elif data.startswith("start_round:"):
        _, block_key, subject_key, minutes_str = data.split(":")
        minutes = int(minutes_str)
        await launch_quiz_round(user_id, block_key, subject_key, minutes, query, context)

    # طلب جولة جديدة مع حذف أسئلة الجولة السابقة
    elif data.startswith("new_round:"):
        _, block_key, subject_key = data.split(":")
        minutes = user_timer_selection.get(user_id, 0)
        # حذف أسئلة الجولة السابقة لتنظيف الشات
        await clean_previous_round(user_id, context)
        await launch_quiz_round(user_id, block_key, subject_key, minutes, query, context)


async def clean_previous_round(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف رسائل الأسئلة السابقة لتنظيف محادثة الطالب"""
    session = user_sessions.get(user_id)
    if not session:
        return
    msg_ids = session.get("poll_msg_ids", [])
    for msg_id in msg_ids:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass
    session["poll_msg_ids"] = []


async def launch_quiz_round(
    user_id: int,
    block_key: str,
    subject_key: str,
    minutes: int,
    query,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """بدء جولة ذكية مكونة من 20 سؤالاً مع تتبع الأسئلة والوقت"""
    all_data = load_questions()
    block_data = all_data.get(block_key, {})
    subject_data = block_data.get("subjects", {}).get(subject_key, {})
    questions_bank = subject_data.get("questions", [])

    if not questions_bank:
        await query.edit_message_text("لا توجد أسئلة مضافة في هذا القسم حالياً.")
        return

    # الاختيار الذكي: الأسئلة الجديدة أولاً ثم الأسئلة السابقة الخاطئة (هدف 20 سؤال)
    selected_questions, stats = database.get_adaptive_questions(
        user_id, block_key, subject_key, questions_bank, target_count=20
    )

    if not selected_questions:
        await query.edit_message_text("عذراً، لم نتمكن من اختيار الأسئلة.")
        return

    # إلغاء أي مؤقت سابق إن وجد
    if user_id in user_sessions and user_sessions[user_id].get("timer_task"):
        user_sessions[user_id]["timer_task"].cancel()

    # إنشاء الجلسة الجديدة
    user_sessions[user_id] = {
        "block_key": block_key,
        "subject_key": subject_key,
        "block_title": block_data["title"],
        "subject_title": subject_data["title"],
        "questions": selected_questions,
        "index": 0,
        "score": 0,
        "total": len(selected_questions),
        "timer_minutes": minutes,
        "timer_task": None,
        "poll_msg_ids": [],
        "last_poll_id": None,
    }

    # تشغيل مؤقت العد التنازلي إذا تم تحديد وقت
    if minutes > 0:
        task = asyncio.create_task(timer_countdown(user_id, minutes, context))
        user_sessions[user_id]["timer_task"] = task

    details_info = f"🆕 أسئلة جديدة: {stats['unseen']} | 🔁 أسئلة تثبيت: {stats['failed'] + stats['mastered']}"
    time_info = "مفتوح" if minutes == 0 else f"{minutes} دقيقة"

    await query.edit_message_text(
        f"🚀 **استعد! بدأت جولة جديدة من 20 سؤالاً:**\n"
        f"🩸 **البلوك:** {block_data['title']}\n"
        f"📚 **المادة:** {subject_data['title']}\n"
        f"🎯 عدد أسئلة الجولة: {len(selected_questions)} سؤالاً.\n"
        f"📊 {details_info}\n"
        f"⏱️ مؤقت الجولة: {time_info}\n\n"
        "بالتوفيق يا دكتور! 🩺🌟",
        parse_mode=ParseMode.MARKDOWN,
    )

    await asyncio.sleep(1.2)
    await send_current_question(user_id, context)


async def timer_countdown(user_id: int, minutes: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مؤقت زمني ينهي الاختبار تلقائياً عند نفاذ الوقت"""
    try:
        await asyncio.sleep(minutes * 60)
        session = user_sessions.get(user_id)
        if session and session["index"] < session["total"]:
            await context.bot.send_message(
                chat_id=user_id,
                text="⏰ **انتهى الوقت المحدد للاختبار!**\nجاري احتساب نتيجتك لما تم إنجازه...",
                parse_mode=ParseMode.MARKDOWN,
            )
            await finish_quiz(user_id, context, timed_out=True)
    except asyncio.CancelledError:
        pass


async def send_current_question(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال السؤال الحالي للطالب"""
    session = user_sessions.get(user_id)
    if not session:
        return

    index = session["index"]
    questions = session["questions"]
    total = session["total"]

    if index >= total:
        await finish_quiz(user_id, context)
        return

    q = questions[index]
    question_title = f"السؤال ({index + 1} من {total}):\n{q['question']}"

    try:
        message = await context.bot.send_poll(
            chat_id=user_id,
            question=question_title[:300],
            options=[opt[:100] for opt in q["options"]],
            type=Poll.QUIZ,
            correct_option_id=q["correct_id"],
            explanation=q.get("explanation", "إجابة صحيحة!")[:200],
            is_anonymous=False,
        )
        session["last_poll_id"] = message.poll.id
        session["poll_msg_ids"].append(message.message_id)
        poll_to_user[message.poll.id] = user_id
    except Exception as e:
        logger.error(f"خطأ في إرسال السؤال: {e}")


async def receive_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """استقبال الإجابة وتسجيلها في قاعدة البيانات للتعلم التكيفي ثم الانتقال للسؤال التالي"""
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = poll_to_user.get(poll_id)

    if not user_id or user_id not in user_sessions:
        return

    session = user_sessions[user_id]
    current_index = session["index"]
    current_question = session["questions"][current_index]

    selected_option = answer.option_ids[0] if answer.option_ids else None
    is_correct = (selected_option == current_question["correct_id"])

    # تحديث النقاط
    if is_correct:
        session["score"] += 1

    # تسجيل الإجابة في قاعدة بيانات التعلم التكيفي
    database.record_answer(
        user_id=user_id,
        question_id=current_question["id"],
        block_key=session["block_key"],
        subject_key=session["subject_key"],
        is_correct=is_correct,
    )

    session["index"] += 1

    if poll_id in poll_to_user:
        del poll_to_user[poll_id]

    # انتظار 1.8 ثانية ليتمكن الطالب من قراءة الشرح الطبي للجواب
    await asyncio.sleep(1.8)
    await send_current_question(user_id, context)


async def finish_quiz(user_id: int, context: ContextTypes.DEFAULT_TYPE, timed_out: bool = False) -> None:
    """إرسال بطاقة النتيجة النهائية للجولة وتوفير زر بدء جولة جديدة"""
    session = user_sessions.get(user_id)
    if not session:
        return

    # إلغاء مؤقت الوقت
    if session.get("timer_task"):
        session["timer_task"].cancel()

    score = session["score"]
    total = session["total"]
    block = session["block_title"]
    subject = session["subject_title"]
    percentage = int((score / total) * 100) if total > 0 else 0

    if percentage == 100:
        grade = "طبيب متميز! إجابات مثالية 100% 🏆🩺"
    elif percentage >= 80:
        grade = "ممتاز جداً! استيعاب قوي للمادة السريرية 🌟👏"
    elif percentage >= 60:
        grade = "جيد جداً! استمر في المراجعة لتعزيز معلوماتك 💪"
    else:
        grade = "محاولة طيبة! راجع الشروحات والأخطاء وكرر الجولة 📖🩺"

    status_header = "⏰ **انتهى الوقت المحدد للجولة!**\n\n" if timed_out else "🏁 **اكتملت الجولة بنجاح!**\n\n"

    result_text = (
        f"{status_header}"
        f"🩸 **البلوك:** {block}\n"
        f"📚 **المادة:** {subject}\n"
        f"🎯 **الدرجة:** {score} من {total}\n"
        f"📊 **النسبة المئوية:** {percentage}%\n"
        f"💬 **التقييم:** {grade}\n\n"
        "💡 عند الضغط على **(بدء جولة جديدة)** سيتم تنظيف الشات واختيار أسئلة جديدة تلقائياً! 👇"
    )

    share_url = f"https://t.me/share/url?url=https://t.me/{config.BOT_USERNAME}&text=حققت%20{score}%20من%20{total}%20في%20جولة%20{subject}%20({block})!%20تحداني%20وجرب%20نفسك%20الآن%20🩺🧠"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بدء جولة جديدة (20 سؤال)", callback_data=f"new_round:{session['block_key']}:{session['subject_key']}")],
        [InlineKeyboardButton("📚 اختيار بلوك / مادة أخرى", callback_data="back_blocks")],
        [InlineKeyboardButton("📢 شارك نتيجتك مع زملائك", url=share_url)],
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text=result_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


async def post_to_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نشر إعلان الاختبار في القناة"""
    channel_id = context.args[0] if context.args else getattr(config, "DEFAULT_CHANNEL", None)

    if not channel_id:
        await update.message.reply_text("⚠️ الرجاء كتابة معرف القناة.")
        return

    post_text = (
        "🩺 **نظام الجولات السريرية الذكية (Doquiz) متاح الآن!**\n\n"
        "نقدّم لطلابنا الأعزاء اختبارات تفاعلية بنظام الجولات (20 سؤالاً):\n"
        "🩸 **بلوك Blood & Lymph** (Pathology | Pharmacology | Microbiology)\n"
        "🔹 بنك أسئلة تكيفي يستهدف نقاط الضعف ويثبت المعلومات\n"
        "🔹 مؤقت زمني قابل للتخصيص وشرح تفصيلي لكل سؤال\n\n"
        "👇 اضغط على الزر أدناه لبدء جولتك الأولى:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ابدأ جولة الاختبار الآن", url=f"https://t.me/{config.BOT_USERNAME}?start=channel")]
    ])

    try:
        await context.bot.send_message(
            chat_id=channel_id,
            text=post_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_text(f"✅ تم نشر الاختبار بنجاح في القناة: {channel_id}")
    except Exception as e:
        logger.error(f"فشل النشر: {e}")
        await update.message.reply_text(f"❌ فشل النشر في القناة: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🤖 **أوامر بوت Doquiz الطبي:**\n\n"
        "• `/start` - استعراض البلوكات والبدء في جولة 20 سؤالاً.\n"
        "• `/post` - نشر إعلان الاختبار في قناتك (@yashrahly).\n"
        "• `/help` - عرض المساعدة.\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def start_web_server() -> None:
    """خادم ويب مصغر يعمل في الخلفية لضمان عمل البوت 24/7 مجاناً على Render.com Web Service"""
    port_env = os.environ.get("PORT")
    # في التشغيل المحلي على ويندوز، نتجاوز تشغيل خادم الويب لأنه مخصص لاستضافة Render السحابية
    if not port_env and sys.platform == "win32":
        logger.info("Local Windows mode: Skipping background web server.")
        return

    try:
        app = web.Application()

        async def handle_ping(request):
            return web.Response(text="Doquiz Medical Quiz Bot is running 24/7 on Render!")

        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)

        runner = web.AppRunner(app)
        await runner.setup()
        port = int(port_env or 10000)
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Render Healthcheck Web Server started on port {port}")
    except Exception as e:
        logger.warning(f"Could not bind web server (safe to ignore locally): {e}")


def main() -> None:
    print("=" * 50)
    print(f"Starting {config.BOT_USERNAME} with Smart Adaptive 20-Q Engine...")
    print("=" * 50)

    # تشغيل قاعدة البيانات
    database.init_db()

    # إعداد الطلب وتفادي تعارض بروكسي النظام في ويندوز
    req_handler = HTTPXRequest(httpx_kwargs={"trust_env": False})
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(req_handler)
        .get_updates_request(req_handler)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("post", post_to_channel_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(PollAnswerHandler(receive_quiz_answer))

    # دمج خادم الويب الخاص بـ Render داخل دورة حياة التطبيق
    async def post_init(application: Application):
        await start_web_server()

    app.post_init = post_init

    print("Bot is running successfully!")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()

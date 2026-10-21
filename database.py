import sqlite3
import random
from datetime import datetime
from typing import List, Dict, Any, Tuple

DB_PATH = "doquiz.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """تهيئة جدول تتبع إجابات الطلاب للتعلم التكيفي"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_question_history (
                user_id INTEGER,
                question_id TEXT,
                block_key TEXT,
                subject_key TEXT,
                is_correct INTEGER,
                attempts INTEGER DEFAULT 1,
                updated_at TIMESTAMP,
                PRIMARY KEY (user_id, question_id)
            )
        """)
        conn.commit()

def record_answer(user_id: int, question_id: str, block_key: str, subject_key: str, is_correct: bool):
    """تسجيل أو تحديث نتيجة إجابة الطالب على سؤال معين"""
    now = datetime.now()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT attempts FROM user_question_history
            WHERE user_id = ? AND question_id = ?
        """, (user_id, question_id))
        row = cursor.fetchone()

        if row:
            attempts = row["attempts"] + 1
            cursor.execute("""
                UPDATE user_question_history
                SET is_correct = ?, attempts = ?, updated_at = ?
                WHERE user_id = ? AND question_id = ?
            """, (1 if is_correct else 0, attempts, now, user_id, question_id))
        else:
            cursor.execute("""
                INSERT INTO user_question_history
                (user_id, question_id, block_key, subject_key, is_correct, attempts, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (user_id, question_id, block_key, subject_key, 1 if is_correct else 0, now))
        conn.commit()

def get_adaptive_questions(
    user_id: int,
    block_key: str,
    subject_key: str,
    all_questions: List[Dict[str, Any]],
    target_count: int = 20
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    جلب أسئلة ذكية وفق معايير التعلم التكيفي:
    1. الأسئلة الجديدة (Unseen) التي لم يختبرها الطالب مطلقاً أولاً.
    2. إكمال النقص من الأسئلة التي أخفق فيها سابقاً (Failed) لترسيخها.
    3. إذا لم يتبق سوى أسئلة متقنة (Mastered) يتم مراجعتها.
    """
    if not all_questions:
        return [], {"unseen": 0, "failed": 0, "mastered": 0}

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT question_id, is_correct
            FROM user_question_history
            WHERE user_id = ? AND block_key = ? AND subject_key = ?
        """, (user_id, block_key, subject_key))
        rows = cursor.fetchall()

    history_map = {row["question_id"]: row["is_correct"] for row in rows}

    unseen = []
    failed = []
    mastered = []

    for q in all_questions:
        q_id = q["id"]
        if q_id not in history_map:
            unseen.append(q)
        elif history_map[q_id] == 0:
            failed.append(q)
        else:
            mastered.append(q)

    # خلط الأسئلة عشوائياً لكل تصنيف
    random.shuffle(unseen)
    random.shuffle(failed)
    random.shuffle(mastered)

    selected = []
    unseen_used = 0
    failed_used = 0
    mastered_used = 0

    # 1. أخذ الأسئلة الجديدة أولاً
    take_unseen = min(len(unseen), target_count)
    selected.extend(unseen[:take_unseen])
    unseen_used = take_unseen

    # 2. إكمال النقص من الأسئلة الخاطئة سابقاً
    needed = target_count - len(selected)
    if needed > 0 and failed:
        take_failed = min(len(failed), needed)
        selected.extend(failed[:take_failed])
        failed_used = take_failed

    # 3. إذا ما زال هناك نقص وبنك الأسئلة صغير أو أنجز كل شيء، نأخذ من المتقنة
    needed = target_count - len(selected)
    if needed > 0 and mastered:
        take_mastered = min(len(mastered), needed)
        selected.extend(mastered[:take_mastered])
        mastered_used = take_mastered

    # إعادة خلط الأسئلة المختارة في الجولة لعدم توقع ترتيبها
    random.shuffle(selected)

    stats = {
        "unseen": unseen_used,
        "failed": failed_used,
        "mastered": mastered_used,
        "total_selected": len(selected),
        "total_bank": len(all_questions)
    }
    return selected, stats

def reset_user_history(user_id: int, block_key: str, subject_key: str):
    """إعادة تصفير سجل الطالب لمادة معينة للمراجعة الشاملة"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM user_question_history
            WHERE user_id = ? AND block_key = ? AND subject_key = ?
        """, (user_id, block_key, subject_key))
        conn.commit()

# تشغيل التهيئة فور استدعاء الملف
init_db()

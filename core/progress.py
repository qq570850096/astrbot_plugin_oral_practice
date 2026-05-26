"""
Progress Tracker — 用户进度追踪
使用 SQLite 存储练习记录、发音错误和用户数据
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite
from astrbot.api import logger


@dataclass
class UserProfile:
    """用户档案"""
    user_id: str
    display_name: str
    cefr_level: str
    total_sessions: int = 0
    total_practice_minutes: float = 0.0
    avg_accuracy: float = 0.0
    avg_fluency: float = 0.0
    created_at: str = ""
    last_active: str = ""


@dataclass
class PracticeRecord:
    """练习记录"""
    mode: str
    duration_seconds: int
    avg_accuracy: float
    avg_fluency: float
    avg_prosody: float
    words_practiced: int
    timestamp: str


@dataclass
class PronunciationError:
    """发音错误记录"""
    word: str
    error_type: str
    occurrences: int
    last_accuracy: float
    next_review: str


class ProgressTracker:
    """
    用户进度追踪器

    使用 SQLite 存储用户练习数据，支持：
    - 用户档案管理
    - 练习会话记录
    - 发音错误追踪（含间隔重复）
    - 进度报告生成
    """

    # 间隔重复天数梯度
    SPACED_REPETITION_DAYS = [1, 3, 7, 14, 30, 60]

    def __init__(self, db_path: str):
        """
        初始化进度追踪器

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def initialize(self):
        """创建数据库表（如果不存在）"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        display_name TEXT,
                        cefr_level TEXT DEFAULT 'A2',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS practice_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ended_at TIMESTAMP,
                        duration_seconds INTEGER DEFAULT 0,
                        avg_accuracy REAL DEFAULT 0,
                        avg_fluency REAL DEFAULT 0,
                        avg_prosody REAL DEFAULT 0,
                        words_practiced INTEGER DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    );

                    CREATE TABLE IF NOT EXISTS pronunciation_errors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        word TEXT NOT NULL,
                        phoneme TEXT,
                        error_type TEXT DEFAULT 'mispronunciation',
                        accuracy_score REAL DEFAULT 0,
                        occurrences INTEGER DEFAULT 1,
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        next_review TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_sessions_user
                        ON practice_sessions(user_id);
                    CREATE INDEX IF NOT EXISTS idx_sessions_time
                        ON practice_sessions(started_at);
                    CREATE INDEX IF NOT EXISTS idx_errors_user
                        ON pronunciation_errors(user_id);
                    CREATE INDEX IF NOT EXISTS idx_errors_review
                        ON pronunciation_errors(next_review);
                    CREATE INDEX IF NOT EXISTS idx_errors_word
                        ON pronunciation_errors(user_id, word);
                """)
                await db.commit()
            logger.info("[Progress] 数据库初始化完成")
        except Exception as e:
            logger.error(f"[Progress] 数据库初始化失败: {e}")

    # ------------------------------------------------------------------
    # 用户管理
    # ------------------------------------------------------------------

    async def get_or_create_user(
        self, user_id: str, display_name: str = None
    ) -> UserProfile:
        """获取或创建用户档案"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 尝试获取现有用户
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()

            if row:
                # 更新最后活跃时间
                await db.execute(
                    "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (user_id,),
                )
                if display_name and display_name != row["display_name"]:
                    await db.execute(
                        "UPDATE users SET display_name = ? WHERE user_id = ?",
                        (display_name, user_id),
                    )
                await db.commit()

                # 获取统计数据
                stats = await self._get_basic_stats(db, user_id)

                return UserProfile(
                    user_id=row["user_id"],
                    display_name=display_name or row["display_name"] or "User",
                    cefr_level=row["cefr_level"] or "A2",
                    total_sessions=stats["total_sessions"],
                    total_practice_minutes=stats["total_minutes"],
                    avg_accuracy=stats["avg_accuracy"],
                    avg_fluency=stats["avg_fluency"],
                    created_at=str(row["created_at"]),
                    last_active=str(row["last_active"]),
                )
            else:
                # 创建新用户
                name = display_name or "User"
                await db.execute(
                    "INSERT INTO users (user_id, display_name) VALUES (?, ?)",
                    (user_id, name),
                )
                await db.commit()
                logger.info(f"[Progress] 新用户创建: {name} ({user_id[:20]}...)")

                return UserProfile(
                    user_id=user_id,
                    display_name=name,
                    cefr_level="A2",
                    created_at=datetime.now().isoformat(),
                    last_active=datetime.now().isoformat(),
                )

    async def update_user_level(self, user_id: str, level: str):
        """更新用户 CEFR 等级"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET cefr_level = ? WHERE user_id = ?",
                (level, user_id),
            )
            await db.commit()
            logger.info(f"[Progress] 用户等级更新: {user_id[:20]}... → {level}")

    async def get_user_level(self, user_id: str) -> str:
        """获取用户 CEFR 等级"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT cefr_level FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else "A2"

    # ------------------------------------------------------------------
    # 练习记录
    # ------------------------------------------------------------------

    async def record_session(
        self,
        user_id: str,
        mode: str,
        duration_seconds: int,
        avg_accuracy: float = 0.0,
        avg_fluency: float = 0.0,
        avg_prosody: float = 0.0,
        words_practiced: int = 0,
    ):
        """记录一次完成的练习会话"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO practice_sessions
                   (user_id, mode, duration_seconds, avg_accuracy,
                    avg_fluency, avg_prosody, words_practiced, ended_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    user_id, mode, duration_seconds,
                    avg_accuracy, avg_fluency, avg_prosody, words_practiced,
                ),
            )
            # 更新用户最后活跃时间
            await db.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

        logger.info(
            f"[Progress] 会话记录: mode={mode}, "
            f"duration={duration_seconds}s, accuracy={avg_accuracy:.0f}"
        )

    # ------------------------------------------------------------------
    # 发音错误追踪
    # ------------------------------------------------------------------

    async def record_pronunciation_error(
        self,
        user_id: str,
        word: str,
        phoneme: str = None,
        error_type: str = "mispronunciation",
        accuracy_score: float = 0.0,
    ):
        """
        记录或更新发音错误

        如果该用户已有该单词的错误记录，则更新出现次数和下次复习时间。
        使用间隔重复算法计算下次复习时间。
        """
        word_lower = word.lower().strip()
        if not word_lower:
            return

        async with aiosqlite.connect(self.db_path) as db:
            # 查找已有记录
            cursor = await db.execute(
                "SELECT id, occurrences FROM pronunciation_errors "
                "WHERE user_id = ? AND word = ?",
                (user_id, word_lower),
            )
            row = await cursor.fetchone()

            if row:
                # 更新现有记录
                error_id, occurrences = row
                new_occurrences = occurrences + 1

                # 间隔重复：根据出现次数决定下次复习间隔
                repeat_idx = min(new_occurrences - 1, len(self.SPACED_REPETITION_DAYS) - 1)
                days_until_review = self.SPACED_REPETITION_DAYS[repeat_idx]
                next_review = datetime.now() + timedelta(days=days_until_review)

                await db.execute(
                    """UPDATE pronunciation_errors
                       SET occurrences = ?, accuracy_score = ?,
                           last_seen = CURRENT_TIMESTAMP,
                           next_review = ?, phoneme = COALESCE(?, phoneme),
                           error_type = ?
                       WHERE id = ?""",
                    (
                        new_occurrences, accuracy_score,
                        next_review.isoformat(), phoneme,
                        error_type, error_id,
                    ),
                )
            else:
                # 新记录 — 1 天后复习
                next_review = datetime.now() + timedelta(days=1)
                await db.execute(
                    """INSERT INTO pronunciation_errors
                       (user_id, word, phoneme, error_type, accuracy_score, next_review)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        user_id, word_lower, phoneme,
                        error_type, accuracy_score, next_review.isoformat(),
                    ),
                )

            await db.commit()

    async def get_words_for_review(
        self, user_id: str, limit: int = 10
    ) -> list[PronunciationError]:
        """获取需要复习的单词（next_review <= 当前时间）"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            now = datetime.now().isoformat()

            cursor = await db.execute(
                """SELECT word, error_type, occurrences, accuracy_score, next_review
                   FROM pronunciation_errors
                   WHERE user_id = ? AND next_review <= ?
                   ORDER BY accuracy_score ASC, occurrences DESC
                   LIMIT ?""",
                (user_id, now, limit),
            )
            rows = await cursor.fetchall()

            return [
                PronunciationError(
                    word=row["word"],
                    error_type=row["error_type"],
                    occurrences=row["occurrences"],
                    last_accuracy=row["accuracy_score"],
                    next_review=str(row["next_review"]),
                )
                for row in rows
            ]

    async def get_problem_words(
        self, user_id: str, limit: int = 10
    ) -> list[PronunciationError]:
        """获取最有问题的单词（按准确度升序）"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """SELECT word, error_type, occurrences, accuracy_score, next_review
                   FROM pronunciation_errors
                   WHERE user_id = ?
                   ORDER BY accuracy_score ASC, occurrences DESC
                   LIMIT ?""",
                (user_id, limit),
            )
            rows = await cursor.fetchall()

            return [
                PronunciationError(
                    word=row["word"],
                    error_type=row["error_type"],
                    occurrences=row["occurrences"],
                    last_accuracy=row["accuracy_score"],
                    next_review=str(row["next_review"]) if row["next_review"] else "",
                )
                for row in rows
            ]

    # ------------------------------------------------------------------
    # 统计与报告
    # ------------------------------------------------------------------

    async def get_user_stats(self, user_id: str) -> dict:
        """
        获取用户综合统计数据

        Returns:
            dict 包含：total_sessions, total_minutes, avg_accuracy,
            avg_fluency, avg_prosody, sessions_this_week,
            minutes_this_week, problem_words, score_trend
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 基础统计
            stats = await self._get_basic_stats(db, user_id)

            # 本周统计
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            cursor = await db.execute(
                """SELECT COUNT(*) as cnt,
                          COALESCE(SUM(duration_seconds), 0) as total_secs,
                          COALESCE(AVG(avg_accuracy), 0) as avg_acc
                   FROM practice_sessions
                   WHERE user_id = ? AND started_at >= ?""",
                (user_id, week_ago),
            )
            week_row = await cursor.fetchone()

            # 上周统计（用于趋势对比）
            two_weeks_ago = (datetime.now() - timedelta(days=14)).isoformat()
            cursor = await db.execute(
                """SELECT COALESCE(AVG(avg_accuracy), 0) as avg_acc
                   FROM practice_sessions
                   WHERE user_id = ? AND started_at >= ? AND started_at < ?""",
                (user_id, two_weeks_ago, week_ago),
            )
            last_week_row = await cursor.fetchone()

            # 计算趋势
            this_week_acc = week_row["avg_acc"] if week_row else 0
            last_week_acc = last_week_row["avg_acc"] if last_week_row else 0

            if this_week_acc > 0 and last_week_acc > 0:
                diff = this_week_acc - last_week_acc
                if diff > 3:
                    trend = f"进步中 ↑ (比上周提高 {diff:.0f} 分)"
                elif diff < -3:
                    trend = f"需加油 ↓ (比上周下降 {abs(diff):.0f} 分)"
                else:
                    trend = "保持稳定 →"
            elif this_week_acc > 0:
                trend = "刚开始练习，继续加油！"
            else:
                trend = "本周还没练习哦~"

            # 最有问题的单词
            cursor = await db.execute(
                """SELECT word, accuracy_score
                   FROM pronunciation_errors
                   WHERE user_id = ?
                   ORDER BY accuracy_score ASC
                   LIMIT 5""",
                (user_id,),
            )
            problem_rows = await cursor.fetchall()
            problem_words = [
                {"word": r["word"], "accuracy": r["accuracy_score"]}
                for r in problem_rows
            ]

            return {
                **stats,
                "sessions_this_week": week_row["cnt"] if week_row else 0,
                "minutes_this_week": (week_row["total_secs"] / 60.0) if week_row else 0,
                "score_trend": trend,
                "problem_words": problem_words,
            }

    async def generate_report(self, user_id: str) -> str:
        """
        生成格式化的练习报告文本

        Returns:
            包含 emoji 和进度条的文本报告
        """
        # 获取用户信息
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT display_name, cefr_level FROM users WHERE user_id = ?",
                (user_id,),
            )
            user_row = await cursor.fetchone()

        if not user_row:
            return (
                "📊 暂无练习数据\n\n"
                "你还没有开始练习哦！\n"
                "发送 /oral talk 开始你的第一次口语练习吧~ 🎙️"
            )

        name, level = user_row
        stats = await self.get_user_stats(user_id)

        # 构建报告
        lines = [
            "📊 口语练习报告",
            "━━━━━━━━━━━━━━━━━━━",
            f"👤 用户: {name or 'User'}",
            f"📚 等级: CEFR {level or 'A2'}",
            "",
            "📈 总体统计",
        ]

        total_sessions = stats.get("total_sessions", 0)
        total_minutes = stats.get("total_minutes", 0)

        if total_sessions == 0:
            lines.extend([
                "  还没有练习记录哦~",
                "",
                "💡 发送 /oral talk 开始你的第一次口语练习！",
            ])
            return "\n".join(lines)

        # 总体数据
        hours = total_minutes / 60.0
        if hours >= 1:
            time_str = f"{hours:.1f} 小时"
        else:
            time_str = f"{total_minutes:.0f} 分钟"

        lines.extend([
            f"  • 练习次数: {total_sessions} 次",
            f"  • 练习时长: {time_str}",
        ])

        avg_acc = stats.get("avg_accuracy", 0)
        avg_flu = stats.get("avg_fluency", 0)
        if avg_acc > 0:
            lines.append(f"  • 平均准确度: {avg_acc:.0f}/100  {self._bar(avg_acc)}")
        if avg_flu > 0:
            lines.append(f"  • 平均流利度: {avg_flu:.0f}/100  {self._bar(avg_flu)}")

        # 本周
        week_sessions = stats.get("sessions_this_week", 0)
        week_minutes = stats.get("minutes_this_week", 0)
        lines.extend([
            "",
            f"📅 本周练习: {week_sessions} 次 ({week_minutes:.1f} 分钟)",
        ])

        # 趋势
        trend = stats.get("score_trend", "")
        if trend:
            lines.append(f"📈 趋势: {trend}")

        # 问题单词
        problem_words = stats.get("problem_words", [])
        if problem_words:
            lines.extend(["", "⚠️ 需要复习的单词:"])
            for pw in problem_words[:5]:
                lines.append(
                    f"  • {pw['word']} (准确度: {pw['accuracy']:.0f})"
                )

        # 鼓励语
        lines.extend(["", "💪 继续加油，每天坚持练习进步最快！"])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    async def _get_basic_stats(self, db, user_id: str) -> dict:
        """获取基础统计数据"""
        cursor = await db.execute(
            """SELECT COUNT(*) as total_sessions,
                      COALESCE(SUM(duration_seconds), 0) as total_secs,
                      COALESCE(AVG(CASE WHEN avg_accuracy > 0 THEN avg_accuracy END), 0) as avg_acc,
                      COALESCE(AVG(CASE WHEN avg_fluency > 0 THEN avg_fluency END), 0) as avg_flu,
                      COALESCE(AVG(CASE WHEN avg_prosody > 0 THEN avg_prosody END), 0) as avg_pro
               FROM practice_sessions
               WHERE user_id = ?""",
            (user_id,),
        )
        row = await cursor.fetchone()

        if row:
            return {
                "total_sessions": row[0],
                "total_minutes": row[1] / 60.0,
                "avg_accuracy": row[2],
                "avg_fluency": row[3],
                "avg_prosody": row[4],
            }
        return {
            "total_sessions": 0,
            "total_minutes": 0.0,
            "avg_accuracy": 0.0,
            "avg_fluency": 0.0,
            "avg_prosody": 0.0,
        }

    @staticmethod
    def _bar(score: float, width: int = 10) -> str:
        """生成文本进度条"""
        score = max(0.0, min(100.0, score))
        filled = round(score / 100.0 * width)
        return "█" * filled + "░" * (width - filled)

    async def close(self):
        """清理资源（当前 aiosqlite 无需显式关闭连接池）"""
        logger.info("[Progress] 进度追踪器已关闭")
